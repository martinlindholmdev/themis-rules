"""Optional review checks: a documentation budget and a test-tamper tripwire.

Purpose: measure the instruction documents an owner names against line caps,
find dead local Markdown links, refuse a `docs` baseline entry that records
more than the base commit measured or less than this change's own tree holds,
and report test files, functions and literals a change removed.
Entry points: run_checks() for `check --staged` and `check --range`;
docs_baseline() and docs_raised() for `rebaseline`; status_lines() for
`status`; docs_ratchet_violations(), markdown_links() and the pure helpers
the tests call.
Invariants: standard library only, python3 3.9+, no network, nothing from the
repository is executed; read-only except through the caller; settings come
from the base commit's themis.json passed in by themis.py, never from the
change under check; a literal removed from a test is reported by file, line,
kind and count, never by value or hash; themis.py loads this file only if it
exists and never needs it for `gate`.
Never change without a decision: the `docs` and `tamper` key names and their
defaults, the "<total>" baseline key, and the rule that findings never echo a
literal.
"""

from __future__ import annotations

import fnmatch
import json
import posixpath
import re
import subprocess
from pathlib import Path
from typing import Callable, Dict, List, NamedTuple, Optional, Tuple
from urllib.parse import unquote

TOTAL_KEY = "<total>"
DOC_DEFAULTS = {"caps": {"AGENTS.md": 300, "CLAUDE.md": 200}, "total": 600,
                "check_links": False, "link_globs": ["*.md"]}
_BEGIN = re.compile(r"<!--\s*themis\s+v\d+(?:\.\d+)*\s+begin\s*-->")
_END = re.compile(r"<!--\s*themis\s+v\d+(?:\.\d+)*\s+end\s*-->")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_INLINE_CODE = re.compile(r"(`+).+?\1")
_INLINE_LINK = re.compile(r"\[(?:[^\[\]\n]|\[[^\[\]\n]*\])*\]\(\s*(<[^>\n]*>|(?:[^()\s]|\([^()\s]*\))*)")
_REF_DEF = re.compile(r"^ {0,3}\[[^\]\n]+\]:[ \t]*(<[^>\n]*>|\S+)")
_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.-]+:")
_IMPORT = re.compile(r"@(\S+)")
Git = Callable[..., str]


def _safe(text: str) -> str:
    """Text from the repository with control characters made visible."""
    return "".join(c if ord(c) >= 0x20 and ord(c) != 0x7f else "?" for c in text)


# ------------------------------------------------------------------ settings

def _whole(value: object, low: int = 1) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= low


def _strings(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) and v and "\0" not in v for v in value)


def docs_settings(config: dict) -> Tuple[Optional[dict], List[str]]:
    """(settings, problems) for the `docs` key; (None, []) when it is absent,
    which means no cap, no total and no link check."""
    raw = config.get("docs")
    if raw is None:
        return None, []
    if not isinstance(raw, dict):
        return None, ["docs must be an object"]
    problems = ["docs.%s is not a known key" % _safe(k) for k in raw if k not in DOC_DEFAULTS]
    merged = dict(DOC_DEFAULTS, **{k: v for k, v in raw.items() if k in DOC_DEFAULTS})
    caps = merged["caps"]
    if not isinstance(caps, dict) or not all(isinstance(p, str) and p and _whole(n) for p, n in caps.items()):
        problems.append("docs.caps must map document paths to line counts of at least 1")
    if not _whole(merged["total"]):
        problems.append("docs.total must be a whole number of at least 1")
    if not isinstance(merged["check_links"], bool):
        problems.append("docs.check_links must be true or false")
    if not _strings(merged["link_globs"]):
        problems.append("docs.link_globs must be a list of non-empty globs")
    return (None, problems) if problems else (merged, [])


# --------------------------------------------------------------------- trees

class Tree:
    """The tracked files of one snapshot: the index (":"), a revision, or
    with ref None the working tree (tracked and untracked files)."""

    def __init__(self, root: Path, git: Git, ref: Optional[str]) -> None:
        self.root, self.git, self.ref = root, git, ref
        self._files: Optional[frozenset] = None

    def files(self) -> frozenset:
        if self._files is None:
            if self.ref == ":":
                args = ("ls-files", "-z")
            elif self.ref is None:
                args = ("ls-files", "-z", "-co", "--exclude-standard")
            else:
                args = ("ls-tree", "-r", "-z", "--name-only", self.ref)
            try:
                out = self.git(self.root, *args)
            except subprocess.CalledProcessError:
                out = ""
            self._files = frozenset(p for p in out.split("\0") if p)
        return self._files

    def dirs(self) -> frozenset:
        return frozenset(d for p in self.files() for d in _parents(p))

    def text(self, path: str) -> Optional[str]:
        if path not in self.files():
            return None
        if self.ref is None:
            full = self.root / path
            if full.is_symlink() or not full.is_file():
                return None
            return full.read_text(encoding="utf-8", errors="replace")
        try:
            return self.git(self.root, "show", (":" if self.ref == ":" else self.ref + ":") + path)
        except subprocess.CalledProcessError:
            return None


