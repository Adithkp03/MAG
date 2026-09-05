"""Shop config endpoint — exposes non-secret frontend configuration."""
from fastapi import APIRouter

router = APIRouter(prefix="/shop", tags=["shop"])


@router.get("/config")
def shop_config():
    """Return public-safe config for the buyer storefront.
    Only the Razorpay *public* key_id is exposed — never the secret."""
    from ...core.config import settings
    from ...services.razorpay_adapter import has_keys
    return {
        "razorpay_key_id": settings.razorpay_key_id if has_keys() else None,
        "has_live_keys": has_keys(),
        "merchant_id": "m_demo",
        "currency": "INR",
    }
