from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import extract, and_
from uuid import UUID
from datetime import datetime
from zoneinfo import ZoneInfo

from app.db import SessionLocal
from app.model import Transaction, User ,Upload
from app.deps import get_current_user
import os
API_BASE = os.getenv("API_BASE", "http://127.0.0.1:8000")

router = APIRouter(prefix="/transactions", tags=["Transactions"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class TransactionUpdate(BaseModel):
    bank: str | None = None
    amount: float | None = None
    date: str | None = None   # "YYYY-MM-DD" or "DD/MM/YY"
    time: str | None = None   # "HH:MM"
    memo: str | None = None
    category: str | None = None
    transferred_at: str | None = None

def _parse_transferred_at_iso(s: str):
    if not s:
        return None
    bkk = ZoneInfo("Asia/Bangkok")
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        # ถ้าไม่มี tz -> ใส่ Bangkok
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=bkk)
        else:
            dt = dt.astimezone(bkk)
        return dt
    except ValueError:
        return None

@router.get("/")
def list_transactions(
    range: str = Query("all", pattern="^(all|month|year)$"),
    year: int | None = None,
    month: int | None = None,  # 1-12
    bank: str | None = None,   # search bank
    page: int = 1,
    page_size: int = 100,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = (
        db.query(Transaction, Upload)
        .join(Upload, Transaction.upload_id == Upload.id)
        .filter(Upload.user_id == user.id)
    )

    if bank:
        q = q.filter(Transaction.bank.ilike(f"%{bank}%"))

    if range == "year":
        if not year:
            raise HTTPException(status_code=400, detail="year is required for range=year")
        q = q.filter(extract("year", Transaction.transferred_at) == year)

    elif range == "month":
        if not year or not month:
            raise HTTPException(status_code=400, detail="year and month are required for range=month")
        q = q.filter(
            and_(
                extract("year", Transaction.transferred_at) == year,
                extract("month", Transaction.transferred_at) == month,
            )
        )

    q = q.order_by(Transaction.created_at.desc())

    total = q.count()
    items = q.offset((page - 1) * page_size).limit(page_size).all()

    rows = []
    bkk = ZoneInfo("Asia/Bangkok")

    for tx, up in items:
        dt = tx.transferred_at

        if dt and dt.tzinfo is None:
            dt = dt.replace(tzinfo=bkk)

        file_path = f"/{up.file_path.lstrip('/')}" if up.file_path else None

        rows.append({
            "id": str(tx.id),
            "qr": f"{API_BASE}{file_path}" if file_path else None,
            "bank": tx.bank,
            "amount": float(tx.amount) if tx.amount is not None else 0,
            "date": dt.astimezone(bkk).date().isoformat() if dt else None,
            "time": dt.astimezone(bkk).strftime("%H:%M") if dt else None,
            "category": tx.category,
            "memo": tx.memo,
            "transferred_at": dt.astimezone(bkk).isoformat() if dt else None,
        })

    return {
        "rows": rows,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.patch("/{tx_id}")
def update_transaction(
    tx_id: UUID,
    payload: TransactionUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    tx = db.query(Transaction).filter(Transaction.id == tx_id).first()
    if not tx:
        raise HTTPException(status_code=404, detail="transaction not found")

    if not tx.upload or tx.upload.user_id != user.id:
        raise HTTPException(status_code=403, detail="forbidden")

    if payload.bank is not None:
        tx.bank = payload.bank
    if payload.amount is not None:
        tx.amount = payload.amount
    if payload.memo is not None:
        tx.memo = payload.memo
    if payload.category is not None:
        tx.category = payload.category
        tx.category_source = "user_selected"

    if payload.transferred_at is not None:
        new_dt = _parse_transferred_at_iso(payload.transferred_at)
        if not new_dt:
            raise HTTPException(status_code=400, detail="invalid transferred_at")
        tx.transferred_at = new_dt

    elif payload.date is not None or payload.time is not None:
        base_dt = tx.transferred_at
        bkk = ZoneInfo("Asia/Bangkok")

        if base_dt is None:
            if not payload.date:
                raise HTTPException(status_code=400, detail="date is required")
            new_dt = _parse_date_time(payload.date, payload.time or "00:00")
            if not new_dt:
                raise HTTPException(status_code=400, detail="invalid date/time")
            tx.transferred_at = new_dt
        else:
            if base_dt.tzinfo is None:
                base_dt = base_dt.replace(tzinfo=bkk)
            else:
                base_dt = base_dt.astimezone(bkk)

            if payload.date:
                tmp = _parse_date_time(payload.date, "00:00")
                if not tmp:
                    raise HTTPException(status_code=400, detail="invalid date")
                base_dt = base_dt.replace(year=tmp.year, month=tmp.month, day=tmp.day)

            if payload.time:
                tmp = _parse_date_time("2026-01-01", payload.time)
                if not tmp:
                    raise HTTPException(status_code=400, detail="invalid time")
                base_dt = base_dt.replace(hour=tmp.hour, minute=tmp.minute, second=0, microsecond=0)

            tx.transferred_at = base_dt


    db.commit()
    db.refresh(tx)

    dt = tx.transferred_at
    bkk = ZoneInfo("Asia/Bangkok")
    return {
        "id": str(tx.id),
        "bank": tx.bank,
        "amount": float(tx.amount) if tx.amount is not None else None,
        "memo": tx.memo,
        "category": tx.category,
        "transferred_at": dt.isoformat() if dt else None,
        "date": dt.astimezone(bkk).date().isoformat() if dt else None,
        "time": dt.astimezone(bkk).strftime("%H:%M") if dt else None,
        "file_path": f"/{tx.upload.file_path.lstrip('/')}" if tx.upload and tx.upload.file_path else None
    }
