from fastapi import APIRouter, UploadFile, File, Depends, Form, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime
from zoneinfo import ZoneInfo

from app.db import SessionLocal
from app.services.storage_service import prepare_upload_file, save_file_content
from app.services.ocr_service import run_ocr
from app.services.extract_service import extract_fields
from app.model import Upload, Transaction
from app.deps import get_current_user
from app.model import User

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
    force_upload: bool = Form(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        content, file_hash, ext = prepare_upload_file(file)
    except ValueError:
        raise HTTPException(status_code=400, detail="empty file")

    existing_upload = (
        db.query(Upload)
        .filter(
            Upload.user_id == current_user.id,
            Upload.file_hash == file_hash,
        )
        .first()
    )

    if existing_upload and not force_upload:
        existing_tx = (
            db.query(Transaction)
            .filter(Transaction.upload_id == existing_upload.id)
            .first()
        )

        return {
            "duplicate": True,
            "message": "This slip appears to have already been uploaded.",
            "existing_upload_id": existing_upload.id,
            "existing_transaction_id": existing_tx.id if existing_tx else None,
            "existing_filename": existing_upload.original_filename,
            "existing_file_path": existing_upload.file_path,
        }

    path = save_file_content(content, ext)

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
        file_hash=file_hash,
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
        raw_ocr={"texts": texts, "scores": scores},
    )

    db.add(tx)
    db.commit()
    db.refresh(tx)

    row = db.execute(text("""
        select inet_server_addr(), inet_server_port(), current_database(), current_user
    """)).fetchone()

    print("API CONNECTED TO:", row)
    print("TX ID AFTER COMMIT:", tx.id)

    return {
        "duplicate": False,
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