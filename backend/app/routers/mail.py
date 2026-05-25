from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, aliased
from ..db.database import get_db
from ..models.mail_message import MailMessage
from ..models.nation import Nation
from ..models.player import Player
from ..schemas.messaging import (
    MailSendRequest,
    MailSummaryResponse,
    MailDetailResponse,
    UnreadCountResponse,
)
from ..routers.auth import get_current_player

router = APIRouter(prefix="/api/mail", tags=["mail"])


def _summary(msg: MailMessage, sender_name: str, recipient_name: str) -> MailSummaryResponse:
    return MailSummaryResponse(
        id=msg.id,
        sender_nation_id=msg.sender_nation_id,
        sender_nation_name=sender_name,
        recipient_nation_id=msg.recipient_nation_id,
        recipient_nation_name=recipient_name,
        subject=msg.subject,
        read=msg.read,
        sent_at=msg.sent_at.isoformat(),
    )


def _detail(msg: MailMessage, sender_name: str, recipient_name: str) -> MailDetailResponse:
    return MailDetailResponse(
        id=msg.id,
        sender_nation_id=msg.sender_nation_id,
        sender_nation_name=sender_name,
        recipient_nation_id=msg.recipient_nation_id,
        recipient_nation_name=recipient_name,
        subject=msg.subject,
        body=msg.body,
        read=msg.read,
        sent_at=msg.sent_at.isoformat(),
    )


def _get_nation(player: Player, db: Session) -> Nation:
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        raise HTTPException(status_code=404, detail="No nation found")
    return nation


@router.get("/unread-count", response_model=UnreadCountResponse)
def unread_count(
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = _get_nation(player, db)
    count = (
        db.query(MailMessage)
        .filter(
            MailMessage.recipient_nation_id == nation.id,
            MailMessage.read == False,  # noqa: E712
            MailMessage.deleted_by_recipient == False,  # noqa: E712
        )
        .count()
    )
    return UnreadCountResponse(count=count)


@router.get("/inbox", response_model=list[MailSummaryResponse])
def inbox(
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = _get_nation(player, db)
    SenderN = aliased(Nation)
    RecipN = aliased(Nation)
    rows = (
        db.query(MailMessage, SenderN.name, RecipN.name)
        .join(SenderN, MailMessage.sender_nation_id == SenderN.id)
        .join(RecipN, MailMessage.recipient_nation_id == RecipN.id)
        .filter(
            MailMessage.recipient_nation_id == nation.id,
            MailMessage.deleted_by_recipient == False,  # noqa: E712
        )
        .order_by(MailMessage.sent_at.desc())
        .all()
    )
    return [_summary(msg, sn, rn) for msg, sn, rn in rows]


@router.get("/outbox", response_model=list[MailSummaryResponse])
def outbox(
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = _get_nation(player, db)
    SenderN = aliased(Nation)
    RecipN = aliased(Nation)
    rows = (
        db.query(MailMessage, SenderN.name, RecipN.name)
        .join(SenderN, MailMessage.sender_nation_id == SenderN.id)
        .join(RecipN, MailMessage.recipient_nation_id == RecipN.id)
        .filter(
            MailMessage.sender_nation_id == nation.id,
            MailMessage.deleted_by_sender == False,  # noqa: E712
        )
        .order_by(MailMessage.sent_at.desc())
        .all()
    )
    return [_summary(msg, sn, rn) for msg, sn, rn in rows]


@router.get("/{mail_id}", response_model=MailDetailResponse)
def read_mail(
    mail_id: int,
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = _get_nation(player, db)
    SenderN = aliased(Nation)
    RecipN = aliased(Nation)
    row = (
        db.query(MailMessage, SenderN.name, RecipN.name)
        .join(SenderN, MailMessage.sender_nation_id == SenderN.id)
        .join(RecipN, MailMessage.recipient_nation_id == RecipN.id)
        .filter(MailMessage.id == mail_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Mail not found")
    msg, sender_name, recipient_name = row
    if msg.sender_nation_id != nation.id and msg.recipient_nation_id != nation.id:
        raise HTTPException(status_code=403, detail="Access denied")
    if msg.recipient_nation_id == nation.id and not msg.read:
        msg.read = True
        db.commit()
    return _detail(msg, sender_name, recipient_name)


@router.post("", status_code=201)
def send_mail(
    body: MailSendRequest,
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = _get_nation(player, db)
    if body.recipient_nation_id == nation.id:
        raise HTTPException(status_code=409, detail="Cannot send mail to yourself")
    recipient = db.get(Nation, body.recipient_nation_id)
    if not recipient:
        raise HTTPException(status_code=404, detail="Recipient nation not found")
    msg = MailMessage(
        sender_nation_id=nation.id,
        recipient_nation_id=body.recipient_nation_id,
        subject=body.subject,
        body=body.body,
    )
    db.add(msg)
    db.commit()
    return {"id": msg.id}


@router.delete("/{mail_id}", status_code=204)
def delete_mail(
    mail_id: int,
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = _get_nation(player, db)
    msg = db.get(MailMessage, mail_id)
    if not msg:
        raise HTTPException(status_code=404, detail="Mail not found")
    if msg.sender_nation_id == nation.id:
        msg.deleted_by_sender = True
    elif msg.recipient_nation_id == nation.id:
        msg.deleted_by_recipient = True
    else:
        raise HTTPException(status_code=403, detail="Access denied")
    db.commit()
