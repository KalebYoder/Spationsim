from sqlalchemy import Column, Integer, String, Numeric, Boolean, DateTime, ForeignKey, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from ..db.database import Base


class Territory(Base):
    __tablename__ = "territories"

    id = Column(Integer, primary_key=True)
    node_key = Column(String(32), unique=True, nullable=False)
    name = Column(String(128), nullable=True)
    territory_type = Column(String(16), nullable=False, default='normal')
    nation_id = Column(Integer, ForeignKey("nations.id"), index=True)
    mineral_richness = Column(Numeric(4, 2), nullable=False)
    fuel_richness = Column(Numeric(4, 2), nullable=False)
    distance_from_center = Column(Integer, nullable=False, index=True)
    is_colonized = Column(Boolean, default=False, nullable=False, index=True)
    colonized_at = Column(DateTime(timezone=True))

    nation = relationship("Nation", back_populates="territories", foreign_keys=[nation_id])
    infrastructure = relationship("Infrastructure", back_populates="territory")
    population = relationship("TerritoryPopulation", back_populates="territory", uselist=False)
    probe_data = relationship("ProbeData", back_populates="territory")
    fleets_origin = relationship("Fleet", back_populates="origin_territory_rel",
                                 foreign_keys="Fleet.origin_territory")
    fleets_destination = relationship("Fleet", back_populates="destination_territory_rel",
                                      foreign_keys="Fleet.destination_territory")
    probes_origin = relationship("Probe", back_populates="origin_territory_rel",
                                 foreign_keys="Probe.origin_territory")
    probes_destination = relationship("Probe", back_populates="destination_territory_rel",
                                      foreign_keys="Probe.destination_territory")

    __table_args__ = (
        # Tick processing finds all colonized territories for a nation together
        Index("ix_territories_nation_colonized", "nation_id", "is_colonized"),
        # Map rendering and probe range queries filter by distance band
        Index("ix_territories_distance_colonized", "distance_from_center", "is_colonized"),
    )
