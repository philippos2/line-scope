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


def _render_reference(normalized, kind):
    def replace(match):
        number = _number(match[1])
        if number is None or not 0 <= number <= 9999:
            return match[0]
        rendered = _kanji(number) if kind == "kanji" else str(number)
        if kind == "wide":
            rendered = rendered.translate(str.maketrans("0123456789", "０１２３４５６７８９"))
        return "第" + rendered

    return re.sub(
        r"第([0-9零〇一二三四五六七八九十百千]+)(?![0-9零〇一二三四五六七八九十百千万億兆.,，])",
        replace,
        normalized,
    )


def reference_key(text):
    """Stable grouping key; it is never substituted into an actual Tool filter."""
    return _render_reference(unicodedata.normalize("NFKC", text), "ascii")


def reference_variants(text):
    normalized = unicodedata.normalize("NFKC", text)
    variants = [text, normalized]
    variants.extend(_render_reference(normalized, kind) for kind in ("ascii", "kanji", "wide"))
    return tuple(dict.fromkeys(variants))


def selected_reference(message, reference):
    """A deictic subject may use the UI hint; all codes remain untrusted lookup input."""
    match = re.match(r"調査対象の設備コードは([^\n]+)です。\n(.+)\Z", message, re.DOTALL)
    if match and re.fullmatch(
        r"(?:この|その|選択(?:中|した)|調査中)(?:の)?(?:設備|機械|機材|装置)", reference
    ):
        return match[1]
    return reference


def question_messages(message):
    """Keep the UI selection as untrusted context, separate from the actual question."""
    match = re.match(r"調査対象の設備コードは([^\n]+)です。\n(.+)\Z", message, re.DOTALL)
    if not match:
        return [{"role": "user", "content": message}]
    question = match[2]
    # Only an explicit reference to the screen selection admits that context.
    # Do not offer an unrelated equipment code as a competing question target.
    if not re.search(
        r"(?:この|その|選択(?:中|した)|調査中)(?:の)?(?:設備|機械|機材|装置)", question
    ):
        return [{"role": "user", "content": question}]
    return [
        {
            "role": "user",
            "content": "画面で選択中の設備コード（補足情報）："
            + match[1]
            + "。次の質問に設備名・コードが明記されている場合はそちらを優先し、"
            "「この設備」など対象を省略した場合だけこの選択を参照してください。",
        },
        {"role": "user", "content": match[2]},
    ]
