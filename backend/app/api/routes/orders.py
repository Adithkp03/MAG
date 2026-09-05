
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ...core.database import get_db
from ...core.auth import require_merchant_auth
from ...models.entities import Order
router = APIRouter(prefix="/orders", tags=["orders"])

def _scoped(order_merchant: str, merchant: str):
    if order_merchant != merchant:
        raise HTTPException(status_code=403, detail={"code": "cross_tenant", "message": "order belongs to another merchant"})

@router.get("")
def list_orders(db: Session = Depends(get_db), merchant=Depends(require_merchant_auth)):
    return db.query(Order).filter(Order.merchant_id == merchant).order_by(Order.created_at.desc()).limit(50).all()

@router.get("/{order_id}")
def get_order(order_id: str, db: Session = Depends(get_db), merchant=Depends(require_merchant_auth)):
    o = db.query(Order).filter(Order.id == order_id).first()
    if not o:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "order not found"})
    _scoped(o.merchant_id, merchant)
    return o

@router.post("")
def create_order(payload: dict, db: Session = Depends(get_db), merchant=Depends(require_merchant_auth)):
    # merchant is always the authenticated identity; payload cannot override it
    payload = dict(payload or {})
    payload["merchant_id"] = merchant
    o = Order(**{k: v for k, v in payload.items() if hasattr(Order, k)})
    db.add(o); db.commit(); db.refresh(o)
    return o
