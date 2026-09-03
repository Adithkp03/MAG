
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session
from ...core.database import get_db
from ...core.auth import require_merchant_auth
from ...models.entities import Cart, CartItem, Product
from ...schemas import CartCreate, AddItemReq, ErrorResponse
from ...services.commerce import create_cart_svc, add_item_svc, get_cart_svc

router = APIRouter(prefix="/carts", tags=["cart"])

@router.post("", responses={400: {"model": ErrorResponse}})
def create_cart(payload: CartCreate, db: Session = Depends(get_db), merchant=Depends(require_merchant_auth)):
    return create_cart_svc(db, payload.merchant_id, payload.customer_id)

@router.get("/{cart_id}", responses={404: {"model": ErrorResponse}})
def get_cart(cart_id: str, db: Session = Depends(get_db), merchant=Depends(require_merchant_auth)):
    return get_cart_svc(db, cart_id)

@router.post("/{cart_id}/items", responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}})
def add_item(cart_id: str, payload: AddItemReq, db: Session = Depends(get_db), merchant=Depends(require_merchant_auth), idempotency_key: str = Header(None, alias="Idempotency-Key")):
    return add_item_svc(db, cart_id, payload.product_id, int(payload.quantity), idempotency_key)

@router.delete("/{cart_id}/items/{item_id}", responses={404: {"model": ErrorResponse}})
def remove_item(cart_id: str, item_id: str, db: Session = Depends(get_db), merchant=Depends(require_merchant_auth)):
    from ...core.events import publish
    it = db.query(CartItem).filter(CartItem.id==item_id, CartItem.cart_id==cart_id).first()
    if not it: raise HTTPException(status_code=404, detail={"code":"item_not_found","message":"item not found"})
    cart = db.query(Cart).filter(Cart.id==cart_id).first()
    cart.total -= it.line_total
    db.delete(it); db.commit()
    publish("cart.item_removed", {"cart_id": cart_id, "item_id": item_id})
    return {"ok": True, "total": cart.total}
