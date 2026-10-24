"""Deterministic lookup policy shared by every equipment search caller.

Compatibility/case normalization is lexical, not an equipment identity claim.
Japanese ordinal integer notation is a grammar; arbitrary words and business
aliases are not rewritten. SQL callers bind the generated literal regex.
"""

import re
import unicodedata

DIGITS = "零一二三四五六七八九"


def _number(text):
    if text.isascii() and text.isdecimal():
        return int(text) if len(text) <= 4 else None
    if all(char in DIGITS + "〇" for char in text):
        value = "".join(str(DIGITS.index(char)) if char != "〇" else "0" for char in text)
        return int(value) if len(value) <= 4 else None
    total, digit, previous_unit = 0, None, 10000
    for char in text:
        if char in DIGITS:
            if digit is not None:
                return None
            digit = DIGITS.index(char)
        elif char in "十百千":
            unit = {"十": 10, "百": 100, "千": 1000}[char]
            if unit >= previous_unit or digit == 0:
                return None
            total += (digit or 1) * unit
            digit, previous_unit = None, unit
        else:
            return None
    return total + (digit or 0)


def _kanji(value):
    if value == 0:
        return "零"
    parts = []
    for unit, suffix in ((1000, "千"), (100, "百"), (10, "十"), (1, "")):
        digit, value = divmod(value, unit)
        if digit:
            parts.append((DIGITS[digit] if digit != 1 or unit == 1 else "") + suffix)
    return "".join(parts)


def lexical_key(text):
    return unicodedata.normalize("NFKC", text).casefold().strip()


ORDINAL = re.compile(
    r"第([0-9零〇一二三四五六七八九十百千]+)(?![0-9零〇一二三四五六七八九十百千万億兆.,，])"
)
NUMERALS = "0-9零〇一二三四五六七八九十百千万億兆"


def ordinal_forms(text):
    # Preserve identifier-like zero padding rather than guessing its meaning.
    if text.isascii() and len(text) > 1 and text.startswith("0"):
        return (text,)
    value = _number(text)
    if value is None or not 0 <= value <= 9999:
        return (text,)
    positional = "".join(DIGITS[int(char)] for char in str(value))
    forms = tuple(
        dict.fromkeys((str(value), _kanji(value), positional, positional.replace("零", "〇")))
    )
    return forms if text in forms else (text,)


def reference_key(text):
    """Grouping only: actual matches and collisions must come from registered IDs."""
    return lexical_key(text)


def name_reference_pattern(text):
    """Literal substring with bounded numeric tokens and per-token alternatives.

    Alternation is local to each ordinal. Multiple numbers never create a
    Cartesian product of search requests. Everything else is regex-escaped.
    """
    normalized = lexical_key(text)
    parts, offset = [], 0
    for match in ORDINAL.finditer(normalized):
        parts.append(_literal_pattern(normalized[offset : match.start()]))
        forms = "|".join(re.escape(value) for value in ordinal_forms(match[1]))
        parts.append("第(?:" + forms + ")(?![" + NUMERALS + "])")
        offset = match.end()
    parts.append(_literal_pattern(normalized[offset:]))
    return "".join(parts)


def _literal_pattern(text):
    parts, offset = [], 0
    for match in re.finditer(r"[0-9]+", text):
        parts.extend(
            (re.escape(text[offset : match.start()]), r"(?<![0-9])", match[0], r"(?![0-9])")
        )
        offset = match.end()
    parts.append(re.escape(text[offset:]))
    return "".join(parts)
