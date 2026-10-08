"""LineScope canonical JSON v1 primitives; not a Snapshot schema validator.

UUID/time normalization applies only when the caller's schema marks a field
as that type. Ordinary strings and ordered arrays are never rewritten.
"""

import hashlib
import json
import re
from datetime import datetime, timezone
from uuid import UUID


def _quote(value):
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise ValueError("Unicode surrogate is not permitted")
    return (
        '"'
        + "".join(
            '\\"'
            if character == '"'
            else "\\\\"
            if character == "\\"
            else f"\\u{ord(character):04x}"
            if ord(character) < 32
            else character
            for character in value
        )
        + '"'
    )


def _encode(value, ancestors):
    if value is None:
        return "null"
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is int:
        return str(value)
    if type(value) is str:
        return _quote(value)
    if type(value) not in (list, dict):
        raise ValueError("Unsupported canonical JSON type")
    identifier = id(value)
    if identifier in ancestors:
        raise ValueError("Cyclic JSON value")
    ancestors.add(identifier)
    try:
        if type(value) is list:
            return "[" + ",".join(_encode(item, ancestors) for item in value) + "]"
        if any(type(key) is not str for key in value):
            raise ValueError("Object keys must be strings")
        return (
            "{"
            + ",".join(_quote(key) + ":" + _encode(value[key], ancestors) for key in sorted(value))
            + "}"
        )
    finally:
        ancestors.remove(identifier)


def canonical_json(value):
    """Serialize only JSON types, with integer-only numbers and explicit nulls."""
    try:
        return _encode(value, set())
    except RecursionError as error:
        raise ValueError("JSON nesting exceeds the supported limit") from error


def canonical_hash(value):
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def strict_json(text):
    """Reject duplicate keys, noninteger numbers, invalid Unicode and non-UTF8."""

    def object_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    def reject_number(_):
        raise ValueError("Only integer JSON numbers are permitted")

    try:
        if isinstance(text, bytes):
            text = text.decode("utf-8")
        if not isinstance(text, str):
            raise ValueError("JSON input must be text or UTF-8 bytes")
        value = json.loads(
            text,
            object_pairs_hook=object_pairs,
            parse_float=reject_number,
            parse_constant=reject_number,
        )
        canonical_json(value)
        return value
    except (ValueError, RecursionError) as error:
        raise ValueError("Invalid strict JSON input") from error


def normalize_uuid(value):
    if not isinstance(value, (str, UUID)):
        raise ValueError("UUID must be a string or UUID value")
    try:
        return str(UUID(str(value)))
    except ValueError as error:
        raise ValueError("Invalid UUID") from error


def normalize_timestamp(value):
    if isinstance(value, str):
        if re.search(r"[.,]\d{7,}", value):
            raise ValueError("Timestamp precision must not exceed microseconds")
        try:
            value = datetime.fromisoformat(value)
        except ValueError as error:
            raise ValueError("Invalid timestamp") from error
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError("A timezone-aware timestamp is required")
    try:
        return (
            value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
        )
    except (ValueError, OverflowError) as error:
        raise ValueError("Timestamp is outside the supported range") from error


def normalize_id_set(values):
    if not isinstance(values, list):
        raise ValueError("ID set must be an array")
    normalized = [normalize_uuid(value) for value in values]
    if len(set(normalized)) != len(normalized):
        raise ValueError("Duplicate ID in set")
    return sorted(normalized)
