from pydantic_settings import BaseSettings
import os
from pathlib import Path

# resolve .env relative to this file, not cwd (uvicorn --app-dir changes cwd)
ENV_PATH = Path(__file__).resolve().parents[2] / ".env"  # backend/.env

class Settings(BaseSettings):
    database_url: str = os.getenv("DATABASE_URL","sqlite:///./dev.db")
    redis_url: str = os.getenv("REDIS_URL","redis://localhost:6379/0")
    groq_api_key: str = os.getenv("GROQ_API_KEY","")
    groq_model: str = os.getenv("GROQ_MODEL","openai/gpt-oss-20b")
    razorpay_key_id: str = os.getenv("RAZORPAY_KEY_ID","")
    razorpay_key_secret: str = os.getenv("RAZORPAY_KEY_SECRET","")
    razorpay_webhook_secret: str = os.getenv("RAZORPAY_WEBHOOK_SECRET","")
    jwt_secret: str = os.getenv("JWT_SECRET","dev-secret")
    env: str = os.getenv("ENV","development")
    allowed_origins: str = os.getenv("ALLOWED_ORIGINS","http://localhost:3000,http://127.0.0.1:3000")
    rate_limit_per_min: int = int(os.getenv("RATE_LIMIT_PER_MIN","60"))
    log_level: str = os.getenv("LOG_LEVEL","INFO")
    cache_ttl_seconds: int = int(os.getenv("CACHE_TTL_SECONDS","60"))
    class Config:
        env_file = str(ENV_PATH)
        env_file_encoding = "utf-8"
        extra = "ignore"
settings = Settings()
