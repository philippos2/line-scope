"""Conservative spelling candidates for read-only equipment lookup."""

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


def reference_variants(text):
    normalized = unicodedata.normalize("NFKC", text)

    def replace(match, kind):
        number = _number(match[1])
        if number is None or not 0 <= number <= 9999:
            return match[0]
        rendered = _kanji(number) if kind == "kanji" else str(number)
        if kind == "wide":
            rendered = rendered.translate(str.maketrans("0123456789", "０１２３４５６７８９"))
        return "第" + rendered

    variants = [text, normalized]
    for kind in ("ascii", "kanji", "wide"):
        variants.append(
            re.sub(
                r"第([0-9零〇一二三四五六七八九十百千]+)(?![0-9零〇一二三四五六七八九十百千万億兆.,，])",
                lambda m: replace(m, kind),
                normalized,
            )
        )
    return tuple(dict.fromkeys(variants))
