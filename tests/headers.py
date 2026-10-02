"""Purpose: the header text that test fixtures open with, so a fixture that
is not about headers passes rule 2 and each test fails only for its own reason.
Entry points: PY (a docstring), HASH (# lines) and SLASH (// lines), each
ending in a newline, imported by the tests that write throwaway files.
Invariants: every constant holds the four labels, each with real text, in a
handful of lines.
Never change without a decision: the four labels, which are rule 2's.
"""

BODY = ("Purpose: a throwaway fixture.\nEntry points: none.\nInvariants: none.\n"
        "Never change without a decision: nothing.\n")
PY = '"""' + BODY + '"""\n'
HASH = "".join("# " + line + "\n" for line in BODY.splitlines())
SLASH = "".join("// " + line + "\n" for line in BODY.splitlines())
