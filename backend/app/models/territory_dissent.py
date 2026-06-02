from sqlalchemy import Column, Integer, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from ..db.database import Base


class TerritoryDissent(Base):
    __tablename__ = "territory_dissent"

    territory_id = Column(Integer, ForeignKey("territories.id"), primary_key=True)
    dissent = Column(Integer, nullable=False, default=0)
    last_updated = Column(DateTime(timezone=True), server_default=func.now())

    territory = relationship("Territory", back_populates="dissent")
