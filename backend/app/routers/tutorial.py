from datetime import datetime, timezone
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ..db.database import get_db
from ..routers.auth import get_current_player
from ..models.player import Player
from ..models.nation import Nation
from ..models.tutorial import TutorialState
from ..models.event import Event
from ..services.tutorial import get_tutorial_reward, next_step

router = APIRouter(prefix="/api/tutorial", tags=["tutorial"])


def _state_dict(t: TutorialState) -> dict:
    return {
        "current_step": t.current_step,
        "dismissed": t.dismissed,
        "step1_completed_at": t.step1_completed_at.isoformat() if t.step1_completed_at else None,
        "step2_completed_at": t.step2_completed_at.isoformat() if t.step2_completed_at else None,
        "step3_completed_at": t.step3_completed_at.isoformat() if t.step3_completed_at else None,
        "step4_completed_at": t.step4_completed_at.isoformat() if t.step4_completed_at else None,
    }


@router.get("/")
def get_tutorial_state(
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        return {"current_step": 5, "dismissed": False, "step1_completed_at": None,
                "step2_completed_at": None, "step3_completed_at": None, "step4_completed_at": None}
    tutorial = db.query(TutorialState).filter(TutorialState.nation_id == nation.id).first()
    if not tutorial:
        return {"current_step": 5, "dismissed": False, "step1_completed_at": None,
                "step2_completed_at": None, "step3_completed_at": None, "step4_completed_at": None}
    return _state_dict(tutorial)


@router.post("/complete-step-3")
def complete_step_3(
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        return {"current_step": 5, "dismissed": False, "step1_completed_at": None,
                "step2_completed_at": None, "step3_completed_at": None, "step4_completed_at": None}
    tutorial = db.query(TutorialState).filter(TutorialState.nation_id == nation.id).first()
    if not tutorial:
        return {"current_step": 5, "dismissed": False, "step1_completed_at": None,
                "step2_completed_at": None, "step3_completed_at": None, "step4_completed_at": None}
    if tutorial.current_step != 3 or tutorial.dismissed:
        return _state_dict(tutorial)
    now = datetime.now(timezone.utc)
    tutorial.step3_completed_at = now
    tutorial.current_step = next_step(3)
    db.add(Event(
        type="tutorial_step_complete",
        payload={"step": 3, "nation_id": nation.id},
        scheduled_for=now,
        processed_at=now,
        status="processed",
    ))
    db.commit()
    db.refresh(tutorial)
    return _state_dict(tutorial)


@router.post("/dismiss")
def dismiss_tutorial(
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        return {"ok": True}
    tutorial = db.query(TutorialState).filter(TutorialState.nation_id == nation.id).first()
    if not tutorial:
        return {"ok": True}
    tutorial.dismissed = True
    db.commit()
    return {"ok": True}
