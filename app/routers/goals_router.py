from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from datetime import datetime
from zoneinfo import ZoneInfo
from uuid import UUID
import re

from app.db import SessionLocal
from app.deps import get_current_user
from app.model import Goal, User

router = APIRouter(prefix="/goals", tags=["Goals"])

BKK = ZoneInfo("Asia/Bangkok")
MONTH_RE = re.compile(r"^\d{4}-\d{2}$")  # YYYY-MM

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def month_key_now() -> str:
    return datetime.now(tz=BKK).strftime("%Y-%m")

class GoalUpsert(BaseModel):
    month: str = Field(..., description="YYYY-MM เช่น 2026-03")
    amount: float = Field(..., gt=0)

@router.get("/current")
def get_current_goal(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    ใช้กับ popup:
    - คืน month ปัจจุบัน
    - has_goal = ตั้งแล้วหรือยัง
    """
    month = month_key_now()
    g = db.query(Goal).filter(Goal.user_id == user.id, Goal.month == month).first()
    return {
        "month": month,
        "has_goal": bool(g),
        "amount": float(g.amount) if g else None,
    }

@router.get("/")
def list_goals(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    goals = (
        db.query(Goal)
        .filter(Goal.user_id == user.id)
        .order_by(Goal.month.desc(), Goal.created_at.desc())
        .all()
    )
    return [
        {
            "id": str(g.id),
            "month": g.month,
            "amount": float(g.amount),
            "created_at": g.created_at.astimezone(BKK).isoformat() if g.created_at else None,
            "updated_at": g.updated_at.astimezone(BKK).isoformat() if g.updated_at else None,
        }
        for g in goals
    ]

@router.post("/")
def upsert_goal(
    payload: GoalUpsert,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Upsert:
    - ถ้ามี goal ของเดือนนั้นแล้ว -> update amount
    - ถ้ายังไม่มี -> create
    """
    if not MONTH_RE.match(payload.month):
        raise HTTPException(status_code=400, detail="month must be YYYY-MM")

    # normalize month (กันเคสแปลก)
    month = payload.month.strip()

    g = db.query(Goal).filter(Goal.user_id == user.id, Goal.month == month).first()
    if g:
        g.amount = payload.amount
        db.commit()
        db.refresh(g)
        return {
            "id": str(g.id),
            "month": g.month,
            "amount": float(g.amount),
            "updated_at": g.updated_at.astimezone(BKK).isoformat() if g.updated_at else None,
        }

    g = Goal(user_id=user.id, month=month, amount=payload.amount)
    db.add(g)

    try:
        db.commit()
    except IntegrityError:
        # กัน race condition: ถ้ามีแทรกซ้อนแล้วชน unique
        db.rollback()
        g2 = db.query(Goal).filter(Goal.user_id == user.id, Goal.month == month).first()
        if not g2:
            raise
        g2.amount = payload.amount
        db.commit()
        db.refresh(g2)
        return {"id": str(g2.id), "month": g2.month, "amount": float(g2.amount)}

    db.refresh(g)
    return {"id": str(g.id), "month": g.month, "amount": float(g.amount)}

@router.delete("/{goal_id}")
def delete_goal(
    goal_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    g = db.query(Goal).filter(Goal.id == goal_id, Goal.user_id == user.id).first()
    if not g:
        raise HTTPException(status_code=404, detail="goal not found")
    db.delete(g)
    db.commit()
    return {"ok": True}

class GoalUpdate(BaseModel):
    amount: float = Field(..., gt=0)

@router.patch("/{goal_id}")
def update_goal(
    goal_id: UUID,
    payload: GoalUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    g = db.query(Goal).filter(Goal.id == goal_id, Goal.user_id == user.id).first()
    if not g:
        raise HTTPException(status_code=404, detail="goal not found")

    g.amount = payload.amount
    db.commit()
    db.refresh(g)

    return {
        "id": str(g.id),
        "month": g.month,
        "amount": float(g.amount),
        "updated_at": g.updated_at.astimezone(BKK).isoformat() if g.updated_at else None,
    }