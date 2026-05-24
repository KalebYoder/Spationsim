from sqlalchemy import Column, Integer, String, DateTime, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from ..db.database import Base


class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True)
    type = Column(String(64), nullable=False)
    payload = Column(JSONB)
    scheduled_for = Column(DateTime(timezone=True), nullable=False)
    processed_at = Column(DateTime(timezone=True))
    status = Column(String(16), default="pending", nullable=False)

    __table_args__ = (
        # Primary Celery tick query: find pending events due for processing
        Index("ix_events_status_scheduled_for", "status", "scheduled_for"),
    )
