from sqlalchemy import Column, Integer, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from ..db.database import Base


class TutorialState(Base):
    __tablename__ = "tutorial_state"

    nation_id = Column(Integer, ForeignKey("nations.id"), primary_key=True)
    current_step = Column(Integer, default=1, nullable=False)
    dismissed = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    step1_completed_at = Column(DateTime(timezone=True), nullable=True)
    step2_completed_at = Column(DateTime(timezone=True), nullable=True)
    step3_completed_at = Column(DateTime(timezone=True), nullable=True)
    step4_completed_at = Column(DateTime(timezone=True), nullable=True)

    nation = relationship("Nation", back_populates="tutorial_state")
