import sys
import os
import pandas as pd
from pathlib import Path

# เพิ่ม root project (BACKEND-CS) เข้า path
sys.path.append(os.path.abspath(".."))

from app.services.ocr_service import run_ocr
from parsers import extract_fields

BASE_DIR = Path(__file__).resolve().parent   # .../tools
PROJECT_ROOT = BASE_DIR.parent              # .../backend-cs

SLIP_ROOT = str(BASE_DIR / "slip")                 # tools/slip
INPUT_EXCEL = str(PROJECT_ROOT / "slip_OCR.xlsx")  # backend-cs/slip_OCR.xlsx
OUTPUT_EXCEL = str(PROJECT_ROOT / "slip_OCR_filled.xlsx")

IMG_EXTS = (".png", ".jpg", ".jpeg", ".webp")


def find_image_path_strict(slips_root: str, bank_folder: str, filename: str) -> str | None:
    bank_folder = (bank_folder or "").strip()
    filename = (filename or "").strip()
    if not bank_folder or not filename:
        return None

    p = os.path.join(slips_root, bank_folder, filename)
    if os.path.exists(p):
        return p

    root, ext = os.path.splitext(filename)
    if not ext:
        for e in IMG_EXTS:
            p2 = os.path.join(slips_root, bank_folder, filename + e)
            if os.path.exists(p2):
                return p2
    return None


def ensure_columns(df: pd.DataFrame) -> pd.DataFrame:
    # คอลัมน์ผลลัพธ์ที่เราจะเขียน
    out_cols = ["Amount", "DateTime", "Receipient", "Status", "Error", "ImagePath"]
    for c in out_cols:
        if c not in df.columns:
            df[c] = None
        # กัน warning dtype
        df[c] = df[c].astype("object")
    return df


def process_excel(sheet_name=0):
    print("START PROCESS")
    print("INPUT_EXCEL:", INPUT_EXCEL)
    print("SLIP_ROOT:", SLIP_ROOT)
    print("OUTPUT_EXCEL:", OUTPUT_EXCEL)

    if not os.path.exists(INPUT_EXCEL):
        raise FileNotFoundError(f"Excel not found: {INPUT_EXCEL}")

    # อ่าน excel พร้อมระบุ sheet
    df = pd.read_excel(INPUT_EXCEL, sheet_name=sheet_name)
    print("ROWS (read):", len(df))
    print("COLUMNS:", list(df.columns))

    # ตรวจคอลัมน์ที่จำเป็น
    required = ["Bank", "New File Name"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns in Excel: {missing}")

    df = ensure_columns(df)

    total = len(df)
    ok = miss = err = 0

    for idx, row in df.iterrows():
        bank = str(row.get("Bank", "")).strip()
        fname = str(row.get("New File Name", "")).strip()

        if not bank or not fname or fname.lower() == "nan":
            df.at[idx, "Status"] = "INVALID_ROW"
            df.at[idx, "Error"] = "Missing Bank/New File Name"
            miss += 1
            continue

        img_path = find_image_path_strict(SLIP_ROOT, bank, fname)
        df.at[idx, "ImagePath"] = img_path

        if not img_path:
            df.at[idx, "Status"] = "MISS_FILE"
            df.at[idx, "Error"] = f"file not found: {bank}/{fname}"
            miss += 1
            # ไม่ continue แบบหาย ๆ — แถวจะยังอยู่ครบ
            continue

        try:
            texts, scores = run_ocr(img_path)
            fields = extract_fields(bank, texts, scores)

            df.at[idx, "Amount"] = fields.get("Amount")
            df.at[idx, "DateTime"] = fields.get("DateTime")
            df.at[idx, "Receipient"] = fields.get("Receipient")

            df.at[idx, "Status"] = "OK"
            df.at[idx, "Error"] = None
            ok += 1

            print(f"[OK] row {idx} {bank} -> {fields}")

        except Exception as e:
            df.at[idx, "Status"] = "ERROR"
            df.at[idx, "Error"] = repr(e)
            err += 1
            print(f"[ERROR] row {idx} {bank}/{fname}: {e}")

    print(f"SUMMARY: total={total} ok={ok} miss={miss} err={err}")
    df.to_excel(OUTPUT_EXCEL, index=False)
    print("DONE ->", OUTPUT_EXCEL)

    # ✅ ตรวจซ้ำว่าไฟล์ output มีครบจริงไหม
    df_check = pd.read_excel(OUTPUT_EXCEL)
    print("ROWS (saved):", len(df_check))


if __name__ == "__main__":
    process_excel(sheet_name=0)  # ถ้าไฟล์มีหลายชีท เปลี่ยนเป็นชื่อชีทได้ เช่น "Sheet1"