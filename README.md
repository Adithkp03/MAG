# 🚀 Merchant Autonomous Growth & Commerce Agent (MAG)

![Version](https://img.shields.io/badge/version-0.22.0-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115.0-009688?logo=fastapi)
![Next.js](https://img.shields.io/badge/Next.js-14.2.5-000000?logo=next.js)
![License](https://img.shields.io/badge/license-MIT-green)

A 7-layer commerce platform designed to bridge AI-driven autonomous growth strategies for merchants with intelligent purchasing behaviors (AI Buyer Mode). The system establishes a **Shared Trust Layer** for secure, policy-driven autonomous commerce, deeply integrated with **Razorpay** for payment processing and **Groq** for high-speed AI inference.

## ✨ Key Features

- 🧠 **Autonomous Growth Mode:** Automatically detects growth opportunities (cross-selling, churn prevention) by analyzing product velocity, margins, and customer behavior (RFM, CLV).
- 🛒 **AI Buyer Mode:** Intelligent agents capable of executing purchasing strategies.
- 🤝 **Shared Trust Layer:** Authorizes operations through a strictly defined policy layer—AI proposes, policy authorizes, audit records.
- 💳 **Razorpay Integration:** Secure, seamless checkout, payments, and webhook handling.
- 📊 **Merchant Dashboard:** A Next.js 14 based control center tracking real-time KPIs, active campaigns, and customer/product intelligence.
- 🛡️ **Rate Limiting & Tenant Isolation:** Multi-tenant architecture designed to safely scale across multiple merchants.

## 🛠️ Tech Stack

- **Backend:** Python, FastAPI, SQLAlchemy (v2.0), Alembic, Pydantic, Uvicorn
- **Frontend:** Next.js (14.2), React (18.3), TailwindCSS
- **Databases:** PostgreSQL (Production), SQLite (Dev Fallback), Redis (Caching & Rate Limiting)
- **AI Integrations:** Groq API

## 📂 Project Structure

```
.
├── backend/          # FastAPI application, database models, AI agents, and core commerce logic
│   ├── app/          # Main application code (routes, models, services, core)
│   ├── alembic/      # Database migrations
│   └── requirements.txt
├── frontend/         # Next.js 14 merchant dashboard
│   ├── app/          # Next.js app router pages & components
│   └── package.json
└── docker-compose.yml # Infrastructure (Postgres & Redis)
```

## 🚀 Quick Start

### 1. Environment Setup

Copy the backend environment template and populate the necessary keys:
```bash
cp backend/.env.example backend/.env
```
Ensure you set your `GROQ_API_KEY`, `RAZORPAY_KEY_ID`, and `RAZORPAY_KEY_SECRET` when ready.

### 2. Run with Docker (Recommended)

Starts PostgreSQL and Redis in the background.

```bash
# Start infrastructure
docker compose up -d

# Setup and run backend
pip install -r backend/requirements.txt
uvicorn backend.app.main:app --reload --port 8000
```

### 3. Run without Docker (SQLite Dev Fallback)

If you don't run Postgres, the app automatically creates a local SQLite database (`dev.db`) and seeds it with demo data.

```bash
pip install -r backend/requirements.txt
uvicorn backend.app.main:app --reload --port 8000
```

### 4. Run the Frontend Dashboard

Open a new terminal window to start the Next.js frontend:

```bash
cd frontend
npm install
npm run dev
```
The dashboard will be available at [http://localhost:3000](http://localhost:3000).

## 📍 Important URLs

- **API Swagger Docs:** [http://localhost:8000/docs](http://localhost:8000/docs)
- **API Health Check:** [http://localhost:8000/health](http://localhost:8000/health)
- **Merchant Dashboard:** [http://localhost:3000](http://localhost:3000)

## 🗺️ Development Phases

The project follows a structured progression to ensure secure autonomous commerce:

- **Phase 0:** Documentation & Architecture (Frozen)
- **Phase 1:** Core Commerce APIs
- **Phase 2:** Razorpay Integration
- **Phase 3:** Trust & Policy Layer
- **Phase 4:** Commerce Agent (Groq integration)
- **Phase 5:** Autonomous Growth Engine
- **Phase 6:** Universal Commerce Protocol (UCP)
- **Phase 7:** Security Hardening & Tenant Isolation

## 🔒 Security Principles

> **Commerce is the source of truth.** The AI proposes actions based on data intelligence, the strict policy engine authorizes them, and all events are immutably audited.
