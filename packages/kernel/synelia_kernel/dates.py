"""Dates : toujours UTC, sérialisées ISO 8601."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


def maintenant() -> datetime:
    return datetime.now(UTC)


def iso(d: datetime | None = None) -> str:
    return (d or maintenant()).isoformat().replace("+00:00", "Z")


def dans(secondes: int) -> datetime:
    return maintenant() + timedelta(seconds=secondes)


def depuis_iso(s: str) -> datetime:
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=UTC)
