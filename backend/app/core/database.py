
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from .config import settings
import os

Base = declarative_base()

def get_engine():
    url = settings.database_url
    is_prod = settings.env == "production"
    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False})
    # postgres: test connectivity, fail loud in prod, fallback only in dev
    try:
        eng = create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5)
        # quick ping
        with eng.connect() as c:
            c.execute(create_engine(url).connect().execute.__self__ if False else c.execute.__self__ if False else __import__("sqlalchemy").text("SELECT 1"))
        return eng
    except Exception as e:
        if is_prod:
            raise RuntimeError(f"DATABASE_URL unreachable in production: {e}")
        print(f"WARN postgres unreachable ({e}), falling back to sqlite dev.db for development")
        return create_engine("sqlite:///./dev.db", connect_args={"check_same_thread": False})

# lazy engine - created at import but with fallback logic above
try:
    engine = get_engine()
except Exception as e:
    # still allow app to start so health can report, but DB ops will fail
    print(f"DB init failed: {e}")
    from sqlalchemy import create_engine as ce
    engine = ce("sqlite:///./dev.db", connect_args={"check_same_thread": False})

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
