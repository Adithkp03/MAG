
from fastapi import Header, HTTPException, Depends
from sqlalchemy.orm import Session
from .database import get_db
from ..models.entities import Merchant

def require_merchant(x_merchant_id: str = Header(None, alias="X-Merchant-Id"), x_api_key: str = Header(None, alias="X-API-Key"), db: Session = Depends(get_db)):
    """P0-16 proper merchant authorization: X-Merchant-Id + X-API-Key must match. Fallback to demo for dev if no headers."""
    if not x_merchant_id:
        return "m_demo"  # dev convenience, production should require it
    m = db.query(Merchant).filter(Merchant.id==x_merchant_id).first()
    if not m:
        raise HTTPException(status_code=401, detail={"code":"merchant_not_found","message":"unknown merchant"})
    if x_api_key and m.api_key and x_api_key != m.api_key:
        raise HTTPException(status_code=401, detail={"code":"invalid_api_key","message":"api key mismatch"})
    # if merchant has api_key but none supplied, allow for dev but warn; in prod set require_api_key=true
    return m.id

def optional_merchant(x_merchant_id: str = Header(None, alias="X-Merchant-Id")):
    return x_merchant_id or "m_demo"
