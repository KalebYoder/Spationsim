from sqlalchemy import Column, Integer, DateTime, ForeignKey, UniqueConstraint, Index
from sqlalchemy.sql import func
from ..db.database import Base


class ProbeVisibility(Base):
    __tablename__ = "probe_visibility"

    id            = Column(Integer, primary_key=True)
    nation_id     = Column(Integer, ForeignKey("nations.id"), nullable=False)
    territory_id  = Column(Integer, ForeignKey("territories.id"), nullable=False)
    discovered_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("nation_id", "territory_id", name="uq_probe_visibility"),
        Index("ix_probe_visibility_nation", "nation_id"),
        Index("ix_probe_visibility_territory", "territory_id"),
    )
