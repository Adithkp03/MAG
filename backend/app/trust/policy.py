from sqlalchemy.orm import Session
from ..models.entities import Policy
import uuid

DEFAULT_POLICY = {
    "max_transaction": 500000,
    "max_discount": 15,
    "auto_approve": True,
    "allowed_actions": ["create_cart", "add_item", "remove_item", "create_payment", "recommend_product", "search_products"],
    "allowed_categories": []
}

POLICY_VERSION = 3


def get_policy(db: Session, merchant_id: str) -> Policy:
    pol = db.query(Policy).filter(Policy.merchant_id == merchant_id).first()
    if not pol:
        pol = Policy(merchant_id=merchant_id, **DEFAULT_POLICY)
        db.add(pol); db.commit(); db.refresh(pol)
    # legacy rows may carry NULL numerics/actions (raw inserts predate defaults)
    for k, v in {"allowed_actions": DEFAULT_POLICY["allowed_actions"],
                 "max_transaction": 500000, "max_discount": 15}.items():
        if getattr(pol, k, None) is None:
            setattr(pol, k, v)
    return pol


def update_policy(db: Session, merchant_id: str, updates: dict) -> Policy:
    pol = get_policy(db, merchant_id)
    for k, v in updates.items():
        if v is not None and hasattr(pol, k):
            setattr(pol, k, v)
    pol.version = (pol.version or 1) + 1
    db.commit(); db.refresh(pol)
    return pol


def _result(decision, reason, risk, requires_approval, pol, violated=None, limits=None):
    return {
        "allowed": decision == "approved",
        "decision": decision,  # approved | escalated | blocked
        "reason": reason,
        "risk": risk,
        "requires_approval": requires_approval,
        "policy_version": pol.version,
        "violated_rule": violated,
        "limits": limits or {
            "max_transaction": pol.max_transaction,
            "max_discount": pol.max_discount,
            "max_campaign_budget": getattr(pol, "max_campaign_budget", 1000000),
            "min_margin_pct": getattr(pol, "min_margin_pct", 10),
        },
    }


def check_policy(db: Session, merchant_id: str, action: str, amount: int = 0, discount: int = 0, category: str = ""):
    """Tiered policy: APPROVED (within limits) / ESCALATED (over auto threshold,
    needs human approval) / BLOCKED (hard constraint violation)."""
    pol = get_policy(db, merchant_id)
    if action not in (pol.allowed_actions or []):
        return _result("blocked", f"Action {action} not allowed", 1.0, False, pol, violated="allowed_actions")
    auto_limit = getattr(pol, "auto_approve_limit", None) or pol.max_transaction
    hard_limit = getattr(pol, "hard_block_limit", None) or pol.max_transaction * 2
    if amount and amount > hard_limit:
        return _result("blocked", f"Amount {amount/100:.0f} exceeds hard limit {hard_limit/100:.0f}", 0.95, False, pol, violated="hard_block_limit")
    if amount and amount > auto_limit:
        return _result("escalated", f"Amount {amount/100:.0f} exceeds auto-approve {auto_limit/100:.0f} — requires approval", 0.7, True, pol, violated="auto_approve_limit")
    if discount and discount > pol.max_discount:
        return _result("blocked", f"Discount {discount}% exceeds max {pol.max_discount}%", 0.6, False, pol, violated="max_discount")
    if pol.allowed_categories and category and category not in pol.allowed_categories:
        return _result("blocked", f"Category {category} not allowed", 0.5, False, pol, violated="allowed_categories")
    risk = 0.1 + (0.2 if amount and amount > auto_limit * 0.6 else 0)
    return _result("approved", "Policy check passed", risk, False, pol)


def check_campaign_policy(db: Session, merchant_id: str, discount: int, budget: int,
                          expected_margin_pct: float | None, action_type: str = "execute_campaign"):
    """Server-side enforcement of merchant objective constraints:
    max discount, campaign budget, minimum margin. Returns tiered decision."""
    from ..models.entities import MerchantObjective
    pol = get_policy(db, merchant_id)
    obj = db.query(MerchantObjective).filter(MerchantObjective.merchant_id == merchant_id).first()
    max_disc = obj.max_discount if obj and obj.max_discount is not None else pol.max_discount
    max_budget = obj.max_campaign_budget if obj and obj.max_campaign_budget is not None else getattr(pol, "max_campaign_budget", 1000000)
    min_margin = obj.min_margin_pct if obj and obj.min_margin_pct is not None else getattr(pol, "min_margin_pct", 10)
    risk_tol = (obj.risk_tolerance if obj else "medium")
    if discount and discount > max_disc:
        return _result("blocked", f"Discount {discount}% exceeds merchant max {max_disc}%", 0.6, False, pol, violated="max_discount")
    if budget and budget > max_budget:
        # over budget but within 2x -> escalate; beyond -> block
        if budget <= max_budget * 2:
            return _result("escalated", f"Budget {budget/100:.0f} exceeds max {max_budget/100:.0f} — requires approval", 0.7, True, pol, violated="max_campaign_budget")
        return _result("blocked", f"Budget {budget/100:.0f} exceeds hard cap {max_budget*2/100:.0f}", 0.9, False, pol, violated="max_campaign_budget")
    if expected_margin_pct is not None and expected_margin_pct < min_margin:
        return _result("escalated", f"Expected margin {expected_margin_pct:.1f}% below minimum {min_margin}%", 0.75, True, pol, violated="min_margin_pct")
    # risk tolerance gates high discount / high budget combos
    if risk_tol == "low" and ((discount or 0) >= 10 or (budget and budget > max_budget * 0.5)):
        return _result("escalated", "Low risk tolerance: human approval required for this spend/discount", 0.6, True, pol, violated="risk_tolerance")
    return _result("approved", "Campaign policy check passed", 0.15, False, pol)
