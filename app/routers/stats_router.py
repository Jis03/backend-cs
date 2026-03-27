from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, extract, distinct
from datetime import datetime, date
from zoneinfo import ZoneInfo
from calendar import monthrange

from app.db import SessionLocal
from app.model import Transaction, Upload, User, Goal
from app.deps import get_current_user

router = APIRouter(prefix="/stats", tags=["Statistics"])

BKK = ZoneInfo("Asia/Bangkok")


# -------------------------
# DB
# -------------------------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# -------------------------
# Helpers
# -------------------------
def _month_range(y: int, m: int):
    start = date(y, m, 1)
    if m == 12:
        end = date(y + 1, 1, 1)
    else:
        end = date(y, m + 1, 1)
    return start, end


def _days_in_month(y: int, m: int) -> int:
    return monthrange(y, m)[1]


def _five_day_labels(days_in_month: int):
    labels = []
    start = 1
    while start <= days_in_month:
        end = min(start + 4, days_in_month)
        labels.append({
            "label": f"{start}-{end}",
            "start": start,
            "end": end,
        })
        start += 5
    return labels


def _base_query(db: Session, user_id: int):
    return (
        db.query(Transaction)
        .join(Upload, Transaction.upload_id == Upload.id)
        .filter(Upload.user_id == user_id)
    )


def _apply_range(q, period: str, year: int | None, month: int | None):
    if period == "all":
        return q, None, None

    if period == "year":
        if year is None:
            raise HTTPException(status_code=400, detail="year is required for range=year")
        q = q.filter(extract("year", Transaction.transferred_at) == year)
        return q, year, None

    if period == "month":
        if year is None or month is None:
            raise HTTPException(status_code=400, detail="year and month are required for range=month")

        if month < 1 or month > 12:
            raise HTTPException(status_code=400, detail="month must be between 1 and 12")

        start, end = _month_range(year, month)
        start_dt = datetime.combine(start, datetime.min.time(), tzinfo=BKK)
        end_dt = datetime.combine(end, datetime.min.time(), tzinfo=BKK)

        q = q.filter(
            Transaction.transferred_at >= start_dt,
            Transaction.transferred_at < end_dt,
        )
        return q, year, month

    raise HTTPException(status_code=400, detail="invalid range")


CATEGORY_ORDER = ["Food&Drink", "Transport", "Shopping", "Utilities", "Others"]
CATEGORY_KEY_TO_LABEL = {
    "food-drink": "Food&Drink",
    "transport": "Transport",
    "shopping": "Shopping",
    "utilities": "Utilities",
    "others": "Others",
}
LABEL_SET = set(CATEGORY_ORDER)
KEY_SET = set(CATEGORY_KEY_TO_LABEL.keys())

BANK_ORDER = ["KBank", "SCB", "BBL", "Krungsri", "TTB", "KTB", "GSB", "TrueMoney"]


def normalize_category(v: str | None) -> str:
    if not v:
        return "Others"

    s = v.strip()
    if s in LABEL_SET:
        return s

    low = s.lower()
    if low in KEY_SET:
        return CATEGORY_KEY_TO_LABEL[low]
    if low == "others":
        return "Others"

    return "Others"


def normalize_bank(v: str | None) -> str:
    if not v:
        return "-"

    s = v.strip()
    low = s.lower()

    # KBank
    if "kbank" in low or "kasikorn" in low or "กสิกร" in s:
        return "KBank"

    # SCB
    if "scb" in low or "siam commercial" in low or "ไทยพาณิชย์" in s:
        return "SCB"

    # BBL
    if "bbl" in low or "bangkok bank" in low or "กรุงเทพ" in s:
        return "BBL"

    # Krungsri
    if "krungsri" in low or "bay" in low or "กรุงศรี" in s:
        return "Krungsri"

    # TTB
    if (
        "ttb" in low
        or "tmb" in low
        or "thanachart" in low
        or "ธนชาต" in s
        or "ทหารไทยธนชาต" in s
    ):
        return "TTB"

    # KTB
    if (
        "ktb" in low
        or "krungthai" in low
        or "krung thai" in low
        or "กรุงไทย" in s
    ):
        return "KTB"

    # GSB
    if "gsb" in low or "government savings" in low or "ออมสิน" in s:
        return "GSB"

    # TrueMoney
    if (
        "truemoney" in low
        or "true money" in low
        or "true wallet" in low
        or "truemoney wallet" in low
        or "ทรูมันนี่" in s
        or "ทรูวอลเล็ท" in s
        or "วอลเล็ท" in s
    ):
        return "TrueMoney"

    return s


