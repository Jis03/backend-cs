import re
from datetime import datetime

# ----------------------
# Keywords / stopwords
# ----------------------
AMOUNT_KEYWORDS = ["จำนวน", "ยอด", "amount", "Amount", "AMOUNT", "บาท", "THB", "thb"]

RECIPIENT_ANCHORS = ["ไปยัง", "ไปที่", "ถึง", "ผู้รับ", "รับ", "to", "To"]
RECIPIENT_STOPWORDS = [
    "PromptPay", "พร้อมเพย์", "QR", "QR Code", "สแกน", "Scan",
    "หมายเลขอ้างอิง", "เลขที่อ้างอิง", "รหัสอ้างอิง", "ค่าธรรมเนียม",
    "บาท", "THB", "Biller", "Biller ID", "หมายเลขร้านค้า", "เลขทีรายการ", "เลขที่รายการ",
    "จาก", "ไปยัง", "ไปที่", "ถึง"
]

# ----------------------
# Thai months
# ----------------------
THAI_MONTHS = {
    "ม.ค.": 1, "ก.พ.": 2, "มี.ค.": 3, "เม.ย.": 4,
    "พ.ค.": 5, "มิ.ย.": 6, "ก.ค.": 7, "ส.ค.": 8,
    "ก.ย.": 9, "ต.ค.": 10, "พ.ย.": 11, "ธ.ค.": 12,
    # เผื่อ OCR ตัดจุด
    "มค": 1, "กพ": 2, "มีค": 3, "เมย": 4,
    "พค": 5, "มิย": 6, "กค": 7, "สค": 8,
    "กย": 9, "ตค": 10, "พย": 11, "ธค": 12,
    # OCR เพี้ยนที่คุณเคยเจอ (KTB)
    "n.w.": 2, "N.W.": 2, "n.w": 2, "N.W": 2,
}

# ----------------------
# Regex
# ----------------------
RE_MONEY_DECIMAL = re.compile(r"\d{1,3}(?:,\d{3})*\.\d{2}")
RE_MONEY_BAHT = re.compile(r"(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)\s*บาท")
RE_MONEY_THB = re.compile(r"(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)\s*THB", re.IGNORECASE)

RE_TIME = re.compile(r"(\d{1,2}:\d{2})")
RE_DATE_DASH = re.compile(r"(\d{1,2})\s+([^\s]+)\s+(\d{2,4})\s*[-–]\s*(\d{1,2}:\d{2})")     # 25 ม.ค. 2569 - 18:23
RE_DATE_COMMA = re.compile(r"(\d{1,2})\s+([^\s]+)\s*(\d{2,4})\s*,\s*(\d{1,2}:\d{2})")          # 14 ม.ค.69, 11:49
RE_DATE_ONLY = re.compile(r"(\d{1,2})\s*(ม\.ค\.|ก\.พ\.|มี\.ค\.|เม\.ย\.|พ\.ค\.|มิ\.ย\.|ก\.ค\.|ส\.ค\.|ก\.ย\.|ต\.ค\.|พ\.ย\.|ธ\.ค\.)\s*(\d{2,4})")

def _clean_tokens(texts, scores=None, min_score=0.30):
    """
    production-style: ไม่กรองหนักเกินไป
    - เก็บ token ที่มี keyword สำคัญแม้ score ต่ำ
    """
    KEEP_ALWAYS_SUBSTR = ["บาท", "THB", "จาก", "ไปยัง", "ไปที่", "ถึง", "วันที่ทำรายการ", "ค่าธรรมเนียม", "อ้างอิง"]

    out = []
    if scores is None:
        for t in texts:
            t = (t or "").strip()
            if t:
                out.append(t)
        return out

    for t, s in zip(texts, scores):
        t = (t or "").strip()
        if not t:
            continue

        if any(k in t for k in KEEP_ALWAYS_SUBSTR):
            out.append(t)
            continue

        try:
            if float(s) >= min_score:
                out.append(t)
        except Exception:
            out.append(t)
    return out

