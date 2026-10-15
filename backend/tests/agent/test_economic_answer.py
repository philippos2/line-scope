from types import SimpleNamespace

from linescope.agent.economic_answer import economic_answer


def observation(tool, data):
    return SimpleNamespace(tool=tool, result=SimpleNamespace(data=data))


def test_candidate_search_does_not_claim_to_have_calculated_costs():
    result = economic_answer(
        [
            observation(
                "search_economic_inputs", {"items": [{"input_code": "A"}], "next_cursor": "more"}
            )
        ]
    )
    assert "候補を1件" in result and "続きは未取得" in result
    assert "計算結果はまだ取得していません" in result


def test_multiple_inputs_are_not_added_or_ranked():
    result = economic_answer(
        [
            observation("get_economic_input", {"source": "REGISTERED_INPUT"}),
            observation("get_economic_input", {"source": "REGISTERED_INPUT"}),
        ]
    )
    assert "合算せず" in result and "優劣は未評価" in result
