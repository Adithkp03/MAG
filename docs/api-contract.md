
# API Contract (Phase 0 — Frozen)

Base: /api/v1

## Catalog
GET /products -> list {id,name,price,category,inventory}
GET /products/{id}
GET /products/search?q=&category=&max_price=
GET /products/{id}/inventory

## Cart
POST /carts {customer_id, merchant_id} -> {cart_id, status}
GET /carts/{id} -> cart + items + total
POST /carts/{id}/items {product_id, quantity}
DELETE /carts/{id}/items/{item_id}

## Checkout
POST /checkout {cart_id} -> {checkout_id, total, status}
GET /checkout/{id}
POST /checkout/{id}/cancel
POST /checkout/{id}/complete -> initiates Payment

## Order
POST /orders {checkout_id} -> order
GET /orders/{id}
GET /orders?merchant_id=&customer_id=

## Payment (Razorpay adapter behind)
POST /payments {order_id, amount, method}
GET /payments/{id}
POST /webhooks/razorpay  (signature verification + dedup)

## Trust
GET /policies/{merchant_id}
PUT /policies/{merchant_id} {max_transaction, max_discount, auto_approve, allowed_actions}
POST /authorizations/check {merchant_id, action, amount} -> {allowed, reason, requires_approval}

## Agent
POST /agent/chat {session_id, message, merchant_id, customer_id} -> {reply, tool_calls, cart, recommendation, audit_id}
GET /agent/sessions/{id}/audit -> timeline
GET /audit?merchant_id=&limit=

## UCP (Phase 6)
GET /.well-known/ucp
POST /ucp/checkout
GET /ucp/checkout/{id}

All money endpoints require: Idempotency-Key header
