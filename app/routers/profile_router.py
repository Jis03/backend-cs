from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from app.db import SessionLocal
from app.model import User, UserProfile
from app.deps import get_current_user
import os
import shutil
from uuid import uuid4

router = APIRouter(prefix="/profile", tags=["Profile"])

UPLOAD_DIR = "uploads/profile_images"
os.makedirs(UPLOAD_DIR, exist_ok=True)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/")
def get_my_profile(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    profile = db.query(UserProfile).filter(UserProfile.user_id == current_user.id).first()

    if not profile:
        profile = UserProfile(
            user_id=current_user.id,
            display_name=current_user.username,
        )
        db.add(profile)
        db.commit()
        db.refresh(profile)

    return {
        "user_id": current_user.id,
        "username": current_user.username,
        "email": current_user.email,
        "display_name": profile.display_name or current_user.username,
        "first_name": profile.first_name,
        "last_name": profile.last_name,
        "phone": profile.phone,
        "profile_image_url": profile.profile_image_url,
    }


@router.put("/")
def update_my_profile(
    payload: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    profile = db.query(UserProfile).filter(UserProfile.user_id == current_user.id).first()

    if not profile:
        profile = UserProfile(user_id=current_user.id)
        db.add(profile)

    profile.display_name = payload.get("display_name")
    profile.first_name = payload.get("first_name")
    profile.last_name = payload.get("last_name")
    profile.phone = payload.get("phone")

    db.commit()
    db.refresh(profile)

    return {
        "message": "Profile updated successfully",
        "profile": {
            "display_name": profile.display_name,
            "first_name": profile.first_name,
            "last_name": profile.last_name,
            "phone": profile.phone,
            "profile_image_url": profile.profile_image_url,
        },
    }


@router.post("/image")
def upload_profile_image(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    profile = db.query(UserProfile).filter(UserProfile.user_id == current_user.id).first()

    if not profile:
        profile = UserProfile(
            user_id=current_user.id,
            display_name=current_user.username,
        )
        db.add(profile)
        db.flush()

    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in [".jpg", ".jpeg", ".png", ".webp"]:
        raise HTTPException(status_code=400, detail="Invalid image type")

    filename = f"{uuid4()}{ext}"
    filepath = os.path.join(UPLOAD_DIR, filename)

    with open(filepath, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    profile.profile_image_url = f"/uploads/profile_images/{filename}"

    db.commit()
    db.refresh(profile)

    return {
        "message": "Profile image uploaded successfully",
        "profile_image_url": profile.profile_image_url,
    }