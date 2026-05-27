from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, UniqueConstraint, Index, CheckConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from ..db.database import Base


class Diplomacy(Base):
    __tablename__ = "diplomacy"

    id = Column(Integer, primary_key=True)
    nation_a = Column(Integer, ForeignKey("nations.id"), nullable=False)
    nation_b = Column(Integer, ForeignKey("nations.id"), nullable=False)
    status = Column(String(16), default="neutral", nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now())
    war_starts_at = Column(DateTime(timezone=True), nullable=True)
    requested_by = Column(Integer, ForeignKey("nations.id"), nullable=True)

    nation_a_rel = relationship("Nation", back_populates="diplomacy_as_a", foreign_keys=[nation_a])
    nation_b_rel = relationship("Nation", back_populates="diplomacy_as_b", foreign_keys=[nation_b])

    __table_args__ = (
        # Enforces exactly one row per pair, with the lower id always in nation_a
        UniqueConstraint("nation_a", "nation_b", name="uq_diplomacy_pair"),
        CheckConstraint("nation_a < nation_b", name="ck_diplomacy_order"),
        # The unique constraint indexes (nation_a, nation_b) but not nation_b alone.
        # Add a standalone index on nation_b so "all diplomacy for nation X" is fast
        # regardless of which side of the pair they appear on.
        Index("ix_diplomacy_nation_b", "nation_b"),
        # Index for filtering by status across the whole table (e.g., all wars)
        Index("ix_diplomacy_status", "status"),
    )
