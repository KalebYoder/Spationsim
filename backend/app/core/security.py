from datetime import datetime, timedelta, timezone
from jose import jwt, JWTError
from passlib.context import CryptContext
from .config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(player_id: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=settings.access_token_expire_days)
    return jwt.encode(
        {"sub": str(player_id), "exp": expire},
        settings.secret_key,
        algorithm=settings.algorithm,
    )


def decode_token(token: str) -> int | None:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        return int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        return None
