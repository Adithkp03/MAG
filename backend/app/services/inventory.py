
from sqlalchemy.orm import Session
from sqlalchemy import text as sql
def reserve_stock(db: Session, product_id: str, qty: int=1):
    """P2-25 reserve inventory: available = stock - reserved"""
    row=db.execute(sql("SELECT stock, reserved FROM products WHERE id=:pid"), {"pid": product_id}).mappings().first()
    if not row: return {"ok": False, "reason": "product not found"}
    available=(row["stock"] or 0) - (row["reserved"] or 0)
    if available < qty:
        return {"ok": False, "reason": f"insufficient available {available} < {qty}"}
    db.execute(sql("UPDATE products SET reserved = COALESCE(reserved,0)+:qty WHERE id=:pid"), {"qty": qty, "pid": product_id})
    db.commit()
    return {"ok": True, "available_after": available-qty}
def release_stock(db: Session, product_id: str, qty: int=1):
    db.execute(sql("UPDATE products SET reserved = GREATEST(0, COALESCE(reserved,0)-:qty) WHERE id=:pid"), {"qty": qty, "pid": product_id})
    db.commit()
    return {"ok": True}
def commit_stock(db: Session, product_id: str, qty: int=1):
    """On order paid: stock--, reserved--"""
    db.execute(sql("UPDATE products SET stock = GREATEST(0, stock - :qty), reserved = GREATEST(0, COALESCE(reserved,0)-:qty) WHERE id=:pid"), {"qty": qty, "pid": product_id})
    db.commit()
    return {"ok": True}
