"""Bounded text and exact decimal strings shared by registered business inputs."""

import re
from decimal import Decimal


def exact(value, fields):
    if type(value) is not dict or set(value) != fields:
        raise ValueError("Invalid input fields")


def text(value, limit=1000):
    if type(value) is not str or not value.strip() or len(value) > limit:
        raise ValueError("Nonempty bounded text is required")
    return value


def quantity(value, *, nullable=False):
    """Exact nonnegative decimal strings, at most 15 integral and 6 fractional digits."""
    if value is None and nullable:
        return None
    if type(value) is not str or not re.fullmatch(
        r"(?:0|[1-9][0-9]{0,14})(?:\.[0-9]{1,6})?", value
    ):
        raise ValueError("A nonnegative bounded decimal string is required")
    return format(Decimal(value), "f").rstrip("0").rstrip(".") if "." in value else value
