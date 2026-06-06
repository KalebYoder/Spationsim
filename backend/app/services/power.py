from sqlalchemy.orm import Session
from sqlalchemy import func as sqlfunc
from ..models.fleet import Fleet


def military_strength(db: Session, nation_id: int) -> int:
    return int(
        db.query(sqlfunc.coalesce(sqlfunc.sum(Fleet.unit_count), 0))
        .filter(Fleet.nation_id == nation_id)
        .scalar()
    )
