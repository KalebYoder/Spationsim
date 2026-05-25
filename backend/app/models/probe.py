from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from ..db.database import Base


class Probe(Base):
    __tablename__ = "probes"

    id = Column(Integer, primary_key=True)
    nation_id = Column(Integer, ForeignKey("nations.id"), nullable=False, index=True)
    origin_territory = Column(Integer, ForeignKey("territories.id"))
    current_territory = Column(Integer, ForeignKey("territories.id"))
    destination_territory = Column(Integer, ForeignKey("territories.id"), index=True)
    status = Column(String(32), default="in_transit", nullable=False, index=True)
    departs_at = Column(DateTime(timezone=True))
    arrives_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    nation = relationship("Nation", back_populates="probes")
    origin_territory_rel = relationship("Territory", back_populates="probes_origin",
                                        foreign_keys=[origin_territory])
    current_territory_rel = relationship("Territory", back_populates="probes_current",
                                         foreign_keys=[current_territory])
    destination_territory_rel = relationship("Territory", back_populates="probes_destination",
                                             foreign_keys=[destination_territory])

    __table_args__ = (
        Index("ix_probes_status_arrives_at", "status", "arrives_at"),
        Index("ix_probes_nation_status", "nation_id", "status"),
    )
