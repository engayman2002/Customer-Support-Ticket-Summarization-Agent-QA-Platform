# Customer Support Ticket Summarization & Agent QA Platform

An enterprise-grade, asynchronous AI Quality Assurance (QA), Ticket Summarization, and Agent Coaching Platform powered by **Next.js 15 (App Router)**, **FastAPI (Python 3.12 Async)**, **PostgreSQL 16**, **Redis 7 + Celery**, and **LangChain + Groq (`llama-3.3-70b-versatile` / `llama-3.1-8b-instant`)**.

---

## 1. System Architecture Overview

```
                               +-----------------------------------+
                               |   External CRM Platforms          |
                               | (Zendesk / Intercom / Freshdesk)  |
                               +-----------------+-----------------+
                                                 |
                            Webhooks (HMAC-SHA256) / 15m Delta-Sync
                                                 v
+--------------------------------------------------------------------------------------------------+
|                                    FastAPI Backend (:8000)                                       |
|  - Sub-50ms Non-Blocking Webhook Ingestion (202 Accepted)                                        |
|  - Redis SETNX Idempotency Guard (24h TTL)                                                       |
|  - CRM Adapter Strategy Pattern (Zendesk, Intercom, Freshdesk, Custom)                           |
|  - Stage-1 Pre-Processing: HTML Strip + Regex PII Scrubber (Credit Cards, SSNs, Phones, Keys)    |
|  - Head-Body-Tail Context Window Compressor (>10,000 tokens -> <=8,000 token budget)             |
|  - Redis Lua Atomic Dual-Bucket Rate Limiter (30 RPM / 15,000 TPM)                               |
|  - LangChain LCEL + ChatGroq Structured Outputs (TicketQAEvaluation Pydantic v2 Schema)          |
|  - Post-Inference Guardrails (Weighted Composite Math + Verbatim Quote Grounding)                |
+------------------------------------------------+-------------------------------------------------+
                                                 |
                        +------------------------+------------------------+
                        |                                                 |
                        v                                                 v
        +-------------------------------+                 +-------------------------------+
        |       PostgreSQL 16 (:5432)   |                 |         Redis 7 (:6379)       |
        |  - users                      |                 |  - ingestion_queue            |
        |  - integrations (AES-256-GCM) |                 |  - ai_evaluation_queue        |
        |  - tickets (JSONB thread)     |                 |  - ai_evaluation_dlq (DLQ)    |
        |  - ai_qa_reports              |                 |  - Lua RPM/TPM Rate Buckets   |
        |  - manager_feedback           |                 |  - SETNX Webhook Idempotency  |
        +---------------+---------------+                 +-------------------------------+
                        ^
                        | Dual-Service ORM Parity (Prisma + SQLAlchemy 2.0 Async)
                        v
+--------------------------------------------------------------------------------------------------+
|                               Next.js 15 App Router (:3000)                                      |
|  - Unified Cross-Service HS256 JWT Authentication (Auth.js v5 + FastAPI Bearer Verification)     |
|  - Edge Middleware Role-Based Access Control (ADMIN / MANAGER / AGENT)                           |
|  - Manager Command Center: Recharts QA Trends, Sentiment Distribution, Agent Leaderboard         |
|  - 3-Pane Split Ticket QA Workspace: Verbatim Evidence Quote Highlighting + Coaching Dispatch    |
|  - Agent Personal Portal: Action-Item Completion Gating + AI Coaching History Library            |
|  - Admin Operations Console: p50/p95/p99 Inference Telemetry, CRM Connectors, 1-Click DLQ Replay |
+--------------------------------------------------------------------------------------------------+
```

### Core Capabilities Across Phases 1–5
- **Phase 1 — Database Foundation, Dual-Service ORM Parity & Unified HS256 RBAC:**
  - Single source of truth across Prisma (`frontend/prisma/schema.prisma`) and SQLAlchemy 2.0 Async (`backend/app/models/__init__.py`) for `users`, `integrations`, `tickets`, `ai_qa_reports`, and `manager_feedback`.
  - Shared `AUTH_SECRET` `HS256` JWT tokens minted by Next.js Auth.js v5 and verified by FastAPI dependencies (`get_current_user`, `require_roles`) with row-level `AGENT` ownership isolation.
- **Phase 2 — Webhook Ingestion Engine, CRM Adapters, PII Scrubber & Celery Queue Topology:**
  - Strategy Pattern CRM normalization (`ZendeskConnector`, `IntercomConnector`, `FreshdeskConnector`, `CustomCRMConnector`) with constant-time HMAC-SHA256 verification and AES-256-GCM credential encryption at rest.
  - Pre-LLM HTML stripping and regex PII redaction (`[REDACTED_CREDIT_CARD]`, `[REDACTED_SSN]`, `[REDACTED_PHONE]`, `[REDACTED_API_KEY]`, `[REDACTED_EMAIL]`).
  - 3-queue Celery architecture (`ingestion_queue`, `ai_evaluation_queue`, `ai_evaluation_dlq`) plus 15-minute Celery Beat delta-sync reconciliation.
- **Phase 3 — LangChain + Groq AI Evaluation Pipeline & Guardrails:**
  - Head-Body-Tail Context Window Compressor preserving ticket opening context, status/escalation events, and resolution turns within an `8,000`-token ceiling.
  - Distributed Redis Lua rate limiter enforcing `30 RPM` and `15,000 TPM` across workers.
  - `GroqTicketEvaluator` using `llama-3.3-70b-versatile` (`temperature=0.0`) with automatic exponential backoff and fallback to `llama-3.1-8b-instant`.
  - Deterministic post-inference guardrails recomputing weighted `overall_qa_score` (`0.35 * tone + 0.45 * resolution + 0.20 * policy`), enforcing critical policy overrides (`<= 40`), and validating verbatim quote substrings.
