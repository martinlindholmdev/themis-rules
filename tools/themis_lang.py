"""Reads comments and measures function length in seven brace languages.

Purpose: for Rust, Go, Swift, Kotlin, Java, C# and JS/TS source text, find
every comment (string- and nesting-aware), measure each function's length
in lines, mark Rust test modules, spot generated files, match history words
in comments, and clamp per-extension limits to the hard limits.
Entry points: EXTENSIONS, functions(), comments(), test_spans(),
generated(), history_hits(), clamp_limits().
Invariants: standard library only, python3 3.9+; pure functions over text,
with no file or git access, no printing and no module-level mutable state;
odd input yields notes, never an exception; time is linear in the file plus
at most 2,000 characters per brace; a size runs from a function's first line
to its last; an anonymous function body outside any function is measured
too: with a binding name it runs first line to last and closures inside
count toward it; without one (<anonymous>#n) its size is its own lines, its
span minus the spans of the function blocks inside it, each measured and
keyed itself; a closure inside a named function counts toward that function.
Never change without a decision: the extension list, the key shape
(Type.method, #n for repeats), the 2,000-character header window and the
generated-file marker table.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.dont_write_bytecode = True
_SCAN_PATH = Path(__file__).resolve().parent / "themis_scan.py"
if not _SCAN_PATH.is_file():
    raise ImportError("themis_lang.py needs its sibling file %s" % _SCAN_PATH)
_spec = importlib.util.spec_from_file_location("themis_scan", _SCAN_PATH)
_scan_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_scan_module)
Scan = _scan_module.Scan

_FAMILY = {
    ".rs": "rust", ".go": "go", ".swift": "swift", ".kt": "kotlin", ".kts": "kotlin",
    ".java": "java", ".cs": "csharp", ".js": "js", ".jsx": "js", ".mjs": "js",
    ".cjs": "js", ".ts": "js", ".tsx": "js",
}
EXTENSIONS = tuple(_FAMILY)

_WINDOW = 2000
_BRACKET = re.compile(r"[()\[\]{}\n]")

# ---- header classification ---------------------------------------------------
_KW = {"if", "for", "while", "switch", "catch", "return", "new", "else", "do", "try", "foreach",
       "using", "lock", "fixed", "synchronized", "when", "function", "sizeof", "typeof",
       "checked", "unchecked", "defined", "with", "await", "throw", "yield", "case", "in", "is"}
_CONTAINER = {
    "rust": re.compile(r"\b(?:impl\b(?:\s*<[^{]*?>)?\s+(?:[^{]*?\bfor\s+)?&?(?:dyn\s+)?([\w:]+)"
                       r"|(?:trait|mod)\s+(\w+))"),
    "swift": re.compile(r"\b(?:class|struct|enum|extension|protocol|actor)\s+([\w.]+)"),
    "kotlin": re.compile(r"\b(?:class|interface|object)\s+(\w+)|\b(companion\s+object)\b"),
    "java": re.compile(r"\b(?:class|interface|enum|record|@interface)\s+(\w+)|\bnew\s+([\w.]+)"),
    "csharp": re.compile(r"\b(?:class|interface|struct|record|namespace)\s+([\w.]+)"),
    "js": re.compile(r"\bclass\s+([\w$]+)|\b(?:namespace|module)\s+([\w.$]+)"),
}
_SIG = {
    "rust": re.compile(r"\bfn\s+(?:r#)?([A-Za-z_]\w*)"),
    "go": re.compile(r"\bfunc\s+(?:\(\s*(?:\w+\s+)?\*?([A-Za-z_]\w*)[^()]*\)\s*)?([A-Za-z_]\w*)\s*(?=[\[(])"),
    "swift": re.compile(r"(?<![.\w])(?:func\s+([^\s(<]+|[-+*/%<>=!&|^~?.]+)|(init)[?!]?|(deinit)\b|(subscript))"
                        r"\s*(?:<[^{]*?>)?\s*(?=[({]|$)"),
    "kotlin": re.compile(r"\bfun\s+(?:<[^>]*>\s*)?(?:[\w.<>?, ]+\.)?(`[^`]+`|\w+)\s*(?=\()"
                         r"|\b(constructor)\s*(?=\()|\b(init)\s*$"),
}
_SWIFT_VAR = re.compile(r"\bvar\s+(\w+)\s*:\s*[^=]+$", re.S)
_GO_TYPE = re.compile(r"\b(struct|interface)\s*$")
_PAREN_PAIR = re.compile(r"\([^()]*\)")
_TEST_MOD = re.compile(r"#\[\s*cfg\s*\(\s*test\s*\)\s*\]\s*(?:#\[[^\]]*\]\s*)*"
                       r"(?:pub(?:\([^)]*\))?\s+)?mod\s+(\w+)\s*$")
_TRAILER = {
    "java": re.compile(r"\s*(throws\s+[\w.<>,\s]+)?\s*$"),
    "csharp": re.compile(r"\s*(:\s*(base|this)\s*\(.*\)\s*)?(where\s+.+)?\s*$", re.S),
    "js": re.compile(r"\s*(:\s*[^=;]+)?\s*$", re.S),
}
_JS_MOD = re.compile(r"^(?:\s*(?:@[\w.]+(?:\([^)]*\))?|public|private|protected|static|async|get|set|"
                     r"readonly|override|abstract|export|default|declare)\b)*\s*\*?\s*", re.S)
_JS_ARROW = re.compile(r"(?:^|[\s,;{])(?:(?:const|let|var)\s+)?(#?[\w$]+)\s*(?:\?\s*)?(?::[^=]*?)?[=:]\s*"
                       r"(?:async\s*)?(?:<[^>]*>\s*)?(?:\(.*\)|[\w$]+)\s*(?::[^=]*)?=>\s*$", re.S)
_JS_FUNC = re.compile(r"\bfunction\b\s*\*?\s*([\w$]*)\s*(?:<[^>]*>)?\s*\(")
_JS_FUNC_EXPR = re.compile(r"(?:const|let|var)\s+([\w$]+)\s*(?::[^=]*)?=\s*(?:async\s+)?function\b")
_JS_FUNC_TAIL = re.compile(r"\bfunction\b\s*\*?\s*([\w$]*)[^{};]*$")
_ATTRS = re.compile(r"@[\w.]+(?:\([^()]*\))?|^\s*\[[^\]]*\]")
_CALL_NAME = re.compile(r"([A-Za-z_$][\w$]*)\s*(?:<[^()<>]*>)?\s*$")
_CALL_PRE = re.compile(r"(?:\bnew|\.|=|\breturn|\bcase)\s*$")
_GO_LIT = re.compile(r"(?:([A-Za-z_]\w*)\s*(?::=|=|:)\s*)?\bfunc\s*\([^{}]*$")
_ARROW_BIND = re.compile(r"(?:([\w$]+)\s*=\s*)?[^=;]*?(?:->|=>)\s*$")
_CS_DELEGATE = re.compile(r"(?:([\w$]+)\s*=\s*)?(?:async\s+)?\bdelegate\b[^{};]*$")
_FIRST_WORD = re.compile(r"\s*(?:@[\w.]+(?:\([^)]*\))?\s+)*(\w+)")
_CONTROL = {"if", "else", "for", "while", "switch", "guard", "do", "try", "catch", "finally",
            "when", "defer", "repeat", "case", "default", "get", "set", "willSet", "didSet"}
_NOT_CLOSURE = re.compile(r"\b(?:class|struct|enum|interface|protocol|extension|object|actor|"
                          r"record|new|typealias|where|import)\b")
_CALL_END = re.compile(r"[\w)\]>?!=]$")
_PROPERTY = re.compile(r"\b(?:val|var|let)\s+(\w+)\b[^=]*=[^=]*$")


def _top_tail(h: str) -> Tuple[str, int]:
    """(text after the last depth-0 comma, its offset): one object-literal entry."""
    depth, cut = 0, 0
    for m in re.finditer(r"[()\[\]{},]", h):
        ch = m.group()
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth = max(depth - 1, 0)
        elif depth == 0:
            cut = m.end()
    return h[cut:], cut


def _first_call(header: str) -> Optional[Tuple[str, int, str]]:
    """(name before the first depth-0 '(', its index, text after its ')')."""
    depth = 0
    for m in re.finditer(r"[()\[\]]", header):
        ch = m.group()
        if ch == "(" and depth == 0:
            name = _CALL_NAME.search(header[:m.start()])
            close, d = m.start(), 0
            for p in re.finditer(r"[()]", header[m.start():]):
                d += 1 if p.group() == "(" else -1
                if d == 0:
                    close = m.start() + p.start()
                    break
            else:
                close = len(header)
            return (name.group(1) if name else "", name.start(1) if name else m.start(),
                    header[close + 1:])
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth = max(depth - 1, 0)
    return None


def _sig_func(h: str, lang: str) -> Optional[Tuple[str, str, int]]:
    """A Rust, Go, Swift or Kotlin function header ending at the brace."""
    if lang not in _SIG:
        return None
    ms = list(_SIG[lang].finditer(h))
    if not ms:
        return None
    m = ms[-1]
    name = next(g for g in m.groups() if g) if lang != "go" else (m.group(1) + "." if m.group(1) else "") + m.group(2)
    rest = h[m.end():]
    flat = rest
    while _PAREN_PAIR.search(flat):
        flat = _PAREN_PAIR.sub("", flat)
    if ";" in rest or (lang in ("swift", "kotlin") and "=" in re.sub(r"->|==|<=|>=|!=", "", flat)):
        return None
    return "func", name, m.start()


def _swift_var(h: str, lang: str) -> Optional[Tuple[str, str, int]]:
    m = _SWIFT_VAR.search(h) if lang == "swift" else None
    return ("func", m.group(1), m.start()) if m else None


def _container(h: str, lang: str) -> Optional[Tuple[str, str, int]]:
    if lang == "go":
        return None
    mc = _CONTAINER[lang].search(h)
    return ("container", next((g for g in mc.groups() if g), ""), 0) if mc else None


def _js_func(h: str, lang: str) -> Optional[Tuple[str, str, int]]:
    """A JS/TS function declaration, named function expression or named arrow."""
    if lang != "js":
        return None
    if re.search(r"\)\s*:\s*$", h):
        return "type", "", 0                                   # TS return or parameter type literal
    m = _JS_FUNC.search(h) if "function" in h else None
    if m:
        named = _JS_FUNC_EXPR.search(h)
        name = m.group(1) or (named.group(1) if named else "")
        if not name and re.search(r"\bexport\s+default\s+(?:async\s+)?function\b", h):
            name = "default"
        if name:
            return "func", name, m.start()
    if h.rstrip().endswith("=>"):
        tail, cut = _top_tail(h)
        a = _JS_ARROW.search(tail)
        if a and a.group(1) not in _KW:
            return "func", a.group(1), cut + a.start(1)
    return None


def _trailer_func(h: str, lang: str) -> Optional[Tuple[str, str, int]]:
    """A Java, C# or JS method: a call-shaped header with only a legal trailer."""
    if lang not in _TRAILER:
        return None
    off = 0
    if lang == "js":
        off = _JS_MOD.match(h).end()
    else:
        h = _ATTRS.sub(lambda m: " " * len(m.group()), h)
    call = _first_call(h[off:])
    if not call or not call[0] or call[0] in _KW:
        return None
    if _CALL_PRE.search(h[:off + call[1]].rstrip()) or not _TRAILER[lang].match(call[2]):
        return None
    return "func", call[0], off + call[1]


