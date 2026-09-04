
import httpx, hmac, hashlib, base64, os
from ..core.config import settings

RAZORPAY_BASE = "https://api.razorpay.com/v1"

def has_keys():
    return bool(settings.razorpay_key_id and settings.razorpay_key_secret and "xxx" not in settings.razorpay_key_id)

async def create_razorpay_order(amount_paise: int, receipt: str, notes: dict = None):
    """Create Razorpay Order (test mode). Amount in paise. Returns dict or mock."""
    if not has_keys():
        return {"id": f"order_mock_{receipt[:8]}", "amount": amount_paise, "currency": "INR", "receipt": receipt, "status": "created", "mock": True}
    auth = (settings.razorpay_key_id, settings.razorpay_key_secret)
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(f"{RAZORPAY_BASE}/orders", auth=auth, json={"amount": amount_paise, "currency": "INR", "receipt": receipt, "notes": notes or {}})
        r.raise_for_status()
        return r.json()

async def fetch_payment(payment_id: str):
    if not has_keys() or payment_id.startswith("pay_mock") or payment_id.startswith("pay_test"):
        return {"id": payment_id, "status": "captured", "mock": True}
    auth = (settings.razorpay_key_id, settings.razorpay_key_secret)
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{RAZORPAY_BASE}/payments/{payment_id}", auth=auth)
        r.raise_for_status()
        return r.json()

def verify_webhook_signature(body: bytes, signature: str) -> bool:
    secret = settings.razorpay_webhook_secret or ""
    if not secret or "xxx" in secret:
        # Fix #9: in production missing secret = fail (was True -> bypass). In dev, allow but warn
        if settings.env == "production":
            return False
        # dev: allow missing sig when no secret configured
        return True if not signature else True
    if not signature:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)

def verify_payment_signature(order_id: str, payment_id: str, signature: str) -> bool:
    secret = settings.razorpay_key_secret or ""
    if not secret: return False
    msg = f"{order_id}|{payment_id}"
    expected = hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
