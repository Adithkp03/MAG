
# DB Schema (PostgreSQL + pgvector, SQLite-compatible for dev)

## Entities

Merchant(id PK, name, email, created_at)
Customer(id PK, merchant_id FK, name, email, phone, metadata JSON)
Product(id PK, merchant_id FK, name, description, price INT paise, category, image_url, embedding vector(768) nullable, created_at)
Inventory(id PK, product_id FK unique, stock INT, reserved INT, updated_at)
Cart(id PK, merchant_id FK, customer_id FK, status: active|checked_out|abandoned, total INT, created_at, updated_at)
CartItem(id PK, cart_id FK, product_id FK, quantity INT, unit_price INT, line_total INT)
Checkout(id PK, cart_id FK unique, merchant_id FK, customer_id FK, status: created|validated|authorized|payment_pending|captured|failed|cancelled, total INT, idempotency_key UNIQUE, created_at)
Order(id PK, checkout_id FK unique, merchant_id FK, customer_id FK, status: pending|paid|failed|cancelled, total INT, payment_id FK nullable, created_at)
Payment(id PK, order_id FK, merchant_id FK, amount INT, status: created|pending|captured|failed, razorpay_order_id TEXT nullable, razorpay_payment_id TEXT nullable, idempotency_key UNIQUE, created_at)
Policy(id PK, merchant_id FK unique, max_transaction INT default 500000, max_discount INT default 15, auto_approve BOOL, allowed_actions JSON, allowed_categories JSON)
Authorization(id PK, merchant_id FK, action TEXT, amount INT, decision: approved|blocked|escalated, reason TEXT, created_at)
AgentSession(id PK, merchant_id FK, customer_id FK, status, created_at)
AgentAction(id PK, session_id FK, tool TEXT, input JSON, output JSON, policy_result TEXT, created_at)
AuditEvent(id PK, event_id TEXT UNIQUE, merchant_id FK, agent_id TEXT, action TEXT, reason TEXT, amount INT nullable, policy_result TEXT, risk_score FLOAT, authorization TEXT, result TEXT, timestamp, payload JSON)

## Indexes
- products(merchant_id, category), products(price)
- carts(merchant_id, customer_id, status)
- audit_events(merchant_id, timestamp)

## Notes
- Amounts stored as integer paise (₹1 = 100)
- State machines enforced in service layer, not just DB check constraints
- Vector column: pgvector on Postgres, nullable/ignored on SQLite dev
