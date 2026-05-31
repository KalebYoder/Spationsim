from sqlalchemy import Boolean, Column, Integer, Numeric, String, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from ..db.database import Base


class Trade(Base):
    __tablename__ = "trades"

    id               = Column(Integer, primary_key=True)
    from_nation_id   = Column(Integer, ForeignKey("nations.id"), nullable=False)
    to_nation_id     = Column(Integer, ForeignKey("nations.id"), nullable=False)
    offer_minerals   = Column(Numeric(12, 2), default=0, nullable=False)
    offer_fuel       = Column(Numeric(12, 2), default=0, nullable=False)
    offer_currency   = Column(Numeric(12, 2), default=0, nullable=False)
    request_minerals = Column(Numeric(12, 2), default=0, nullable=False)
    request_fuel     = Column(Numeric(12, 2), default=0, nullable=False)
    request_currency = Column(Numeric(12, 2), default=0, nullable=False)
    status           = Column(String(16), default="pending", nullable=False)
    created_at       = Column(DateTime(timezone=True), server_default=func.now())
    resolved_at      = Column(DateTime(timezone=True))
    from_accepted_at  = Column(DateTime(timezone=True))
    from_confirmed_at = Column(DateTime(timezone=True))
    to_accepted_at    = Column(DateTime(timezone=True))
    to_confirmed_at   = Column(DateTime(timezone=True))
    includes_peace       = Column(Boolean, default=False, nullable=False)
    offer_territory_id   = Column(Integer, ForeignKey("territories.id"), nullable=True)
    request_territory_id = Column(Integer, ForeignKey("territories.id"), nullable=True)
    offer_probe_data_ids = Column(JSONB, nullable=False, default=list, server_default="[]")

    from_nation      = relationship("Nation", foreign_keys=[from_nation_id])
    to_nation        = relationship("Nation", foreign_keys=[to_nation_id])
    offer_territory  = relationship("Territory", foreign_keys=[offer_territory_id])
    request_territory = relationship("Territory", foreign_keys=[request_territory_id])

    __table_args__ = (
        Index("ix_trades_from",   "from_nation_id"),
        Index("ix_trades_to",     "to_nation_id"),
        Index("ix_trades_status", "status"),
    )