def _anon_name(h: str, lang: str) -> Optional[str]:
    """For a header that ends in an anonymous function body: its binding name,
    or "" when it has none; None when the brace is not a function body."""
    h = h.rstrip()
    if not h:
        return None
    if lang == "js":
        if h.endswith("=>"):
            return ""
        m = _JS_FUNC_TAIL.search(h)
        return m.group(1) if m else None
    if lang == "go":
        m = _GO_LIT.search(h)
        return (m.group(1) or "") if m else None
    if lang in ("java", "csharp"):
        arrow = "->" if lang == "java" else "=>"
        m = _ARROW_BIND.search(h) if h.endswith(arrow) else None
        m = m or (_CS_DELEGATE.search(h) if lang == "csharp" else None)
        return (m.group(1) or "") if m else None
    if lang in ("swift", "kotlin"):
        return _trailing_closure(h, lang)
    return None


def _trailing_closure(h: str, lang: str) -> Optional[str]:
    first = _FIRST_WORD.match(h)
    if not first or first.group(1) in _CONTROL or _NOT_CLOSURE.search(h) or not _CALL_END.search(h):
        return None
    m = _PROPERTY.search(h)
    if m:
        return m.group(1)
    fun = list(_SIG[lang].finditer(h)) if lang == "kotlin" else []
    return next(g for g in fun[-1].groups() if g) if fun else ""


