"""A small, fast S-expression reader for KiCad files.

KiCad 6+ stores schematics (.kicad_sch), boards (.kicad_pcb), and projects in
S-expressions. Parsing them directly rather than shelling out to `kicad-cli`
means the HUD can read a BOM off a schematic **without KiCad installed at
all** — which matters, because the machine reviewing a design is often not the
machine that authored it.

Deliberately not a general Lisp reader: no quoting, no dotted pairs, no
numeric coercion. KiCad's dialect is atoms, quoted strings with backslash
escapes, and nested lists. Keeping it to that makes it a single linear scan.
"""

from __future__ import annotations

from typing import Iterator, Union

Node = Union[str, list["Node"]]

_WHITESPACE = " \t\r\n"


class SExprError(ValueError):
    """Malformed input. Callers treat this as 'unreadable file', never a crash."""


def _tokenize(text: str) -> Iterator[str]:
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]

        if ch in _WHITESPACE:
            i += 1
            continue

        if ch in "()":
            yield ch
            i += 1
            continue

        if ch == '"':
            start = i
            i += 1
            buf: list[str] = []
            while i < n:
                c = text[i]
                if c == "\\" and i + 1 < n:
                    # KiCad escapes quotes and backslashes inside strings.
                    nxt = text[i + 1]
                    buf.append({"n": "\n", "t": "\t"}.get(nxt, nxt))
                    i += 2
                    continue
                if c == '"':
                    i += 1
                    yield '"' + "".join(buf)
                    break
                buf.append(c)
                i += 1
            else:
                raise SExprError(f"unterminated string at offset {start}")
            continue

        start = i
        while i < n and text[i] not in _WHITESPACE and text[i] not in "()":
            i += 1
        yield text[start:i]


def loads(text: str) -> Node:
    """Parse one S-expression. Quoted strings come back prefixed with '"'.

    The prefix is how callers distinguish the string "1k" from the bare atom
    1k — KiCad property values are always quoted, symbol names never are.
    """
    stack: list[list[Node]] = []
    root: Node | None = None

    for token in _tokenize(text):
        if token == "(":
            new: list[Node] = []
            if stack:
                stack[-1].append(new)
            stack.append(new)
        elif token == ")":
            if not stack:
                raise SExprError("unbalanced closing paren")
            done = stack.pop()
            if not stack:
                root = done
        else:
            if not stack:
                raise SExprError("atom outside any list")
            stack[-1].append(token)

    if stack:
        raise SExprError("unbalanced opening paren")
    if root is None:
        raise SExprError("empty input")
    return root


def unquote(token: Node) -> str:
    """Strip the quoted-string marker added by loads()."""
    if isinstance(token, str) and token.startswith('"'):
        return token[1:]
    return token if isinstance(token, str) else ""


def head(node: Node) -> str:
    """The symbol naming a list, e.g. 'symbol' for (symbol ...)."""
    if isinstance(node, list) and node and isinstance(node[0], str):
        return node[0]
    return ""


def find_all(node: Node, name: str) -> Iterator[list[Node]]:
    """Every descendant list whose head is `name`, depth-first."""
    if not isinstance(node, list):
        return
    if head(node) == name:
        yield node
    for child in node:
        if isinstance(child, list):
            yield from find_all(child, name)


def children(node: Node, name: str) -> Iterator[list[Node]]:
    """Direct children only — avoids matching nested symbols inside a symbol."""
    if not isinstance(node, list):
        return
    for child in node:
        if isinstance(child, list) and head(child) == name:
            yield child
