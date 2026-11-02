"""Turning issue text into words and identifiers. Everything is linear in the text length and capped."""

from __future__ import annotations

import re

MAX_WORDS = 100
MAX_IDENTIFIERS = 200
MIN_WORD_CHARS = 3
MIN_IDENTIFIER_CHARS = 4

_WORD = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+")
_IDENT = r"[A-Za-z_][A-Za-z0-9_]*"
_BACKTICK = re.compile(r"`([^`\n]{1,200})`")
_DOTTED = re.compile(rf"{_IDENT}(?:\.{_IDENT})*")
_CAMEL = re.compile(r"\b(?:[A-Z][A-Za-z0-9]{2,}|[a-z]+[A-Z][A-Za-z0-9]*)\b")
_SNAKE = re.compile(r"\b_{0,2}[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+_{0,2}\b")
_CALL = re.compile(rf"\b({_IDENT})\(")
_DOTTED_PLAIN = re.compile(rf"(?<![\w./\\-]){_IDENT}(?:\.{_IDENT})+(?![\w(/])")
_FILE_ENDINGS = {"py", "pyi", "md", "txt", "rst", "json", "yaml", "yml", "toml", "cfg", "ini", "js", "ts", "c", "h", "html", "css", "sh", "com", "org", "net", "io", "git"}

STOP_WORDS = frozenset(
    """
    a about above after again all also am an and any are as at be because been before being below between both but by can cannot could did do does doing
    done down during each either else etc even ever every few for from further get gets got had has have having he her here hers him his how i if in into is it
    its just like made make makes many may me might more most much must my need needs new no nor not now of off often on once one only onto or other our out
    over own per please same see seems she should since so some such than that the their them then there these they this those though through thus to too
    under until up upon us use used uses using very via want was we well were what when where whether which while who whom whose why will with within without
    would yes yet you your
    bug issue problem error errors fail fails failed failing failure expected expect actual result results work works working worked break breaks broken
    code file files function functions method methods class classes test tests testing python version call calls called return returns returned value values
    raise raises raised exception exceptions traceback line lines none true false thing something anything seem happen happens happened instead maybe
    reproduce reproduction steps example examples following above below thanks thank hello hi report reported behavior behaviour output input
    """.split()
)

COMMON_NAMES = frozenset(
    "__init__ __call__ __str__ __repr__ __eq__ __hash__ __enter__ __exit__ __len__ __iter__ __new__ __del__ setup teardown self cls main".split()
)


def stem(word: str) -> str:
    """A very light stemmer so that `parsing`, `parsed` and `parses` meet `parse`."""
    if len(word) > 5 and word.endswith("ing"):
        word = word[:-3]
    elif len(word) > 4 and word.endswith("ed"):
        word = word[:-2]
    elif len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        word = word[:-1]
    return word[:-1] if len(word) > 3 and word.endswith("e") else word


def raw_words(text: str) -> list[str]:
    """Lowercase words from snake_case, camelCase and plain text; letters only, at least three letters."""
    return [w.lower() for w in _WORD.findall(text) if len(w) >= MIN_WORD_CHARS]


def split_words(text: str) -> list[str]:
    """`raw_words` with stems applied."""
    return [stem(w) for w in raw_words(text)]


def issue_words(text: str) -> dict[str, str]:
    """The distinct meaningful words of an issue, as `{stem: the word as first written}`, in order of first appearance (stop-words removed)."""
    seen: dict[str, str] = {}
    for raw in raw_words(text):
        if raw in STOP_WORDS:
            continue
        seen.setdefault(stem(raw), raw)
        if len(seen) >= MAX_WORDS:
            break
    return seen


def identifiers(text: str) -> list[str]:
    """Names that look like code: in backticks, CamelCase, snake_case, `name(` calls, and dotted names. Distinct, in order, capped.

    A dotted name comes through whole (`Cache.get`) and its plain last part is not added on its own."""
    found: dict[str, None] = {}

    def add(name: str) -> None:
        if len(name) >= MIN_IDENTIFIER_CHARS and name not in COMMON_NAMES and len(found) < MAX_IDENTIFIERS:
            parts = name.split(".")
            if parts[-1] in _FILE_ENDINGS:
                return
            found.setdefault(name, None)

    for match in _BACKTICK.finditer(text):
        for token in _DOTTED.findall(match.group(1)):
            add(token)
    for match in _CAMEL.finditer(text):
        word = match.group(0)
        humps = sum(c.isupper() for c in word)
        if any(c.islower() for c in word) and (humps >= 2 or word[0].islower()):  # CamelCase, LRUCache, getItem; not Config or HTTP
            add(word)
    for match in _SNAKE.finditer(text):
        add(match.group(0))
    for match in _CALL.finditer(text):
        add(match.group(1))
    for match in _DOTTED_PLAIN.finditer(text):
        add(match.group(0))
    return list(found)
