
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ...core.database import get_db
from ...trust.policy import get_policy, check_policy, DEFAULT_POLICY
from ...models.entities import AuditEvent

router = APIRouter(tags=["trust"])

@router.get("/policies/{merchant_id}")
def get_pol(merchant_id: str, db: Session = Depends(get_db)):
    return get_policy(db, merchant_id)

@router.put("/policies/{merchant_id}")
def update_pol(merchant_id: str, payload: dict, db: Session = Depends(get_db)):
    pol = get_policy(db, merchant_id)
    for k in ["max_transaction","max_discount","auto_approve","allowed_actions","allowed_categories"]:
        if k in payload: setattr(pol, k, payload[k])
    db.commit(); db.refresh(pol)
    return pol

@router.post("/authorizations/check")
def auth_check(payload: dict, db: Session = Depends(get_db)):
    return check_policy(db, payload["merchant_id"], payload["action"], payload.get("amount",0), payload.get("discount",0), payload.get("category",""))

@router.get("/audit")
def audit(merchant_id: str = None, limit: int = 20, db: Session = Depends(get_db)):
    q=db.query(AuditEvent).order_by(AuditEvent.timestamp.desc())
    if merchant_id: q=q.filter(AuditEvent.merchant_id==merchant_id)
    return q.limit(limit).all()
