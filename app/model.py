from sqlalchemy import Column, String, Numeric, Text, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
import uuid
from .db import Base
from sqlalchemy.orm import relationship

class User(Base):
    __tablename__ = "users"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    email = Column(String, unique=True, nullable=False)  


class Upload(Base):
    __tablename__ = "uploads"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    file_path = Column(Text)
    original_filename = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    transactions = relationship(
        "Transaction",
        back_populates="upload",
        cascade="all, delete-orphan",
    )

class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    upload_id = Column(UUID(as_uuid=True), ForeignKey("uploads.id"))
    upload = relationship("Upload", back_populates="transactions")

    bank = Column(String)
    transferred_at = Column(DateTime(timezone=True))
    amount = Column(Numeric(12, 2))

    memo = Column(Text)
    category = Column(Text)
    category_source = Column(Text)

    raw_ocr = Column(JSONB)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

