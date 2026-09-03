
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ...core.database import get_db
from ...models.entities import Product, Cart, CartItem, Checkout, Order, Payment, Approval, AuditEvent
from ...services.catalog import search_products
from ...trust.policy import check_policy
from ...core.events import publish
import uuid
from datetime import datetime

router = APIRouter(prefix="/ucp", tags=["ucp"])

@router.get("/discover")
def discover(db: Session = Depends(get_db)):
    return {"merchant_id":"m_demo","name":"Demo Merchant","capabilities":["catalog","checkout","payment","policy","approval","trusted_ui"], "implemented":["catalog","checkout","get","update","complete","cancel","policy","approval","trusted_ui","razorpay","audit"], "profile":"/.well-known/ucp", "endpoints": {"catalog":"/api/v1/ucp/catalog","checkout":"/api/v1/ucp/checkout","get":"/api/v1/ucp/checkout/{id}","update":"PUT /api/v1/ucp/checkout/{id}","complete":"POST /api/v1/ucp/checkout/{id}/complete","cancel":"POST /api/v1/ucp/checkout/{id}/cancel","trusted_ui":"/api/v1/checkout/{id}/approve","well_known":"/.well-known/ucp"}, "note":"All UCP ops delegate to canonical Commerce Core — no duplicated logic; AP2 Mandates hint in 402"}

@router.get("/catalog")
def catalog(q: str="", category: str="", max_price: int=None, db: Session = Depends(get_db)):
    return search_products(db, "m_demo", q, category, max_price)

def _to_ucp_checkout(chk: Checkout, db: Session):
    order=db.query(Order).filter(Order.checkout_id==chk.id).first()
    pay=db.query(Payment).filter(Payment.razorpay_order_id.isnot(None)).filter(Payment.order_id==order.id).first() if order else None
    # also find pending approval
    appr=db.query(Approval).filter(Approval.checkout_id==chk.id, Approval.status=="pending").first()
    return {
        "id": chk.id,
        "status": chk.status,  # UCP maps: created->validated->payment_pending->captured->cancelled/blocked
        "merchant_id": chk.merchant_id,
        "total": chk.total,
        "total_inr": round(chk.total/100,2),
        "currency": "INR",
        "order_id": order.id if order else None,
        "razorpay_order_id": pay.razorpay_order_id if pay and pay.razorpay_order_id else None,
        "requires_approval": chk.status=="blocked",
        "approval_id": appr.id if appr else None,
        "trusted_ui_required": chk.status=="blocked",  # per UCP spec: must finalize via trusted UI unless AP2 Mandates supported
        "policy_version": chk.policy_version,
        "created_at": chk.created_at.isoformat() if chk.created_at else None
    }

@router.post("/checkout")
def ucp_create_checkout(payload: dict, db: Session = Depends(get_db)):
    """UCP Adapter: create -> delegates to internal Cart+Checkout core, no duplicate logic."""
    from .checkout import create_checkout
    from ...schemas import CheckoutCreate
    merchant_id=payload.get("merchant_id","m_demo")
    customer_id=payload.get("customer_id","cust_demo")
    items=payload.get("items", [])
    idempotency_key=payload.get("idempotency_key")
    # create cart via core
    cart=Cart(merchant_id=merchant_id, customer_id=customer_id, status="active", total=0)
    db.add(cart); db.flush()
    total=0
    for it in items:
        pid=it.get("product_id") or it.get("id")
        qty=int(it.get("quantity",1))
        prod=db.query(Product).filter(Product.id==pid, Product.merchant_id==merchant_id).first()
        if not prod:
            db.rollback()
            raise HTTPException(status_code=404, detail={"code":"product_not_found","message":f"product {pid} not found"})
        if prod.stock < qty:
            db.rollback()
            raise HTTPException(status_code=409, detail={"code":"insufficient_stock","message":f"product {pid} stock {prod.stock} insufficient"})
        ci=CartItem(cart_id=cart.id, product_id=prod.id, quantity=qty, unit_price=prod.price, line_total=prod.price*qty)
        db.add(ci); total+=ci.line_total
    cart.total=total
    if total==0:
        db.rollback()
        raise HTTPException(status_code=422, detail={"code":"empty_cart","message":"no valid items"})
    db.commit(); db.refresh(cart)
    # delegate to canonical checkout service
    try:
        res=create_checkout(CheckoutCreate(cart_id=cart.id), db=db, idempotency_key=idempotency_key or f"ucp_{uuid.uuid4().hex[:8]}")
        chk=res["checkout"] if isinstance(res, dict) and "checkout" in res else res
        # chk is ORM object
        ucp=_to_ucp_checkout(chk, db)
        return {"checkout": ucp, "cart_id": cart.id, "order": res.get("order"), "policy": res.get("policy"), "via": "ucp_adapter"}
    except HTTPException as e:
        # map 402 blocked to UCP escalation shape with trusted UI hint
        if e.status_code==402:
            d=e.detail
            chk_info=d.get("checkout", {})
            # fetch actual chk
            chk=db.query(Checkout).filter(Checkout.id==chk_info.get("id")).first()
            if chk:
                ucp=_to_ucp_checkout(chk, db)
                raise HTTPException(status_code=402, detail={
                    "code":"approval_required",
                    "message": d.get("message"),
                    "checkout": ucp,
                    "approval_id": d.get("approval_id"),
                    "requires_approval": True,
                    "trusted_ui": f"/api/v1/checkout/{chk.id}/approve",
                    "ucp_hint": "Complete via trusted UI or POST /api/v1/ucp/checkout/{id}/complete after approval (AP2 Mandates extension)"
                })
        raise e

