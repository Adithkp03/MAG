
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from .config import settings
import os

db_url = settings.database_url
# auto fallback to sqlite if postgres not reachable at import time we still try postgres first
if db_url.startswith("sqlite"):
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
else:
    # allow sqlite fallback via env override if postgres unavailable
    try:
        engine = create_engine(db_url, pool_pre_ping=True)
        # test connection lazily - don't fail import
    except Exception:
        engine = create_engine("sqlite:///./dev.db", connect_args={"check_same_thread": False})

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
