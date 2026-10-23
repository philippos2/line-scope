"""Question context handling; lexical matching belongs to the shared search layer."""

import re

from ..domain.reference_normalization import reference_key as reference_key


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
