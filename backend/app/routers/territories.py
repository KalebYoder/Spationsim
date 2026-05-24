from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ..db.database import get_db
from ..models.territory import Territory
from ..schemas.nation import TerritoryResponse

router = APIRouter(prefix="/api/territories", tags=["territories"])


@router.get("/available", response_model=list[TerritoryResponse])
def available_territories(db: Session = Depends(get_db)):
    return (
        db.query(Territory)
        .filter(Territory.is_colonized == False)
        .order_by(Territory.distance_from_center)
        .all()
    )
