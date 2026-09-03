
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ...core.database import get_db
from ...models.entities import Order
router = APIRouter(prefix="/orders", tags=["orders"])
@router.get("")
def list_orders(merchant_id: str = None, db: Session = Depends(get_db)):
    q=db.query(Order)
    if merchant_id: q=q.filter(Order.merchant_id==merchant_id)
    return q.limit(50).all()
@router.get("/{order_id}")
def get_order(order_id: str, db: Session = Depends(get_db)):
    o=db.query(Order).filter(Order.id==order_id).first()
    if not o: return {"error":"not found"}
    return o
@router.post("")
def create_order(payload: dict, db: Session = Depends(get_db)):
    o=Order(**payload)
    db.add(o); db.commit(); db.refresh(o)
    return o
