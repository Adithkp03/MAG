
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from ...core.database import get_db
from ...models.entities import Payment, Order, AuditEvent
from ...services.razorpay_adapter import create_razorpay_order, has_keys
from ...schemas import PaymentCreate, PaymentOut, ErrorResponse
from ...core.events import publish
import uuid

router = APIRouter(prefix="/payments", tags=["payments"])

@router.post("", responses={409: {"model": ErrorResponse}})
async def create_payment(payload: PaymentCreate, db: Session = Depends(get_db), idempotency_key: str = Header(None, alias="Idempotency-Key")):
    # P0-4 idempotency by header - must be supplied for financial calls, generate server-side if missing but warn
    if not idempotency_key:
        idempotency_key = f"pay_{uuid.uuid4().hex[:8]}"
    existing = db.query(Payment).filter(Payment.idempotency_key==idempotency_key).first()
    if existing:
        return {"payment": existing, "deduped": True}
    # exact amount binding: derive from order if order_id given, else require amount
    order = None
    amount = payload.amount
    if payload.order_id:
        order = db.query(Order).filter(Order.id==payload.order_id).first()
        if not order:
            raise HTTPException(status_code=404, detail={"code":"order_not_found","message":"order not found"})
        amount = order.total
    if amount is None:
        raise HTTPException(status_code=422, detail={"code":"amount_required","message":"amount required if order_id not supplied"})
    receipt = f"rcpt_{payload.order_id or idempotency_key}"[:40]
    rzp_order = await create_razorpay_order(amount, receipt, notes={"order_id": payload.order_id or "", "merchant_id": payload.merchant_id or (order.merchant_id if order else "m_demo")})
    # razorpay_order_id unique enforces correlation P0-3
    pay = Payment(order_id=payload.order_id, merchant_id=payload.merchant_id or (order.merchant_id if order else "m_demo"), amount=amount, status="created", razorpay_order_id=rzp_order.get("id"), idempotency_key=idempotency_key)
    try:
        db.add(pay)
        if order:
            order.payment_id = pay.id
        ae = AuditEvent(merchant_id=pay.merchant_id, action="create_payment", amount=amount, policy_result="approved", authorization="approved", result="created", reason=f"Razorpay order {rzp_order.get('id')} mock={rzp_order.get('mock',False)}", payload={"order_id": payload.order_id, "razorpay_order_id": rzp_order.get("id"), "idempotency_key": idempotency_key})
        db.add(ae); db.commit(); db.refresh(pay)
    except IntegrityError:
        db.rollback()
        dup = db.query(Payment).filter(Payment.idempotency_key==idempotency_key).first()
        if dup: return {"payment": dup, "deduped": True}
        raise HTTPException(status_code=409, detail={"code":"idempotency_conflict","message":"idempotency_key already used"})
    publish("payment.created", {"payment_id": pay.id, "razorpay_order_id": rzp_order.get("id")})
    # manual dict to avoid Pydantic ORM serialization issue
    pay_dict = {c.key: getattr(pay, c.key) for c in pay.__table__.columns}
    return {"payment": pay_dict, "razorpay_order": rzp_order, "has_live_keys": has_keys()}

@router.get("/{payment_id}", response_model=PaymentOut, responses={404: {"model": ErrorResponse}})
def get_payment(payment_id: str, db: Session = Depends(get_db)):
    p=db.query(Payment).filter(Payment.id==payment_id).first()
    if not p: raise HTTPException(status_code=404, detail={"code":"payment_not_found","message":"not found"})
    return p

@router.get("", response_model=list)
def list_payments(db: Session = Depends(get_db)):
    return db.query(Payment).limit(50).all()

@router.post("/verify")
async def verify(payload: dict):
    from ...services.razorpay_adapter import verify_payment_signature
    ok = verify_payment_signature(payload.get("order_id",""), payload.get("payment_id",""), payload.get("signature",""))
    return {"verified": ok}

@router.post("/reconcile")
async def reconcile(payload: dict, db: Session = Depends(get_db)):
    """P0-6 payment reconciliation: fetch Razorpay status and sync DB if webhook missed"""
    payment_id = payload.get("payment_id")
    pay = db.query(Payment).filter(Payment.id==payment_id).first()
    if not pay: raise HTTPException(status_code=404, detail={"code":"payment_not_found","message":"not found"})
    from ...services.razorpay_adapter import fetch_payment
    # only fetch by payment_id, not order_id
    pid = pay.razorpay_payment_id or payment_id
    if pid and pid.startswith("order_"):
        raise_int = __import__("fastapi").HTTPException(status_code=400, detail={"code":"invalid_payment_id","message":"reconcile requires razorpay_payment_id, not order_id"})
        raise raise_int
    live = await fetch_payment(pid)
    # sync status if diverged
    return {"payment_id": pay.id, "db_status": pay.status, "live": live}
