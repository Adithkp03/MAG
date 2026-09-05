import requests
import json
import time
import sys
import hmac
import hashlib
import os
from dotenv import load_dotenv

BASE_URL = "http://127.0.0.1:8000/api/v1"
HEADERS = {
    "X-Merchant-Id": "m_demo",
    "X-API-Key": "demo_key_123",
    "Content-Type": "application/json"
}

def test_flow():
    print("Starting MAG Shop end-to-end test...")

    # 1. Product listing
    print("\n1. Testing Product Catalog...")
    res = requests.get(f"{BASE_URL}/ucp/catalog?merchant_id=m_demo")
    assert res.status_code == 200
    catalog = res.json()
    assert len(catalog["products"]) > 0
    print(f"[OK] Found {len(catalog['products'])} products.")

    # 2. Product search
    print("\n2. Testing Product Search...")
    res = requests.get(f"{BASE_URL}/ucp/catalog?merchant_id=m_demo&q=running&max_price=500000")
    assert res.status_code == 200
    search_results = res.json()
    assert len(search_results["products"]) > 0
    product = search_results["products"][0]
    print(f"[OK] Found: {product['name']} (INR {product['price_inr']})")

    # 3. Create Cart
    print("\n3. Testing Cart Creation...")
    res = requests.post(f"{BASE_URL}/carts", headers=HEADERS, json={"customer_id": "cust_test"})
    assert res.status_code == 200
    cart_id = res.json()["id"]
    print(f"[OK] Cart created: {cart_id}")

    # 4. Add to Cart & Inventory check
    print("\n4. Testing Add to Cart...")
    res = requests.post(f"{BASE_URL}/carts/{cart_id}/items", headers=HEADERS, json={
        "product_id": product["id"],
        "quantity": 1
    })
    assert res.status_code == 200
    print(f"[OK] Added item to cart. Total: INR {res.json()['total'] / 100}")

    # 5. Checkout
    print("\n5. Testing Checkout Creation...")
    res = requests.post(f"{BASE_URL}/checkout", headers=HEADERS, json={"cart_id": cart_id})
    assert res.status_code == 200
    checkout_id = res.json()["checkout"]["id"]
    print(f"[OK] Checkout created: {checkout_id}")

    # 6. Complete Checkout (creates Razorpay order / Mock)
    print("\n6. Testing Checkout Completion (Payment setup)...")
    res = requests.post(f"{BASE_URL}/checkout/{checkout_id}/complete", headers=HEADERS, json={})
    assert res.status_code == 200
    comp_data = res.json()
    assert "razorpay_order" in comp_data
    rzp_order_id = comp_data["razorpay_order"]["id"]
    payment_id = comp_data["payment"]["id"]
    order_id = comp_data["order"]["id"]
    print(f"[OK] Payment setup complete. Razorpay Order: {rzp_order_id}")
    
    # Simulate webhook
    print("\n7. Simulating successful Razorpay webhook...")
    webhook_payload = {
        "event_id": f"evt_test_{int(time.time())}",
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": f"pay_test_{int(time.time())}",
                    "order_id": rzp_order_id,
                    "status": "captured"
                }
            }
        }
    }
    
    # Compute signature
    load_dotenv("backend/.env")
    secret = os.getenv("RAZORPAY_WEBHOOK_SECRET", "")
    body = json.dumps(webhook_payload, separators=(',', ':')).encode('utf-8')
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    
    # Webhook does not use merchant auth, it relies on signature or dev mode fallback
    res = requests.post(f"{BASE_URL}/webhooks/razorpay", data=body, headers={"Content-Type": "application/json", "X-Razorpay-Signature": signature})
    # The webhook might return 200 or 202 depending on exact state, but should not be 500
    if res.status_code not in (200, 202):
        print(f"Webhook simulation unexpected status: {res.status_code} - {res.text}")

    # 8. Order Status check
    print("\n8. Checking Order Status...")
    time.sleep(1) # wait for async outbox/processing
    res = requests.get(f"{BASE_URL}/orders/{order_id}", headers=HEADERS)
    assert res.status_code == 200
    final_order = res.json()
    assert final_order["status"] == "paid"
    print(f"[OK] Order status is PAID.")

    # 9. Dashboard health
    print("\n9. Testing Dashboard Health...")
    res = requests.get("http://127.0.0.1:8000/health")
    assert res.status_code == 200
    print(f"[OK] Backend health OK: {res.json()['status']}")

    print("\n[SUCCESS] All MAG Shop end-to-end tests passed successfully!")

if __name__ == "__main__":
    try:
        test_flow()
    except AssertionError as e:
        print(f"[ERROR] Test failed!")
        sys.exit(1)
    except Exception as e:
        print(f"[ERROR] Error: {e}")
        sys.exit(1)
