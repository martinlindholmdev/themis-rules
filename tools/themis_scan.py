"""Scans source text for comments and literals in seven brace languages.

Purpose: walk Rust, Go, Swift, Kotlin, Java, C# and JS/TS text once, blank
every comment and literal (keeping newlines), and collect the comments with
their line numbers, for themis_lang.py to measure and match.
Entry points: Scan(text, lang) with lang one of rust, go, swift, kotlin,
java, csharp, js; its code, comments, notes, broken and line_at();
legacy_comments(), a plain scanner for other languages, and
python_comments(), which reads Python through the tokenizer.
Invariants: standard library only, python3 3.9+; pure over the text, no file
access, no printing, no module-level mutable state; code has the same
length and line breaks as the text, and a literal leaves one quote mark; an
unterminated literal is not a literal; a RecursionError from absurd nesting
sets broken instead of raising; comments nest in Rust, Swift and Kotlin.
Never change without a decision: the language names and the blanking rule
(newlines kept, offsets unchanged), which every line number depends on.
"""

from __future__ import annotations

import bisect
import io
import re
import tokenize
from typing import Dict, List, Optional, Tuple

_NESTED = {"rust", "swift", "kotlin"}
_JS_REGEX_KW = {"return", "typeof", "case", "do", "else", "in", "of", "new", "delete",
                "void", "throw", "yield", "await"}

# ---- scanner patterns ------------------------------------------------------
_NEXT = {
    "rust": re.compile(r"/[/*]|[(){}\"']|(?<!\w)[bcr](?=[#\"'r])"),
    "swift": re.compile(r"/[/*]|[(){}\"#`]"),
    "kotlin": re.compile(r"/[/*]|[(){}\"'`]"),
    "go": re.compile(r"/[/*]|[(){}\"'`]"),
    "java": re.compile(r"/[/*]|[(){}\"']"),
    "csharp": re.compile(r"/[/*]|[(){}\"']"),
    "js": re.compile(r"/[/*]|[(){}\"'`/]"),
}
_RUST_RAW = re.compile(r'(?<!\w)[bc]?r(#*)"')
_RUST_STR = re.compile(r'(?<!\w)[bc]?"')
_RUST_CHAR = re.compile(r"(?<!\w)b?'(?:\\(?:x..|u\{[0-9a-fA-F]{1,6}\}|.)|[^\\\n'])'", re.S)
_SWIFT_STR = re.compile(r'(#*)("""|"|/)')
_CS_RAW = re.compile(r'"{3,}')
_DIRECTIVE = re.compile(r"[ \t]*#[ \t]*(\w+)")
_DIRECTIVE_WORDS = {"if", "ifdef", "ifndef", "else", "elif", "elseif", "endif", "region",
                    "endregion", "pragma", "define", "undef", "line", "nullable", "warning", "error"}
_NON_NEWLINE = re.compile(r"[^\n]")


