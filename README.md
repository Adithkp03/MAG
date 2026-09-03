
# Merchant Autonomous Growth & Commerce Agent

7-layer platform: AI Growth Mode + AI Buyer Mode -> Shared Trust Layer -> Razorpay

Phase 0 frozen: commerce is source of truth, AI proposes, policy authorizes, audit records.

## Quick Start

### With Docker (Postgres + Redis)
```
docker compose up -d
pip install -r backend/requirements.txt
uvicorn backend.app.main:app --reload --port 8000
```

### Without Docker (SQLite dev fallback)
```
pip install -r backend/requirements.txt
uvicorn backend.app.main:app --reload --port 8000
# auto-creates sqlite dev.db and seeds demo data
```

API: http://localhost:8000/docs
Health: http://localhost:8000/health

Env: copy backend/.env.example -> backend/.env and set GROQ_API_KEY + RAZORPAY_KEY_ID/SECRET when ready

Phases: 0 docs -> 1 commerce -> 2 razorpay -> 3 trust -> 4 commerce agent (Groq) -> 5 growth -> 6 UCP -> 7 hardening
