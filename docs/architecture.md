
# Merchant Autonomous Growth & Commerce Agent — Architecture (Phase 0)

## 1. Product Definition (Frozen)

An AI merchant agent that can discover products, recommend upsells, create a cart, execute a bounded checkout through Razorpay test mode, and maintain a complete audit trail.

What the agent CAN do (v1):
- search_products, get_product, check_inventory
- create_cart, add_to_cart, remove_from_cart, get_cart
- recommend upsell/cross-sell with explainability
- propose checkout/payment
- All financial actions gated by Policy Engine + Authorization

What the agent CANNOT do (v1):
- Directly call Razorpay
- Bypass policy limits
- Invent cart totals (commerce core is source of truth)
- Direct DB writes — only via Tool Gateway

## 2. Seven Layer Architecture

```
Experience Layer:  Merchant Dashboard | Shopper/AI Chat | Agent APIs | Webhooks
Agent Layer:       Orchestrator -> Growth Agent | Commerce Agent | Campaign Agent -> Tool Gateway
Intelligence:      Customer/Product intelligence, ranking, recommendations, forecasting
Trust & Control:   Policy Engine | Authorization | Risk Engine | Idempotency | Approvals
Commerce:          Catalog | Cart | Checkout | Order | Payment | Promotion + Transaction Gateway
Data & Event:      PostgreSQL | Redis | Event Bus (Redis Streams) | Vector (pgvector) | Audit Ledger
Integrations:      Razorpay APIs/Webhooks | UCP Adapter | AP2 | Groq LLM
```

## 3. Core Principle

LLM -> Tool Gateway -> Policy Engine -> Authorization -> Commerce Core -> Razorpay -> Webhook -> Event Bus -> Order -> Audit

- AI proposes
- Policy approves/bounds
- Deterministic services execute
- Razorpay confirms
- Audit records everything

## 4. State Ownership

| Entity | Owner Service | Truth |
|--------|--------------|-------|
| Product/Catalog | Catalog Service | DB |
| Cart/CartItem | Cart Service | DB (authoritative total) |
| Checkout | Checkout Service | DB State Machine |
| Order/Payment | Order/Payment Service | DB + Razorpay |
| Policy | Policy Engine | DB |
| AuditEvent | Audit Service | Append-only ledger |

## 5. Transaction State Machine

CREATED -> VALIDATED -> AUTHORIZED -> PAYMENT_PENDING -> CAPTURED/FAILED -> ORDERED/RECOVERY

## 6. Tool Gateway Rule

LLM never calls arbitrary APIs. Every tool call validated: allowed_action?, within_limits?, idempotent?, requires_approval?

## 7. Repo Structure

```
merchant-autonomous-agent/
  docs/           Phase 0 deliverables
  backend/        FastAPI + SQLAlchemy + LangGraph + Groq
  frontend/       Next.js + Tailwind + shadcn/ui
  docker-compose.yml  Postgres + Redis
```