def _classify(h: str, lang: str, outside: bool) -> Tuple[str, str, int]:
    """(kind, name, pos): kind is func, container, test, anon, type or block;
    pos is where a function or test module starts within h."""
    if lang == "go" and _GO_TYPE.search(h):
        return "type", "", 0
    if lang == "rust":
        m = _TEST_MOD.search(h)
        if m:
            return "test", m.group(1), m.start()
    for probe in (_sig_func, _swift_var, _container, _js_func, _trailer_func):
        got = probe(h, lang)
        if got:
            return got
    if outside:
        name = _anon_name(h, lang)
        if name is not None:
            return "anon", name, 0
    return "block", "", 0


# ---- structure pass ----------------------------------------------------------
_TOKEN = re.compile(r"[()\[\]{},;]")
_NEWLINE_LANGS = {"js", "go", "swift", "kotlin"}
_ENDERS = (",", "(", "[", "=", "+", "-", ".", "&", "|", ":", "^", "=>", "->")
_STARTER = re.compile(r"[.,?:&|+\-=)\]>*{^]|(?:where|extends|implements|throws|rethrows)\b")
_NAMED = ("func", "container", "test")


class _Frame:
    __slots__ = ("kind", "name", "start", "seg", "line", "arg", "nested", "covered")

    def __init__(self, kind: str, line: int, arg: int = 0) -> None:
        self.kind, self.line, self.arg = kind, line, arg
        self.name, self.start, self.seg, self.nested, self.covered = "", line, 0, False, 0


