"""The code view: source text as content signals should see it.

Detectors look for evidence of practices (webhooks, OAuth, rate limits...) by
matching source text. Text that talks *about* a practice is not evidence of
it: comments, docstrings and regular expressions. A linter or scanner (this
one included) is full of regexes naming exactly the things detectors look
for. The code view removes comments and docstrings and blanks the contents of
regex literals, keeping their delimiters so the surrounding syntax still
matches (`re_path(r'...')` still looks like a route).

Python is handled with `tokenize`; C-family languages and `#`-comment
languages with a small scanner. Anything that fails to scan is returned as is.
"""
from __future__ import annotations

import io
import re
import tokenize
from typing import List

C_LIKE = {"javascript", "typescript", "go", "rust", "java", "kotlin", "scala", "c", "cpp", "csharp",
          "swift", "dart", "php", "vue", "svelte"}
HASH_COMMENT = {"ruby", "perl", "shell", "elixir", "r", "julia"}
JS_LIKE = {"javascript", "typescript", "vue", "svelte"}

# Strings that read like English sentences are messages, help texts and
# prompts: prose *about* things, not usage of them.
STOPWORDS = {"the", "a", "an", "to", "of", "and", "or", "is", "are", "be", "so", "for", "with", "without",
             "not", "can", "this", "that", "it", "your", "you", "we", "when", "if", "how", "what", "only",
             "use", "has", "have", "no", "on", "in", "by", "from", "about", "as", "at", "its", "their"}
WORD = re.compile(r"[A-Za-z][A-Za-z'-]*")
PRAGMA = re.compile(r"neosloc:\s*ignore\b")


def is_prose(content: str) -> bool:
    tokens = content.split()
    if len(tokens) < 3:
        return False
    words = [w.lower() for t in tokens for w in WORD.findall(t)]
    return any(w in STOPWORDS for w in words)


def has_ignore_pragma(text: str) -> bool:
    """`neosloc: ignore` in a comment within the first 5 lines opts a file out
    of content signals (for files whose strings are detection vocabulary)."""
    return bool(PRAGMA.search("\n".join(text.splitlines()[:5])))


# Calls whose string argument is a regex, per language family.
PY_REGEX_CALLS = {"compile", "search", "match", "fullmatch", "findall", "finditer", "sub", "subn", "split"}
C_REGEX_CALL = re.compile(
    r"(RegExp|MustCompile|regexp\.Compile|Regex::new|RegexBuilder::new|Pattern\.compile|new\s+Regex|Regex\.(?:Match|IsMatch|Replace)"
    r"|preg_\w+|Pattern\(|toRegex|Regex)\s*\(\s*$"
    r"|NSRegularExpression\(\s*pattern:\s*$"  # Swift
)
JS_REGEX_PREV = set("(,=:[!&|?{};+-*%<>~^")
JS_REGEX_KEYWORDS = ("return", "typeof", "case", "do", "else", "in", "of", "yield", "await")


def code_view(text: str, language: str, keep_regex: bool = False) -> str:
    try:
        if language == "python":
            return _python(text, keep_regex)
        if language in C_LIKE:
            return _c_like(text, language in JS_LIKE, keep_regex)
        if language in HASH_COMMENT:
            return _hash_comments(text)
    except (tokenize.TokenError, IndentationError, SyntaxError, ValueError):
        pass
    return text


# ---------------------------------------------------------------------------
# Python


def _blank_string(tok: str) -> str:
    """Keep the prefix and quotes of a string literal, blank its contents."""
    m = re.match(r"(?is)^([a-z]*)('''|\"\"\"|'|\")", tok)
    if not m:
        return tok
    prefix, q = m.group(1), m.group(2)
    inner = tok[len(prefix) + len(q):len(tok) - len(q)]
    return prefix + q + re.sub(r"[^\n]", " ", inner) + q


def _string_content(tok: str) -> str:
    m = re.match(r"(?is)^[a-z]*('''|\"\"\"|'|\")", tok)
    if not m:
        return tok
    q = m.group(1)
    return tok[m.end():len(tok) - len(q)]


def _python(text: str, keep_regex: bool) -> str:
    lines = text.splitlines(keepends=True)
    edits: List[tuple] = []  # (start, end, replacement)
    toks = list(tokenize.generate_tokens(io.StringIO(text).readline))
    significant = [t for t in toks if t.type not in (tokenize.NL, tokenize.COMMENT, tokenize.ENCODING)]
    pos_index = {id(t): i for i, t in enumerate(significant)}
    for tok in toks:
        if tok.type == tokenize.COMMENT:
            edits.append((tok.start, tok.end, ""))
            continue
        if tok.type != tokenize.STRING:
            continue
        i = pos_index[id(tok)]
        prev = significant[i - 1] if i else None
        nxt = significant[i + 1] if i + 1 < len(significant) else None
        # A string that is a whole statement is a docstring or a comment in disguise.
        if (prev is None or prev.type in (tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT)) \
                and nxt is not None and nxt.type in (tokenize.NEWLINE, tokenize.ENDMARKER):
            edits.append((tok.start, tok.end, _blank_string(tok.string)))
            continue
        if is_prose(_string_content(tok.string)):
            edits.append((tok.start, tok.end, _blank_string(tok.string)))
            continue
        if keep_regex:
            continue
        prefix = re.match(r"(?i)^[a-z]*", tok.string).group(0).lower()
        is_raw = "r" in prefix
        regex_call = (i >= 2 and significant[i - 1].string == "(" and significant[i - 2].type == tokenize.NAME
                      and significant[i - 2].string in PY_REGEX_CALLS)
        if is_raw or regex_call:
            edits.append((tok.start, tok.end, _blank_string(tok.string)))
    return _apply(lines, edits)


