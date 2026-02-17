from fastapi import APIRouter, UploadFile, File, Depends
from sqlalchemy.orm import Session
from app.db import SessionLocal
from app.services.storage_service import save_upload_file
from app.services.ocr_service import run_ocr
from app.services.extract_service import extract_fields
from app.model import Upload, Transaction

from app.deps import get_current_user
from app.model import User

from datetime import datetime
from zoneinfo import ZoneInfo

router = APIRouter(prefix="/upload", tags=["Upload"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def parse_transferred_at(data: dict):
    bkk = ZoneInfo("Asia/Bangkok")

    v = data.get("transferred_at")

    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=bkk)

    if isinstance(v, str) and v.strip():
        s = v.strip()
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=bkk)
        except ValueError:
            pass

    date = (data.get("date") or "").strip()
    time = (data.get("time") or "").strip() or "00:00"

    if not date:
        return None

    try:
        if "-" in date:
            dt = datetime.fromisoformat(f"{date} {time}:00")
        else:
            dt = datetime.strptime(f"{date} {time}", "%d/%m/%y %H:%M")
        return dt.replace(tzinfo=bkk)
    except ValueError:
        return None

@router.post("/")
async def upload_image(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    saved = save_upload_file(file)

    if isinstance(saved, tuple):
        path, file_hash = saved
    else:
        path, file_hash = saved, None

    texts, scores = run_ocr(path)
    data = extract_fields(texts)

    memo = data.get("memo")
    suggested_category = data.get("suggested_category")
    category_required = bool(data.get("category_required"))
    category_source = "ocr_guess" if suggested_category else None

    upload = Upload(
        user_id=current_user.id,
        file_path=path,
        original_filename=file.filename,
    )

    db.add(upload)
    db.commit()
    db.refresh(upload)

    tx = Transaction(
        upload_id=upload.id,
        bank=data.get("bank"),
        amount=data.get("amount"),
        transferred_at=parse_transferred_at(data),  

        memo=memo,
        category=suggested_category,
        category_source=category_source,

        raw_ocr={"texts": texts, "scores": scores}
    )

    db.add(tx)
    db.commit()
    db.refresh(tx)

    return {
        "transaction_id": str(tx.id),
        "file_path": path,
        "ocr_texts": texts,
        "extracted": data,

        "file_url": f"/{path.lstrip('/')}",

        "memo": memo,
        "suggested_category": suggested_category,
        "category_required": category_required,

        
        "transferred_at": tx.transferred_at.isoformat() if tx.transferred_at else None,
    }
