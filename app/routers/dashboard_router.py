from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime
from zoneinfo import ZoneInfo

from app.db import SessionLocal
from app.model import Transaction, Upload, User
from app.deps import get_current_user

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

BKK = ZoneInfo("Asia/Bangkok")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _pct_change(current: float, previous: float) -> float:
    if previous == 0:
        return 0.0 if current == 0 else 100.0
    return ((current - previous) / previous) * 100.0


def _tz_date_expr():
    # แปลง transferred_at เป็นเวลาไทย แล้วตัดเหลือเฉพาะ date
    return func.date(func.timezone("Asia/Bangkok", Transaction.transferred_at))


@router.get("/")
def dashboard(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    now = datetime.now(tz=BKK)
    today = now.date()

    # เทียบกับเมื่อวานเฉพาะ % บนการ์ด
    from datetime import timedelta
    yesterday = today - timedelta(days=1)

    # query base ของ user คนนี้เท่านั้น
    base = (
        db.query(Transaction)
        .join(Upload, Transaction.upload_id == Upload.id)
        .filter(Upload.user_id == user.id)
    )

    # -------------------------
    # 1) Total Today + % เทียบเมื่อวาน
    # -------------------------
    today_sum = (
        base.filter(_tz_date_expr() == today)
        .with_entities(func.coalesce(func.sum(Transaction.amount), 0))
        .scalar()
    )
    yesterday_sum = (
        base.filter(_tz_date_expr() == yesterday)
        .with_entities(func.coalesce(func.sum(Transaction.amount), 0))
        .scalar()
    )

    today_sum = float(today_sum or 0)
    yesterday_sum = float(yesterday_sum or 0)
    total_today_pct = _pct_change(today_sum, yesterday_sum)

    # -------------------------
    # 2) Total Transactions Today + % เทียบเมื่อวาน
    # -------------------------
    today_tx_count = (
        base.filter(_tz_date_expr() == today)
        .with_entities(func.count(Transaction.id))
        .scalar()
    )
    yesterday_tx_count = (
        base.filter(_tz_date_expr() == yesterday)
        .with_entities(func.count(Transaction.id))
        .scalar()
    )

    today_tx_count = int(today_tx_count or 0)
    yesterday_tx_count = int(yesterday_tx_count or 0)
    tx_pct = _pct_change(today_tx_count, yesterday_tx_count)

    # -------------------------
    # 3) Top Spending Category Today
    #    ใช้ยอดรวม amount ต่อหมวดของวันนี้
    # -------------------------
    top_cat_q = (
        base.filter(_tz_date_expr() == today)
        .with_entities(
            Transaction.category,
            func.coalesce(func.sum(Transaction.amount), 0).label("total")
        )
        .group_by(Transaction.category)
        .order_by(func.coalesce(func.sum(Transaction.amount), 0).desc())
        .first()
    )

    top_category = top_cat_q[0] if top_cat_q and top_cat_q[0] else "Others"
    top_category_value = float(top_cat_q[1] or 0) if top_cat_q else 0.0

    prev_top_cat_q = (
        base.filter(_tz_date_expr() == yesterday)
        .with_entities(
            Transaction.category,
            func.coalesce(func.sum(Transaction.amount), 0).label("total")
        )
        .group_by(Transaction.category)
        .order_by(func.coalesce(func.sum(Transaction.amount), 0).desc())
        .first()
    )
    prev_top_category_value = float(prev_top_cat_q[1] or 0) if prev_top_cat_q else 0.0
    top_cat_pct = _pct_change(top_category_value, prev_top_category_value)

    # -------------------------
    # 4) Expense by Category (today only)
    # -------------------------
    by_category = (
        base.filter(_tz_date_expr() == today)
        .with_entities(
            Transaction.category,
            func.coalesce(func.sum(Transaction.amount), 0).label("total")
        )
        .group_by(Transaction.category)
        .order_by(func.coalesce(func.sum(Transaction.amount), 0).desc())
        .all()
    )

    chart = [
        {
            "category": (c or "Others"),
            "total": float(t or 0)
        }
        for c, t in by_category
    ]

    # -------------------------
    # 5) Recent Transactions (คงเดิม)
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
            "file_url": file_url,
        })

    return {
        "cards": {
            # คง key เดิมเพื่อให้ FE ใช้งานต่อได้ง่าย
            "average_per_day": {
                "value": today_sum,
                "pct": total_today_pct,
            },
            "total_transactions": {
                "value": today_tx_count,
                "pct": tx_pct,
            },
            "top_spending_category": {
                "category": top_category,
                "value": top_category_value,
                "pct": top_cat_pct,
            },
        },
        "expense_by_category": {
            "view": "today",
            "items": chart,
        },
        "recent_transactions": recent_rows,
    }