import email
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.db import SessionLocal
from app.model import User  # ต้องมี model User
from app.services.auth_service import hash_password, verify_password, create_access_token

router = APIRouter(prefix="/auth", tags=["Auth"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class RegisterRequest(BaseModel):
    username: str
    password: str
    email: str

@router.post("/register")
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    username = payload.username.strip()
    if len(username) < 3:
        raise HTTPException(status_code=400, detail="username too short")
    if len(payload.password) < 6:
        raise HTTPException(status_code=400, detail="password too short")

    email_ = payload.email.strip().lower()

    existing = db.query(User).filter(
        or_(
            User.username == username,
            User.email == email_
        )
    ).first()
    if existing:
        if existing.username == username:
            raise HTTPException(status_code=409, detail="username already exists")
        if existing.email == email_:
            raise HTTPException(status_code=409, detail="email already exists")

    user = User(
        username=username,
        password_hash=hash_password(payload.password),
        email=email_
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token({"sub": str(user.id)})
    return {"access_token": token, "token_type": "bearer"}

@router.post("/login")
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    login_value = form.username.strip()

    user = db.query(User).filter(
        or_(
            User.username == login_value,
            User.email == login_value.lower()
        )
    ).first()

    if not user:
        raise HTTPException(status_code=401, detail="invalid username/email or password")

    if not verify_password(form.password, user.password_hash):
        raise HTTPException(status_code=401, detail="invalid username/email or password")

    token = create_access_token({"sub": str(user.id)})
    return {"access_token": token, "token_type": "bearer"}