class Scan:
    """code: the text with every literal and comment blanked (newlines kept);
    comments: (line, text); notes: what the scan could not read cleanly."""

    def __init__(self, text: str, lang: str) -> None:
        self.t, self.lang, self.n = text, lang, len(text)
        self.keep = bytearray(b"\x01") * self.n
        self.spans: List[Tuple[int, int, bool]] = []
        self.comments: List[Tuple[int, str]] = []
        self.notes: List[str] = []
        self.broken = False
        self.starts = [0] + [m.end() for m in re.finditer("\n", text)]
        if lang in ("csharp", "swift"):
            self.blank_directives()
        try:
            self.code_until(0, None)
        except RecursionError:
            self.broken = True
        self.code = self.build_code()

    def line_at(self, i: int) -> int:
        return bisect.bisect_right(self.starts, i)

    def blank(self, a: int, b: int, literal: bool = False) -> None:
        self.keep[a:b] = b"\x00" * (b - a)
        self.spans.append((a, b, literal))

    def build_code(self) -> str:
        out, pos = [], 0
        for a, b, literal in sorted(self.spans):
            if b <= pos:
                continue
            a = max(a, pos)
            out.append(self.t[pos:a])
            out.append(_NON_NEWLINE.sub(" ", self.t[a:b]))
            if literal and a < b and out[-1][:1] == " ":
                out[-1] = '"' + out[-1][1:]                     # a literal stays as one quote mark
            pos = b
        out.append(self.t[pos:])
        return "".join(out)

    def blank_directives(self) -> None:
        """Directive lines are not code; an #else/#elif branch is dropped so
        a brace repeated across branches is counted once."""
        skip_depth, depth, pos = 0, 0, 0
        for raw in self.t.splitlines(keepends=True):
            m = _DIRECTIVE.match(raw)
            word = m.group(1) if m and m.group(1) in _DIRECTIVE_WORDS else ""
            if word.startswith("if"):
                depth += 1
            elif word in ("else", "elif", "elseif") and not skip_depth:
                skip_depth = depth
            elif word == "endif":
                if skip_depth == depth:
                    skip_depth = 0
                depth -= 1
            if word or skip_depth:
                self.blank(pos, pos + len(raw.rstrip("\r\n")))
            pos += len(raw)

    # ---- code ---------------------------------------------------------
    def code_until(self, i: int, closer: Optional[str]) -> int:
        """Scan code from i; with a closer (')' or '}'), stop after the
        unmatched one and return the index past it."""
        t, n, depth = self.t, self.n, 0
        opener = {"}": "{", ")": "("}.get(closer or "", "")
        pat = _NEXT[self.lang]
        while i < n:
            m = pat.search(t, i)
            if m is None:
                return n
            i = m.start()
            c = t[i]
            if c == "/" and t.startswith("//", i):
                i = self.line_comment(i)
            elif c == "/" and t.startswith("/*", i):
                i = self.block_comment(i)
            elif closer and c == opener:
                depth, i = depth + 1, i + 1
            elif closer and c == closer:
                if depth == 0:
                    return i + 1
                depth, i = depth - 1, i + 1
            elif c in "(){}":
                i += 1
            else:
                j = self.literal(i)
                i = j if j is not None else i + 1
        return n

    def line_comment(self, i: int) -> int:
        end = self.t.find("\n", i)
        end = self.n if end == -1 else end
        self.comments.append((self.line_at(i), self.t[i + 2:end]))
        self.blank(i, end)
        return end

    def block_comment(self, i: int) -> int:
        t, depth, j = self.t, 1, i + 2
        while j < self.n and depth:
            if self.lang in _NESTED and t.startswith("/*", j):
                depth, j = depth + 1, j + 2
            elif t.startswith("*/", j):
                depth, j = depth - 1, j + 2
            else:
                j += 1
        if depth:
            self.notes.append("unterminated comment at line %d" % self.line_at(i))
        first = self.line_at(i)
        for k, part in enumerate(t[i + 2:j - 2 if not depth else j].split("\n")):
            self.comments.append((first + k, part))
        self.blank(i, j)
        return j

    def prev_code(self, i: int) -> Tuple[str, str]:
        """(previous non-space code char, word ending there)."""
        j = i - 1
        while j >= 0 and (not self.keep[j] or self.t[j].isspace()):
            j -= 1
        if j < 0:
            return "", ""
        if j + 1 < i and not self.keep[j + 1] and not self.t[j + 1].isspace():
            return ")", ""                                     # a literal ends an operand
        k = j
        while k >= 0 and self.keep[k] and (self.t[k].isalnum() or self.t[k] in "_$"):
            k -= 1
        return self.t[j], self.t[k + 1:j + 1]

    # ---- literals -----------------------------------------------------
    def literal(self, i: int) -> Optional[int]:
        """If a literal starts at i, blank it and return the index past it."""
        t, lang, c = self.t, self.lang, self.t[i]
        start, j = i, None
        if c == "`" and lang in ("kotlin", "swift"):           # `identifier`, kept as code
            nl = t.find("\n", i)
            end = t.find("`", i + 1, self.n if nl == -1 else nl)
            return end + 1 if end != -1 else i + 1
        if lang == "rust":
            j = self.rust_literal(i)
        elif lang == "swift":
            j = self.swift_literal(i)
        elif c == "/":
            j = self.js_slash(i)
        else:
            got = self.quote_literal(i)
            if got:
                start, j = got
        if j is None or j < 0:
            return None                                        # unterminated: not a literal
        self.blank(start, j, True)
        return j

    def quote_literal(self, i: int) -> Optional[Tuple[int, int]]:
        """(start, end) of a quoted literal at i for Go, Java, Kotlin, C#, JS."""
        t, lang, c = self.t, self.lang, self.t[i]
        before = t[i - 1] if i else ""
        start, j = i, None
        if lang == "js" and c in "'\"" and (before.isalnum() or before in "_$"):
            return None                                        # JSX text: not a string
        if lang == "csharp" and c == '"':
            start = self.prefix_start(i)
            j = self.csharp_string(i)
        elif t.startswith('"""', i) and lang in ("kotlin", "java"):
            j = self.quoted(i + 3, '"""', "${" if lang == "kotlin" else None, True, lang == "java")
        elif c == "`" and lang in ("js", "go"):
            j = self.quoted(i + 1, "`", "${" if lang == "js" else None, True, lang == "js")
        elif c in "\"'":
            j = self.quoted(i + 1, c, "${" if lang == "kotlin" and c == '"' else None)
        return (start, j) if j is not None and j >= 0 else None

    def prefix_start(self, i: int) -> int:
        while i > 0 and self.t[i - 1] in "$@":
            i -= 1
        return i

    def quoted(self, i: int, close: str, interp: Optional[str] = None, multi: bool = False,
               escapes: bool = True, interp_close: str = "}") -> int:
        t, n = self.t, self.n
        while i < n:
            if escapes and t[i] == "\\":
                i += 2
            elif t.startswith(close, i):
                k = i + len(close)
                if close == '"""':                             # """" ends at the last quote
                    while k < n and t[k] == '"':
                        k += 1
                return k
            elif interp and t.startswith(interp, i):
                i = self.code_until(i + len(interp), interp_close)
            elif t[i] == "\n" and not multi:
                return i                                       # recover at end of line
            else:
                i += 1
        return -1

    def rust_literal(self, i: int) -> Optional[int]:
        t = self.t
        m = _RUST_RAW.match(t, i)
        if m:
            end = t.find('"' + m.group(1), m.end())
            return self.n if end == -1 else end + 1 + len(m.group(1))
        m = _RUST_STR.match(t, i)
        if m:
            return self.quoted(m.end(), '"', multi=True)
        m = _RUST_CHAR.match(t, i)
        return m.end() if m else None                          # a lifetime is not a char

    def swift_literal(self, i: int) -> Optional[int]:
        t = self.t
        m = _SWIFT_STR.match(t, i)
        if not m or (m.group(2) == "/" and not m.group(1)):
            return None                                        # bare /regex/ is not read
        hashes, q = m.group(1), m.group(2)
        if q == "/":
            end = t.find("/" + hashes, m.end())
            return self.n if end == -1 else end + 1 + len(hashes)
        return self.quoted(m.end(), q + hashes, "\\" + hashes + "(", q == '"""',
                           not hashes, ")")

    def csharp_string(self, i: int) -> int:
        t, n = self.t, self.n
        pre = t[self.prefix_start(i):i]
        dollars = pre.count("$")
        m = _CS_RAW.match(t, i)
        if m:                                                  # raw """...""", $$"""..."""
            end = t.find(m.group(), m.end())
            return n if end == -1 else end + len(m.group())
        verbatim, j = "@" in pre, i + 1
        while j < n:
            if verbatim and t.startswith('""', j):
                j += 2
            elif t[j] == '"':
                return j + 1
            elif t[j] == "\\" and not verbatim:
                j += 2
            elif t[j] == "\n" and not verbatim:
                return j
            elif dollars and t[j] == "{" and not t.startswith("{{", j):
                j = self.code_until(j + 1, "}")
            else:
                j += 1 + bool(dollars and t.startswith("{{", j))
        return n

    def js_slash(self, i: int) -> Optional[int]:
        """A regex literal at i (JS only), or None for a division sign."""
        if self.lang != "js":
            return None
        p, word = self.prev_code(i)
        if p == "<" or (p and (p.isalnum() or p in "_$)]}") and word not in _JS_REGEX_KW):
            return None                                        # closing tag or division
        t, j, in_class = self.t, i + 1, False
        while j < self.n and t[j] != "\n":
            if t[j] == "\\":
                j += 2
                continue
            if t[j] == "[":
                in_class = True
            elif t[j] == "]":
                in_class = False
            elif t[j] == "/" and not in_class:
                return j + 1
            j += 1
        return None


