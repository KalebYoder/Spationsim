from sqlalchemy import Column, Integer, DateTime, ForeignKey, String, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from ..db.database import Base


class ColonyShip(Base):
    __tablename__ = "colony_ships"

    id = Column(Integer, primary_key=True)
    nation_id = Column(Integer, ForeignKey("nations.id"), nullable=False, index=True)
    origin_territory = Column(Integer, ForeignKey("territories.id"))
    destination_territory = Column(Integer, ForeignKey("territories.id"), index=True)
    cargo_population = Column(Integer, default=0, nullable=False)
    status = Column(String(32), default="stationed", nullable=False, index=True)
    departs_at = Column(DateTime(timezone=True))
    arrives_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    nation = relationship("Nation", back_populates="colony_ships")
    origin_territory_rel = relationship(
        "Territory", foreign_keys=[origin_territory],
        back_populates="colony_ships_origin",
    )
    destination_territory_rel = relationship(
        "Territory", foreign_keys=[destination_territory],
        back_populates="colony_ships_destination",
    )

    __table_args__ = (
        Index("ix_colony_ships_status_arrives_at", "status", "arrives_at"),
    )
