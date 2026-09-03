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

SYSTEM_PROMPT = """You are Commerce Agent. You MUST use tools to act.

Workflow:
1. search_products to find items (q=keywords, max_price works in INR or paise)
2. create_cart with merchant_id=m_demo
3. add_to_cart for each chosen product using returned cart_id
4. get_cart to verify total
5. request_checkout if user wants to buy and within policy
6. If blocked, explain limit and ask for approval.

Rules: Never invent prices or ids. Always create cart before adding. After search, pick best match and proceed to cart without extra searches. Explain why recommend: affinity, inventory, uplift."""

TOOLS_SCHEMA = [
    {"type":"function","function":{"name":"search_products","description":"Search catalog","parameters":{"type":"object","properties":{"q":{"type":"string"},"category":{"type":"string"},"max_price":{"type":"integer"}},"required":[]}}},
    {"type":"function","function":{"name":"get_product","description":"Get product by id","parameters":{"type":"object","properties":{"product_id":{"type":"string"}},"required":["product_id"]}}},
    {"type":"function","function":{"name":"create_cart","description":"Create cart","parameters":{"type":"object","properties":{"merchant_id":{"type":"string"},"customer_id":{"type":"string"}},"required":[]}}},
    {"type":"function","function":{"name":"add_to_cart","description":"Add item to cart","parameters":{"type":"object","properties":{"cart_id":{"type":"string"},"product_id":{"type":"string"},"quantity":{"type":"integer"}},"required":["cart_id","product_id"]}}},
    {"type":"function","function":{"name":"get_cart","description":"Get cart","parameters":{"type":"object","properties":{"cart_id":{"type":"string"}},"required":["cart_id"]}}},
    {"type":"function","function":{"name":"check_inventory","description":"Check inventory for product","parameters":{"type":"object","properties":{"product_id":{"type":"string"}},"required":["product_id"]}}},
    {"type":"function","function":{"name":"request_checkout","description":"Request checkout for cart","parameters":{"type":"object","properties":{"cart_id":{"type":"string"}},"required":["cart_id"]}}},
]
