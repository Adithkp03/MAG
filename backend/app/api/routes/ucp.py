"""
Full UCP (Universal Commerce Protocol) ecosystem — adapter that is also a
complete checkout lifecycle owner.

External AI flow (no custom internal endpoint needed):
  1. Discover  -> GET /.well-known/ucp  (profile)  + GET /api/v1/ucp/discover
  2. Catalog   -> GET /api/v1/ucp/catalog?q=&category=&max_price=&merchant_id=
  3. Create    -> POST /api/v1/ucp/checkout {merchant_id, customer_id, items[], continue_url, idempotency_key}
  4. Get       -> GET  /api/v1/ucp/checkout/{id}
  5. Update    -> PUT  /api/v1/ucp/checkout/{id} {items}
  6. Complete  -> POST /api/v1/ucp/checkout/{id}/complete
  7. Cancel    -> POST /api/v1/ucp/checkout/{id}/cancel

Internally every step calls canonical Commerce Core (cart/checkout/order)
services directly — never delegates to the custom /api/v1/checkout router.
continue_url (Phase 16) is preserved end-to-end for buyer redirect.
"""

from fastapi import APIRouter, Depends, HTTPException, Header, Query
from sqlalchemy.orm import Session
from ...core.database import get_db
from ...models.entities import Product, Cart, CartItem, Checkout, Order, Payment, Approval, AuditEvent
from ...services.catalog import search_products
from ...services.commerce import create_checkout_svc, complete_checkout_svc
from ...trust.policy import check_policy
from ...core.events import publish
import uuid
from datetime import datetime

router = APIRouter(prefix="/ucp", tags=["ucp"])

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _to_ucp_checkout(chk: Checkout, db: Session, continue_url: str | None = None):
    order = db.query(Order).filter(Order.checkout_id == chk.id).first()
    pay = None
    if order:
        pay = db.query(Payment).filter(Payment.order_id == order.id).first()
        if not pay:
            pay = db.query(Payment).filter(Payment.razorpay_order_id.isnot(None)).filter(Payment.merchant_id == chk.merchant_id).order_by(Payment.created_at.desc()).first() if False else None
    # also find pending approval
    appr = db.query(Approval).filter(Approval.checkout_id == chk.id, Approval.status == "pending").first()
    out = {
        "id": chk.id,
        "status": chk.status,
        "merchant_id": chk.merchant_id,
        "cart_id": chk.cart_id,
        "customer_id": chk.customer_id,
        "total": chk.total,
        "total_inr": round(chk.total / 100, 2) if chk.total else 0,
        "currency": "INR",
        "order_id": order.id if order else None,
        "order_status": order.status if order else None,
        "razorpay_order_id": pay.razorpay_order_id if pay and pay.razorpay_order_id else None,
        "payment_id": pay.id if pay else None,
        "requires_approval": chk.status == "blocked",
        "approval_id": appr.id if appr else None,
        "trusted_ui_required": chk.status == "blocked",
        "policy_version": chk.policy_version,
        "idempotency_key": chk.idempotency_key,
        "created_at": chk.created_at.isoformat() if chk.created_at else None,
    }
    if continue_url:
        out["continue_url"] = continue_url
    else:
        # try to recover continue_url from audit payload if present
        try:
            ae = db.query(AuditEvent).filter(AuditEvent.payload["checkout_id"].astext == chk.id).first() if False else None
        except Exception:
            ae = None
        # fallback: look up last audit with checkout_id
        if not continue_url:
            # check if any audit payload stored continue_url (best-effort)
            for row in db.query(AuditEvent).filter(AuditEvent.action == "create_checkout").order_by(AuditEvent.timestamp.desc()).limit(5).all():
                try:
                    if row.payload and row.payload.get("continue_url") and row.payload.get("cart_id") == chk.cart_id:
                        out["continue_url"] = row.payload["continue_url"]
                        break
                except Exception:
                    continue
    return out