def _looks_like_account_or_id(t: str) -> bool:
    tt = t.strip()
    if not tt:
        return True
    if re.fullmatch(r"[xX*0-9\-]{6,}", tt):  # masked/บัญชี
        return True
    if re.fullmatch(r"\d{10,}", tt):         # เลขยาว
        return True
    if re.fullmatch(r"[A-Za-z0-9]{18,}", tt):# ref ยาว
        return True
    return False

def _is_noise_token(t: str) -> bool:
    tt = t.strip()
    if not tt:
        return True
    if len(tt) <= 1:
        return True
    if re.fullmatch(r"[A-Za-z]{1,3}", tt):   # เศษ OCR
        return True
    return False

def _extract_amount_prod_style(tokens: list[str]) -> float | None:
    """
    robust แบบ production:
    - หา candidate ทุกแบบ (xxx.xx, xxx บาท, xxx THB)
    - ถ้ามี keyword จะเลือกค่าที่อยู่ใกล้ keyword
    - กันเคสไปหยิบเลขอ้างอิงด้วยการ "ไม่เอาเลขยาวผิดปกติ" (เราหาเฉพาะเงินรูปแบบปกติ)
    """
    if not tokens:
        return None

    keyword_positions = []
    for i, t in enumerate(tokens):
        if any(k.lower() in t.lower() for k in AMOUNT_KEYWORDS):
            keyword_positions.append(i)

    candidates = []  # (idx, value)
    for i, t in enumerate(tokens):
        # money แบบมีทศนิยม
        for m in RE_MONEY_DECIMAL.findall(t):
            v = float(m.replace(",", ""))
            if v > 0:
                candidates.append((i, v))
        # money แบบติดบาท/THB
        for m in RE_MONEY_BAHT.findall(t):
            v = float(m.replace(",", ""))
            if v > 0:
                candidates.append((i, v))
        for m in RE_MONEY_THB.findall(t):
            v = float(m.replace(",", ""))
            if v > 0:
                candidates.append((i, v))

    if not candidates:
        return None

    # ถ้ามี keyword เลือกตัวที่ใกล้สุด
    if keyword_positions:
        best_val, best_dist = None, 10**9
        for kpos in keyword_positions:
            for i, v in candidates:
                d = abs(i - kpos)
                if d < best_dist:
                    best_val, best_dist = v, d
        return best_val

    # ถ้าไม่มี keyword: เลือกค่าที่ “เหมาะจะเป็นยอดโอน” => ส่วนใหญ่เป็นค่ามากสุด (และตัด 0 แล้ว)
    return max(v for _, v in candidates)

def _parse_year_to_ad(year_raw: str) -> int | None:
    y = re.sub(r"[^\d]", "", year_raw)
    if not y:
        return None
    if len(y) == 2:
        # 69 -> 2569 -> 2026
        return (2500 + int(y)) - 543
    yy = int(y)
    if yy >= 2400:
        return yy - 543
    return yy

