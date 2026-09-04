from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, String, TypeDecorator, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from synelia_kernel.dates import maintenant
from synelia_kernel.ids import nouvel_id


class DateTimeUTC(TypeDecorator[datetime]):
    """SQLite rend des datetimes naïfs : on les re-scelle en UTC à la lecture."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_result_value(self, value, dialect):  # type: ignore[override]
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, list[Any]: JSON, datetime: DateTimeUTC}


class Identifie:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=nouvel_id)


class Horodate:
    cree_le: Mapped[datetime] = mapped_column(
        DateTimeUTC, default=maintenant, server_default=func.now()
    )
    modifie_le: Mapped[datetime] = mapped_column(
        DateTimeUTC, default=maintenant, onupdate=maintenant, server_default=func.now()
    )
