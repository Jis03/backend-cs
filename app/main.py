from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from .db import engine, Base
from .routers import auth_router, upload_router, dashboard_router, transactions_router, stats_router, finance_router , goals_router , profile_router
import os


Base.metadata.create_all(bind=engine)

app = FastAPI()

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router.router)
app.include_router(upload_router.router)
app.include_router(dashboard_router.router)
app.include_router(transactions_router.router)
app.include_router(stats_router.router)
app.include_router(finance_router.router)
app.include_router(goals_router.router)
app.include_router(profile_router.router)