class _Finder:
    def __init__(self, scan: Scan, lang: str) -> None:
        self.scan, self.code, self.lang = scan, scan.code, lang
        self.sizes: Dict[str, int] = {}
        self.notes: List[str] = list(scan.notes)
        self.tests: List[Tuple[int, int]] = []
        self.stack: List[_Frame] = []
        self.seen: Dict[str, int] = {}
        self.counted, self.seg, self.stray = 0, 0, 0

    def run(self) -> None:
        for m in _TOKEN.finditer(self.code):
            i, ch = m.start(), m.group()
            top = self.stack[-1] if self.stack else None
            in_paren = top is not None and top.kind == "paren"
            if ch in "([":
                self.stack.append(_Frame("paren", self.scan.line_at(i), i + 1))
            elif ch in ")]":
                if in_paren:
                    self.stack.pop()
            elif ch == ",":
                if in_paren:
                    top.arg = i + 1
            elif ch == ";":
                if not in_paren:
                    self.seg = i + 1
            elif ch == "{":
                self.open(i, in_paren, top)
            else:
                self.close(i)
        self.finish()

    def trim(self, i: int) -> int:
        """Start of the last statement of the header ending at i: for
        newline-terminated languages a depth-0 line break ends a statement
        unless the lines around it continue one."""
        code = self.code
        hs = max(self.seg, i - _WINDOW)
        if self.lang not in _NEWLINE_LANGS or code.find("\n", hs, i) == -1:
            return hs
        depth, cands = 0, []
        for m in _BRACKET.finditer(code, hs, i):
            ch = m.group()
            if ch == "\n":
                if depth == 0:
                    cands.append(m.end())
            elif ch in "([{":
                depth += 1
            else:
                depth = max(depth - 1, 0)
        for c in reversed(cands):
            before, after = code[hs:c].rstrip(), code[c:i].lstrip()
            if before and after and self.ends_statement(before) and not _STARTER.match(after):
                return c
        return hs

    @staticmethod
    def ends_statement(before: str) -> bool:
        if before.endswith(("++", "--")):
            return True
        return not (before.endswith(_ENDERS) or before.endswith(" ?"))

    def open(self, i: int, in_paren: bool, top: Optional[_Frame]) -> None:
        line = self.scan.line_at(i)
        outside = self.counted == 0
        hs = max(top.arg, i - _WINDOW) if in_paren else self.trim(i)
        header = self.code[hs:i]
        kind, name, pos = "type", "", 0
        if not in_paren or outside:
            kind, name, pos = _classify(header, self.lang, outside)
            if in_paren and kind not in ("container", "anon", "func"):
                kind = "type"
        f = _Frame(kind, line)
        f.name, f.seg, f.nested = name, self.seg, in_paren
        f.start = self.scan.line_at(hs + pos) if kind in ("func", "test") else line
        self.counted += self.counts(f)
        self.stack.append(f)
        self.seg = i + 1

    def close(self, i: int) -> None:
        while self.stack and self.stack[-1].kind == "paren":
            self.stack.pop()
        if not self.stack:
            if not self.stray:
                self.stray = self.scan.line_at(i)
                self.notes.append("unmatched closing brace at line %d" % self.stray)
            self.seg = i + 1
            return
        f = self.stack.pop()
        line = self.scan.line_at(i)
        if f.kind in ("func", "anon"):
            self.counted -= self.counts(f)
            self.record(f, line)
        elif f.kind == "test":
            self.tests.append((f.start, line))
        self.seg = f.seg if f.kind == "type" or f.nested else i + 1

    @staticmethod
    def counts(f: _Frame) -> int:
        """1 when a block swallows the closures inside it: a function or a
        bound closure. An unbound closure does not, so what is inside it is
        measured on its own."""
        return 1 if f.kind == "func" or (f.kind == "anon" and f.name) else 0

    def record(self, f: _Frame, line: int) -> None:
        prefix = ".".join(s.name for s in self.stack if s.kind in _NAMED and s.name)
        base = (prefix + "." if prefix else "") + (f.name or "<anonymous>")
        self.seen[base] = n = self.seen.get(base, 0) + 1
        key = base + "#%d" % n if (n > 1 or not f.name) else base
        span = line - f.start + 1
        outer = next((s for s in reversed(self.stack) if s.kind in ("func", "anon")), None)
        if outer is not None and outer.kind == "anon" and not outer.name:
            outer.covered += span
        self.sizes[key] = max(span - f.covered, 1)

    def finish(self) -> None:
        braces = [f for f in self.stack if f.kind != "paren"]
        if braces:
            self.notes.append("unclosed brace: functions after line %d not measured" % braces[0].line)
        elif self.stack:
            self.notes.append("unclosed parenthesis at line %d: functions after it may be missed"
                              % self.stack[0].line)


