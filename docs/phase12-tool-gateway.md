# Tool Gateway -> Policy -> Canonical (Phase 12)

Reasoning (LLM) never mutates financial state directly. All tool calls flow:

LLM --tool_call--> Tool Gateway (auth + schema validation + tenant isolation)
        --check--> Policy Engine (limits, approval tiers, objectives)
        --call--> Canonical Service (commerce/campaign/inventory - single source of truth, audit logged)

Example: Growth Agent propose_campaign -> growth_gateway validates merchant_id -> plan_action checks Policy.max_discount/max_campaign_budget -> creates Campaign PROPOSED (not ACTIVE). Execution requires separate authorized /campaigns/{id}/execute which re-checks Policy.

Files:
- backend/app/agent/runtime.py:tool_gateway (commerce) — validates merchant_id mismatch, calls commerce services via Policy
- backend/app/agent/growth_runtime.py:growth_gateway (growth) — 14 tools, all read-only except propose_campaign which is gated
- backend/app/trust/policy.py:check_policy — enforces auto_approve/approval/hard_block tiers
- backend/app/services/autonomous_growth.py:plan_action/execute_campaign — canonical campaign lifecycle
- backend/app/services/commerce.py — canonical cart/checkout/order (audit via AuditEvent)

Enforcement verified: growth_gateway returns error on unknown merchant, runtime tool_gateway rejects merchant_id mismatch, propose_campaign never creates captured payment.
