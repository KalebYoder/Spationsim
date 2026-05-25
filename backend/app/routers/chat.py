from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session
from ..db.database import get_db
from ..models.chat_message import ChatMessage
from ..models.nation import Nation
from ..models.player import Player
from ..schemas.messaging import ChatMessageCreate, ChatMessageResponse, DmChannelInfo
from ..routers.auth import get_current_player

router = APIRouter(prefix="/api/chat", tags=["chat"])

ALLOWED_PUBLIC_CHANNELS = {"general", "trade"}
HISTORY_LIMIT = 100


def _dm_channel(id1: int, id2: int) -> str:
    return f"dm_{min(id1, id2)}_{max(id1, id2)}"


def _authorize_channel(channel: str, nation_id: int) -> None:
    if channel in ALLOWED_PUBLIC_CHANNELS:
        return
    if channel.startswith("dm_"):
        parts = channel.split("_")
        if len(parts) == 3:
            try:
                if nation_id in {int(parts[1]), int(parts[2])}:
                    return
            except ValueError:
                pass
    raise HTTPException(status_code=403, detail="Not authorized for this channel")


def _msg_response(msg: ChatMessage, sender_name: str) -> ChatMessageResponse:
    return ChatMessageResponse(
        id=msg.id,
        channel=msg.channel,
        sender_nation_id=msg.sender_nation_id,
        sender_nation_name=sender_name,
        content=msg.content,
        created_at=msg.created_at.isoformat(),
    )


@router.get("/messages", response_model=list[ChatMessageResponse])
def get_messages(
    channel: str,
    after_id: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        raise HTTPException(status_code=404, detail="No nation found")
    _authorize_channel(channel, nation.id)

    q = (
        db.query(ChatMessage, Nation.name)
        .join(Nation, ChatMessage.sender_nation_id == Nation.id)
        .filter(ChatMessage.channel == channel)
    )
    if after_id > 0:
        q = q.filter(ChatMessage.id > after_id)
        rows = q.order_by(ChatMessage.id.asc()).all()
    else:
        rows = q.order_by(ChatMessage.id.desc()).limit(HISTORY_LIMIT).all()
        rows = list(reversed(rows))

    return [_msg_response(msg, name) for msg, name in rows]


@router.post("/messages", response_model=ChatMessageResponse, status_code=201)
def send_message(
    body: ChatMessageCreate,
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        raise HTTPException(status_code=404, detail="No nation found")
    _authorize_channel(body.channel, nation.id)

    msg = ChatMessage(
        channel=body.channel,
        sender_nation_id=nation.id,
        content=body.content,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return _msg_response(msg, nation.name)


@router.get("/dm-channels", response_model=list[DmChannelInfo])
def get_dm_channels(
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        raise HTTPException(status_code=404, detail="No nation found")

    nid = nation.id
    rows = (
        db.query(ChatMessage.channel)
        .filter(
            or_(
                ChatMessage.channel.like(f"dm\\_{nid}\\_%", escape="\\"),
                ChatMessage.channel.like(f"dm\\_%" + f"\\_{nid}", escape="\\"),
            )
        )
        .distinct()
        .all()
    )

    result = []
    for (channel,) in rows:
        parts = channel.split("_")
        if len(parts) != 3:
            continue
        try:
            id1, id2 = int(parts[1]), int(parts[2])
        except ValueError:
            continue
        other_id = id2 if id1 == nid else id1
        other = db.get(Nation, other_id)
        if other:
            result.append(DmChannelInfo(
                channel=channel,
                other_nation_id=other_id,
                other_nation_name=other.name,
            ))
    return result
