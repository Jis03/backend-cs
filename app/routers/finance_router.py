from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from zoneinfo import ZoneInfo

from app.db import SessionLocal
from app.model import Transaction, Upload, User
from app.deps import get_current_user

router = APIRouter(prefix="/finance", tags=["Finance"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ✅ FE ใช้ key ชุดนี้
CATEGORY_ORDER = ["food-drink", "transport", "shopping", "utilities", "others"]
CATEGORY_KEY_TO_LABEL = {
    "food-drink": "Food&Drink",
    "transport": "Transport",
    "shopping": "Shopping",
    "utilities": "Utilities",
    "others": "Others",
}
CATEGORY_LABEL_TO_KEY = {v: k for k, v in CATEGORY_KEY_TO_LABEL.items()}

def normalize_category_to_key(v: str | None) -> str | None:
    """รับทั้ง key/label แล้วคืนเป็น key"""
    if not v:
        return None
    v = v.strip()
    if v in CATEGORY_KEY_TO_LABEL:
        return v
    if v in CATEGORY_LABEL_TO_KEY:
        return CATEGORY_LABEL_TO_KEY[v]
    # เผื่อเคสแปลก ๆ เช่น others / Others
    low = v.lower()
    if low in ("others", "other"):
        return "others"
    return None

def category_db_values_for_key(key: str) -> list[str]:
    """คืนค่าที่อาจถูกเก็บใน DB สำหรับหมวดนี้ (ทั้ง key และ label)"""
    if key not in CATEGORY_KEY_TO_LABEL:
        return []
    return [key, CATEGORY_KEY_TO_LABEL[key]]

def to_file_path(file_path: str | None):
    if not file_path:
        return None
    norm = file_path.replace("\\", "/").lstrip("/")
    return f"/{norm}"  # => /uploads/...

@router.get("/categories/summary")
def categories_summary(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    สรุปข้อมูลหน้าโฟลเดอร์:
    - รวมข้อมูลทั้ง category ที่เก็บเป็น key และ label เข้าด้วยกัน
    - คืนผลเป็น key เสมอ
    """
    bkk = ZoneInfo("Asia/Bangkok")

    # ดึง aggregate แบบ "raw" ตามค่าจริงใน DB ก่อน (อาจเป็น key หรือ label)
    raw_rows = (
        db.query(
            Transaction.category.label("raw_category"),
            func.count(Transaction.id).label("tx_count"),
            func.coalesce(func.sum(Transaction.amount), 0).label("total_amount"),
            func.max(Transaction.transferred_at).label("latest_at"),
        )
        .join(Upload, Transaction.upload_id == Upload.id)
        .filter(Upload.user_id == user.id)
        .group_by(Transaction.category)
        .all()
    )

    # รวมผลให้เป็น key เดียวกัน
    merged = {k: {"tx_count": 0, "total_amount": 0.0, "latest_at": None} for k in CATEGORY_ORDER}

    for r in raw_rows:
        key = normalize_category_to_key(r.raw_category)
        if not key or key not in merged:
            continue

        merged[key]["tx_count"] += int(r.tx_count)
        merged[key]["total_amount"] += float(r.total_amount) if r.total_amount is not None else 0.0

        # latest_at เอา max ระหว่างที่มี
        if r.latest_at:
            cur = merged[key]["latest_at"]
            merged[key]["latest_at"] = r.latest_at if (cur is None or r.latest_at > cur) else cur

    # cover: รูปล่าสุดของหมวด (ต้อง filter ทั้ง key+label)
    result = []
    for key in CATEGORY_ORDER:
        db_vals = category_db_values_for_key(key)

        cover = (
            db.query(Upload.file_path)
            .join(Transaction, Transaction.upload_id == Upload.id)
            .filter(Upload.user_id == user.id)
            .filter(Transaction.category.in_(db_vals))
            .order_by(desc(Transaction.transferred_at).nullslast(), desc(Transaction.created_at))
            .first()
        )

        latest_at = merged[key]["latest_at"]
        latest_at_iso = None
        if latest_at:
            dt = latest_at
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=bkk)
            else:
                dt = dt.astimezone(bkk)
            latest_at_iso = dt.isoformat()

        result.append(
            {
                "key": key,
                "label": CATEGORY_KEY_TO_LABEL[key],
                "tx_count": merged[key]["tx_count"],
                "total_amount": float(merged[key]["total_amount"]),
                "latest_at": latest_at_iso,
                "cover_path": to_file_path(cover[0]) if cover else None,
            }
        )

    return result


@router.get("/categories/{key}/transactions")
def list_transactions_by_category(
    key: str,
    page: int = 1,
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if key not in CATEGORY_KEY_TO_LABEL:
        raise HTTPException(status_code=400, detail="invalid category key")

    db_vals = category_db_values_for_key(key)

    q = (
        db.query(Transaction, Upload)
        .join(Upload, Transaction.upload_id == Upload.id)
        .filter(Upload.user_id == user.id)
        .filter(Transaction.category.in_(db_vals))  # ✅ รองรับทั้ง key และ label
        .order_by(desc(Transaction.transferred_at).nullslast(), desc(Transaction.created_at))
    )

    total = q.count()
    items = q.offset((page - 1) * page_size).limit(page_size).all()

    bkk = ZoneInfo("Asia/Bangkok")
    rows = []

    for tx, up in items:
        dt = tx.transferred_at
        if dt and dt.tzinfo is None:
            dt = dt.replace(tzinfo=bkk)

        rows.append(
            {
                "id": str(tx.id),
                "bank": tx.bank,
                "amount": float(tx.amount) if tx.amount is not None else 0.0,
                "memo": tx.memo,
                "category_key": key,  # ✅ คืนเป็น key ให้ FE ใช้
                "category_raw": tx.category,  # ✅ debug: ค่าเดิมใน DB
                "category_source": tx.category_source,
                "transferred_at": dt.astimezone(bkk).isoformat() if dt else None,
                "file_path": to_file_path(up.file_path),
            }
        )

    return {"rows": rows, "total": total, "page": page, "page_size": page_size}