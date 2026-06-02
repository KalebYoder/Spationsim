from sqlalchemy import Column, Integer, String, Numeric, DateTime, ForeignKey, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from ..db.database import Base


class Nation(Base):
    __tablename__ = "nations"

    id = Column(Integer, primary_key=True)
    player_id = Column(Integer, ForeignKey("players.id"), unique=True, nullable=False)
    name = Column(String(128), unique=True, nullable=False)
    currency_name = Column(String(64), nullable=False, default="Credits")
    flag_color = Column(String(7), nullable=False, default="#3A86FF")
    home_territory_id = Column(Integer, ForeignKey("territories.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    minerals = Column(Numeric(12, 2), default=0, nullable=False)
    fuel = Column(Numeric(12, 2), default=0, nullable=False)
    currency = Column(Numeric(12, 2), default=0, nullable=False)
    probes_reserve = Column(Integer, default=0, nullable=False)
    diplomatic_status_default = Column(String(16), default="neutral", nullable=False)

    player = relationship("Player", back_populates="nation")
    territories = relationship("Territory", back_populates="nation", foreign_keys="Territory.nation_id")
    probe_data_discovered = relationship("ProbeData", back_populates="discovered_by_nation",
                                         foreign_keys="ProbeData.discovered_by")
    probe_data_access = relationship("ProbeDataAccess", back_populates="granted_to_nation",
                                     foreign_keys="ProbeDataAccess.granted_to")
    fleets = relationship("Fleet", back_populates="nation")
    colony_ships = relationship("ColonyShip", back_populates="nation")
    probes = relationship("Probe", back_populates="nation")
    resource_logs = relationship("ResourceLog", back_populates="nation")
    diplomacy_as_a = relationship("Diplomacy", back_populates="nation_a_rel",
                                  foreign_keys="Diplomacy.nation_a")
    diplomacy_as_b = relationship("Diplomacy", back_populates="nation_b_rel",
                                  foreign_keys="Diplomacy.nation_b")
    tutorial_state = relationship("TutorialState", back_populates="nation", uselist=False)

    # player_id unique constraint already creates an index; no additional index needed there.
    # Index on name is covered by the unique constraint.