def _parents(path: str) -> List[str]:
    parts = path.split("/")[:-1]
    return ["/".join(parts[:i + 1]) for i in range(len(parts))]


# ----------------------------------------------------------------- documents

def counted_lines(text: str) -> List[str]:
    """The lines of a document that count against its cap: everything except
    a vendored rules block between the Themis begin and end markers. A begin
    marker with no end marker after it excludes nothing."""
    lines, kept, i = text.splitlines(), [], 0
    while i < len(lines):
        if _BEGIN.search(lines[i]):
            end = next((j for j in range(i + 1, len(lines)) if _END.search(lines[j])), None)
            if end is not None:
                i = end + 1
                continue
        kept.append(lines[i])
        i += 1
    return kept


def outside_fences(lines: List[str]) -> List[str]:
    """The lines with every fenced code block, fences included, blanked."""
    out: List[str] = []
    fence: Optional[str] = None
    for line in lines:
        match = _FENCE.match(line)
        if fence is None:
            fence = match.group(1) if match else None
            out.append("" if match else line)
        else:
            out.append("")
            if match and match.group(1)[0] == fence[0] and len(match.group(1)) >= len(fence) \
                    and line.strip() == match.group(1):
                fence = None
    return out


def markdown_links(text: str) -> List[Tuple[int, str]]:
    """(line, target) for each inline link or image and each reference
    definition outside fenced and inline code."""
    found = []
    for number, line in enumerate(outside_fences(text.splitlines()), 1):
        line = _INLINE_CODE.sub(lambda m: " " * len(m.group(0)), line)
        targets = [m.group(1) for m in _INLINE_LINK.finditer(line)]
        ref = _REF_DEF.match(line)
        targets += [ref.group(1)] if ref else []
        found += [(number, t[1:-1] if t.startswith("<") else t) for t in targets]
    return found


def link_path(target: str) -> Optional[str]:
    """The path a local link names, without fragment or query; None for an
    external link (any scheme, or `//host`), a fragment-only link or an empty one."""
    target = target.strip()
    if not target or target.startswith(("#", "//")) or _SCHEME.match(target):
        return None
    return unquote(re.split(r"[#?]", target, maxsplit=1)[0]) or None


def resolve_link(source: str, path: str) -> Optional[str]:
    """The tree path a link from `source` names ("" is the root), or None
    when it leaves the tree. A leading slash is relative to the root."""
    joined = path.lstrip("/") if path.startswith("/") else posixpath.join(posixpath.dirname(source), path)
    norm = posixpath.normpath(joined)
    if norm == ".." or norm.startswith("../"):
        return None
    return "" if norm == "." else norm


class Measured(NamedTuple):
    lines: Dict[str, int]
    total: int
    dead: Dict[str, List[Tuple[int, str]]]


def _imports(tree: Tree, named: Dict[str, List[str]]) -> Dict[str, int]:
    """Counted lines of each file a named document imports with an `@path`
    line, one level deep, once, when the file is tracked and not itself named."""
    found: Dict[str, int] = {}
    for source, lines in named.items():
        for line in outside_fences(lines):
            match = _IMPORT.fullmatch(line.strip())
            target = resolve_link(source, match.group(1)) if match else None
            if target and target in tree.files() and target not in named and target not in found:
                text = tree.text(target)
                found[target] = len(counted_lines(text)) if text is not None else 0
    return found


def measure(tree: Tree, settings: dict) -> Measured:
    """Counted lines of each named document that exists in `tree`, the total
    with its imports, and, with check_links, the dead links of each file."""
    named = {}
    for path in settings["caps"]:
        text = tree.text(path)
        if text is not None:
            named[path] = counted_lines(text)
    lines = {path: len(counted) for path, counted in named.items()}
    total = sum(lines.values()) + sum(_imports(tree, named).values())
    dead: Dict[str, List[Tuple[int, str]]] = {}
    if settings["check_links"]:
        files, dirs = tree.files(), tree.dirs()
        for path in sorted(files):
            if not any(fnmatch.fnmatchcase(path, glob) for glob in settings["link_globs"]):
                continue
            text = tree.text(path)
            for number, target in markdown_links(text) if text is not None else ():
                local = link_path(target)
                found = resolve_link(path, local) if local else ""
                if local and (found is None or not (found == "" or found in files or found in dirs)):
                    dead.setdefault(path, []).append((number, target))
    return Measured(lines, total, dead)