def _find(text: str, ext: str) -> Tuple[Optional[_Finder], List[str]]:
    lang = _FAMILY.get(ext)
    if lang is None:
        return None, ["%s: extension not measured" % ext]
    scan = Scan(text, lang)
    if scan.broken:
        return None, ["nesting too deep to read: functions not measured"]
    finder = _Finder(scan, lang)
    finder.run()
    return finder, finder.notes


def functions(text: str, ext: str) -> Tuple[Dict[str, int], List[str]]:
    """({qualified name: lines}, notes). Notes say what could not be read."""
    finder, notes = _find(text, ext)
    return (finder.sizes if finder else {}), notes


def test_spans(text: str, ext: str) -> List[Tuple[int, int]]:
    """Line spans of Rust `#[cfg(test)] mod` blocks; empty for other languages."""
    if ext != ".rs":
        return []
    finder, _ = _find(text, ext)
    return finder.tests if finder else []


def comments(text: str, ext: str) -> Dict[int, str]:
    """Line number -> comment text, string- and nesting-aware."""
    lang = _FAMILY.get(ext)
    if lang is None:
        return {}
    found: Dict[int, str] = {}
    for number, part in Scan(text, lang).comments:
        found[number] = found.get(number, "") + part
    return found


# ---- generated files ---------------------------------------------------------
_GENERATED = re.compile(
    r"Code generated .*? DO NOT EDIT|@generated\b|Generated by the protocol buffer compiler"
    r"|Generated by the Swift generator plugin|Generated by the gRPC|Autogenerated by Thrift Compiler"
    r"|DO NOT EDIT THIS FILE - it is machine generated|<auto-?generated", re.IGNORECASE)


