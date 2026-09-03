
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session
from ...core.database import get_db
from ...models.entities import Checkout
from ...schemas import CheckoutCreate, CheckoutApproveReq, ErrorResponse
from ...services.commerce import create_checkout_svc, approve_checkout_svc, complete_checkout_svc
from ...core.auth import require_merchant_auth

router = APIRouter(prefix="/checkout", tags=["checkout"])

@router.post("", responses={400: {"model": ErrorResponse}, 402: {"model": ErrorResponse}})
def create_checkout(payload: CheckoutCreate, db: Session = Depends(get_db), idempotency_key: str = Header(None, alias="Idempotency-Key"), merchant=Depends(require_merchant_auth)):
    return create_checkout_svc(db, payload.cart_id, idempotency_key)

@router.get("/{checkout_id}")
def get_checkout(checkout_id: str, db: Session = Depends(get_db), merchant=Depends(require_merchant_auth)):
    chk = db.query(Checkout).filter(Checkout.id==checkout_id).first()
    if not chk: raise HTTPException(status_code=404, detail={"code":"checkout_not_found","message":"not found"})
    return chk

@router.post("/{checkout_id}/approve", responses={403: {"model": ErrorResponse}})
def approve(checkout_id: str, payload: CheckoutApproveReq, db: Session = Depends(get_db), x_approved_by: str = Header(None, alias="X-Approved-By"), merchant=Depends(require_merchant_auth)):
    # P0 #4 strict: derive from authenticated header only, not body
    if not x_approved_by or not x_approved_by.strip():
        raise HTTPException(status_code=401, detail={"code":"approver_required","message":"X-Approved-By header required (authenticated approver identity)"})
    derived = x_approved_by.strip()
    if payload.approved_by and payload.approved_by.strip() and payload.approved_by.strip() != derived:
        raise HTTPException(status_code=422, detail={"code":"approver_mismatch","message":"X-Approved-By header must match approved_by in body if provided"})
    return approve_checkout_svc(db, checkout_id, derived, payload.reason)

@router.post("/{checkout_id}/cancel")
def cancel(checkout_id: str, db: Session = Depends(get_db), merchant=Depends(require_merchant_auth)):
    chk = db.query(Checkout).filter(Checkout.id==checkout_id).first()
    if not chk: raise HTTPException(status_code=404, detail={"code":"checkout_not_found","message":"not found"})
    if not chk.can_transition("cancelled"): raise HTTPException(status_code=409, detail={"code":"invalid_state_transition","message": f"cannot transition {chk.status} -> cancelled"})
    chk.status="cancelled"; db.commit(); return chk

@router.post("/{checkout_id}/complete")
async def complete(checkout_id: str, payload: dict = {}, db: Session = Depends(get_db), merchant=Depends(require_merchant_auth)):
    return await complete_checkout_svc(db, checkout_id)
