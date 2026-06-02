from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ..db.database import get_db
from ..models.mail_message import MailMessage
from ..models.trade import Trade
from ..models.diplomacy import Diplomacy
from ..models.nation import Nation
from ..models.player import Player
from ..routers.auth import get_current_player

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("")
def get_notifications(
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        return {"mail_unread": 0, "friend_pending": 0, "trade_incoming": 0}

    mail_unread = (
        db.query(MailMessage)
        .filter(
            MailMessage.recipient_nation_id == nation.id,
            MailMessage.read == False,  # noqa: E712
            MailMessage.deleted_by_recipient == False,  # noqa: E712
        )
        .count()
    )

    friend_pending = (
        db.query(Diplomacy)
        .filter(
            Diplomacy.status == "friend_pending",
            Diplomacy.requested_by != nation.id,
            (Diplomacy.nation_a == nation.id) | (Diplomacy.nation_b == nation.id),
        )
        .count()
    )

    trade_incoming = (
        db.query(Trade)
        .filter(
            Trade.to_nation_id == nation.id,
            Trade.status == "pending",
        )
        .count()
    )

    return {
        "mail_unread": mail_unread,
        "friend_pending": friend_pending,
        "trade_incoming": trade_incoming,
    }