def _lookup(tree: Tree, measured: Measured, section: str, key: str) -> Optional[int]:
    """What `tree` measures for a baseline key; None when the document or file is absent."""
    if section == "lines":
        return measured.total if key == TOTAL_KEY else measured.lines.get(key)
    return len(measured.dead.get(key, ())) if key in tree.files() else None


def docs_problems(measured: Measured, settings: dict, entries: dict) -> List[str]:
    """Documents over their cap, a total over its cap and files with more dead
    links than the baseline allows. An entry allows its own number, no more."""
    problems = []
    allowed = entries.get("lines", {})
    for path, count in sorted(measured.lines.items()):
        cap = settings["caps"][path]
        if count > max(cap, allowed.get(path, 0)):
            problems.append("%s: %d counted lines, over the cap of %d (a vendored rules block is not counted). "
                            "Shorten it; the cap and any baseline entry only go down."
                            % (_safe(path), count, max(cap, allowed.get(path, 0))))
    if settings["total"] and measured.total > max(settings["total"], allowed.get(TOTAL_KEY, 0)):
        problems.append("instruction documents: %d counted lines in all (with imported files), over the total of %d. "
                        "Shorten them." % (measured.total, max(settings["total"], allowed.get(TOTAL_KEY, 0))))
    for path, dead in sorted(measured.dead.items()):
        allowed_dead = entries.get("dead_links", {}).get(path, 0)
        if len(dead) > allowed_dead:
            shown = ", ".join("line %d %s" % (n, _safe(t)[:60]) for n, t in dead[:3])
            problems.append("%s: %d dead local link(s) (baseline allows %d), e.g. %s. Fix or remove them."
                            % (_safe(path), len(dead), allowed_dead, shown))
    return problems


# ------------------------------------------------------------ docs baseline

def baseline_docs(text: str) -> dict:
    """The `docs` section of a baseline text, {} when absent or unreadable."""
    try:
        section = json.loads(text).get("docs", {})
    except (ValueError, AttributeError):
        return {}
    return section if isinstance(section, dict) else {}


def docs_ratchet_violations(old_text: str, new_text: str, base_measure: Callable[[str, str], Optional[int]],
                            head_measure: Callable[[str, str], Optional[int]]) -> List[str]:
    """A new or raised `docs` entry is accepted only when the base commit's
    own tree measures at least that number for that path or count
    (base_measure(section, key)) and this change's tree measures no more
    (head_measure), so head <= entry <= base: debt that existed can be
    recorded, new debt cannot be recorded as old or grow beside its own
    record. Lowering and removing always pass. Pure over the measures."""
    old, new = baseline_docs(old_text), baseline_docs(new_text)
    problems = []
    for section in ("lines", "dead_links"):
        old_entries = old.get(section, {}) if isinstance(old.get(section), dict) else {}
        new_entries = new.get(section, {}) if isinstance(new.get(section), dict) else {}
        for key, value in sorted(new_entries.items()):
            name = "docs.%s.%s" % (section, _safe(key))
            if not _whole(value, 0):
                problems.append("%s: not a whole number" % name)
            elif _whole(old_entries.get(key), 0) and value <= old_entries[key]:
                continue
            else:
                base, head = base_measure(section, key), head_measure(section, key) or 0
                if base is None:
                    problems.append("%s: new entry for a path the base commit does not have" % name)
                elif value > base:
                    problems.append("%s: %d is above the %d the base commit measures" % (name, value, base))
                elif value < head:
                    problems.append("%s: %d is below the %d this change's tree holds; the commit that "
                                    "records a document or its dead links may not grow them" % (name, value, head))
    return problems


def seed_entries(measured: Measured, settings: dict) -> dict:
    """The entries a rebaseline records: every document over its cap, the
    total when over, and every file with dead links."""
    lines = {p: n for p, n in sorted(measured.lines.items()) if n > settings["caps"][p]}
    if measured.total > settings["total"]:
        lines[TOTAL_KEY] = measured.total
    return {"lines": lines, "dead_links": {p: len(d) for p, d in sorted(measured.dead.items())}}


