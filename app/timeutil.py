from datetime import UTC, datetime


def utcnow() -> datetime:
    """Naive UTC timestamp.

    The database stores naive UTC datetimes; this replaces the deprecated
    ``datetime.utcnow()`` while staying comparable with existing rows.
    """
    return datetime.now(UTC).replace(tzinfo=None)
