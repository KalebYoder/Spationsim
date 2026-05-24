from sqlalchemy import Column, Integer, Numeric, DateTime, ForeignKey, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from ..db.database import Base


class ResourceLog(Base):
    __tablename__ = "resource_log"

    id = Column(Integer, primary_key=True)
    nation_id = Column(Integer, ForeignKey("nations.id"), nullable=False, index=True)
    tick_at = Column(DateTime(timezone=True), nullable=False, index=True)
    minerals_delta = Column(Numeric(12, 2))
    fuel_delta = Column(Numeric(12, 2))
    population_delta = Column(Integer)

    nation = relationship("Nation", back_populates="resource_logs")

    __table_args__ = (
        # History queries are almost always "for nation X over time range Y"
        Index("ix_resource_log_nation_tick", "nation_id", "tick_at"),
    )
