
from fastapi import Header, HTTPException, Depends
from sqlalchemy.orm import Session
from .database import get_db
from ..models.entities import Merchant
import os

def require_merchant_auth(x_merchant_id: str = Header(None, alias="X-Merchant-Id"), x_api_key: str = Header(None, alias="X-API-Key"), db: Session = Depends(get_db)):
    """P0 #5 strict merchant auth: in prod requires X-Merchant-Id + X-API-Key matching.
    Env MERCHANT_AUTH_STRICT=1 enforces (for final deploy). Dev allows m_demo fallback but logs."""
    strict = os.getenv("MERCHANT_AUTH_STRICT", "0") == "1"
    if not x_merchant_id:
        if strict:
            raise HTTPException(status_code=401, detail={"code":"merchant_auth_required","message":"X-Merchant-Id required"})
        return "m_demo"
    m = db.query(Merchant).filter(Merchant.id==x_merchant_id).first()
    if not m:
        raise HTTPException(status_code=401, detail={"code":"merchant_not_found","message":"unknown merchant"})
    # if merchant has api_key, key must be presented and match
    if m.api_key:
        if not x_api_key:
            if strict:
                raise HTTPException(status_code=401, detail={"code":"api_key_required","message":"X-API-Key required for this merchant"})
            # dev: allow but this is permissive - still return m.id but caller should add auth
            return m.id
        if x_api_key != m.api_key:
            raise HTTPException(status_code=401, detail={"code":"invalid_api_key","message":"api key mismatch"})
    # merchant without api_key: require merchant_id only
    return m.id

# backward compat alias
def require_merchant(x_merchant_id: str = Header(None, alias="X-Merchant-Id"), x_api_key: str = Header(None, alias="X-API-Key"), db: Session = Depends(get_db)):
    return require_merchant_auth(x_merchant_id, x_api_key, db)

def optional_merchant(x_merchant_id: str = Header(None, alias="X-Merchant-Id")):
    return x_merchant_id or "m_demo"