def _apply(lines: List[str], edits: List[tuple]) -> str:
    """Apply (start, end, replacement) edits given as tokenize (row, col) positions."""
    offsets, total = [], 0
    for line in lines:
        offsets.append(total)
        total += len(line)
    text = "".join(lines)
    out, pos = [], 0
    for (sr, sc), (er, ec), repl in sorted(edits):
        a, b = offsets[sr - 1] + sc, offsets[er - 1] + ec
        if a < pos:
            continue  # overlapping edit
        out.append(text[pos:a])
        out.append(repl)
        pos = b
    out.append(text[pos:])
    return "".join(out)


# ---------------------------------------------------------------------------
# C family


def _c_like(text: str, js: bool, keep_regex: bool) -> str:
    out: List[str] = []
    i, n = 0, len(text)
    last_sig = ""      # last non-space character emitted
    last_word = ""     # last identifier emitted (for `return /re/`)
    while i < n:
        c = text[i]
        two = text[i:i + 2]
        if two == "//":
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        if two == "/*":
            j = text.find("*/", i + 2)
            end = n if j < 0 else j + 2
            out.append("\n" * text.count("\n", i, end))
            i = end
            continue
        if text.startswith('"""', i):  # Swift, Kotlin and Java text blocks
            j = text.find('"""', i + 3)
            j = n if j < 0 else j + 3
            literal = text[i:j]
            if is_prose(literal[3:-3]):
                literal = '"""' + re.sub(r"[^\n]", " ", literal[3:-3]) + '"""'
            out.append(literal)
            last_sig, last_word = '"', ""
            i = j
            continue
        if c in "\"'`":
            j = _string_end(text, i, c)
            literal = text[i:j]
            before = "".join(out)[-60:]
            if is_prose(literal[1:-1]) or (not keep_regex and C_REGEX_CALL.search(before)):
                literal = c + re.sub(r"[^\n]", " ", literal[1:-1]) + literal[-1:]
            out.append(literal)
            last_sig, last_word = c, ""
            i = j
            continue
        if js and c == "/" and _js_regex_start(last_sig, last_word):
            j = _js_regex_end(text, i)
            if j > 0:
                out.append(text[i:j] if keep_regex else "/" + " " * (j - i - 2) + "/")
                last_sig, last_word = "/", ""
                i = j
                continue
        out.append(c)
        if not c.isspace():
            last_sig = c
            if c.isalnum() or c == "_":
                last_word = (last_word + c) if (i and (text[i - 1].isalnum() or text[i - 1] == "_")) else c
            else:
                last_word = ""
        i += 1
    return "".join(out)


def _string_end(text: str, i: int, q: str) -> int:
    j = i + 1
    while j < len(text):
        ch = text[j]
        if ch == "\\":
            j += 2
            continue
        if ch == q:
            return j + 1
        if ch == "\n" and q != "`":
            return j  # unterminated: stop at end of line
        j += 1
    return len(text)


def _js_regex_start(last_sig: str, last_word: str) -> bool:
    return last_sig == "" or last_sig in JS_REGEX_PREV or last_word in JS_REGEX_KEYWORDS


def _js_regex_end(text: str, i: int) -> int:
    """Index just past the closing `/` of a regex literal starting at i, or -1."""
    j, in_class = i + 1, False
    if j < len(text) and text[j] in "/*":
        return -1
    while j < len(text):
        ch = text[j]
        if ch == "\n":
            return -1
        if ch == "\\":
            j += 2
            continue
        if ch == "[":
            in_class = True
        elif ch == "]":
            in_class = False
        elif ch == "/" and not in_class:
            return j + 1
        j += 1
    return -1


# ---------------------------------------------------------------------------
# '#' comments


def _hash_comments(text: str) -> str:
    out = []
    for line in text.splitlines(keepends=True):
        q = None
        for k, ch in enumerate(line):
            if q:
                if ch == q and line[k - 1] != "\\":
                    q = None
            elif ch in "\"'":
                q = ch
            elif ch == "#" and (k == 0 or line[k - 1] in " \t") and not line.startswith("#!"):
                line = line[:k].rstrip() + ("\n" if line.endswith("\n") else "")
                break
        out.append(line)
    return "".join(out)
