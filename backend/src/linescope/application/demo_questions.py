"""Question-only demo: finite catalog, shared identity search and typed reads."""

import re
from uuid import UUID, uuid4

from ..agent.question_catalog import ASPECTS, DEICTIC, guidance, matches, subject_expression
from ..agent.read_agent import ReadObservation
from ..agent.registered_question_read import response, valid
from ..domain.reference_normalization import close_codes, lexical_key
from .reads import ReadResult, ToolError


class DemoQuestions:
    def __init__(self, reader):
        self.reader = reader

    def answer(self, context, incoming, conversation):
        session = self.reader.session(context, incoming)
        observations = []

        def search(reference=None):
            rows, cursor, seen = {}, None, set()
            for _ in range(2):
                args = {
                    "filter": {} if reference is None else {"reference": reference},
                    "page_size": 100,
                    "cursor": cursor,
                }
                call_id = str(uuid4())
                result = session.run("search_equipment", args, tool_call_id=call_id)
                item = ReadObservation(call_id, "search_equipment", result, args)
                if (
                    not isinstance(result, ReadResult)
                    or not valid(item)
                    or type(result.data.get("items")) is not list
                ):
                    raise ToolError("INTERNAL_ERROR", "Invalid equipment search result")
                for row in result.data["items"]:
                    UUID(row["equipment_id"])
                    if not all(
                        isinstance(row.get(key), str)
                        for key in ("equipment_name", "equipment_code")
                    ):
                        raise ToolError("INTERNAL_ERROR", "Invalid equipment identity")
                    rows[row["equipment_id"]] = row
                observations.append(item)
                cursor = result.data.get("next_cursor")
                if cursor is None:
                    return list(rows.values()), True
                if cursor in seen:
                    raise ToolError("INTERNAL_ERROR", "Repeated search cursor")
                seen.add(cursor)
            return list(rows.values()), False

        def label(row):
            return f"{row['equipment_name']}（{row['equipment_code']}）"

        def finish(text, outcome, rows=(), *, pending=None):
            # Search projections identify equipment only; never publish unrelated columns.
            public = tuple(
                ReadObservation(
                    o.tool_call_id,
                    o.tool,
                    ReadResult(
                        {
                            **o.result.data,
                            "items": [
                                {
                                    k: v
                                    for k, v in row.items()
                                    if k in {"equipment_id", "equipment_name", "equipment_code"}
                                }
                                for row in o.result.data["items"]
                            ],
                        },
                        o.result.evidence,
                    ),
                    o.arguments,
                )
                for o in observations
            )
            result = response(
                text, outcome, public if rows else (), needs_input=pending is not None
            )
            if rows:
                result.answer_sections["facts"][0]["text"] = "確認した登録設備：" + "、".join(
                    label(row) for row in rows
                )
            return result, pending

        try:
            if incoming.explicit_as_of or incoming.replace_update_request_id:
                return finish(
                    "この質問欄では現在の登録情報だけを照会します。過去時点の実状態は復元できません。"
                    + guidance(),
                    "UNSUPPORTED",
                )
            previous = conversation.get("question") or {}
            original = incoming.message
            key = None
            rows = None
            if previous and not re.search("[のはが?？]", incoming.message):
                selected, complete = search(incoming.message.strip())
                allowed = previous.get("candidates", [])
                if (
                    complete
                    and len(selected) == 1
                    and (not allowed or selected[0]["equipment_id"] in allowed)
                ):
                    rows, original, key = selected, previous["original"], previous.get("key")
            found = matches(original)
            reference = subject_expression(original)
            if rows is None:
                keys = {value[0] for value in found}
                exact_subjects = {
                    lexical_key(value[1])
                    for value in found
                    if lexical_key(value[1]) == lexical_key(reference)
                }
                key = (
                    next(iter(keys))
                    if len(keys) == 1 and exact_subjects == {lexical_key(reference)}
                    else None
                )
                if reference in DEICTIC:
                    return finish(
                        "どの設備についてですか？ 設備名またはコードを同じ質問欄に入力してください。",
                        "TARGET_REQUIRED",
                        pending={"original": original, "key": key, "candidates": []},
                    )
                parts = re.split("と|及び", reference)
                if len(parts) > 1:
                    return finish(
                        "複数設備をまとめた質問には対応していません。設備と調べる内容を一つずつ指定してください。"
                        + guidance(),
                        "UNSUPPORTED",
                    )
                rows, complete = search(reference)
                if not complete:
                    return finish(
                        "設備検索の全件を確認できませんでした。一意な対象や不存在とは判断できません。コードを確かめて再試行してください。",
                        "SEARCH_INCOMPLETE",
                    )
                if not rows:
                    registered, complete = search()
                    near = close_codes(reference, registered)
                    text = f"『{reference}』に一致する設備は今回の検索では見つかりませんでした。"
                    if near:
                        text += (
                            "近い設備コード："
                            + "、".join(row["equipment_code"] for row in near)
                            + "。コードを確認して入力してください。"
                        )
                    if not complete:
                        text += "候補の探索は不完全です。"
                    text += "設備が存在しないと断定したものではありません。" + guidance()
                    return finish(text, "TARGET_NOT_FOUND" if key else "UNSUPPORTED")
            if len(rows) > 1:
                text = (
                    "複数の設備が該当します。"
                    + "、".join(label(row) for row in rows[:10])
                    + "。どの設備か、設備コードを同じ質問欄に入力してください。"
                )
                if key is None:
                    text += "ただし、この質問全体の内容は照会範囲外です。" + guidance()
                return finish(
                    text,
                    "TARGET_AMBIGUOUS" if key is not None else "UNSUPPORTED",
                    rows,
                    pending={
                        "original": original,
                        "key": key,
                        "candidates": [row["equipment_id"] for row in rows],
                    },
                )
            row = rows[0]
            if key is None:
                text = (
                    f"{label(row)}は確認できましたが、『{original}』の内容は、このデモの照会範囲では回答できません。"
                    + guidance()
                )
                return finish(text, "UNSUPPORTED", rows)
            if key not in {aspect.key for aspect in ASPECTS}:
                raise ToolError("INVALID_ARGUMENT", "Unknown stored demo viewpoint")
            return self.reader.run(context, incoming, key, row["equipment_id"]), None
        except (ToolError, ValueError, KeyError, TypeError) as error:
            code = error.code if isinstance(error, ToolError) else "INTERNAL_ERROR"
            return response(
                "設備情報を取得・検証できませんでした。未登録や不存在とは判断していません。時間をおいて同じ質問を送ってください。",
                "READ_FAILED",
                errors=({"code": code, "message": "Equipment lookup failed", "details": {}},),
            ), None
