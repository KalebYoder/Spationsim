from datetime import datetime, timezone
from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from sqlalchemy.orm import Session
from ..db.database import get_db
from ..models.player import Player
from ..models.nation import Nation
from ..schemas.auth import LoginRequest, PlayerResponse, RegisterRequest
from ..core.security import create_access_token, decode_token, hash_password, verify_password
from ..core.config import settings

router = APIRouter(prefix="/api/auth", tags=["auth"])

_COOKIE = "session"
_COOKIE_MAX_AGE = 60 * 60 * 24 * 7  # 7 days


def _player_response(player: Player, db: Session) -> PlayerResponse:
    has_nation = db.query(Nation).filter(Nation.player_id == player.id).first() is not None
    return PlayerResponse(
        id=player.id,
        username=player.username,
        email=player.email,
        has_nation=has_nation,
    )


def _set_session_cookie(response: Response, player_id: int) -> None:
    token = create_access_token(player_id)
    response.set_cookie(
        key=_COOKIE,
        value=token,
        httponly=True,
        samesite="lax",
        secure=settings.environment == "production",
        max_age=_COOKIE_MAX_AGE,
    )


def get_current_player(
    session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
) -> Player:
    if not session:
        raise HTTPException(status_code=401, detail="Not authenticated")
    player_id = decode_token(session)
    if not player_id:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    player = db.get(Player, player_id)
    if not player or not player.is_active:
        raise HTTPException(status_code=401, detail="Account not found or inactive")
    return player


@router.post("/register", response_model=PlayerResponse, status_code=201)
def register(body: RegisterRequest, response: Response, db: Session = Depends(get_db)):
    if db.query(Player).filter(Player.username.ilike(body.username)).first():
        raise HTTPException(status_code=409, detail="Username already taken")
    if db.query(Player).filter(Player.email == body.email).first():
        raise HTTPException(status_code=409, detail="Email already registered")

    player = Player(
        username=body.username,
        email=body.email,
        password_hash=hash_password(body.password),
    )
    db.add(player)
    db.commit()
    db.refresh(player)

    _set_session_cookie(response, player.id)
    return _player_response(player, db)


@router.post("/login", response_model=PlayerResponse)
def login(body: LoginRequest, response: Response, db: Session = Depends(get_db)):
    player = db.query(Player).filter(Player.username.ilike(body.username)).first()
    if not player or not verify_password(body.password, player.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    if not player.is_active:
        raise HTTPException(status_code=403, detail="Account is inactive")

    player.last_login = datetime.now(timezone.utc)
    db.commit()

    _set_session_cookie(response, player.id)
    return _player_response(player, db)


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(_COOKIE)
    return {"ok": True}


@router.get("/me", response_model=PlayerResponse)
def me(player: Player = Depends(get_current_player), db: Session = Depends(get_db)):
    return _player_response(player, db)