def _product_to_ucp(p: Product):
    return {
        "id": p.id,
        "product_id": p.id,
        "merchant_id": p.merchant_id,
        "name": p.name,
        "description": p.description,
        "price": p.price,
        "price_inr": round(p.price / 100, 2),
        "currency": "INR",
        "category": p.category,
        "stock": p.stock,
        "image_url": p.image_url or "",
    }

# ---------------------------------------------------------------------------
# Discover & Catalog — UCP-native discovery (no internal delegation)
# ---------------------------------------------------------------------------

@router.get("/discover")
def discover(db: Session = Depends(get_db)):
    """UCP discover — advertises merchant capabilities for external AI."""
    return {
        "merchant_id": "m_demo",
        "name": "Demo Merchant",
        "description": "Demo Merchant — autonomous commerce via UCP. External AI can discover catalog, create checkout, and complete payment entirely through UCP without calling custom internal endpoints.",
        "ucp_version": "1.0-draft",
        "capabilities": ["catalog", "checkout", "payment", "policy", "approval", "trusted_ui"],
        "implemented": ["catalog", "checkout", "get", "update", "complete", "cancel", "policy", "approval", "trusted_ui", "razorpay", "audit"],
        "profile": "/.well-known/ucp",
        "endpoints": {
            "profile": "/.well-known/ucp",
            "discover": "/api/v1/ucp/discover",
            "catalog": "/api/v1/ucp/catalog",
            "checkout_create": "POST /api/v1/ucp/checkout",
            "checkout_get": "GET /api/v1/ucp/checkout/{id}",
            "checkout_update": "PUT /api/v1/ucp/checkout/{id}",
            "checkout_complete": "POST /api/v1/ucp/checkout/{id}/complete",
            "checkout_cancel": "POST /api/v1/ucp/checkout/{id}/cancel",
            "trusted_ui": "/api/v1/checkout/{id}/approve",
        },
        "flow": {
            "1_discover": "GET /.well-known/ucp -> read capabilities + endpoints",
            "2_catalog": "GET /api/v1/ucp/catalog?q=keyboard -> list products",
            "3_create": "POST /api/v1/ucp/checkout {merchant_id, customer_id, items:[{product_id, quantity}], continue_url, idempotency_key} -> creates cart + checkout + order via Commerce Core",
            "4_complete": "POST /api/v1/ucp/checkout/{id}/complete -> creates Razorpay order + payment via Commerce Core",
            "approval": "If 402 approval_required -> human approves via trusted UI then retry complete",
        },
        "continue_url": "Pass continue_url in POST /api/v1/ucp/checkout to receive buyer redirect URL in response; echoed in checkout resource and respected on completion.",
        "note": "All UCP ops call canonical Commerce Core (services/commerce.py + services/catalog.py) directly — no delegation to custom /api/v1/checkout router. AP2 Mandates hint included in 402.",
    }


