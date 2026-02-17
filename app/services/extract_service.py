import re
from datetime import datetime
from zoneinfo import ZoneInfo 

THAI_MONTHS = {
    "ม.ค.": 1, "ก.พ.": 2, "มี.ค.": 3, "เม.ย.": 4,
    "พ.ค.": 5, "มิ.ย.": 6, "ก.ค.": 7, "ส.ค.": 8,
    "ก.ย.": 9, "ต.ค.": 10, "พ.ย.": 11, "ธ.ค.": 12
}

BANK_PATTERNS = [
    (r"(กรุงไทย|Krungthai|KTB)", "ธนาคารกรุงไทย"),
    (r"(กสิกร|K\s?PLUS|KBank)", "ธนาคารกสิกรไทย"),
    (r"(ไทยพาณิชย์|SCB)", "ธนาคารไทยพาณิชย์"),
    (r"(กรุงเทพ|BBL|Bangkok\s?Bank)", "ธนาคารกรุงเทพ"),
    (r"(กรุงศรี|BAY)", "ธนาคารกรุงศรีอยุธยา"),
    (r"(ออมสิน|GSB|by\s?GSB|CILBMIMGEMMMIMCSLUBLE)", "ธนาคารออมสิน"), 
    (r"(ทีทีบี|ttb|TMB|ธนชาต)", "ธนาคารทหารไทยธนชาต"),
    (r"(Dime!|ไดม์)", "Dime"),
    (r"(TrueMoney|ทรูมันนี่|True\s?Wallet)", "TrueMoney Wallet"),
]

AMOUNT_KEYWORDS = ["จำนวน", "ยอด", "amount", "Amount", "AMOUNT"]

MEMO_KEYWORDS = ["บันทึกความจำ", "หมายเหตุ", "memo", "note" , "บันทึกช่วยจำ","LCBCฉuunn","LCBcauunn","บันทึก"]

CATEGORY_KEYWORDS = {
    "Food&Drink": ["อาหาร", "ข้าว", "กาแฟ", "ชา", "น้ำ", "ร้านอาหาร", "คาเฟ่"],
    "Transport": ["เดินทาง", "รถ", "แท็กซี่", "bts", "mrt", "grab", "น้ำมัน"],
    "Shopping": ["ของใช้", "จิปาถะ", "เซเว่น", "7-11", "ซื้อของ", "lotus", "big c"],
    "Utilities": ["ที่พัก", "โรงแรม", "ค่าเช่า", "ค่าน้ำ", "ค่าไฟ", "อินเทอร์เน็ต"],
}

ALLOWED_CATEGORIES = set(CATEGORY_KEYWORDS.keys()) | {"Others"}


BANGKOK_TZ = ZoneInfo("Asia/Bangkok")

def _combine_transferred_at(date_str: str | None, time_str: str | None):
    """
    รวม date + time เป็น datetime (tz-aware) สำหรับเก็บลง transferred_at
    - ถ้าไม่มี date หรือ time -> None (ไม่ทำให้ของเดิมพัง)
    """
    if not date_str or not time_str:
        return None
    try:
        dt = datetime.fromisoformat(f"{date_str} {time_str}:00")
        return dt.replace(tzinfo=BANGKOK_TZ)
    except ValueError:
        return None


def _match_bank(text: str):
    for pat, bank_name in BANK_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            return bank_name
    return None


def _extract_amount(texts: list[str]) -> float | None:
    keyword_positions = []
    for i, t in enumerate(texts):
        if any(k in t for k in AMOUNT_KEYWORDS):
            keyword_positions.append(i)

    money_candidates = []
    for i, t in enumerate(texts):
        for m in re.findall(r"\d{1,3}(?:,\d{3})*\.\d{2}", t):
            v = float(m.replace(",", ""))
            if v > 0:
                money_candidates.append((i, v))

    if not money_candidates:
        return None

    if keyword_positions:
        best, dist = None, 10**9
        for k in keyword_positions:
            for i, v in money_candidates:
                d = abs(i - k)
                if d < dist:
                    best, dist = v, d
        return best

    return max(v for _, v in money_candidates)


def _extract_memo(texts: list[str]) -> str | None:
    for i, t in enumerate(texts):
        for kw in MEMO_KEYWORDS:
            if kw in t:
                m = re.search(rf"{kw}\s*[:：\-]?\s*(.+)$", t, re.IGNORECASE)
                if m and m.group(1).strip():
                    return m.group(1).strip()

                if i + 1 < len(texts):
                    nxt = texts[i + 1].strip()
                    if nxt:
                        return nxt
    return None


def _classify_category_from_memo(memo: str) -> str | None:
    if not memo:
        return None

    text = memo.lower()
    best_cat, best_score = None, 0

    for cat, kws in CATEGORY_KEYWORDS.items():
        score = sum(1 for kw in kws if kw in text)
        if score > best_score:
            best_cat, best_score = cat, score

    return best_cat if best_cat else None


def extract_fields(texts: list[str]):
    # ---------- BANK ----------
    sender_bank = None
    from_idx = None

    for i, t in enumerate(texts):
        if t.strip().lower() in ["จาก", "from"]:
            from_idx = i
            break

    if from_idx is not None:
        for t in texts[from_idx: from_idx + 12]:
            b = _match_bank(t)
            if b:
                sender_bank = b
                break

    if not sender_bank:
        for t in texts[:8]:
            b = _match_bank(t)
            if b:
                sender_bank = b
                break

    # ---------- AMOUNT ----------
    amount = _extract_amount(texts)

    # ---------- TIME ----------
    full = " ".join(texts)
    tm = re.search(r"(\d{1,2}:\d{2})", full)
    time = tm.group(1) if tm else None

    # ---------- DATE ----------
    date = None
    d = re.search(
        r"(\d{1,2})\s*(ม\.ค\.|ก\.พ\.|มี\.ค\.|เม\.ย\.|พ\.ค\.|มิ\.ย\.|ก\.ค\.|ส\.ค\.|ก\.ย\.|ต\.ค\.|พ\.ย\.|ธ\.ค\.)\s*(\d{2,4})",
        full
    )
    if d:
        day = int(d.group(1))
        month = THAI_MONTHS[d.group(2)]
        year = int(d.group(3))
        if year < 100:
            year += 2500
        if year > 2400:
            year -= 543
        date = datetime(year, month, day).strftime("%Y-%m-%d")

    
    transferred_at = _combine_transferred_at(date, time)

    
    memo = _extract_memo(texts)
    suggested_category = _classify_category_from_memo(memo) if memo else None
    category_required = suggested_category is None

    return {
        "bank": sender_bank,
        "amount": amount,
        "time": time,
        "date": date,
        "memo": memo,
        "transferred_at": transferred_at,
        "suggested_category": suggested_category,
        "category_required": category_required,
    }
