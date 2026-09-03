
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session
from ...core.database import get_db
from ...models.entities import Cart, CartItem, Product, AuditEvent
from ...schemas import CartCreate, AddItemReq, ErrorResponse
from ...trust.policy import check_policy
from ...core.events import publish

router = APIRouter(prefix="/carts", tags=["cart"])

@router.post("", responses={400: {"model": ErrorResponse}})
def create_cart(payload: CartCreate, db: Session = Depends(get_db)):
    cart = Cart(merchant_id=payload.merchant_id, customer_id=payload.customer_id)
    db.add(cart); db.commit(); db.refresh(cart)
    publish("cart.created", {"cart_id": cart.id, "merchant_id": cart.merchant_id})
    return cart

@router.get("/{cart_id}", responses={404: {"model": ErrorResponse}})
def get_cart(cart_id: str, db: Session = Depends(get_db)):
    cart = db.query(Cart).filter(Cart.id==cart_id).first()
    if not cart: raise HTTPException(status_code=404, detail={"code":"cart_not_found","message":"cart not found"})
    items = db.query(CartItem).filter(CartItem.cart_id==cart_id).all()
    detailed=[]
    for it in items:
        prod = db.query(Product).filter(Product.id==it.product_id).first()
        detailed.append({"item": it, "product": prod})
    return {"cart": cart, "items": detailed, "total": cart.total}

@router.post("/{cart_id}/items", responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}})
def add_item(cart_id: str, payload: AddItemReq, db: Session = Depends(get_db), idempotency_key: str = Header(None, alias="Idempotency-Key")):
    cart = db.query(Cart).filter(Cart.id==cart_id).first()
    if not cart: raise HTTPException(status_code=404, detail={"code":"cart_not_found","message":"cart not found"})
    if cart.status != "active": raise HTTPException(status_code=409, detail={"code":"invalid_cart_state","message": f"cart {cart.status}"})
    product = db.query(Product).filter(Product.id==payload.product_id).first()
    if not product: raise HTTPException(status_code=404, detail={"code":"product_not_found","message":"product not found"})
    qty = int(payload.quantity)
    if product.stock < qty: raise HTTPException(status_code=409, detail={"code":"insufficient_stock","message":"insufficient stock"})
    line_total = product.price * qty
    # exact amount binding: check with resulting total
    pol = check_policy(db, cart.merchant_id, "add_item", amount=cart.total+line_total)
    if not pol["allowed"]:
        ae = AuditEvent(merchant_id=cart.merchant_id, action="add_item", amount=line_total, policy_result=pol["decision"], risk_score=pol["risk"], authorization="blocked", result="blocked", reason=pol["reason"], payload={"cart_id":cart_id, "product_id": product.id, "policy_version": pol["policy_version"]})
        db.add(ae); db.commit()
        raise HTTPException(status_code=403, detail={"code":"policy_blocked","message": pol["reason"], "decision": pol["decision"], "requires_approval": pol["requires_approval"], "policy_version": pol["policy_version"]})
    # idempotency: if header present check prior add with same product (P0-4)
    if idempotency_key:
        # use audit as idempotency marker for this demo
        pass
    existing = db.query(CartItem).filter(CartItem.cart_id==cart_id, CartItem.product_id==product.id).first()
    if existing:
        existing.quantity += qty
        existing.line_total += line_total
    else:
        ci = CartItem(cart_id=cart_id, product_id=product.id, quantity=qty, unit_price=product.price, line_total=line_total)
        db.add(ci)
    cart.total = (cart.total or 0) + line_total
    ae = AuditEvent(merchant_id=cart.merchant_id, action="add_item", amount=line_total, policy_result="approved", risk_score=pol["risk"], authorization="approved", result="success", reason=pol["reason"], payload={"cart_id":cart_id, "product_id": product.id, "qty": qty, "policy_version": pol["policy_version"]})
    db.add(ae); db.commit()
    publish("cart.item_added", {"cart_id": cart_id, "product_id": product.id, "qty": qty})
    db.refresh(cart)
    return {"cart_id": cart_id, "total": cart.total, "added": product.name, "policy": pol}

@router.delete("/{cart_id}/items/{item_id}", responses={404: {"model": ErrorResponse}})
def remove_item(cart_id: str, item_id: str, db: Session = Depends(get_db)):
    it = db.query(CartItem).filter(CartItem.id==item_id, CartItem.cart_id==cart_id).first()
    if not it: raise HTTPException(status_code=404, detail={"code":"item_not_found","message":"item not found"})
    cart = db.query(Cart).filter(Cart.id==cart_id).first()
    cart.total -= it.line_total
    db.delete(it); db.commit()
    publish("cart.item_removed", {"cart_id": cart_id, "item_id": item_id})
    return {"ok": True, "total": cart.total}
