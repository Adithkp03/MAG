
from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session
from ...core.database import get_db
from ...models.entities import Cart, CartItem, Product, AuditEvent
from ...trust.policy import check_policy
from ...core.events import publish
import uuid, datetime

router = APIRouter(prefix="/carts", tags=["cart"])

@router.post("")
def create_cart(payload: dict, db: Session = Depends(get_db)):
    cart = Cart(merchant_id=payload.get("merchant_id","m_demo"), customer_id=payload.get("customer_id"))
    db.add(cart); db.commit(); db.refresh(cart)
    publish("cart.created", {"cart_id": cart.id, "merchant_id": cart.merchant_id})
    return cart

@router.get("/{cart_id}")
def get_cart(cart_id: str, db: Session = Depends(get_db)):
    cart = db.query(Cart).filter(Cart.id==cart_id).first()
    if not cart: return {"error":"cart not found"}
    items = db.query(CartItem).filter(CartItem.cart_id==cart_id).all()
    detailed=[]
    for it in items:
        prod = db.query(Product).filter(Product.id==it.product_id).first()
        detailed.append({"item": it, "product": prod})
    return {"cart": cart, "items": detailed, "total": cart.total}

@router.post("/{cart_id}/items")
def add_item(cart_id: str, payload: dict, db: Session = Depends(get_db), idempotency_key: str = Header(None, alias="Idempotency-Key")):
    cart = db.query(Cart).filter(Cart.id==cart_id).first()
    if not cart: return {"error":"cart not found"}
    if cart.status != "active": return {"error": f"cart {cart.status}, cannot add items"}
    product = db.query(Product).filter(Product.id==payload["product_id"]).first()
    if not product: return {"error":"product not found"}
    qty = int(payload.get("quantity",1))
    if product.stock < qty: return {"error":"insufficient stock"}
    line_total = product.price * qty
    # policy check LOW_RISK_WRITE
    pol = check_policy(db, cart.merchant_id, "add_item", amount=cart.total+line_total)
    if not pol["allowed"]:
        # audit blocked
        ae = AuditEvent(merchant_id=cart.merchant_id, action="add_item", amount=line_total, policy_result=pol["decision"], risk_score=pol["risk"], authorization="blocked", result="blocked", reason=pol["reason"], payload={"cart_id":cart_id, "product_id": product.id})
        db.add(ae); db.commit()
        return {"error": pol["reason"], "decision": pol["decision"], "requires_approval": pol["requires_approval"]}

    # idempotency simple: if header present check existing item with same product in last add
    existing = db.query(CartItem).filter(CartItem.cart_id==cart_id, CartItem.product_id==product.id).first()
    if existing:
        existing.quantity += qty
        existing.line_total += line_total
    else:
        ci = CartItem(cart_id=cart_id, product_id=product.id, quantity=qty, unit_price=product.price, line_total=line_total)
        db.add(ci)
    cart.total = (cart.total or 0) + line_total
    # audit
    ae = AuditEvent(merchant_id=cart.merchant_id, action="add_item", amount=line_total, policy_result="approved", risk_score=pol["risk"], authorization="approved", result="success", reason=pol["reason"], payload={"cart_id":cart_id, "product_id": product.id, "qty": qty})
    db.add(ae); db.commit()
    publish("cart.item_added", {"cart_id": cart_id, "product_id": product.id, "qty": qty})
    # return updated cart
    db.refresh(cart)
    return {"cart_id": cart_id, "total": cart.total, "added": product.name, "policy": pol}

@router.delete("/{cart_id}/items/{item_id}")
def remove_item(cart_id: str, item_id: str, db: Session = Depends(get_db)):
    it = db.query(CartItem).filter(CartItem.id==item_id, CartItem.cart_id==cart_id).first()
    if not it: return {"error":"item not found"}
    cart = db.query(Cart).filter(Cart.id==cart_id).first()
    cart.total -= it.line_total
    db.delete(it); db.commit()
    publish("cart.item_removed", {"cart_id": cart_id, "item_id": item_id})
    return {"ok": True, "total": cart.total}
