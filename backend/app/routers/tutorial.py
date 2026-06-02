from datetime import datetime, timezone
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ..db.database import get_db
from ..routers.auth import get_current_player
from ..models.player import Player
from ..models.nation import Nation
from ..models.tutorial import TutorialState
from ..models.event import Event
from ..services.tutorial import get_tutorial_reward, next_step, should_complete_step_on_action

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


def _no_nation_state() -> dict:
    return {
        "current_step": 11,
        "dismissed": False,
        "step1_completed_at": None,
        "step2_completed_at": None,
        "step3_completed_at": None,
        "step4_completed_at": None,
    }


@router.get("/")
def get_tutorial_state(
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        return _no_nation_state()
    tutorial = db.query(TutorialState).filter(TutorialState.nation_id == nation.id).first()
    if not tutorial:
        return _no_nation_state()
    return _state_dict(tutorial)


@router.post("/complete-step-3")
def complete_step_3(
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        return _no_nation_state()
    tutorial = db.query(TutorialState).filter(TutorialState.nation_id == nation.id).first()
    if not tutorial:
        return _no_nation_state()
    if tutorial.current_step != 3 or tutorial.dismissed:
        return _state_dict(tutorial)
    now = datetime.now(timezone.utc)
    tutorial.step3_completed_at = now
    tutorial.current_step = next_step(3)
    reward = get_tutorial_reward(3)
    nation.minerals += reward["minerals"]
    nation.fuel += reward["fuel"]
    nation.currency += reward["currency"]
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


@router.post("/complete-step-6")
def complete_step_6(
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        return _no_nation_state()
    tutorial = db.query(TutorialState).filter(TutorialState.nation_id == nation.id).first()
    if not tutorial:
        return _no_nation_state()
    if tutorial.current_step != 6 or tutorial.dismissed:
        return _state_dict(tutorial)
    now = datetime.now(timezone.utc)
    tutorial.current_step = next_step(6)
    db.add(Event(
        type="tutorial_step_complete",
        payload={"step": 6, "nation_id": nation.id},
        scheduled_for=now,
        processed_at=now,
        status="processed",
    ))
    db.commit()
    db.refresh(tutorial)
    return _state_dict(tutorial)


@router.post("/complete-step-9")
def complete_step_9(
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        return _no_nation_state()
    tutorial = db.query(TutorialState).filter(TutorialState.nation_id == nation.id).first()
    if not tutorial:
        return _no_nation_state()
    if tutorial.current_step != 9 or tutorial.dismissed:
        return _state_dict(tutorial)
    now = datetime.now(timezone.utc)
    tutorial.current_step = next_step(9)
    db.add(Event(
        type="tutorial_step_complete",
        payload={"step": 9, "nation_id": nation.id},
        scheduled_for=now,
        processed_at=now,
        status="processed",
    ))
    db.commit()
    db.refresh(tutorial)
    return _state_dict(tutorial)


@router.post("/complete-step-10")
def complete_step_10(
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        return _no_nation_state()
    tutorial = db.query(TutorialState).filter(TutorialState.nation_id == nation.id).first()
    if not tutorial:
        return _no_nation_state()
    if tutorial.current_step != 10 or tutorial.dismissed:
        return _state_dict(tutorial)
    now = datetime.now(timezone.utc)
    reward = get_tutorial_reward(10)
    nation.minerals += reward["minerals"]
    nation.fuel += reward["fuel"]
    nation.currency += reward["currency"]
    tutorial.current_step = next_step(10)
    db.add(Event(
        type="tutorial_step_complete",
        payload={
            "step": 10,
            "nation_id": nation.id,
            "reward_minerals": reward["minerals"],
            "reward_fuel": reward["fuel"],
            "reward_currency": reward["currency"],
        },
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


def _apply_tutorial_action(nation_id: int, action: str, db) -> None:
    tutorial = db.query(TutorialState).filter(
        TutorialState.nation_id == nation_id,
        TutorialState.dismissed == False,
    ).first()
    if not tutorial:
        return
    if not should_complete_step_on_action(tutorial.current_step, action):
        return

    reward = get_tutorial_reward(tutorial.current_step)
    nation_obj = db.get(Nation, nation_id)
    if nation_obj:
        nation_obj.minerals += reward["minerals"]
        nation_obj.fuel += reward["fuel"]
        nation_obj.currency += reward["currency"]

    completed_step = tutorial.current_step
    tutorial.current_step = next_step(tutorial.current_step)
    now = datetime.now(timezone.utc)
    db.add(Event(
        type="tutorial_step_complete",
        payload={
            "step": completed_step,
            "nation_id": nation_id,
            "reward_minerals": reward["minerals"],
            "reward_fuel": reward["fuel"],
            "reward_currency": reward["currency"],
        },
        scheduled_for=now,
        processed_at=now,
        status="processed",
    ))