@router.get("/checkout/{checkout_id}")
def ucp_get_checkout(checkout_id: str, db: Session = Depends(get_db)):
    chk=db.query(Checkout).filter(Checkout.id==checkout_id).first()
    if not chk: raise HTTPException(status_code=404, detail={"code":"checkout_not_found","message":"not found"})
    return {"checkout": _to_ucp_checkout(chk, db)}

@router.put("/checkout/{checkout_id}")
def ucp_update_checkout(checkout_id: str, payload: dict, db: Session = Depends(get_db)):
    chk=db.query(Checkout).filter(Checkout.id==checkout_id).first()
    if not chk: raise HTTPException(status_code=404, detail={"code":"checkout_not_found","message":"not found"})
    if chk.status != "validated":
        raise HTTPException(status_code=409, detail={"code":"invalid_state","message":f"can only update validated checkout, current {chk.status}"})
    # Allow updating items via cart: only if still validated and not yet payment_pending
    items=payload.get("items")
    if not items:
        return {"checkout": _to_ucp_checkout(chk, db), "message":"no items to update"}
    cart=db.query(Cart).filter(Cart.id==chk.cart_id).first()
    # clear old items and recreate
    db.query(CartItem).filter(CartItem.cart_id==cart.id).delete()
    total=0
    for it in items:
        pid=it.get("product_id") or it.get("id")
        qty=int(it.get("quantity",1))
        prod=db.query(Product).filter(Product.id==pid).first()
        if not prod: raise HTTPException(status_code=404, detail={"code":"product_not_found","message":pid})
        ci=CartItem(cart_id=cart.id, product_id=prod.id, quantity=qty, unit_price=prod.price, line_total=prod.price*qty)
        db.add(ci); total+=ci.line_total
    cart.total=total
    # re-check policy on new total
    pol=check_policy(db, chk.merchant_id, "create_payment", amount=total)
    if not pol["allowed"]:
        # transition to blocked and create approval
        chk.total=total; chk.status="blocked"
        appr=Approval(merchant_id=chk.merchant_id, checkout_id=chk.id, action="create_payment", amount=total, status="pending", requested_by="ucp_update", policy_version=pol["policy_version"], reason=pol["reason"])
        db.add(appr); db.commit(); db.refresh(chk)
        raise HTTPException(status_code=402, detail={"code":"approval_required","message":pol["reason"],"checkout": _to_ucp_checkout(chk, db), "approval_id": appr.id})
    chk.total=total
    # update linked order
    order=db.query(Order).filter(Order.checkout_id==chk.id).first()
    if order: order.total=total
    db.commit(); db.refresh(chk)
    publish("checkout.updated", {"checkout_id": chk.id, "total": total})
    return {"checkout": _to_ucp_checkout(chk, db), "cart_id": cart.id}

@router.post("/checkout/{checkout_id}/complete")
async def ucp_complete(checkout_id: str, payload: dict = {}, db: Session = Depends(get_db)):
    from .checkout import complete as core_complete
    chk=db.query(Checkout).filter(Checkout.id==checkout_id).first()
    if not chk: raise HTTPException(status_code=404, detail={"code":"checkout_not_found","message":"not found"})
    if chk.status=="blocked":
        raise HTTPException(status_code=402, detail={
            "code":"approval_required",
            "message":"checkout blocked - requires human approval before trusted completion",
            "checkout": _to_ucp_checkout(chk, db),
            "trusted_ui": f"/api/v1/checkout/{checkout_id}/approve",
            "hint": "UCP spec: checkout must be finalized through trusted UI unless AP2 Mandates extension supported"
        })
    res=await core_complete(checkout_id, payload, db)
    chk=db.query(Checkout).filter(Checkout.id==checkout_id).first()
    return {"checkout": _to_ucp_checkout(chk, db), "payment": res.get("payment"), "razorpay_order": res.get("razorpay_order"), "order": res.get("order"), "via": "ucp_adapter"}

@router.post("/checkout/{checkout_id}/cancel")
def ucp_cancel(checkout_id: str, db: Session = Depends(get_db)):
    from .checkout import cancel as core_cancel
    res=core_cancel(checkout_id, db)
    return {"checkout": _to_ucp_checkout(res, db), "cancelled": True}
