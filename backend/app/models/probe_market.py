from sqlalchemy import Column, Integer, Numeric, DateTime, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from ..db.database import Base


class ProbeMarketListing(Base):
    __tablename__ = "probe_market_listings"

    id = Column(Integer, primary_key=True)
    probe_data_id = Column(Integer, ForeignKey("probe_data.id", ondelete="CASCADE"), nullable=False)
    seller_nation_id = Column(Integer, ForeignKey("nations.id"), nullable=False)
    price = Column(Numeric(12, 2), nullable=False)
    listed_at = Column(DateTime(timezone=True), server_default=func.now())

    probe_data = relationship("ProbeData")
    seller = relationship("Nation", foreign_keys=[seller_nation_id])

    __table_args__ = (
        UniqueConstraint("probe_data_id", "seller_nation_id", name="uq_probe_market_listing"),
        Index("ix_probe_market_seller", "seller_nation_id"),
    )