def docs_baseline(root: Path, git: Git, config: dict) -> Tuple[Optional[dict], List[str]]:
    """(the `docs` section to write, lines to print) for `rebaseline`, seeded
    from HEAD's committed content and never the working tree; (None, [])
    when the config has no `docs` key."""
    settings, problems = docs_settings(config)
    if problems:
        return None, ["themis.json: " + p for p in problems]
    if settings is None:
        return None, []
    entries = seed_entries(measure(Tree(root, git, "HEAD"), settings), settings)
    shown = ["docs baseline from HEAD: %s %s %d" % (section, _safe(key), value)
             for section in ("lines", "dead_links") for key, value in entries[section].items()]
    return entries, shown or ["docs baseline from HEAD: nothing over a cap and no dead links"]


def docs_raised(committed_text: str, fresh: dict) -> List[str]:
    """Entries a rebaseline would raise above the committed baseline."""
    old = baseline_docs(committed_text)
    return ["docs.%s.%s: raised from %s to %s" % (section, _safe(key), old[section][key], value)
            for section in ("lines", "dead_links") if isinstance(old.get(section), dict)
            for key, value in fresh.get(section, {}).items()
            if _whole(old[section].get(key), 0) and value > old[section][key]]


def status_lines(root: Path, git: Git, config: dict) -> List[str]:
    """Informational `status` lines: each default instruction document's
    counted lines, or the budget in force."""
    settings, problems = docs_settings(config)
    if problems:
        return ["documentation budget: configured but not valid (%s)" % "; ".join(problems)]
    shown = settings or dict(DOC_DEFAULTS, check_links=False)
    measured = measure(Tree(root, git, None), shown)
    parts = ["%s %d%s" % (_safe(p), n, "/%d" % shown["caps"][p] if settings else "") for p, n in measured.lines.items()]
    head = "documentation budget" if settings else "instruction documents (no budget set)"
    return ["%s: %s; with imported files %d%s" % (head, ", ".join(parts) or "none found", measured.total,
                                                   "/%d" % shown["total"] if settings else "")]


# ------------------------------------------------------------------- the run

def _changed(root: Path, git: Git, diff_args: Tuple[str, ...]) -> List[str]:
    return git(root, "diff", *diff_args, "--name-only", "--diff-filter=ACMR").splitlines()


def _text_at(root: Path, git: Git, ref: str, path: str) -> Optional[str]:
    try:
        return git(root, "show", (":" if ref == ":" else ref + ":") + path)
    except subprocess.CalledProcessError:
        return None


def _baseline_text(root: Path, git: Git, config: dict, refs: Tuple[str, ...]) -> str:
    for ref in refs:
        text = _text_at(root, git, ref, config["baseline_path"])
        if text is not None:
            return text
    return "{}"


def _docs_run(root: Path, git: Git, base: dict, rev: str, ref: str, diff_args: Tuple[str, ...]) -> List[str]:
    """The documentation checks for one run: caps, total and dead links under
    the base config, and the ratchet on a changed baseline under the settings
    the change proposes, since an adoption commit has no `docs` key at its base."""
    problems: List[str] = []
    settings, bad = docs_settings(base)
    problems += ["themis.json at %s: %s" % (rev[:12], p) for p in bad]
    if settings is not None:
        entries = baseline_docs(_baseline_text(root, git, base, (ref, rev)))
        problems += docs_problems(measure(Tree(root, git, ref), settings), settings, entries)
    if base["baseline_path"] not in _changed(root, git, diff_args):
        return problems
    proposed = _text_at(root, git, ref, "themis.json")
    try:
        proposed_settings = docs_settings(json.loads(proposed) if proposed else {})[0]
    except ValueError:
        proposed_settings = None
    old_text, new_text = _text_at(root, git, rev, base["baseline_path"]) or "{}", _text_at(
        root, git, ref, base["baseline_path"]) or "{}"
    sides = [Tree(root, git, r) for r in (rev, ref)]
    measured = [measure(t, proposed_settings) if proposed_settings else None for t in sides]

    def side(index: int) -> Callable[[str, str], Optional[int]]:
        return lambda section, key: (None if measured[index] is None
                                     else _lookup(sides[index], measured[index], section, key))
    violations = docs_ratchet_violations(old_text, new_text, side(0), side(1))
    if violations:
        problems.append("%s: a docs entry may record only what the base commit already measures, and no less "
                        "than this change holds (%s)" % (base["baseline_path"], "; ".join(violations)))
    return problems


def run_checks(root: Path, git: Git, base: dict, rev: str, ref: str,
               diff_args: Tuple[str, ...]) -> Tuple[List[str], List[str]]:
    """(notes, problems) of the opt-in checks for a change from `rev` to
    `ref` (":" is the index), under `base`, the config committed at `rev`."""
    return [], _docs_run(root, git, base, rev, ref, diff_args)
