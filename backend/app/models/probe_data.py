from sqlalchemy import Column, Integer, Numeric, DateTime, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from ..db.database import Base


class ProbeData(Base):
    __tablename__ = "probe_data"

    id = Column(Integer, primary_key=True)
    territory_id = Column(Integer, ForeignKey("territories.id"), nullable=False, index=True)
    discovered_by = Column(Integer, ForeignKey("nations.id"), nullable=False, index=True)
    discovered_at = Column(DateTime(timezone=True), server_default=func.now())
    mineral_richness = Column(Numeric(4, 2), nullable=False)
    fuel_richness = Column(Numeric(4, 2), nullable=False)

    territory = relationship("Territory", back_populates="probe_data")
    discovered_by_nation = relationship("Nation", back_populates="probe_data_discovered",
                                         foreign_keys=[discovered_by])
    access_grants = relationship("ProbeDataAccess", back_populates="probe_data")

    __table_args__ = (
        # A nation can only have one probe record per territory
        UniqueConstraint("territory_id", "discovered_by", name="uq_probe_data_territory_nation"),
    )


class ProbeDataAccess(Base):
    __tablename__ = "probe_data_access"

    id = Column(Integer, primary_key=True)
    probe_data_id = Column(Integer, ForeignKey("probe_data.id"), nullable=False, index=True)
    granted_to = Column(Integer, ForeignKey("nations.id"), nullable=False, index=True)
    granted_at = Column(DateTime(timezone=True), server_default=func.now())
    price_paid = Column(Numeric(12, 2))

    probe_data = relationship("ProbeData", back_populates="access_grants")
    granted_to_nation = relationship("Nation", back_populates="probe_data_access",
                                     foreign_keys=[granted_to])

    __table_args__ = (
        UniqueConstraint("probe_data_id", "granted_to", name="uq_probe_data_access"),
    )
