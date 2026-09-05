from fastapi import Header, HTTPException, Depends
from sqlalchemy.orm import Session
from .database import get_db
from ..models.entities import Merchant, hash_api_key
import os


def _verify_key(presented: str, merchant: Merchant) -> bool:
    if merchant.api_key_hash:
        return hash_api_key(presented) == merchant.api_key_hash
    # legacy plaintext row: compare, then upgrade to hash (no logging of secret)
    if merchant.api_key and presented == merchant.api_key:
        try:
            merchant.api_key_hash = hash_api_key(presented)
            merchant.api_key_prefix = presented[:6]
        except Exception:
            pass
        return True
    return False


def require_merchant_auth(x_merchant_id: str = Header(None, alias="X-Merchant-Id"), x_api_key: str = Header(None, alias="X-API-Key"), db: Session = Depends(get_db)):
    """Strict tenant auth. Production default: MERCHANT_AUTH_STRICT=1 unless
    explicitly set to 0. Requires X-Merchant-Id + X-API-Key matching hash."""
    from .config import settings
    strict_env = os.getenv("MERCHANT_AUTH_STRICT")
    if strict_env is None:
        strict = (settings.env == "production")
    else:
        strict = (strict_env == "1")
    if not x_merchant_id:
        raise HTTPException(status_code=401, detail={"code": "merchant_auth_required", "message": "X-Merchant-Id required"})
    m = db.query(Merchant).filter(Merchant.id == x_merchant_id).first()
    if not m:
        raise HTTPException(status_code=401, detail={"code": "merchant_not_found", "message": "unknown merchant"})
    if m.api_key or m.api_key_hash:
        if not x_api_key:
            if strict:
                raise HTTPException(status_code=401, detail={"code": "api_key_required", "message": "X-API-Key required for this merchant"})
            return m.id
        if not _verify_key(x_api_key, m):
            raise HTTPException(status_code=401, detail={"code": "invalid_api_key", "message": "api key mismatch"})
        try:
            db.commit()
        except Exception:
            db.rollback()
    elif strict and not x_api_key:
        raise HTTPException(status_code=401, detail={"code": "api_key_required", "message": "X-API-Key required in strict mode"})
    return m.id


def require_merchant(x_merchant_id: str = Header(None, alias="X-Merchant-Id"), x_api_key: str = Header(None, alias="X-API-Key"), db: Session = Depends(get_db)):
    return require_merchant_auth(x_merchant_id, x_api_key, db)


def optional_merchant(x_merchant_id: str = Header(None, alias="X-Merchant-Id"), db: Session = Depends(get_db)):
    if not x_merchant_id:
        raise HTTPException(status_code=401, detail={"code": "merchant_auth_required", "message": "X-Merchant-Id required"})
    m = db.query(Merchant).filter(Merchant.id == x_merchant_id).first()
    if not m:
        raise HTTPException(status_code=401, detail={"code": "merchant_not_found"})
    return m.id


def issue_api_key() -> tuple[str, str, str]:
    """Returns (raw_key, hash, prefix). Raw key shown once at creation, never stored/logged."""
    import uuid
    raw = f"sk_{uuid.uuid4().hex[:24]}"
    return raw, hash_api_key(raw), raw[:6]
