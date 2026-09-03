
from sqlalchemy.orm import Session
from ..models.entities import Policy
import uuid

DEFAULT_POLICY = {
    "max_transaction": 500000,
    "max_discount": 15,
    "auto_approve": True,
    "allowed_actions": ["create_cart","add_item","remove_item","create_payment","recommend_product","search_products"],
    "allowed_categories": []
}

def get_policy(db: Session, merchant_id: str) -> Policy:
    pol = db.query(Policy).filter(Policy.merchant_id==merchant_id).first()
    if not pol:
        pol = Policy(merchant_id=merchant_id, **DEFAULT_POLICY)
        db.add(pol); db.commit(); db.refresh(pol)
    return pol

def update_policy(db: Session, merchant_id: str, updates: dict) -> Policy:
    pol = get_policy(db, merchant_id)
    for k,v in updates.items():
        if v is not None and hasattr(pol, k):
            setattr(pol, k, v)
    pol.version = (pol.version or 1) + 1  # P0-11 version bump
    db.commit(); db.refresh(pol)
    return pol

def check_policy(db: Session, merchant_id: str, action: str, amount: int = 0, discount: int = 0, category: str = ""):
    """Exact action/amount binding P0-12: caller must supply concrete amount, not generic."""
    pol = get_policy(db, merchant_id)
    if action not in (pol.allowed_actions or []):
        return {"allowed": False, "decision":"blocked", "reason": f"Action {action} not allowed", "risk": 1.0, "requires_approval": True, "policy_version": pol.version}
    if amount and amount > pol.max_transaction:
        if amount <= pol.max_transaction * 2:  # configurable threshold P0-8 (2x)
            return {"allowed": False, "decision":"escalated", "reason": f"Amount {amount/100:.0f} exceeds limit {pol.max_transaction/100:.0f} — requires approval", "risk": 0.7, "requires_approval": True, "policy_version": pol.version}
        else:
            return {"allowed": False, "decision":"blocked", "reason": f"Amount exceeds hard limit {pol.max_transaction*2/100:.0f}", "risk": 0.95, "requires_approval": False, "policy_version": pol.version}
    if discount and discount > pol.max_discount:
        return {"allowed": False, "decision":"blocked", "reason": f"Discount {discount}% exceeds max {pol.max_discount}%", "risk": 0.6, "requires_approval": True, "policy_version": pol.version}
    if pol.allowed_categories and category and category not in pol.allowed_categories:
        return {"allowed": False, "decision":"blocked", "reason": f"Category {category} not allowed", "risk": 0.5, "requires_approval": False, "policy_version": pol.version}
    risk = 0.1 + (0.2 if amount > pol.max_transaction*0.6 else 0)
    return {"allowed": True, "decision":"approved", "reason":"Policy check passed", "risk": risk, "requires_approval": False, "policy_version": pol.version}
