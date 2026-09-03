
from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session
from ...core.database import get_db
from ...models.entities import Payment, Order, Checkout, AuditEvent
from ...services.razorpay_adapter import create_razorpay_order, has_keys
from ...core.events import publish
import uuid

router = APIRouter(prefix="/payments", tags=["payments"])

@router.post("")
async def create_payment(payload: dict, db: Session = Depends(get_db), idempotency_key: str = Header(None, alias="Idempotency-Key")):
    order_id = payload.get("order_id")
    amount = payload.get("amount")  # paise
    order = db.query(Order).filter(Order.id==order_id).first() if order_id else None
    if not order and order_id: return {"error":"order not found"}
    if amount is None and order: amount = order.total
    if not amount: return {"error":"amount required"}
    # idempotency
    if idempotency_key:
        existing = db.query(Payment).filter(Payment.idempotency_key==idempotency_key).first()
        if existing: return existing
    else:
        idempotency_key = f"pay_{uuid.uuid4().hex[:8]}"
    # create Razorpay order
    receipt = f"rcpt_{order_id or idempotency_key}"[:40]
    rzp_order = await create_razorpay_order(amount, receipt, notes={"order_id": order_id or ""})
    pay = Payment(order_id=order_id, merchant_id=order.merchant_id if order else payload.get("merchant_id","m_demo"), amount=amount, status="created", razorpay_order_id=rzp_order.get("id"), idempotency_key=idempotency_key)
    db.add(pay)
    if order:
        order.payment_id = pay.id
    ae = AuditEvent(merchant_id=pay.merchant_id, action="create_payment", amount=amount, policy_result="approved", authorization="approved", result="created", reason=f"Razorpay order {rzp_order.get('id')} mock={rzp_order.get('mock',False)}", payload={"order_id": order_id, "razorpay_order_id": rzp_order.get("id")})
    db.add(ae); db.commit(); db.refresh(pay)
    publish("payment.created", {"payment_id": pay.id, "razorpay_order_id": rzp_order.get("id")})
    return {"payment": pay, "razorpay_order": rzp_order, "has_live_keys": has_keys()}

@router.get("/{payment_id}")
def get_payment(payment_id: str, db: Session = Depends(get_db)):
    p=db.query(Payment).filter(Payment.id==payment_id).first()
    if not p: return {"error":"not found"}
    return p

@router.post("/verify")
async def verify(payload: dict):
    from ...services.razorpay_adapter import verify_payment_signature
    ok = verify_payment_signature(payload.get("order_id",""), payload.get("payment_id",""), payload.get("signature",""))
    return {"verified": ok}
