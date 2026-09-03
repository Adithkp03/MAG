from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from ...core.database import get_db
from ...models.entities import Product
from ...services.catalog import search_products

router = APIRouter(prefix="/ucp", tags=["ucp"])

@router.get("/discover")
def discover(db: Session = Depends(get_db)):
    return {"merchant_id":"m_demo","name":"Demo Merchant","capabilities":["catalog","checkout","payment"], "profile":"/.well-known/ucp"}

@router.get("/catalog")
def catalog(q: str="", category: str="", max_price: int=None, db: Session = Depends(get_db)):
    return search_products(db, "m_demo", q, category, max_price)

@router.post("/checkout")
async def ucp_checkout(payload: dict, db: Session = Depends(get_db)):
    # adapter: translate UCP checkout to internal checkout
    from ...models.entities import Cart, Checkout, Order, AuditEvent, CartItem
    from ...trust.policy import check_policy
    from ...core.events import publish
    import uuid
    items = payload.get("items", [])
    cart = Cart(merchant_id="m_demo", customer_id=payload.get("customer_id","cust_demo"))
    db.add(cart); db.commit(); db.refresh(cart)
    total=0
    for it in items:
        prod = db.query(Product).filter(Product.id==it.get("product_id")).first()
        if prod:
            ci=CartItem(cart_id=cart.id, product_id=prod.id, quantity=it.get("quantity",1), unit_price=prod.price, line_total=prod.price*it.get("quantity",1))
            db.add(ci); total+=ci.line_total
    cart.total=total; db.commit()
    # reuse internal checkout logic
    from ..routes.checkout import create_checkout
    # mimic policy check
    return {"cart_id": cart.id, "total": total, "note":"use POST /api/v1/checkout with cart_id for full flow", "ucp": True}
