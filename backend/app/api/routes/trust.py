
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ...core.database import get_db
from ...core.auth import require_merchant_auth
from ...trust.policy import get_policy, check_policy, DEFAULT_POLICY
from ...models.entities import AuditEvent

router = APIRouter(tags=["trust"])

@router.get("/policies/{merchant_id}")
def get_pol(merchant_id: str, db: Session = Depends(get_db), identity: str = Depends(require_merchant_auth)):
    if merchant_id != identity:
        raise HTTPException(status_code=403, detail={"code": "cross_tenant", "message": "policy belongs to another merchant"})
    return get_policy(db, merchant_id)

@router.put("/policies/{merchant_id}")
def update_pol(merchant_id: str, payload: dict, db: Session = Depends(get_db), identity: str = Depends(require_merchant_auth)):
    if merchant_id != identity:
        raise HTTPException(status_code=403, detail={"code": "cross_tenant", "message": "policy belongs to another merchant"})
    pol = get_policy(db, merchant_id)
    for k in ["max_transaction","max_discount","auto_approve","allowed_actions","allowed_categories"]:
        if k in payload: setattr(pol, k, payload[k])
    db.commit(); db.refresh(pol)
    return pol

@router.post("/authorizations/check")
def auth_check(payload: dict, db: Session = Depends(get_db), identity: str = Depends(require_merchant_auth)):
    if payload.get("merchant_id") and payload["merchant_id"] != identity:
        raise HTTPException(status_code=403, detail={"code": "cross_tenant", "message": "payload merchant does not match authenticated merchant"})
    return check_policy(db, identity, payload["action"], payload.get("amount",0), payload.get("discount",0), payload.get("category",""))

@router.get("/audit")
def audit(limit: int = 20, db: Session = Depends(get_db), merchant_id: str = Depends(require_merchant_auth)):
    q=db.query(AuditEvent).filter(AuditEvent.merchant_id==merchant_id).order_by(AuditEvent.timestamp.desc())
    return q.limit(limit).all()
