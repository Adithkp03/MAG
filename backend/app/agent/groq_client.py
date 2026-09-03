
from ..core.config import settings
def get_groq_client():
    if not settings.groq_api_key or "xxx" in settings.groq_api_key:
        return None
    try:
        from groq import Groq
        return Groq(api_key=settings.groq_api_key)
    except Exception as e:
        print(f"Groq init failed: {e}")
        return None

SYSTEM_PROMPT = """You are Commerce Agent for Merchant Autonomous Growth & Commerce Agent.
You orchestrate commerce via tools only. Never invent prices or bypass policy.
Available tools: search_products(q, category, max_price), get_product(product_id), create_cart(merchant_id), add_to_cart(cart_id, product_id, quantity), get_cart(cart_id), request_checkout(cart_id).
Always explain why you recommend a product (affinity, inventory, expected uplift). If policy blocks, explain limit and ask for human approval.
Keep responses concise and structured. Amounts in paise (100 paise = 1 INR)."""

TOOLS_SCHEMA = [
    {"type":"function","function":{"name":"search_products","description":"Search catalog","parameters":{"type":"object","properties":{"q":{"type":"string"},"category":{"type":"string"},"max_price":{"type":"integer"}},"required":[]}}},
    {"type":"function","function":{"name":"get_product","description":"Get product by id","parameters":{"type":"object","properties":{"product_id":{"type":"string"}},"required":["product_id"]}}},
    {"type":"function","function":{"name":"create_cart","description":"Create cart","parameters":{"type":"object","properties":{"merchant_id":{"type":"string"},"customer_id":{"type":"string"}},"required":[]}}},
    {"type":"function","function":{"name":"add_to_cart","description":"Add item to cart","parameters":{"type":"object","properties":{"cart_id":{"type":"string"},"product_id":{"type":"string"},"quantity":{"type":"integer"}},"required":["cart_id","product_id"]}}},
    {"type":"function","function":{"name":"get_cart","description":"Get cart","parameters":{"type":"object","properties":{"cart_id":{"type":"string"}},"required":["cart_id"]}}},
    {"type":"function","function":{"name":"request_checkout","description":"Request checkout for cart","parameters":{"type":"object","properties":{"cart_id":{"type":"string"}},"required":["cart_id"]}}},
]
