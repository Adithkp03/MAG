
from sqlalchemy.orm import Session
from ..models.entities import Product
from sqlalchemy import or_
def search_products(db: Session, merchant_id: str = None, q: str = "", category: str = "", max_price: int = None):
    query = db.query(Product)
    if merchant_id: query = query.filter(Product.merchant_id==merchant_id)
    # combine q and category as keyword search (agent often sends category as free text)
    keywords = " ".join([k for k in [q, category] if k]).strip()
    if keywords:
        tokens=keywords.split()
        conds=[]
        for token in tokens:
            conds.append(Product.name.ilike(f"%{token}%"))
            conds.append(Product.description.ilike(f"%{token}%"))
            conds.append(Product.category.ilike(f"%{token}%"))
        query = query.filter(or_(*conds))
    if max_price:
        if max_price < 10000:
            max_price = max_price * 100
        query = query.filter(Product.price <= max_price)
    return query.limit(50).all()
