"""Opaque keyset cursors for ``GET /bookmarks``.

The list is ordered by ``(created_at DESC, id DESC)``. A cursor carries the
sort key of the last row on the page it came from, so the next page starts
strictly after that row instead of at a numeric offset. Insertions and
deletions between requests therefore cannot shift the boundary and repeat or
skip surviving rows.

Tokens are versioned and base64url-encoded. Clients must treat them as opaque:
the payload format may change without notice as long as the ``v1.`` shape is
accepted.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from datetime import datetime, timezone

CURSOR_VERSION = "v1"
_SEPARATOR = "|"


@dataclass(frozen=True)
class Cursor:
    """The sort key of the last row returned by the previous page."""

    created_at: datetime
    id: int


class InvalidCursor(ValueError):
    """Raised when a client-supplied cursor cannot be decoded safely."""


def as_utc(value: datetime) -> datetime:
    """Normalise a timestamp for storage in a cursor and for comparison.

    SQLite drops the offset on read, but the stored value is always UTC, so a
    naive value is treated as UTC. A timezone-aware value is converted.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def encode_cursor(created_at: datetime, bookmark_id: int) -> str:
    """Build the opaque token for a row's sort key."""
    payload = f"{as_utc(created_at).isoformat()}{_SEPARATOR}{bookmark_id}".encode("utf-8")
    token = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    return f"{CURSOR_VERSION}.{token}"


def decode_cursor(token: str) -> Cursor:
    """Parse a client cursor, rejecting anything malformed or versionless.

    The timestamp must carry an explicit offset. Accepting a naive timestamp
    would make the comparison depend on the database session timezone on
    Postgres and on the implicit UTC convention on SQLite.
    """
    prefix = f"{CURSOR_VERSION}."
    if not token.startswith(prefix):
        raise InvalidCursor(f"cursor must start with '{prefix}'")
    encoded = token[len(prefix):]
    if not encoded:
        raise InvalidCursor("cursor payload is empty")

    padding = "=" * (-len(encoded) % 4)
    try:
        decoded = base64.urlsafe_b64decode(encoded + padding).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        raise InvalidCursor("cursor is not valid base64url") from None

    timestamp_text, separator, id_text = decoded.rpartition(_SEPARATOR)
    if not separator:
        raise InvalidCursor("cursor payload is malformed")

    try:
        created_at = datetime.fromisoformat(timestamp_text)
    except ValueError:
        raise InvalidCursor("cursor timestamp is not a valid ISO 8601 datetime") from None
    if created_at.tzinfo is None or created_at.utcoffset() is None:
        raise InvalidCursor("cursor timestamp must include a UTC offset")

    try:
        bookmark_id = int(id_text)
    except ValueError:
        raise InvalidCursor("cursor id is not an integer") from None
    if bookmark_id <= 0:
        raise InvalidCursor("cursor id must be positive")

    return Cursor(created_at=as_utc(created_at), id=bookmark_id)
