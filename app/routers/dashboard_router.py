from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

from app.db import SessionLocal
from app.model import Transaction, Upload, User
from app.deps import get_current_user

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

BKK = ZoneInfo("Asia/Bangkok")

def _pct_change(current: float, previous: float) -> float:
    if previous == 0:
        return 0.0 if current == 0 else 100.0
    return ((current - previous) / previous) * 100.0

def _month_range(d: date):
    start = d.replace(day=1)
    if start.month == 12:
        next_month = date(start.year + 1, 1, 1)
    else:
        next_month = date(start.year, start.month + 1, 1)
    return start, next_month

def _dt_start(d: date) -> datetime:
    # 00:00:00 เวลาไทย
    return datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=BKK)

@router.get("/")
def dashboard(
    request: Request,  
    view: str = Query("month", pattern="^(today|month|year)$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    now = datetime.now(tz=BKK)
    today = now.date()
    yesterday = today - timedelta(days=1)

    # เดือนนี้ / เดือนก่อน
    this_m_start, _ = _month_range(today)
    prev_m_end = this_m_start
    prev_m_start, _ = _month_range(prev_m_end - timedelta(days=1))

    # ปีนี้ / ปีหน้า
    this_y_start = date(today.year, 1, 1)
    next_y_start = date(today.year + 1, 1, 1)

    # ✅ query base ของ user นี้เท่านั้น (join uploads แค่ครั้งเดียว)
    base = (
        db.query(Transaction)
        .join(Upload, Transaction.upload_id == Upload.id)
        .filter(Upload.user_id == user.id)
    )

    # -------------------------
    # 1) Average per Day (วันนี้) + % เทียบเมื่อวาน
    # -------------------------
    today_sum = (
        base.filter(func.date(Transaction.transferred_at) == today)
        .with_entities(func.coalesce(func.sum(Transaction.amount), 0))
        .scalar()
    )
    yday_sum = (
        base.filter(func.date(Transaction.transferred_at) == yesterday)
        .with_entities(func.coalesce(func.sum(Transaction.amount), 0))
        .scalar()
    )
    today_sum = float(today_sum or 0)
    yday_sum = float(yday_sum or 0)
    avg_day_pct = _pct_change(today_sum, yday_sum)

    # -------------------------
    # 2) Total Monthly Expense (ต้นเดือน -> ตอนนี้) + % เทียบช่วงเดียวกันเดือนก่อน
    # -------------------------
    month_sum = (
        base.filter(Transaction.transferred_at >= _dt_start(this_m_start))
            .filter(Transaction.transferred_at <= now)
        .with_entities(func.coalesce(func.sum(Transaction.amount), 0))
        .scalar()
    )

    days_into_month = (today - this_m_start).days
    prev_cutoff_date = prev_m_start + timedelta(days=days_into_month)
    prev_cutoff_dt = datetime(
        prev_cutoff_date.year, prev_cutoff_date.month, prev_cutoff_date.day,
        now.hour, now.minute, now.second, tzinfo=BKK
    )

    prev_month_sum = (
        base.filter(Transaction.transferred_at >= _dt_start(prev_m_start))
            .filter(Transaction.transferred_at <= prev_cutoff_dt)
        .with_entities(func.coalesce(func.sum(Transaction.amount), 0))
        .scalar()
    )

    month_sum = float(month_sum or 0)
    prev_month_sum = float(prev_month_sum or 0)
    month_pct = _pct_change(month_sum, prev_month_sum)

    # -------------------------
    # 3) Total Transactions (เดือนนี้) + % เทียบเดือนก่อน
    # -------------------------
    month_tx_count = (
        base.filter(Transaction.transferred_at >= _dt_start(this_m_start))
            .filter(Transaction.transferred_at <= now)
        .with_entities(func.count(Transaction.id))
        .scalar()
    )

    prev_month_tx_count = (
        base.filter(Transaction.transferred_at >= _dt_start(prev_m_start))
            .filter(Transaction.transferred_at <= prev_cutoff_dt)
        .with_entities(func.count(Transaction.id))
        .scalar()
    )

    month_tx_count = int(month_tx_count or 0)
    prev_month_tx_count = int(prev_month_tx_count or 0)
    tx_pct = _pct_change(month_tx_count, prev_month_tx_count)

    # -------------------------
    # 4) Top Spending Category (เดือนนี้) + % เทียบเดือนก่อน (นับจำนวน)
    # -------------------------
    top_cat_q = (
        base.filter(Transaction.transferred_at >= _dt_start(this_m_start))
            .filter(Transaction.transferred_at <= now)
        .with_entities(Transaction.category, func.count(Transaction.id).label("cnt"))
        .group_by(Transaction.category)
        .order_by(func.count(Transaction.id).desc())
        .first()
    )

    top_category = top_cat_q[0] if top_cat_q and top_cat_q[0] else "Others"
    top_category_count = int(top_cat_q[1]) if top_cat_q else 0

    prev_top_cat_q = (
        base.filter(Transaction.transferred_at >= _dt_start(prev_m_start))
            .filter(Transaction.transferred_at <= prev_cutoff_dt)
        .with_entities(Transaction.category, func.count(Transaction.id).label("cnt"))
        .group_by(Transaction.category)
        .order_by(func.count(Transaction.id).desc())
        .first()
    )

    prev_top_category_count = int(prev_top_cat_q[1]) if prev_top_cat_q else 0
    top_cat_pct = _pct_change(top_category_count, prev_top_category_count)

    # -------------------------
    # 5) Expense by Category (today/month/year)
    # -------------------------
    cat_filter = base
    if view == "today":
        cat_filter = cat_filter.filter(func.date(Transaction.transferred_at) == today)
    elif view == "month":
        cat_filter = cat_filter.filter(Transaction.transferred_at >= _dt_start(this_m_start)).filter(Transaction.transferred_at <= now)
    elif view == "year":
        cat_filter = cat_filter.filter(Transaction.transferred_at >= _dt_start(this_y_start)).filter(Transaction.transferred_at < _dt_start(next_y_start))

    by_category = (
        cat_filter.with_entities(
            Transaction.category,
            func.coalesce(func.sum(Transaction.amount), 0).label("total")
        )
        .group_by(Transaction.category)
        .order_by(func.coalesce(func.sum(Transaction.amount), 0).desc())
        .all()
    )

    chart = [{"category": (c or "Others"), "total": float(t)} for c, t in by_category]

    # -------------------------
    # 6) Recent Transactions (ล่าสุด 8 รายการ)
    # ✅ ใช้ base เดิมเพื่อกัน join ซ้ำ + ดึง file_path ผ่าน relationship
    # -------------------------
    recent = (
        base.order_by(Transaction.created_at.desc())
            .limit(8)
            .all()
    )

    api_base = str(request.base_url).rstrip("/")  

    recent_rows = []
    for tx in recent:
        up = tx.upload  
        dt = tx.transferred_at

        
        file_url = None
        if up and up.file_path:
            file_url = f"{api_base}/{up.file_path.lstrip('/')}"

        recent_rows.append({
            "id": str(tx.id),
            "category": tx.category or "Others",
            "bank": tx.bank,
            "date": dt.astimezone(BKK).date().isoformat() if dt else None,
            "amount": float(tx.amount) if tx.amount is not None else 0,
            "file_url": file_url
        })

    return {
        "cards": {
            "average_per_day": {"value": today_sum, "pct": avg_day_pct},
            "total_monthly_expense": {"value": month_sum, "pct": month_pct},
            "total_transactions": {"value": month_tx_count, "pct": tx_pct},
            "top_spending_category": {"category": top_category, "value": top_category_count, "pct": top_cat_pct},
        },
        "expense_by_category": {
            "view": view,
            "items": chart
        },
        "recent_transactions": recent_rows
    }