- **Phase 4 — Manager & Agent Dashboards (Next.js 15 App Router):**
  - Manager Command Center (`/manager`), Filterable Ticket QA Explorer (`/manager/tickets`), 3-Pane Split Workspace (`/manager/tickets/[ticketId]`) with click-to-scroll verbatim evidence quote highlighting, and Agent Leaderboard (`/manager/agents`).
  - Agent Workspace (`/agent`), Feedback Inbox (`/agent/inbox`) with checkbox action-item gating before acknowledging coaching, and AI Coaching Library (`/agent/coaching`).
- **Phase 5 — Admin Operations Console, AI Telemetry, DLQ Replay & Production Readiness:**
  - Real-time AI observability (`p50`, `p95`, `p99` inference latency, prompt/completion token consumption, primary vs. fallback model share, queue depths).
  - CRM Integration Health registry with masked AES-256-GCM credentials and manual delta-sync triggers.
  - Dead-Letter Queue (`ai_evaluation_dlq`) inspection with 1-click individual ticket replay and batch replay.

---

## 2. Quickstart & Setup Instructions

### Prerequisites
- **Docker & Docker Compose** (PostgreSQL 16 & Redis 7)
- **Python 3.12+**
- **Node.js 20+**

### Step 1: Start PostgreSQL 16 & Redis 7
```bash
docker compose up -d postgres redis
```

### Step 2: Configure Environment Variables
Copy `.env.example` to `.env` in the repository root (and `frontend/.env` if running Next.js standalone):
```bash
cp .env.example .env
```
Key environment variables:
- `DATABASE_URL="postgresql://qa_admin:qa_secret_password@localhost:5432/qa_platform_db?schema=public"`
- `ASYNC_DATABASE_URL="postgresql+asyncpg://qa_admin:qa_secret_password@localhost:5432/qa_platform_db"`
- `REDIS_URL="redis://localhost:6379/0"`
- `AUTH_SECRET="super_secret_shared_hs256_jwt_signing_key_minimum_32_bytes_long"`
- `ENCRYPTION_MASTER_KEY="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"`
- `GROQ_API_KEY="your_groq_api_key_here"` *(When unset or using a placeholder key in local dev/CI, `GroqTicketEvaluator` automatically runs its deterministic heuristic rubric evaluator so all flows work offline without external API failures.)*

### Step 3: Run Prisma Database Migrations & Seed Data
```bash
cd frontend
npm install
npx prisma generate
npx prisma migrate deploy
npm run db:seed
cd ..
```

### Step 4: Install Python Dependencies & Start Backend Services
```bash
pip install -r backend/requirements.txt

# Start FastAPI server on :8000
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload

# (Optional) Start Celery Worker & Beat in separate terminals
celery -A backend.app.workers.celery_app worker -Q ingestion_queue,ai_evaluation_queue,ai_evaluation_dlq --loglevel=info
celery -A backend.app.workers.celery_app beat --loglevel=info
```

### Step 5: Start Next.js 15 Frontend Application
```bash
cd frontend
npm run dev
```
Open `http://localhost:3000` in your browser.

### Production Full-Stack Container Deployment
To run all services (`postgres`, `redis`, `backend`, `celery_worker`, `celery_beat`, and `frontend`) in Docker containers:
```bash
docker compose --profile prod up --build -d
```

---

## 3. Seeded Demo Accounts & Credentials

All seeded accounts share the default password: **`Password123!`**

| Role | Email | Password | External CRM Agent ID | Default Landing Route |
| :--- | :--- | :--- | :--- | :--- |
| **ADMIN** | `admin@qa-platform.local` | `Password123!` | — | `/admin/integrations` |
| **MANAGER** | `manager@qa-platform.local` | `Password123!` | — | `/manager` |
| **AGENT** (Sarah Jenkins) | `sarah.agent@qa-platform.local` | `Password123!` | `zd_agent_101` | `/agent` |
| **AGENT** (Omar Hassan) | `omar.agent@qa-platform.local` | `Password123!` | `zd_agent_102` | `/agent` |

---

## 4. Automated Verification & Test Suites

Run the complete backend and frontend verification suites at any time:

### Backend Test Suite (Pytest — Phases 1 through 5)
```bash
pytest -v
```
Covers:
- Database schema parity, HS256 JWT minting/verification, and RBAC ownership enforcement
- AES-256-GCM encryption, PII regex scrubbing, CRM webhook signature verification & payload normalization
- Sub-50ms non-blocking webhook ingestion, Redis `SETNX` idempotency, and delta-sync polling reconciliation
- Context window compression (`>10,000` tokens -> `<=8,000` tokens), Redis Lua rate limiting (`30 RPM` / `15,000 TPM`), post-inference scoring guardrails, 20-ticket gold-standard evaluation accuracy (`MAE <= 5.0`), and 100-ticket concurrent burst resiliency
- Manager analytics, ticket explorer, coaching feedback loop, and Agent action-item completion gating
- Admin telemetry (`p50`/`p95`/`p99` latency, token usage, fallback rates), DLQ 1-click & batch replay, and 100-webhook high-concurrency load verification (`p95 < 75ms`, `0%` `5xx` errors)

### Frontend Test Suite (Vitest + TypeScript Strict Check)
```bash
cd frontend
npm test
npx tsc --noEmit
```

