from sqlalchemy import Column, Integer, Numeric, DateTime, ForeignKey, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from ..db.database import Base


class TerritoryPopulation(Base):
    __tablename__ = "territory_population"

    # territory_id is both PK and FK — one population record per territory
    territory_id = Column(Integer, ForeignKey("territories.id"), primary_key=True)
    current = Column(Integer, default=0, nullable=False)
    growth_rate = Column(Numeric(5, 4), default=0.01, nullable=False)
    last_updated = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    territory = relationship("Territory", back_populates="population")
