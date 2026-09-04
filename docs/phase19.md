# Phase 19 — API / Security Tenant Isolation
Strict: require_merchant_auth checks X-Merchant-Id + X-API-Key (MERCHANT_AUTH_STRICT=1), every query filters by merchant_id. approved_by derived only from X-Approved-By header (campaigns approve). Tool gateway rejects merchant mismatch. No m_demo fallback in growth_runtime/groq — authenticated_merchant_id required.

Files: backend/app/core/auth.py, backend/app/api/routes/campaigns.py:approve, backend/app/agent/growth_runtime.py, backend/app/agent/groq_client.py
