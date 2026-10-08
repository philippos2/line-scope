import hashlib
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

import pytest

from linescope.canonical import (
    canonical_hash,
    canonical_json,
    normalize_id_set,
    normalize_timestamp,
    normalize_uuid,
    strict_json,
)


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, "null"),
        (True, "true"),
        (False, "false"),
        (0, "0"),
        (-123, "-123"),
        (2**63, "9223372036854775808"),
        ({"z": 1, "a": "日本語"}, '{"a":"日本語","z":1}'),
        ([3, 1, None], "[3,1,null]"),
        ({"𐀀": 1, "\ue000": 2}, '{"\ue000":2,"𐀀":1}'),
        ('"\\/\n\t\r', '"\\"\\\\/\\u000a\\u0009\\u000d"'),
    ],
)
def test_exact_canonical_bytes(value, expected):
    assert canonical_json(value).encode("utf-8") == expected.encode("utf-8")
    assert canonical_hash(value) == hashlib.sha256(expected.encode("utf-8")).hexdigest()


def test_all_c0_controls_have_lowercase_hex_escape():
    assert canonical_json("".join(chr(value) for value in range(32))) == (
        '"' + "".join(f"\\u00{value:02x}" for value in range(32)) + '"'
    )


def test_known_sha256_vector_and_object_order():
    assert canonical_hash({}) == "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
    assert canonical_hash({"a": {"b": 2, "a": 1}, "z": None}) == canonical_hash(
        {"z": None, "a": {"a": 1, "b": 2}}
    )


def test_business_changes_null_and_array_order_change_hash():
    assert canonical_hash({"value": 1}) != canonical_hash({"value": 2})
    assert canonical_hash({"value": None}) != canonical_hash({})
    assert canonical_hash([1, 2]) != canonical_hash([2, 1])
    assert canonical_hash(True) != canonical_hash(1)
    assert canonical_hash("é") != canonical_hash("e\u0301")


@pytest.mark.parametrize(
    "value",
    [
        1.0,
        float("nan"),
        float("inf"),
        Decimal("1"),
        Decimal("1.0"),
        {1: "not a string key"},
        b"bytes",
        (1, 2),
        {1, 2},
        object(),
        datetime.now(timezone.utc),
        UUID(int=1),
        "\ud800",
        {"\udfff": 1},
        ["\ud800"],
    ],
)
def test_non_json_and_forbidden_types_rejected(value):
    with pytest.raises(ValueError):
        canonical_json(value)


@pytest.mark.parametrize(
    "text",
    [
        '{"a":1,"a":2}',
        '{"a":1,"\\u0061":2}',
        '{"outer":{"a":1,"a":2}}',
        "1.0",
        "1e0",
        "NaN",
        "Infinity",
        "-Infinity",
        '{"a":[0.1]}',
        '"\\ud800"',
        '{"\\udfff":1}',
        '{"a":}',
        "{} {}",
        b'"\xff"',
        "{}".encode("utf-16"),
        None,
    ],
)
def test_strict_json_rejects_ambiguous_input(text):
    with pytest.raises(ValueError):
        strict_json(text)


def test_strict_json_roundtrip_unicode_and_explicit_null():
    value = strict_json(' {"text":"日本語😀","nullable":null,"active":true,"n":-3} '.encode())
    assert strict_json(canonical_json(value)) == value
    assert strict_json('"\\ud83d\\ude00"') == "😀"


def test_cycles_rejected_but_shared_arrays_are_valid():
    array = []
    array.append(array)
    with pytest.raises(ValueError, match="Cyclic"):
        canonical_json(array)
    mapping = {}
    mapping["self"] = mapping
    with pytest.raises(ValueError, match="Cyclic"):
        canonical_json(mapping)
    shared = [1]
    assert canonical_json([shared, shared]) == "[[1],[1]]"


def test_schema_directed_uuid_and_timestamp_normalization():
    identifier = "ABCDEFAB-1234-5678-ABCD-123456789ABC"
    assert normalize_uuid(identifier) == identifier.lower()
    assert normalize_uuid(UUID(identifier)) == identifier.lower()
    assert normalize_timestamp("2026-10-09T09:12:34.123456+09:00") == "2026-10-09T00:12:34.123456Z"
    assert normalize_timestamp("2026-10-09T00:12:34.123456Z") == "2026-10-09T00:12:34.123456Z"
    assert (
        normalize_timestamp(datetime(2026, 10, 9, 9, tzinfo=timezone(timedelta(hours=9))))
        == "2026-10-09T00:00:00.000000Z"
    )
    # Ordinary body strings must not be interpreted as typed values.
    assert canonical_json(identifier) == '"' + identifier + '"'
    assert canonical_json("2026-10-09T09:00:00+09:00") == '"2026-10-09T09:00:00+09:00"'


@pytest.mark.parametrize("value", [None, 1, "not-uuid", ""])
def test_invalid_uuid_rejected(value):
    with pytest.raises(ValueError):
        normalize_uuid(value)


@pytest.mark.parametrize(
    "value", [None, 123, "invalid", "2026-10-09T00:00:00", datetime(2026, 10, 9)]
)
def test_invalid_timestamp_rejected(value):
    with pytest.raises(ValueError):
        normalize_timestamp(value)


def test_id_sets_sorted_and_duplicates_rejected_after_normalization():
    first = "ABCDEFAB-1234-5678-ABCD-123456789ABC"
    second = str(UUID(int=1))
    assert normalize_id_set([first, second]) == [second, first.lower()]
    assert normalize_id_set([]) == []
    with pytest.raises(ValueError, match="Duplicate"):
        normalize_id_set([first, first.lower()])
    with pytest.raises(ValueError):
        normalize_id_set({first})


def test_timestamp_precision_is_not_silently_truncated():
    with pytest.raises(ValueError, match="precision"):
        normalize_timestamp("2026-10-09T00:00:00.1234567Z")


def test_excessive_nesting_is_rejected_consistently():
    value = []
    for _ in range(1100):
        value = [value]
    with pytest.raises(ValueError):
        canonical_json(value)
    with pytest.raises(ValueError):
        strict_json("[" * 1100 + "0" + "]" * 1100)