def _parse_dt_from_tokens(tokens: list[str]) -> str | None:
    """
    รองรับหลายฟอร์แมต:
    - 25 ม.ค. 2569 - 18:23
    - 04 n.w. 2569 - 14:57
    - 14 ม.ค.69, 11:49
    - แยกวัน/เวลา: 3 ก.พ. 69 + 18:46 น. (fallback)
    """
    if not tokens:
        return None

    # 1) dash format
    for t in tokens:
        m = RE_DATE_DASH.search(t)
        if m:
            d, mon_raw, yraw, hhmm = m.group(1), m.group(2), m.group(3), m.group(4)
            if mon_raw in THAI_MONTHS:
                year = _parse_year_to_ad(yraw)
                if year:
                    dt = datetime.strptime(f"{year:04d}-{THAI_MONTHS[mon_raw]:02d}-{int(d):02d} {hhmm}", "%Y-%m-%d %H:%M")
                    return dt.strftime("%Y-%m-%d %H:%M:%S")

    # 2) comma format
    for t in tokens:
        m = RE_DATE_COMMA.search(t)
        if m:
            d, mon_raw, yraw, hhmm = m.group(1), m.group(2), m.group(3), m.group(4)
            if mon_raw in THAI_MONTHS:
                year = _parse_year_to_ad(yraw)
                if year:
                    dt = datetime.strptime(f"{year:04d}-{THAI_MONTHS[mon_raw]:02d}-{int(d):02d} {hhmm}", "%Y-%m-%d %H:%M")
                    return dt.strftime("%Y-%m-%d %H:%M:%S")

    full = " ".join(tokens)

    # 3) date-only + any time in text
    d = RE_DATE_ONLY.search(full)
    t = RE_TIME.search(full)
    if d and t:
        day = int(d.group(1))
        month = THAI_MONTHS.get(d.group(2))
        year = _parse_year_to_ad(d.group(3))
        if month and year:
            hhmm = t.group(1)
            dt = datetime.strptime(f"{year:04d}-{month:02d}-{day:02d} {hhmm}", "%Y-%m-%d %H:%M")
            return dt.strftime("%Y-%m-%d %H:%M:%S")

    # 4) fallback แยก token วัน/เวลา
    date_part = None
    time_part = None
    # หา token ที่เป็นวันไทย
    for tok in tokens:
        m = re.search(r"(\d{1,2})\s+([^\s]+)\s*([\d]{2,4})", tok.strip())
        if m:
            day = int(m.group(1))
            mon = m.group(2).strip().replace("..", ".")
            yr = m.group(3).strip()
            if mon in THAI_MONTHS:
                year = _parse_year_to_ad(yr)
                if year:
                    date_part = (year, THAI_MONTHS[mon], day)
                    break
    # หา token เวลา
    for tok in tokens:
        m = RE_TIME.search(tok)
        if m:
            time_part = m.group(1)
            break

    if date_part and time_part:
        y, mo, d = date_part
        dt = datetime.strptime(f"{y:04d}-{mo:02d}-{d:02d} {time_part}", "%Y-%m-%d %H:%M")
        return dt.strftime("%Y-%m-%d %H:%M:%S")

    return None

def _extract_recipient_prod_style(tokens: list[str]) -> str | None:
    """
    anchor-based แบบ production-ish:
    - ไปยัง / ถึง / ไปที่ / ผู้รับ
    - ข้าม noise
    - เก็บ 1-4 token จนเจอ stopword/เลขบัญชี   
    """
    if not tokens:
        return None

    for i, t in enumerate(tokens):
        if any(a.lower() == t.strip().lower() for a in RECIPIENT_ANCHORS):
            j = i + 1
            while j < len(tokens) and _is_noise_token(tokens[j]):
                j += 1
            if j >= len(tokens):
                continue

            parts = []
            for k in range(j, min(j + 6, len(tokens))):
                tt = tokens[k].strip()
                if _is_noise_token(tt):
                    continue
                if any(sw.lower() in tt.lower() for sw in RECIPIENT_STOPWORDS):
                    break
                if _looks_like_account_or_id(tt):
                    break
                parts.append(tt)

            if parts:
                return " ".join(parts).strip()

    # fallback: เจอคำนำหน้าชื่อไทย
    for t in tokens:
        tt = t.strip()
        if tt.startswith(("น.ส.", "นาย", "นาง", "บริษัท", "บจก", "หจก")) and not _looks_like_account_or_id(tt):
            return tt

    return None

def extract_fields(bank: str, texts, scores):
    """
    ฟังก์ชันเดียวสำหรับเทส:
    - ไม่พึ่ง bank (รับไว้เฉยๆ)
    - คืนคีย์ให้ตรงกับ Excel: Amount / DateTime / Receipient
    """
    tokens = _clean_tokens(texts, scores, min_score=0.30)

    amount = _extract_amount_prod_style(tokens)
    dt = _parse_dt_from_tokens(tokens)
    recipient = _extract_recipient_prod_style(tokens)

    return {"Amount": amount, "DateTime": dt, "Receipient": recipient}