@router.get("/catalog")
def catalog(
    q: str = Query(default=""),
    category: str = Query(default=""),
    max_price: int | None = None,
    merchant_id: str = Query(default="m_demo"),
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """UCP catalog — external AI discovery. Internally calls catalog service."""
    products = search_products(db, merchant_id, q, category, max_price)
    items = [_product_to_ucp(p) for p in products[:limit]]
    return {
        "merchant_id": merchant_id,
        "query": {"q": q, "category": category, "max_price": max_price},
        "count": len(items),
        "products": items,
        "via": "ucp_catalog_commerce_core",
    }

# ---------------------------------------------------------------------------
# Checkout lifecycle — full UCP, via Commerce Core directly
# ---------------------------------------------------------------------------

@router.post("/checkout")
def ucp_create_checkout(payload: dict, db: Session = Depends(get_db)):
    """
    UCP create checkout — full lifecycle owner.
    Creates Cart + CartItems directly, then calls create_checkout_svc
    (canonical Commerce Core). Handles continue_url and policy escalation.
    """
    merchant_id = payload.get("merchant_id")
    if not merchant_id:
        raise HTTPException(status_code=400, detail={"code": "merchant_id_required", "message": "merchant_id required in payload"})

    customer_id = payload.get("customer_id", "cust_demo")
    items = payload.get("items", [])
    idempotency_key = payload.get("idempotency_key") or f"ucp_{uuid.uuid4().hex[:8]}"
    continue_url = payload.get("continue_url") or payload.get("continueUrl")

    # Idempotency: if key already used for a checkout, return existing (UCP idempotent)
    existing_chk = db.query(Checkout).filter(Checkout.idempotency_key == idempotency_key).first()
    if existing_chk:
        ucp = _to_ucp_checkout(existing_chk, db, continue_url=continue_url)
        order = db.query(Order).filter(Order.checkout_id == existing_chk.id).first()
        return {
            "checkout": ucp,
            "cart_id": existing_chk.cart_id,
            "order": {"id": order.id, "status": order.status} if order else None,
            "via": "ucp_commerce_core",
            "deduped": True,
            "continue_url": continue_url,
        }

    # Create cart via Commerce Core primitives (direct DB, not via /carts router)
    cart = Cart(merchant_id=merchant_id, customer_id=customer_id, status="active", total=0)
    db.add(cart)
    db.flush()

    total = 0
    for it in items:
        pid = it.get("product_id") or it.get("id")
        qty = int(it.get("quantity", 1))
        if qty <= 0:
            db.rollback()
            raise HTTPException(status_code=422, detail={"code": "invalid_quantity", "message": f"quantity must be >0 for {pid}"})
        prod = db.query(Product).filter(Product.id == pid, Product.merchant_id == merchant_id).first()
        if not prod:
            db.rollback()
            raise HTTPException(status_code=404, detail={"code": "product_not_found", "message": f"product {pid} not found"})
        if prod.stock < qty:
            db.rollback()
            raise HTTPException(status_code=409, detail={"code": "insufficient_stock", "message": f"product {pid} stock {prod.stock} insufficient for {qty}"})
        ci = CartItem(cart_id=cart.id, product_id=prod.id, quantity=qty, unit_price=prod.price, line_total=prod.price * qty)
        db.add(ci)
        total += ci.line_total

    cart.total = total
    if total == 0:
        db.rollback()
        raise HTTPException(status_code=422, detail={"code": "empty_cart", "message": "no valid items — cart total is 0"})

    db.commit()
    db.refresh(cart)

    # Delegate to canonical checkout service (Commerce Core), not to /checkout router
    try:
        res = create_checkout_svc(db, cart.id, idempotency_key=idempotency_key)
        chk = res["checkout"] if isinstance(res, dict) and "checkout" in res else res
        # store continue_url in audit payload for recovery (no schema migration needed)
        if continue_url:
            try:
                ae = AuditEvent(
                    merchant_id=merchant_id,
                    action="ucp_checkout_continue_url",
                    amount=chk.total,
                    policy_result="approved",
                    authorization="ucp",
                    result="success",
                    reason=f"continue_url={continue_url}",
                    payload={"checkout_id": chk.id, "cart_id": cart.id, "continue_url": continue_url},
                )
                db.add(ae)
                db.commit()
            except Exception:
                pass
        ucp = _to_ucp_checkout(chk, db, continue_url=continue_url)
        order = res.get("order") if isinstance(res, dict) else None
        policy = res.get("policy") if isinstance(res, dict) else None
        resp = {
            "checkout": ucp,
            "cart_id": cart.id,
            "order": {"id": order.id, "status": order.status, "total": order.total} if order else None,
            "policy": policy,
            "via": "ucp_commerce_core",
            "deduped": res.get("deduped", False) if isinstance(res, dict) else False,
        }
        if continue_url:
            resp["continue_url"] = continue_url
        return resp
    except HTTPException as e:
        # Map 402 blocked to UCP escalation shape with trusted UI hint
        if e.status_code == 402:
            d = e.detail if isinstance(e.detail, dict) else {}
            chk_info = d.get("checkout", {}) if isinstance(d, dict) else {}
            chk = db.query(Checkout).filter(Checkout.id == chk_info.get("id")).first()
            if not chk:
                # checkout was created as blocked but id not in detail — fetch by cart
                chk = db.query(Checkout).filter(Checkout.cart_id == cart.id).first()
            if chk:
                # attach continue_url audit if provided
                if continue_url:
                    try:
                        ae = AuditEvent(
                            merchant_id=merchant_id,
                            action="ucp_checkout_continue_url",
                            amount=chk.total,
                            policy_result=d.get("decision", "escalated"),
                            authorization="ucp",
                            result="blocked",
                            reason=f"continue_url={continue_url}",
                            payload={"checkout_id": chk.id, "cart_id": cart.id, "continue_url": continue_url},
                        )
                        db.add(ae)
                        db.commit()
                    except Exception:
                        pass
                ucp = _to_ucp_checkout(chk, db, continue_url=continue_url)
                raise HTTPException(
                    status_code=402,
                    detail={
                        "code": "approval_required",
                        "message": d.get("message", "requires approval"),
                        "decision": d.get("decision"),
                        "requires_approval": True,
                        "checkout": ucp,
                        "approval_id": d.get("approval_id"),
                        "trusted_ui": f"/api/v1/checkout/{chk.id}/approve",
                        "continue_url": continue_url,
                        "ucp_hint": "Complete via trusted UI (X-Approved-By) or POST /api/v1/ucp/checkout/{id}/complete after approval (AP2 Mandates extension)",
                    },
                )
        raise e


@router.get("/checkout/{checkout_id}")
def ucp_get_checkout(checkout_id: str, db: Session = Depends(get_db)):
    chk = db.query(Checkout).filter(Checkout.id == checkout_id).first()
    if not chk:
        raise HTTPException(status_code=404, detail={"code": "checkout_not_found", "message": "not found"})
    return {"checkout": _to_ucp_checkout(chk, db)}


@router.put("/checkout/{checkout_id}")
def ucp_update_checkout(checkout_id: str, payload: dict, db: Session = Depends(get_db)):
    chk = db.query(Checkout).filter(Checkout.id == checkout_id).first()
    if not chk:
        raise HTTPException(status_code=404, detail={"code": "checkout_not_found", "message": "not found"})
    if chk.status != "validated":
        raise HTTPException(status_code=409, detail={"code": "invalid_state", "message": f"can only update validated checkout, current {chk.status}"})

    items = payload.get("items")
    if not items:
        return {"checkout": _to_ucp_checkout(chk, db), "message": "no items to update"}

    cart = db.query(Cart).filter(Cart.id == chk.cart_id).first()
    if not cart:
        raise HTTPException(status_code=404, detail={"code": "cart_not_found", "message": "cart for checkout not found"})

    # Clear old items and recreate (UCP update semantics)
    db.query(CartItem).filter(CartItem.cart_id == cart.id).delete()
    total = 0
    for it in items:
        pid = it.get("product_id") or it.get("id")
        qty = int(it.get("quantity", 1))
        prod = db.query(Product).filter(Product.id == pid).first()
        if not prod:
            db.rollback()
            raise HTTPException(status_code=404, detail={"code": "product_not_found", "message": f"product {pid} not found"})
        if prod.stock < qty:
            db.rollback()
            raise HTTPException(status_code=409, detail={"code": "insufficient_stock", "message": f"product {pid} stock {prod.stock}"})
        ci = CartItem(cart_id=cart.id, product_id=prod.id, quantity=qty, unit_price=prod.price, line_total=prod.price * qty)
        db.add(ci)
        total += ci.line_total

    cart.total = total

    # Re-check policy on new total via policy engine directly
    pol = check_policy(db, chk.merchant_id, "create_payment", amount=total)
    if not pol["allowed"]:
        # Transition to blocked and create approval (canonical pattern)
        chk.total = total
        chk.status = "blocked"
        appr = Approval(
            merchant_id=chk.merchant_id,
            checkout_id=chk.id,
            action="create_payment",
            amount=total,
            status="pending",
            requested_by="ucp_update",
            policy_version=pol["policy_version"],
            reason=pol["reason"],
        )
        db.add(appr)
        db.commit()
        db.refresh(chk)
        raise HTTPException(
            status_code=402,
            detail={
                "code": "approval_required",
                "message": pol["reason"],
                "decision": pol.get("decision"),
                "checkout": _to_ucp_checkout(chk, db),
                "approval_id": appr.id,
                "trusted_ui": f"/api/v1/checkout/{chk.id}/approve",
            },
        )

    chk.total = total
    order = db.query(Order).filter(Order.checkout_id == chk.id).first()
    if order:
        order.total = total
    db.commit()
    db.refresh(chk)
    publish("checkout.updated", {"checkout_id": chk.id, "total": total, "via": "ucp"})
    return {"checkout": _to_ucp_checkout(chk, db), "cart_id": cart.id, "via": "ucp_commerce_core"}


@router.post("/checkout/{checkout_id}/complete")
async def ucp_complete(checkout_id: str, payload: dict = None, db: Session = Depends(get_db)):
    """UCP complete — calls Commerce Core complete_checkout_svc directly."""
    if payload is None:
        payload = {}
    chk = db.query(Checkout).filter(Checkout.id == checkout_id).first()
    if not chk:
        raise HTTPException(status_code=404, detail={"code": "checkout_not_found", "message": "not found"})
    if chk.status == "blocked":
        raise HTTPException(
            status_code=402,
            detail={
                "code": "approval_required",
                "message": "checkout blocked - requires human approval before trusted completion",
                "checkout": _to_ucp_checkout(chk, db),
                "trusted_ui": f"/api/v1/checkout/{checkout_id}/approve",
                "approval_id": db.query(Approval).filter(Approval.checkout_id == checkout_id, Approval.status == "pending").first().id
                if db.query(Approval).filter(Approval.checkout_id == checkout_id, Approval.status == "pending").first()
                else None,
                "hint": "UCP spec: checkout must be finalized through trusted UI unless AP2 Mandates extension supported. After approval, retry POST /api/v1/ucp/checkout/{id}/complete.",
            },
        )
    # Idempotency: if already payment_pending/captured, complete_checkout_svc handles dedup
    res = await complete_checkout_svc(db, checkout_id)
    # Refresh checkout for response
    chk = db.query(Checkout).filter(Checkout.id == checkout_id).first()
    ucp = _to_ucp_checkout(chk, db)
    # propagate continue_url if present in payload or stored audit
    continue_url = payload.get("continue_url") or payload.get("continueUrl")
    if not continue_url and "continue_url" in ucp:
        continue_url = ucp["continue_url"]
    out = {
        "checkout": ucp,
        "payment": {"id": res["payment"].id, "status": res["payment"].status, "razorpay_order_id": res["payment"].razorpay_order_id} if res.get("payment") else None,
        "razorpay_order": res.get("razorpay_order"),
        "order": {"id": res["order"].id, "status": res["order"].status, "total": res["order"].total} if res.get("order") else None,
        "has_live_keys": res.get("has_live_keys"),
        "deduped": res.get("deduped", False),
        "via": "ucp_commerce_core",
    }
    if continue_url:
        out["continue_url"] = continue_url
        out["checkout"]["continue_url"] = continue_url
    return out


@router.post("/checkout/{checkout_id}/cancel")
def ucp_cancel(checkout_id: str, db: Session = Depends(get_db)):
    """UCP cancel — directly via Commerce Core state machine (no router delegation)."""
    chk = db.query(Checkout).filter(Checkout.id == checkout_id).first()
    if not chk:
        raise HTTPException(status_code=404, detail={"code": "checkout_not_found", "message": "not found"})
    if not chk.can_transition("cancelled"):
        raise HTTPException(status_code=409, detail={"code": "invalid_state_transition", "message": f"cannot transition {chk.status} -> cancelled"})
    chk.status = "cancelled"
    # also cancel order if present
    order = db.query(Order).filter(Order.checkout_id == chk.id).first()
    if order and order.status not in ("cancelled", "paid"):
        order.status = "cancelled"
    db.commit()
    db.refresh(chk)
    publish("checkout.cancelled", {"checkout_id": chk.id, "via": "ucp"})
    return {"checkout": _to_ucp_checkout(chk, db), "cancelled": True, "via": "ucp_commerce_core"}
