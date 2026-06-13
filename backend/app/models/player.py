from sqlalchemy import Column, Integer, String, Boolean, DateTime, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from ..db.database import Base


class Player(Base):
    __tablename__ = "players"

    id = Column(Integer, primary_key=True)
    username = Column(String(64), unique=True, nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_login = Column(DateTime(timezone=True), index=True)
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    vacation_mode = Column(Boolean, default=False, nullable=False, index=True)
    vacation_since = Column(DateTime(timezone=True))
    aggression_lockout_until = Column(DateTime(timezone=True))
    email_notifications_enabled = Column(Boolean, default=False, nullable=False)

    nation = relationship("Nation", back_populates="player", uselist=False)

    __table_args__ = (
        # Composite index for the common auth check: active, non-vacationing players
        Index("ix_players_active_vacation", "is_active", "vacation_mode"),
    )