def _get_month_goal(db: Session, user_id: int, year: int, month: int) -> float | None:
    target = f"{year}-{month:02d}"

    g = (
        db.query(Goal)
        .filter(Goal.user_id == user_id)
        .filter(Goal.month == target)
        .order_by(Goal.created_at.desc())
        .first()
    )

    if not g:
        return None

    try:
        return float(g.amount or 0)
    except Exception:
        return None


def _tz_expr():
    return func.timezone("Asia/Bangkok", Transaction.transferred_at)


def _timeline_config(period: str, year: int | None = None, month: int | None = None):
    if period == "all":
        return {
            "unit": "year",
            "extract_expr": extract("year", _tz_expr()),
            "labels": None,
        }

    if period == "year":
        return {
            "unit": "month",
            "extract_expr": extract("month", _tz_expr()),
            "labels": list(range(1, 13)),
        }

    if period == "month":
        days = _days_in_month(year, month)
        return {
            "unit": "day",
            "extract_expr": extract("day", _tz_expr()),
            "labels": list(range(1, days + 1)),
        }

    raise HTTPException(status_code=400, detail="invalid range")


@router.get("/")
def stats(
    period: str = Query("all", alias="range", pattern="^(all|month|year)$"),
    year: int | None = None,
    month: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q, y, m = _apply_range(_base_query(db, user.id), period, year, month)

    q_valid = q.filter(
        Transaction.transferred_at.isnot(None),
        Transaction.amount.isnot(None),
    )

    # -------------------------
    # Cards
    # -------------------------
    total_expenses = float(
        q_valid.with_entities(func.coalesce(func.sum(Transaction.amount), 0)).scalar() or 0
    )

    total_transactions = int(
        q.with_entities(func.count(distinct(Upload.id))).scalar() or 0
    )

    top_category_row = (
        q_valid.with_entities(
            Transaction.category,
            func.coalesce(func.sum(Transaction.amount), 0).label("total"),
        )
        .group_by(Transaction.category)
        .order_by(func.coalesce(func.sum(Transaction.amount), 0).desc())
        .first()
    )
    top_category = normalize_category(top_category_row[0]) if top_category_row else "Others"

    # รวมยอด top bank หลัง normalize
    raw_top_bank_rows = (
        q_valid.with_entities(
            Transaction.bank,
            func.coalesce(func.sum(Transaction.amount), 0).label("total"),
        )
        .group_by(Transaction.bank)
        .all()
    )

    normalized_bank_totals = {}
    for bank, total in raw_top_bank_rows:
        b = normalize_bank(bank)
        normalized_bank_totals[b] = normalized_bank_totals.get(b, 0.0) + float(total or 0)

    if normalized_bank_totals:
        top_bank = max(normalized_bank_totals.items(), key=lambda x: x[1])[0]
    else:
        top_bank = "-"

    # -------------------------
    # 1) Expenses Over Time
    # all   -> year
    # year  -> month
    # month -> 5-day range cumulative
    # -------------------------
    tl = _timeline_config(period, y, m)

    month_goal = None
    per_bucket_goal = None

    if period == "month" and y and m:
        days = _days_in_month(y, m)

        rows = (
            q_valid.with_entities(
                extract("day", _tz_expr()).label("day"),
                func.coalesce(func.sum(Transaction.amount), 0).label("total"),
            )
            .group_by("day")
            .order_by("day")
            .all()
        )

        day_map = {int(day): float(total) for day, total in rows if day is not None}
        bucket_defs = _five_day_labels(days)

        expenses_over_time = []
        running_total = 0.0

        for item in bucket_defs:
            bucket_total = sum(
                day_map.get(d, 0.0)
                for d in range(item["start"], item["end"] + 1)
            )
            running_total += bucket_total

            expenses_over_time.append({
                "x": item["label"],
                "total": float(running_total),
            })

        month_goal = _get_month_goal(db, user.id, y, m)
        if month_goal is not None and month_goal > 0:
            per_bucket_goal = float(month_goal)
        else:
            per_bucket_goal = None

    else:
        rows = (
            q_valid.with_entities(
                tl["extract_expr"].label("k"),
                func.coalesce(func.sum(Transaction.amount), 0).label("total"),
            )
            .group_by("k")
            .order_by("k")
            .all()
        )

        raw_map = {int(k): float(total) for k, total in rows if k is not None}

        if tl["labels"] is None:
            expenses_over_time = [
                {"x": int(k), "total": float(v)}
                for k, v in sorted(raw_map.items(), key=lambda item: item[0])
            ]
        else:
            expenses_over_time = [
                {"x": label, "total": float(raw_map.get(label, 0.0))}
                for label in tl["labels"]
            ]

    # -------------------------
    # 2) Category by Bank (Stacked)
    # -------------------------
    raw_cat_bank = (
        q_valid.with_entities(
            Transaction.category.label("cat"),
            Transaction.bank.label("bank"),
            func.coalesce(func.sum(Transaction.amount), 0).label("total"),
        )
        .group_by(Transaction.category, Transaction.bank)
        .all()
    )

    bank_totals = {}
    for cat, bank, total in raw_cat_bank:
        b = normalize_bank(bank)
        bank_totals[b] = bank_totals.get(b, 0.0) + float(total or 0)

    # ใช้ลำดับธนาคารคงที่ เพื่อไม่ให้ KTB / TrueMoney หายเพราะไม่ติด top 5
    top_banks = [b for b in BANK_ORDER if b in bank_totals and bank_totals[b] > 0]

    # ถ้ามีชื่อธนาคารอื่นนอก BANK_ORDER ให้ต่อท้าย
    other_banks = [
        b for b, total in sorted(bank_totals.items(), key=lambda x: x[1], reverse=True)
        if b not in top_banks and total > 0
    ]
    top_banks.extend(other_banks)

    cat_bank_map = {
        c: {b: 0.0 for b in top_banks}
        for c in CATEGORY_ORDER
    }

    for cat, bank, total in raw_cat_bank:
        c = normalize_category(cat)
        b = normalize_bank(bank)

        if c in cat_bank_map and b in cat_bank_map[c]:
            cat_bank_map[c][b] += float(total or 0)

    category_by_bank = []
    for c in CATEGORY_ORDER:
        row = {"category": c}
        for b in top_banks:
            row[b] = float(cat_bank_map[c][b])
        category_by_bank.append(row)

    # -------------------------
    # 3) Spending Spread (Box Plot)
    # -------------------------
    box_rows = (
        q_valid.with_entities(
            Transaction.category.label("cat"),
            func.min(Transaction.amount).label("minv"),
            func.percentile_cont(0.25).within_group(Transaction.amount).label("q1"),
            func.percentile_cont(0.50).within_group(Transaction.amount).label("median"),
            func.percentile_cont(0.75).within_group(Transaction.amount).label("q3"),
            func.max(Transaction.amount).label("maxv"),
        )
        .group_by(Transaction.category)
        .all()
    )

    tmp_box = {
        normalize_category(cat): {
            "min": float(minv or 0),
            "q1": float(q1 or 0),
            "median": float(med or 0),
            "q3": float(q3 or 0),
            "max": float(maxv or 0),
        }
        for cat, minv, q1, med, q3, maxv in box_rows
    }

    spending_spread = []
    for c in CATEGORY_ORDER:
        v = tmp_box.get(c)
        if not v:
            spending_spread.append({
                "category": c,
                "min": 0,
                "q1": 0,
                "median": 0,
                "q3": 0,
                "max": 0,
            })
        else:
            spending_spread.append({"category": c, **v})

    # -------------------------
    # 4) Bank Heatmap
    # all   -> bank x year
    # year  -> bank x month
    # month -> bank x 5-day range
    # -------------------------
    if period == "month" and y and m:
        days = _days_in_month(y, m)
        bucket_defs = _five_day_labels(days)
        heat_buckets = [b["label"] for b in bucket_defs]

        raw_heat = (
            q_valid.with_entities(
                Transaction.bank.label("bank"),
                extract("day", _tz_expr()).label("day"),
                func.coalesce(func.sum(Transaction.amount), 0).label("total"),
            )
            .group_by(Transaction.bank, "day")
            .all()
        )

        banks = top_banks[:]
        if not banks:
            fallback_bank_totals = {}
            for bank, day, total in raw_heat:
                b = normalize_bank(bank)
                fallback_bank_totals[b] = fallback_bank_totals.get(b, 0.0) + float(total or 0)

            banks = [b for b in BANK_ORDER if fallback_bank_totals.get(b, 0) > 0]
            other_banks = [
                b for b, total in sorted(fallback_bank_totals.items(), key=lambda x: x[1], reverse=True)
                if b not in banks and total > 0
            ]
            banks.extend(other_banks)

        bank_index = {b: i for i, b in enumerate(banks)}
        matrix = [[0.0 for _ in heat_buckets] for _ in banks]

        for bank, day, total in raw_heat:
            if day is None:
                continue

            b = normalize_bank(bank)
            if b not in bank_index:
                continue

            day_num = int(day)
            for j, bucket in enumerate(bucket_defs):
                if bucket["start"] <= day_num <= bucket["end"]:
                    matrix[bank_index[b]][j] += float(total or 0)
                    break

        bank_heatmap = {
            "banks": banks,
            "labels": heat_buckets,
            "unit": "range",
            "matrix": matrix,
            "metric": "amount",
        }

    else:
        heat_rows = (
            q_valid.with_entities(
                Transaction.bank.label("bank"),
                tl["extract_expr"].label("bucket"),
                func.coalesce(func.sum(Transaction.amount), 0).label("total"),
            )
            .group_by(Transaction.bank, "bucket")
            .all()
        )

        banks = top_banks[:]
        if not banks:
            fallback_bank_totals = {}
            for bank, bucket, total in heat_rows:
                b = normalize_bank(bank)
                fallback_bank_totals[b] = fallback_bank_totals.get(b, 0.0) + float(total or 0)

            banks = [b for b in BANK_ORDER if fallback_bank_totals.get(b, 0) > 0]
            other_banks = [
                b for b, total in sorted(fallback_bank_totals.items(), key=lambda x: x[1], reverse=True)
                if b not in banks and total > 0
            ]
            banks.extend(other_banks)

        if tl["labels"] is None:
            heat_buckets = sorted({int(bucket) for _, bucket, _ in heat_rows if bucket is not None})
        else:
            heat_buckets = tl["labels"]

        bank_index = {b: i for i, b in enumerate(banks)}
        bucket_index = {bucket: i for i, bucket in enumerate(heat_buckets)}

        matrix = [[0.0 for _ in heat_buckets] for _ in banks]

        for bank, bucket, total in heat_rows:
            if bucket is None:
                continue

            b = normalize_bank(bank)
            k = int(bucket)

            if b not in bank_index or k not in bucket_index:
                continue

            matrix[bank_index[b]][bucket_index[k]] += float(total or 0)

        bank_heatmap = {
            "banks": banks,
            "labels": heat_buckets,
            "unit": tl["unit"],
            "matrix": matrix,
            "metric": "amount",
        }

    # -------------------------
    # Return
    # -------------------------
    return {
        "filter": {
            "range": period,
            "year": year,
            "month": month,
        },
        "cards": {
            "total_expenses": total_expenses,
            "top_category": top_category,
            "top_bank": top_bank,
            "total_transactions": total_transactions,
        },
        "expenses_over_time": {
            "unit": tl["unit"] if period != "month" else "range",
            "items": expenses_over_time,
        },
        "goal": {
            "month_goal": month_goal if period == "month" else None,
            "per_day_goal": per_bucket_goal if period == "month" else None,
        },
        "average_line": per_bucket_goal if period == "month" else None,
        "category_by_bank": {
            "banks": top_banks,
            "items": category_by_bank,
        },
        "spending_spread": spending_spread,
        "bank_heatmap": bank_heatmap,
    }