# ---- other languages -----------------------------------------------------------
def _find_unescaped(work: str, token: str) -> int:
    """Like str.find, but a hit right after ':' ('//' in 'https://') isn't one."""
    start = 0
    while True:
        idx = work.find(token, start)
        if idx <= 0 or work[idx - 1] != ":":
            return idx
        start = idx + len(token)

def legacy_comments(text: str, style: Tuple[Optional[str], Optional[Tuple[str, str]], object]) -> Dict[int, str]:
    """Line number -> comment text (not string-aware, but good enough to
    catch history words). Python files use python_comments() instead."""
    line_prefix, block, _ = style
    found: Dict[int, str] = {}
    in_block = False
    for number, line in enumerate(text.splitlines(), start=1):
        work = line
        if in_block:
            end = work.find(block[1])
            found[number] = work if end == -1 else work[:end]
            if end == -1:
                continue
            work, in_block = work[end + len(block[1]):], False
        line_idx = _find_unescaped(work, line_prefix) if line_prefix else -1
        block_idx = work.find(block[0]) if block else -1
        if line_idx == -1 and block_idx == -1:
            continue
        if block_idx == -1 or (line_idx != -1 and line_idx < block_idx):
            found[number] = found.get(number, "") + work[line_idx + len(line_prefix):]
            continue
        end = work.find(block[1], block_idx + len(block[0]))
        if end == -1:
            found[number] = found.get(number, "") + work[block_idx + len(block[0]):]
            in_block = True
        else:
            found[number] = found.get(number, "") + work[block_idx + len(block[0]):end]
    return found

def python_comments(text: str) -> Dict[int, str]:
    """Via the tokenizer, so a '#' inside a string is never a false
    comment; falls back to the generic scan if the file does not parse."""
    found: Dict[int, str] = {}
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.COMMENT:
                found[tok.start[0]] = found.get(tok.start[0], "") + tok.string.lstrip("#")
        return found
    except (tokenize.TokenError, IndentationError, SyntaxError, ValueError):
        return legacy_comments(text, ("#", None, None))
