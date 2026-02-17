# app/routers/stats_router.py
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, extract, and_
from datetime import datetime, date
from zoneinfo import ZoneInfo

from app.db import SessionLocal
from app.model import Transaction, Upload, User
from app.deps import get_current_user

router = APIRouter(prefix="/stats", tags=["Statistics"])

BKK = ZoneInfo("Asia/Bangkok")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def _month_range(y: int, m: int):
    start = date(y, m, 1)
    if m == 12:
        end = date(y + 1, 1, 1)
    else:
        end = date(y, m + 1, 1)
    return start, end

def _base_query(db: Session, user_id):
    # ✅ ของ user คนนี้เท่านั้น
    return (
        db.query(Transaction)
        .join(Upload, Transaction.upload_id == Upload.id)
        .filter(Upload.user_id == user_id)
    )

def _apply_range(q, range: str, year: int | None, month: int | None):
    if range == "all":
        return q

    if range == "year":
        if not year:
            raise HTTPException(status_code=400, detail="year is required for range=year")
        return q.filter(extract("year", Transaction.transferred_at) == year)

    if range == "month":
        if not year or not month:
            raise HTTPException(status_code=400, detail="year and month are required for range=month")
        start, end = _month_range(year, month)
        start_dt = datetime.combine(start, datetime.min.time(), tzinfo=BKK)
        end_dt = datetime.combine(end, datetime.min.time(), tzinfo=BKK)
        return q.filter(Transaction.transferred_at >= start_dt, Transaction.transferred_at < end_dt)

    raise HTTPException(status_code=400, detail="invalid range")

@router.get("/")
def stats(
    range: str = Query("all", pattern="^(all|month|year)$"),
    year: int | None = None,
    month: int | None = None,  # 1-12
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = _apply_range(_base_query(db, user.id), range, year, month)

    # ✅ กัน null transferred_at ทำให้สถิติเพี้ยน (เลือกเอาเฉพาะที่มีเวลาแล้ว)
    q_valid = q.filter(Transaction.transferred_at.isnot(None))

    # -------------------------
    # Cards
    # -------------------------
    total_expenses = (
        q_valid.with_entities(func.coalesce(func.sum(Transaction.amount), 0))
        .scalar()
    )
    total_expenses = float(total_expenses or 0)

    total_transactions = (
        q.with_entities(func.count(Transaction.id)).scalar()
    )
    total_transactions = int(total_transactions or 0)

    top_category_row = (
        q_valid.with_entities(
            Transaction.category,
            func.coalesce(func.sum(Transaction.amount), 0).label("total")
        )
        .group_by(Transaction.category)
        .order_by(func.coalesce(func.sum(Transaction.amount), 0).desc())
        .first()
    )
    top_category = top_category_row[0] if top_category_row and top_category_row[0] else "Others"

    top_bank_row = (
        q_valid.with_entities(
            Transaction.bank,
            func.coalesce(func.sum(Transaction.amount), 0).label("total")
        )
        .group_by(Transaction.bank)
        .order_by(func.coalesce(func.sum(Transaction.amount), 0).desc())
        .first()
    )
    top_bank = top_bank_row[0] if top_bank_row and top_bank_row[0] else "-"

    # -------------------------
    # Category Expenses (bar)
    # -------------------------
    cat_rows = (
        q_valid.with_entities(
            Transaction.category,
            func.coalesce(func.sum(Transaction.amount), 0).label("total")
        )
        .group_by(Transaction.category)
        .order_by(func.coalesce(func.sum(Transaction.amount), 0).desc())
        .all()
    )
    category_expenses = [
        {"category": (c or "Others"), "total": float(t or 0)}
        for c, t in cat_rows
    ]

    # -------------------------
    # Bank Distribution (pie)
    # -------------------------
    bank_rows = (
        q_valid.with_entities(
            Transaction.bank,
            func.coalesce(func.sum(Transaction.amount), 0).label("total")
        )
        .group_by(Transaction.bank)
        .order_by(func.coalesce(func.sum(Transaction.amount), 0).desc())
        .all()
    )
    bank_distribution = [
        {"bank": (b or "-"), "total": float(t or 0)}
        for b, t in bank_rows
    ]

    # -------------------------
    # Expenses Over Time (line/area)
    # -------------------------
    # all  => group by year
    # month => group by day
    # year => group by month
    if range == "all":
        ts_rows = (
            q_valid.with_entities(
                extract("year", Transaction.transferred_at).label("k"),
                func.coalesce(func.sum(Transaction.amount), 0).label("total")
            )
            .group_by("k")
            .order_by("k")
            .all()
        )
        expenses_over_time = [{"x": int(k), "total": float(t)} for k, t in ts_rows]

    elif range == "month":
        # group by day (1..31)
        ts_rows = (
            q_valid.with_entities(
                extract("day", Transaction.transferred_at).label("k"),
                func.coalesce(func.sum(Transaction.amount), 0).label("total")
            )
            .group_by("k")
            .order_by("k")
            .all()
        )
        expenses_over_time = [{"x": int(k), "total": float(t)} for k, t in ts_rows]

    else:  # year
        ts_rows = (
            q_valid.with_entities(
                extract("month", Transaction.transferred_at).label("k"),
                func.coalesce(func.sum(Transaction.amount), 0).label("total")
            )
            .group_by("k")
            .order_by("k")
            .all()
        )
        expenses_over_time = [{"x": int(k), "total": float(t)} for k, t in ts_rows]

    return {
        "filter": {"range": range, "year": year, "month": month},
        "cards": {
            "total_expenses": total_expenses,
            "top_category": top_category,
            "top_bank": top_bank,
            "total_transactions": total_transactions,
        },
        "expenses_over_time": expenses_over_time,
        "bank_distribution": bank_distribution,
        "category_expenses": category_expenses,
    }
