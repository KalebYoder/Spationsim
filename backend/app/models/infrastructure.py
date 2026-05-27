from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from ..db.database import Base


class Infrastructure(Base):
    __tablename__ = "infrastructure"

    id = Column(Integer, primary_key=True)
    territory_id = Column(Integer, ForeignKey("territories.id"), nullable=False, index=True)
    type = Column(String(64), nullable=False)
    level = Column(Integer, default=1, nullable=False)
    population_assigned = Column(Integer, default=0, nullable=False)
    built_at = Column(DateTime(timezone=True), server_default=func.now())
    status = Column(String(32), nullable=False, default="active")
    completes_at = Column(DateTime(timezone=True), nullable=True)

    territory = relationship("Territory", back_populates="infrastructure")

    __table_args__ = (
        Index("ix_infrastructure_territory_type", "territory_id", "type"),
        Index("ix_infrastructure_status_completes_at", "status", "completes_at"),
    )
