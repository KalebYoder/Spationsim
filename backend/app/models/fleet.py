from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from ..db.database import Base


class Fleet(Base):
    __tablename__ = "fleets"

    id = Column(Integer, primary_key=True)
    nation_id = Column(Integer, ForeignKey("nations.id"), nullable=False, index=True)
    name = Column(String(128))
    origin_territory = Column(Integer, ForeignKey("territories.id"))
    destination_territory = Column(Integer, ForeignKey("territories.id"), index=True)
    unit_count = Column(Integer, default=0, nullable=False)
    status = Column(String(32), default="stationed", nullable=False, index=True)
    departs_at = Column(DateTime(timezone=True))
    arrives_at = Column(DateTime(timezone=True))
    confirmation_expires_at = Column(DateTime(timezone=True))
    occupation_expires_at = Column(DateTime(timezone=True))
    standing_order = Column(String(32), default="hold", nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    nation = relationship("Nation", back_populates="fleets")
    origin_territory_rel = relationship("Territory", back_populates="fleets_origin",
                                        foreign_keys=[origin_territory])
    destination_territory_rel = relationship("Territory", back_populates="fleets_destination",
                                             foreign_keys=[destination_territory])

    __table_args__ = (
        # Tick processing finds all in-transit fleets that have arrived
        Index("ix_fleets_status_arrives_at", "status", "arrives_at"),
        # Find fleets pending confirmation window expiry
        Index("ix_fleets_status_confirmation_expires", "status", "confirmation_expires_at"),
        # Find fleets in occupation window
        Index("ix_fleets_status_occupation_expires", "status", "occupation_expires_at"),
    )
