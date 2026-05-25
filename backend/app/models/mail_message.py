from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, Index
from sqlalchemy.sql import func
from ..db.database import Base


class MailMessage(Base):
    __tablename__ = "mail_messages"

    id = Column(Integer, primary_key=True)
    sender_nation_id = Column(Integer, ForeignKey("nations.id"), nullable=False)
    recipient_nation_id = Column(Integer, ForeignKey("nations.id"), nullable=False)
    subject = Column(String(256), nullable=False)
    body = Column(Text, nullable=False)
    read = Column(Boolean, default=False, nullable=False)
    deleted_by_sender = Column(Boolean, default=False, nullable=False)
    deleted_by_recipient = Column(Boolean, default=False, nullable=False)
    sent_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_mail_recipient_read", "recipient_nation_id", "read"),
        Index("ix_mail_sender_sent_at", "sender_nation_id", "sent_at"),
    )