def generated(text: str) -> Optional[str]:
    """The generated-file marker found in the first 10 comment lines before
    any code, else None."""
    taken, in_block = [], False
    for raw in text.splitlines():
        line = raw.strip()
        if in_block:
            in_block = "*/" not in line
        elif not line:
            continue
        elif line.startswith("/*"):
            in_block = "*/" not in line
        elif not line.startswith(("//", "*")):
            break
        taken.append(line)
        if len(taken) == 10:
            break
    m = _GENERATED.search("\n".join(taken))
    return m.group()[:80] if m else None


# ---- history words -----------------------------------------------------------
_QUOTED = re.compile(r"`[^`]*`|\"(?:[^\"\\]|\\.)*\"|\b(?:https?|ftp)://\S+|\bwww\.\S+")
_FENCE = re.compile(r"^[\s*/!]*```")
_PRESENT_PASSIVE = re.compile(r"\b(is|are|be|been|being|get|gets)\s+$", re.IGNORECASE)
_SUBJECT = re.compile(r"\b(?:it|this|that|we|they|he|she|there|which|who|I|you)"
                      r"(?:\s+(?:always|never|also|once))?\s+$", re.IGNORECASE)
_USED_TO_BE = re.compile(r"\s*be\b", re.IGNORECASE)
_DIDNT_USE = re.compile(r"\b(?:didn't|did not)\s+use to\b", re.IGNORECASE)
_NEXT_WORD = re.compile(r"\s+([A-Za-z]+)")
_PARTICIPLES = {"set", "made", "done", "run", "built", "given", "taken", "shown", "seen",
                "written", "kept", "sent", "chosen", "known", "held", "found", "put", "cut"}


def _flagged(line: str, match: "re.Match[str]") -> bool:
    word = match.group().lower()
    if word == "used to":
        before = line[:match.start()]
        if _PRESENT_PASSIVE.search(before):
            return False
        return bool(_SUBJECT.search(before) or _USED_TO_BE.match(line, match.end()))
    if word == "previously":
        nxt = _NEXT_WORD.match(line, match.end())
        w = nxt.group(1).lower() if nxt else ""
        return not (w in _PARTICIPLES or (len(w) > 3 and w.endswith("ed")))
    return True


def history_hits(found: Dict[int, str], pattern: "re.Pattern[str]") -> List[Tuple[int, str]]:
    """(line, word) for each comment line that narrates history: quoted
    text, backtick spans, URLs and fenced code are ignored first."""
    hits, fenced, prev = [], False, 0
    for number in sorted(found):
        if number != prev + 1:
            fenced = False
        prev = number
        if _FENCE.match(found[number]):
            fenced = not fenced
            continue
        if fenced:
            continue
        line = _QUOTED.sub(" ", found[number])
        hit = _DIDNT_USE.search(line)
        for match in pattern.finditer(line):
            if _flagged(line, match):
                hit = match
                break
        if hit:
            hits.append((number, hit.group()))
    return hits


# ---- limits ------------------------------------------------------------------
def clamp_limits(config_limits: object, ext: str, file_max: int, function_max: int) -> Tuple[int, int]:
    """(file limit, function limit) for an extension: a configured value can
    only tighten the hard limits; anything else falls back to them."""
    entry = config_limits.get(ext) if isinstance(config_limits, dict) else None
    entry = entry if isinstance(entry, dict) else {}

    def pick(key: str, hard: int) -> int:
        v = entry.get(key)
        ok = isinstance(v, int) and not isinstance(v, bool) and v >= 1
        return min(hard, v) if ok else hard

    return pick("file", file_max), pick("function", function_max)
