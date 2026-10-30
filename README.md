# Customer Support Ticket Summarization & Agent QA Platform

An enterprise-grade, asynchronous **AI Quality Assurance (QA), Ticket Summarization, and Closed-Loop Agent Coaching Platform** built with **Next.js 15 (App Router)**, **FastAPI (Python 3.12 Async)**, **PostgreSQL 16**, **Redis 7 + Celery**, and a **Pluggable Multi-LLM Provider Engine (`backend/app/LLM_Providers/`)** supporting **Groq LPU (`llama-3.3-70b-versatile`)**, **OpenAI (`gpt-4o`)**, **Google Gemini (`gemini-2.5-pro`)**, **Anthropic Claude (`claude-3-5-sonnet-latest`)**, and **Local Ollama (`llama3.2`)**.

---

## Table of Contents

1. [Project Overview & Core Value Proposition](#1-project-overview--core-value-proposition)
2. [Detailed Breakdown of Every Project Component (How It Works Under the Hood)](#2-detailed-breakdown-of-every-project-component-how-it-works-under-the-hood)
3. [System Requirements & Needed Resources](#3-system-requirements--needed-resources)
4. [3-Tier Environment Variable Architecture (`./.env`, `backend/.env`, `frontend/.env`)](#4-3-tier-environment-variable-architecture-env-backendenv-frontendenv)
5. [Step-by-Step Guide: How to Run the Project](#5-step-by-step-guide-how-to-run-the-project)
6. [How to Configure & Switch LLM Providers (Groq, OpenAI, Gemini, Anthropic, Ollama)](#6-how-to-configure--switch-llm-providers-groq-openai-gemini-anthropic-ollama)
7. [How to Connect External Customer Support Apps (CRM Integration Guide)](#7-how-to-connect-external-customer-support-apps-crm-integration-guide)
8. [Developer Guide: How to Add a Brand-New Custom LLM Provider in `backend/app/LLM_Providers/`](#8-developer-guide-how-to-add-a-brand-new-custom-llm-provider-in-backendappllm_providers)
9. [User Walkthrough & Automated Testing Guide](#9-user-walkthrough--automated-testing-guide)

---

## 1. Project Overview & Core Value Proposition

### What Problem Does This Platform Solve?
In most customer support teams, QA managers manually review less than **2% to 5%** of closed support tickets because reading thousands of transcripts by hand is slow and expensive. As a result, critical issues—such as **premature ticket closures** (closing a ticket while the customer is still locked out or frustrated), **poor agent tone**, or **missed billing/security policies**—slip through unnoticed until customer churn increases.

### How This Platform Works (In Simple Terms)
This platform automates **100% of support ticket QA** from the moment a conversation is marked `Closed` or `Solved` in your CRM:
1. **Real-Time Webhook Listener:** Whenever a support agent closes a ticket in **Zendesk**, **Intercom**, **Freshdesk**, or your **Custom CRM**, the platform receives the webhook in under **50 milliseconds** (`202 Accepted`), verifies its cryptographic signature, strips HTML noise, and redacts sensitive customer PII (credit cards, SSNs, phone numbers, emails, API keys).
2. **Pluggable Multi-LLM QA Auditor:** A background worker sends the sanitized conversation transcript to your configured LLM provider (`backend/app/LLM_Providers/`) bound to a strict **16-field JSON Schema (`TicketQAEvaluation`)**. The AI summarizes the ticket, identifies the root issue, scores the agent from `0–100` across **Empathy**, **Clarity & Accuracy**, and **Ownership & Efficiency**, flags verbatim quotes proving poor tone or premature closure, and writes concrete **Suggested Phrasing Rewrites**.
3. **Deterministic Post-Inference Guardrails:** Before saving the AI report, deterministic Python guardrails verify the math and enforce hard ceilings:
   - If **Premature Closure** is detected, the agent's overall QA score is automatically capped at **`<= 45`**, `is_resolved_properly` is forced to `False`, and the ticket is flagged in red on the Manager Dashboard.
   - If **Poor Tone** is evidenced in a flagged quote, the overall QA score is capped at **`<= 35`**.
4. **Closed-Loop Manager-to-Agent Coaching:** Support Managers inspect flagged tickets in a **3-Pane Split Workspace** (clicking any AI evidence quote scrolls directly to and highlights that exact message in the transcript) and send structured coaching notes with required action items to the agent. Support Agents must check off every required action item in their **Feedback Inbox** before they can acknowledge the coaching note.

### End-to-End Architecture Diagram

```mermaid
flowchart TD
    subgraph ExternalCRMs["External Customer Support Platforms"]
        ZD["Zendesk"]
        IC["Intercom"]
        FD["Freshdesk"]
        CU["Custom CRM / In-House App"]
    end

    subgraph FastAPIIngestion["FastAPI Backend (:8000) — Ingestion & API Layer"]
        WH["POST /api/v1/webhooks/{provider}/{integration_id}<br/>HMAC Verification (<50ms 202 Accepted)"]
        DEDUP["Redis SETNX Idempotency Guard<br/>(24h TTL Deduplication)"]
        NORM["CRM Adapter Strategy + Sanitizer<br/>(HTML Strip + Regex PII Scrubber)"]
        RECON["15-Minute Celery Beat Delta-Sync Reconciler<br/>(Fallback Polling for Missed Webhooks)"]
    end

    subgraph AsyncWorkers["Redis 7 Queues & Celery Worker Topology (:6379)"]
        INGQ["ingestion_queue"]
        EVALQ["ai_evaluation_queue"]
        DLQ["ai_evaluation_dlq<br/>(Dead-Letter Queue + 1-Click Replay)"]
        RL["Redis Lua Atomic Rate Limiter<br/>(30 RPM / 15,000 TPM Sliding Buckets)"]
    end

    subgraph LLMProviders["Pluggable Multi-LLM Engine (backend/app/LLM_Providers/)"]
        COMP["Head-Body-Tail Context Window Compressor<br/>(>10,000 Tokens -> <=8,000 Token Budget)"]
        REG["LLMProviderRegistry<br/>(Groq | OpenAI | Gemini | Anthropic | Ollama)"]
        GUARD["Deterministic Post-Inference Guardrails<br/>(Premature Closure <=45, Poor Tone <=35)"]
    end

    subgraph Database["PostgreSQL 16 (:5432) — Dual-ORM Parity (Prisma + SQLAlchemy 2.0)"]
        DB[("users | integrations | tickets<br/>ai_qa_reports | manager_feedback")]
    end

    subgraph NextJSFrontend["Next.js 15 App Router (:3000) — Role-Based Dashboards"]
        MGR["Manager Command Center & 3-Pane QA Workspace<br/>(/manager, /manager/tickets/[ticketId], /manager/agents)"]
        AGT["Agent Workspace, Action-Gated Inbox & Coaching Library<br/>(/agent, /agent/inbox, /agent/coaching)"]
        ADM["Admin Operations Console, Telemetry & DLQ Replay<br/>(/admin/integrations)"]
    end

    ZD & IC & FD & CU -->|"Webhook (Signed JSON)"| WH
    RECON -.->|"REST Poll Closed Tickets"| ZD & IC & FD
    WH --> DEDUP --> INGQ --> NORM --> DB
    NORM --> EVALQ --> RL --> COMP --> REG --> GUARD --> DB
    REG -.->|"Max Retries Exhausted"| DLQ
    ADM -->|"1-Click Replay"| DLQ
    DB <--> MGR & AGT & ADM
```

---

## 2. Detailed Breakdown of Every Project Component (How It Works Under the Hood)

### 2.1 Frontend (`frontend/` — Next.js 15 App Router, TypeScript, Tailwind CSS)
- **Unified Cross-Service Authentication (`frontend/src/lib/auth.ts` & `frontend/src/lib/jwt.ts`):**
  - Uses Auth.js v5 (`next-auth`) with Credentials login against PostgreSQL `users` (`bcryptjs` password verification).
  - Mints a shared **`HS256` JWT access token** signed with `AUTH_SECRET` containing `sub` (User UUID), `email`, `role` (`ADMIN`, `MANAGER`, `AGENT`), `external_crm_agent_id`, and `manager_id`. FastAPI verifies this exact Bearer token on every backend API call.
- **Edge RBAC Middleware (`frontend/src/middleware.ts` & `frontend/src/lib/rbac.ts`):**
  - Runs at the Next.js Edge layer before any page renders:
    - Unauthenticated users are redirected to `/login`.
    - `AGENT` users are restricted strictly to `/agent/*` and receive `403`/redirects if they attempt to visit `/manager/*` or `/admin/*`.
    - `MANAGER` users can access `/manager/*` and `/agent/*`.
    - `ADMIN` users have full access to `/admin/*`, `/manager/*`, and `/agent/*`.
- **Dual-Mode Data Fetching Client (`frontend/src/lib/api-client.ts`):**
  - Automatically queries FastAPI (`FASTAPI_INTERNAL_URL`) with `Authorization: Bearer <token>` and seamlessly falls back to direct Prisma queries if FastAPI is temporarily unreachable, ensuring zero-downtime server-side rendering.
- **Manager Command Center & 3-Pane Split Workspace:**
  - `frontend/src/app/(dashboard)/manager/page.tsx`: Team KPI summary cards, daily QA score trend chart, customer sentiment trajectory breakdown, and premature closure alert feed.
  - `frontend/src/app/(dashboard)/manager/tickets/page.tsx`: Filterable, paginated Ticket QA Explorer (filter by `Premature Closure Only`, `Resolution Status`, `Issue Category`, or `Score Range`).
  - `frontend/src/app/(dashboard)/manager/tickets/[ticketId]/page.tsx` & `frontend/src/components/manager/TicketThreePaneWorkspace.tsx`:
    - **Left Pane:** Ticket metadata, SLA response/resolution timings, customer identifier, and assigned agent info.
    - **Center Pane:** Sanitized conversation transcript with turn numbers, sender badges, and dynamic scroll-to-quote highlighting.
    - **Right Pane:** AI QA Scorecard (`0–100`), rubric breakdown (`Empathy`, `Clarity & Accuracy`, `Ownership & Efficiency`), clickable **Flagged Verbatim Evidence Quotes**, **AI Actionable Coaching Plan** (with suggested phrasing rewrites), **Re-Evaluate Ticket** button, and **Manager Coaching Feedback Form**.
- **Agent Portal & Action-Item Completion Gating:**
  - `frontend/src/app/(dashboard)/agent/page.tsx`: Personal QA score trend compared against the team average benchmark.
  - `frontend/src/app/(dashboard)/agent/inbox/page.tsx` & `frontend/src/components/agent/AgentInboxClient.tsx`: Displays coaching notes sent by managers. The **"Acknowledge Feedback"** button is strictly disabled in both UI and backend (`PATCH /api/v1/feedback/{id}/status`) until the agent checks off 100% of the required action items.
  - `frontend/src/app/(dashboard)/agent/coaching/page.tsx`: Searchable library of AI-generated coaching steps and phrasing rewrites across all of the agent's evaluated tickets.
- **Admin Operations, Telemetry & DLQ Console:**
  - `frontend/src/app/(dashboard)/admin/integrations/page.tsx` & `frontend/src/components/admin/AdminOperationsConsole.tsx`: Displays real-time `p50`/`p95`/`p99` LLM inference latency (`ms`), prompt/completion token usage, fallback model invocation rate (`%`), active CRM integrations with masked `AES-256-GCM` secrets, **"Trigger Delta-Sync Now"**, and **1-Click Dead-Letter Queue (`ai_evaluation_dlq`) Replay**.

### 2.2 Backend API & Webhook Engine (`backend/app/api/` & `backend/app/integrations/`)
- **Non-Blocking Webhook Receiver (`backend/app/api/v1/webhooks.py`):**
  - Exposes `POST /api/v1/webhooks/{provider}/{integration_id}`.
  - Resolves the active integration config from an in-memory/Redis cache so hot-path webhooks perform zero blocking SQL queries on the request thread.
  - Validates provider-specific HMAC signatures and enforces a **300-second replay window** (`401 Unauthorized` on mismatch or expired timestamp).
  - Ignores non-closed ticket events immediately (`200 OK` with `{"status": "IGNORED_NOT_CLOSED"}`).
  - Checks Redis `SETNX` idempotency (`webhook:dedup:{crm_type}:{external_ticket_id}:{closed_at}`) with a 24-hour TTL so duplicate CRM webhook deliveries never create duplicate database rows or duplicate LLM calls.
  - Pushes the job to `ingestion_queue` and returns `202 Accepted` in **< 50ms**.
- **CRM Adapter Strategy Pattern (`backend/app/integrations/`):**
  - `base.py` (`BaseCRMConnector`), `registry.py` (`ProviderRegistry`), `zendesk.py` (`ZendeskConnector`), `intercom.py` (`IntercomConnector`), `freshdesk.py` (`FreshdeskConnector`), and `custom.py` (`CustomCRMConnector`).
  - Every connector converts raw provider JSON into a unified Pydantic `StandardTicketPayload` (`backend/app/schemas/ticket_payload.py`).
- **Stage-1 Pre-Processing & PII Scrubber (`backend/app/services/sanitizer.py`):**
  - Strips HTML tags, scripts/styles, and quoted email reply chains (`On ... wrote:`).
  - Redacts sensitive PII using compiled regexes before any text is stored or sent to an LLM:
    - Credit Cards -> `[REDACTED_CREDIT_CARD]`
    - US SSNs -> `[REDACTED_SSN]`
    - Phone Numbers -> `[REDACTED_PHONE]`
    - API Keys / Bearer Tokens -> `[REDACTED_API_KEY]`
    - Email Addresses -> `[REDACTED_EMAIL]`
- **AES-256-GCM Credential Encryption (`backend/app/core/crypto.py`):**
  - Encrypts CRM API keys and webhook secrets at rest (`enc_aes256gcm_v1:<nonce>:<ciphertext+tag>`) using a 256-bit key derived from `ENCRYPTION_KEY`.

### 2.3 Async Queue & Distributed Rate Limiter (`backend/app/worker/` & `backend/app/ai/rate_limiter.py`)
- **3-Queue Celery Topology (`backend/app/worker/celery_app.py` & `backend/app/worker/tasks.py`):**
  1. `ingestion_queue` (`process_webhook_ingestion_task`): Normalizes, sanitizes, and persists closed tickets into PostgreSQL with `processing_status = QUEUED`.
  2. `ai_evaluation_queue` (`evaluate_ticket_ai_qa_task`): Runs the Pluggable Multi-LLM evaluation pipeline.
  3. `ai_evaluation_dlq` (`handle_ai_evaluation_dlq_task`): Captures tickets that exhausted all primary and fallback model retries, marking them `FAILED_RETRYABLE` with `last_dlq_error` metadata for 1-click replay in the Admin Console.
- **15-Minute Celery Beat Reconciler:** Automatically polls active CRM integrations every 15 minutes (`reconcile_missed_closed_tickets_task`) to catch any closed tickets whose webhooks were dropped during network outages.
- **Redis Lua Dual-Bucket Rate Limiter (`backend/app/ai/rate_limiter.py`):**
  - Executes an atomic Lua script inside Redis enforcing both **Requests Per Minute (`LLM_RPM_LIMIT`, default `30`)** and **Tokens Per Minute (`LLM_TPM_LIMIT`, default `15,000`)** across all concurrent worker processes.

### 2.4 Pluggable Multi-LLM Provider Engine & AI Evaluation Pipeline (`backend/app/LLM_Providers/` & `backend/app/ai/`)
- **Dedicated `LLM_Providers` Package (`backend/app/LLM_Providers/`):**
  - [`base.py`](file:///workspaces/codespaces-blank/myapps-anti/Customer%20Support%20Ticket%20Summarization%20&%20Agent%20QA%20Platform/backend/app/LLM_Providers/base.py): Defines the abstract `BaseLLMProvider` contract (`is_configured()`, `get_structured_output_runnable()`, `summarize_chunk()`, `primary_model_name`, `fallback_model_name`, `compression_model_name`).
  - [`groq_provider.py`](file:///workspaces/codespaces-blank/myapps-anti/Customer%20Support%20Ticket%20Summarization%20&%20Agent%20QA%20Platform/backend/app/LLM_Providers/groq_provider.py): `GroqProvider` (`llama-3.3-70b-versatile` primary, `llama-3.1-8b-instant` fallback).
  - [`openai_provider.py`](file:///workspaces/codespaces-blank/myapps-anti/Customer%20Support%20Ticket%20Summarization%20&%20Agent%20QA%20Platform/backend/app/LLM_Providers/openai_provider.py): `OpenAIProvider` (`gpt-4o` primary, `gpt-4o-mini` fallback, plus custom `OPENAI_BASE_URL` support).
  - [`gemini_provider.py`](file:///workspaces/codespaces-blank/myapps-anti/Customer%20Support%20Ticket%20Summarization%20&%20Agent%20QA%20Platform/backend/app/LLM_Providers/gemini_provider.py): `GeminiProvider` (`gemini-2.5-pro` primary, `gemini-2.5-flash` fallback).
  - [`anthropic_provider.py`](file:///workspaces/codespaces-blank/myapps-anti/Customer%20Support%20Ticket%20Summarization%20&%20Agent%20QA%20Platform/backend/app/LLM_Providers/anthropic_provider.py): `AnthropicProvider` (`claude-3-5-sonnet-latest` primary, `claude-3-5-haiku-latest` fallback).
  - [`ollama_provider.py`](file:///workspaces/codespaces-blank/myapps-anti/Customer%20Support%20Ticket%20Summarization%20&%20Agent%20QA%20Platform/backend/app/LLM_Providers/ollama_provider.py): `OllamaProvider` (`llama3.2` local model at `http://localhost:11434`).
  - [`registry.py`](file:///workspaces/codespaces-blank/myapps-anti/Customer%20Support%20Ticket%20Summarization%20&%20Agent%20QA%20Platform/backend/app/LLM_Providers/registry.py): `LLMProviderRegistry` resolves the active provider from `LLM_PROVIDER` in `backend/.env` and supports registering custom providers via `LLMProviderRegistry.register_provider(...)`.
- **Head-Body-Tail Context Window Compressor (`backend/app/ai/context_window.py`):**
  - Transcripts `<= 10,000` tokens pass through verbatim.
  - Transcripts `> 10,000` tokens are compressed into an `<= 8,000`-token budget while keeping the **First 3 turns** (Head), **status/escalation events** (Body), and **Last 6 turns** (Tail) 100% verbatim.
- **Post-Inference Deterministic Guardrails (`apply_qa_scoring_guardrails` in `backend/app/schemas/qa_evaluation.py`):**
  - **Premature Closure Cap:** Clamps `agent_score` to **`<= 45`**, sets `resolution_status = PREMATURELY_CLOSED`, and forces `is_resolved_properly = False`.
  - **Poor Tone Cap:** Clamps `agent_score` to **`<= 35`** whenever a `POOR_TONE` quote is flagged.

### 2.5 Database Layer (`frontend/prisma/schema.prisma` & `backend/app/models/`)
Prisma and SQLAlchemy 2.0 Async share 100% identical table names, column types, and PostgreSQL native enums across **5 core tables**: `users`, `integrations`, `tickets`, `ai_qa_reports`, and `manager_feedback`.

---

## 3. System Requirements & Needed Resources

### 3.1 Software Prerequisites

| Requirement | Minimum Version | Recommended Version | Purpose |
| :--- | :--- | :--- | :--- |
| **Node.js & npm** | `v20.10+` | `v20 LTS` or `v22 LTS` | Next.js 15 App Router, Prisma CLI, Vitest |
| **Python** | `3.12+` | `3.12.x` | FastAPI Async Backend, Celery Workers, LangChain, Pytest |
| **Docker & Docker Compose** | `v24.0+` / `v2.20+` | Latest Stable | Running PostgreSQL 16, Redis 7, and production containers |
| **PostgreSQL** | `16.x` | `16-alpine` (via Docker) | Primary relational + `JSONB` datastore |
| **Redis** | `7.x` | `7-alpine` (via Docker) | Celery message broker, `SETNX` idempotency, Lua rate limiter |

### 3.2 Hardware & Cloud Compute Sizing Guide

| Environment / Ticket Volume | Total vCPU | Total RAM | Disk (SSD) | Recommended Process Topology |
| :--- | :--- | :--- | :--- | :--- |
| **Local Development / Demo**<br/>*(Up to 500 tickets/day)* | **2 vCPU** | **4 GB RAM** | **10 GB SSD** | Single machine running Docker (`postgres`, `redis`), `uvicorn` (1 worker), and `next dev` / `next start`. |
| **Small / Medium Production**<br/>*(500 – 10,000 tickets/day)* | **4 vCPU** | **8 GB RAM** | **40 GB NVMe** | • **Next.js 15:** 1 vCPU, 2 GB RAM<br/>• **FastAPI + Celery Worker (`c=4`):** 2 vCPU, 3 GB RAM<br/>• **PostgreSQL 16 + Redis 7:** 1 vCPU, 3 GB RAM |
| **High-Volume Enterprise**<br/>*(10,000 – 100,000+ tickets/day)* | **8–16 vCPU** | **16–32 GB RAM** | **100+ GB NVMe** | • **Next.js 15:** 2+ replicas behind load balancer<br/>• **FastAPI Webhook Tier:** 4 Gunicorn/Uvicorn workers<br/>• **Dedicated Celery Workers:** Separate `ingestion_queue` and `ai_evaluation_queue` pools<br/>• **Managed PostgreSQL 16 & Redis 7** |

---

## 4. 3-Tier Environment Variable Architecture (`./.env`, `backend/.env`, `frontend/.env`)

All configuration values are externalized into three layered `.env` files (with matching `.env.example` templates):

### 4.1 Root `./.env` (Infrastructure & Shared Cross-Service Contract)
Used by `docker-compose.yml` and shared as fallback defaults across services.

| Variable | Example Value | Description |
| :--- | :--- | :--- |
| `POSTGRES_USER` | `qa_admin` | PostgreSQL container superuser |
| `POSTGRES_PASSWORD` | `qa_secret_password` | PostgreSQL container password |
| `POSTGRES_DB` | `qa_platform_db` | PostgreSQL database name |
| `POSTGRES_PORT` | `5432` | Host port mapped to PostgreSQL |
| `REDIS_PORT` | `6379` | Host port mapped to Redis |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection string |
| `AUTH_SECRET` | `super-secret-shared-hs256-signing-key-minimum-32-bytes-long-2026` | Shared `HS256` JWT signing secret (must match in `backend/.env` and `frontend/.env`) |

### 4.2 Backend `backend/.env` (FastAPI, Celery, Security & Multi-LLM Providers)
Loaded directly by [`backend/app/core/config.py`](file:///workspaces/codespaces-blank/myapps-anti/Customer%20Support%20Ticket%20Summarization%20&%20Agent%20QA%20Platform/backend/app/core/config.py).

| Variable | Default in `backend/.env` | Description |
| :--- | :--- | :--- |
| `DATABASE_URL` | `postgresql://qa_admin:...@localhost:5432/qa_platform_db?schema=public` | Standard PostgreSQL URI |
| `ASYNC_DATABASE_URL` | `postgresql+asyncpg://qa_admin:...@localhost:5432/qa_platform_db` | SQLAlchemy 2.0 `asyncpg` connection URI |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis broker, idempotency, and Lua rate-limiter store |
| `AUTH_SECRET` | `super-secret-shared-hs256-...` | `HS256` Bearer token verification secret |
| `ENCRYPTION_KEY` | `0123456789abcdef...` | Master key material for `AES-256-GCM` CRM credential encryption |
| `CORS_ORIGINS` | `http://localhost:3000` | Comma-separated allowed CORS origins |
| `LLM_PROVIDER` | `"groq"` | Active LLM provider (`"groq"`, `"openai"`, `"gemini"`, `"anthropic"`, `"ollama"`) |
| `GROQ_API_KEY` | `""` | Groq Cloud API key (`<YOUR_GROQ_API_KEY>`) |
| `GROQ_PRIMARY_MODEL` | `"llama-3.3-70b-versatile"` | Primary Groq model for 16-field structured evaluation |
| `GROQ_FALLBACK_MODEL` | `"llama-3.1-8b-instant"` | Fallback Groq model on `429` / `503` errors |
| `GROQ_COMPRESSION_MODEL` | `"llama-3.1-8b-instant"` | Model used to compress middle chunks of `>10,000`-token transcripts |
| `OPENAI_API_KEY` | `""` | OpenAI API key (`<YOUR_OPENAI_API_KEY>`) when `LLM_PROVIDER="openai"` |
| `OPENAI_BASE_URL` | `""` | Optional custom OpenAI-compatible endpoint URL |
| `OPENAI_PRIMARY_MODEL` | `"gpt-4o"` | Primary OpenAI model |
| `OPENAI_FALLBACK_MODEL` | `"gpt-4o-mini"` | Fallback OpenAI model |
| `GEMINI_API_KEY` | `""` | Google AI Studio key (`<YOUR_GEMINI_API_KEY>`) when `LLM_PROVIDER="gemini"` |
| `GEMINI_PRIMARY_MODEL` | `"gemini-2.5-pro"` | Primary Google Gemini model |
| `GEMINI_FALLBACK_MODEL` | `"gemini-2.5-flash"` | Fallback Google Gemini model |
| `ANTHROPIC_API_KEY` | `""` | Anthropic key (`<YOUR_ANTHROPIC_API_KEY>`) when `LLM_PROVIDER="anthropic"` |
| `ANTHROPIC_PRIMARY_MODEL` | `"claude-3-5-sonnet-latest"` | Primary Anthropic Claude model |
| `ANTHROPIC_FALLBACK_MODEL` | `"claude-3-5-haiku-latest"` | Fallback Anthropic Claude model |
| `OLLAMA_BASE_URL` | `"http://localhost:11434"` | Local Ollama server URL when `LLM_PROVIDER="ollama"` |
| `OLLAMA_PRIMARY_MODEL` | `"llama3.2"` | Local Ollama model name |
| `LLM_RPM_LIMIT` | `30` | Distributed sliding-window Requests Per Minute limit |
| `LLM_TPM_LIMIT` | `15000` | Distributed sliding-window Tokens Per Minute limit |
| `TRANSCRIPT_MAX_VERBATIM_TOKENS` | `10000` | Token ceiling before Head-Body-Tail compression activates |

### 4.3 Frontend `frontend/.env` (Next.js 15, Prisma & Auth.js v5)
Loaded by Next.js 15 and Prisma CLI inside `frontend/`.

| Variable | Default in `frontend/.env` | Description |
| :--- | :--- | :--- |
| `DATABASE_URL` | `postgresql://qa_admin:...@localhost:5432/qa_platform_db?schema=public` | Used by Prisma Client & migrations |
| `AUTH_SECRET` / `NEXTAUTH_SECRET` | `super-secret-shared-hs256-...` | Mints `HS256` session & `accessToken` JWTs |
| `NEXTAUTH_URL` / `AUTH_URL` | `http://localhost:3000` | Canonical Next.js application URL |
| `FASTAPI_INTERNAL_URL` | `http://localhost:8000` | Server-to-server FastAPI URL used by Next.js BFF Route Handlers |
| `NEXT_PUBLIC_API_BASE_URL` | `http://localhost:8000` | Browser-accessible FastAPI URL |

---

## 5. Step-by-Step Guide: How to Run the Project

### Option A: One-Command Quick Start (Fastest Way to Launch & Test Live)

From the root of the repository, run:

```bash
# 1. Start PostgreSQL 16, Redis 7, FastAPI (:8000), and Next.js (:3000)
./start-dev.sh
```

In a second terminal window, simulate two live Zendesk webhook deliveries (one **Prematurely Closed** red-alert ticket and one **Properly Resolved** high-empathy billing ticket):

```bash
# 2. Fire 2 signed Zendesk webhooks and run end-to-end AI QA evaluation
python3 scripts/simulate_live_webhook.py
```

---

### Option B: Manual Step-by-Step Setup (Full Developer Control)

```bash
# 1. Start PostgreSQL 16 and Redis 7 containers
docker compose up -d postgres redis

# 2. Copy environment templates if setting up for the first time
cp .env.example .env
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env

# 3. Install frontend packages, run Prisma migrations & seed demo data
cd frontend
npm install
npx prisma generate
npx prisma migrate deploy
npm run db:seed
cd ..

# 4. Install Python dependencies and start FastAPI on :8000
pip install -r backend/requirements.txt
PYTHONPATH=backend uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000 --reload

# 5. (In a separate terminal) Start Next.js 15 on :3000
cd frontend
npm run dev
```

---

### Option C: Full Production Docker Compose Deployment

```bash
docker compose --profile prod up --build -d
```

---

### Seeded Demo Accounts & Login Credentials

All seeded demo users share the password: **`Password123!`**

| Role | Email | Password | External CRM Agent ID | Default Dashboard URL |
| :--- | :--- | :--- | :--- | :--- |
| **MANAGER** | `manager@qa-platform.local` | `Password123!` | — | `http://localhost:3000/manager` |
| **AGENT** *(Sarah Jenkins)* | `sarah.agent@qa-platform.local` | `Password123!` | `zd_agent_101` | `http://localhost:3000/agent` |
| **AGENT** *(Omar Hassan)* | `omar.agent@qa-platform.local` | `Password123!` | `zd_agent_102` | `http://localhost:3000/agent` |
| **ADMIN** | `admin@qa-platform.local` | `Password123!` | — | `http://localhost:3000/admin/integrations` |

---

## 6. How to Configure & Switch LLM Providers (Groq, OpenAI, Gemini, Anthropic, Ollama)

Switching LLM providers requires **zero code changes**—simply edit `backend/.env`:

### 6.1 Using Groq LPU (Default — Ultra-Fast Inference)
1. Get an API key from [https://console.groq.com](https://console.groq.com).
2. In `backend/.env`, set:
   ```env
   LLM_PROVIDER="groq"
   GROQ_API_KEY="<YOUR_GROQ_API_KEY>"
   GROQ_PRIMARY_MODEL="llama-3.3-70b-versatile"
   GROQ_FALLBACK_MODEL="llama-3.1-8b-instant"
   ```

### 6.2 Using OpenAI (`gpt-4o` / `gpt-4o-mini`)
1. Install the LangChain OpenAI integration: `pip install langchain-openai`
2. In `backend/.env`, set:
   ```env
   LLM_PROVIDER="openai"
   OPENAI_API_KEY="<YOUR_OPENAI_API_KEY>"
   OPENAI_PRIMARY_MODEL="gpt-4o"
   OPENAI_FALLBACK_MODEL="gpt-4o-mini"
   ```

### 6.3 Using Google Gemini (`gemini-2.5-pro` / `gemini-2.5-flash`)
1. Install the LangChain Google GenAI integration: `pip install langchain-google-genai`
2. In `backend/.env`, set:
   ```env
   LLM_PROVIDER="gemini"
   GEMINI_API_KEY="<YOUR_GEMINI_API_KEY>"
   GEMINI_PRIMARY_MODEL="gemini-2.5-pro"
   GEMINI_FALLBACK_MODEL="gemini-2.5-flash"
   ```

### 6.4 Using Anthropic Claude (`claude-3-5-sonnet-latest`)
1. Install the LangChain Anthropic integration: `pip install langchain-anthropic`
2. In `backend/.env`, set:
   ```env
   LLM_PROVIDER="anthropic"
   ANTHROPIC_API_KEY="<YOUR_ANTHROPIC_API_KEY>"
   ANTHROPIC_PRIMARY_MODEL="claude-3-5-sonnet-latest"
   ANTHROPIC_FALLBACK_MODEL="claude-3-5-haiku-latest"
   ```

### 6.5 Using Local Ollama (`llama3.2` — 100% On-Premise / Offline)
1. Install `langchain-ollama` (`pip install langchain-ollama`) and pull a model (`ollama pull llama3.2`).
2. In `backend/.env`, set:
   ```env
   LLM_PROVIDER="ollama"
   OLLAMA_BASE_URL="http://localhost:11434"
   OLLAMA_PRIMARY_MODEL="llama3.2"
   ```

> **Note on Offline / Empty API Key Mode:** Whenever the selected provider's API key is left blank (`""`) in `backend/.env`, `provider.is_configured()` returns `False` and `TicketQAEvaluator` automatically uses its deterministic rubric analyzer (`analyze_transcript_deterministically`) so local development and CI tests run with zero external API dependencies.

---

## 7. How to Connect External Customer Support Apps (CRM Integration Guide)

### Step 1: Register a Connector in the Admin Console (`/admin/integrations`)
1. Log in as **`admin@qa-platform.local`** (`Password123!`) at `http://localhost:3000/admin/integrations`.
2. Add your CRM (`ZENDESK`, `INTERCOM`, `FRESHDESK`, or `CUSTOM`) with its API Key and Webhook Signing Secret (both are encrypted at rest with **AES-256-GCM**).
3. Copy the generated webhook URL:
   ```text
   https://<your-domain>/api/v1/webhooks/{provider}/{integration_id}
   ```

### Step 2: Configure Provider Webhooks
- **Zendesk (`/api/v1/webhooks/zendesk/{integration_id}`):** Trigger on `Ticket Status Changed to Closed/Solved`. Verified via `X-Zendesk-Webhook-Signature` + `X-Zendesk-Webhook-Signature-Timestamp` (`Base64(HMAC-SHA256(timestamp + raw_body, secret))`).
- **Intercom (`/api/v1/webhooks/intercom/{integration_id}`):** Topic `conversation.admin.closed`. Verified via `X-Hub-Signature-256` (`sha256=<hex_digest>`).
- **Freshdesk (`/api/v1/webhooks/freshdesk/{integration_id}`):** Trigger on `Status changed to Closed`. Verified via `X-Webhook-Signature` or `X-Integration-Api-Key`.
- **Custom CRM (`/api/v1/webhooks/custom/{integration_id}`):** Send any closed conversation JSON with `X-Integration-Api-Key: your_webhook_secret_here` or `X-Webhook-Signature`.

---

## 8. Developer Guide: How to Add a Brand-New Custom LLM Provider in `backend/app/LLM_Providers/`

All LLM provider implementations live in [`backend/app/LLM_Providers/`](file:///workspaces/codespaces-blank/myapps-anti/Customer%20Support%20Ticket%20Summarization%20&%20Agent%20QA%20Platform/backend/app/LLM_Providers):

```text
backend/app/LLM_Providers/
├── __init__.py            # Exports BaseLLMProvider, LLMProviderRegistry, get_llm_provider
├── base.py                # Abstract BaseLLMProvider interface
├── registry.py            # LLMProviderRegistry & get_llm_provider() factory
├── groq_provider.py       # GroqProvider (ChatGroq)
├── openai_provider.py     # OpenAIProvider (ChatOpenAI)
├── gemini_provider.py     # GeminiProvider (ChatGoogleGenerativeAI)
├── anthropic_provider.py  # AnthropicProvider (ChatAnthropic)
└── ollama_provider.py     # OllamaProvider (ChatOllama)
```

### Step-by-Step: Creating & Registering a New Provider (e.g., Mistral or Azure OpenAI)

1. **Create `backend/app/LLM_Providers/my_custom_provider.py` subclassing `BaseLLMProvider`:**

```python
from typing import Any, Optional, Type
from pydantic import BaseModel
from app.LLM_Providers.base import BaseLLMProvider


class MyCustomProvider(BaseLLMProvider):
    provider_name = "my_custom_llm"

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def get_structured_output_runnable(
        self,
        schema: Type[BaseModel],
        use_fallback: bool = False,
        model_override: Optional[str] = None,
    ) -> Any:
        target_model = model_override or (
            self.fallback_model_name if use_fallback else self.primary_model_name
        )
        # Instantiate your LangChain ChatModel and bind `.with_structured_output(schema, include_raw=True)`
        llm = ...
        return llm.with_structured_output(schema, include_raw=True)

    async def summarize_chunk(self, system_prompt: str, chunk_text: str) -> str:
        # Summarize middle transcript chunks for >10,000-token tickets
        return ...
```

2. **Register it in [`backend/app/LLM_Providers/registry.py`](file:///workspaces/codespaces-blank/myapps-anti/Customer%20Support%20Ticket%20Summarization%20&%20Agent%20QA%20Platform/backend/app/LLM_Providers/registry.py):**

```python
from app.LLM_Providers.registry import LLMProviderRegistry
from app.LLM_Providers.my_custom_provider import MyCustomProvider

LLMProviderRegistry.register_provider("my_custom_llm", MyCustomProvider)
```

3. **Activate it in `backend/.env`:**
```env
LLM_PROVIDER="my_custom_llm"
```

---

## 9. User Walkthrough & Automated Testing Guide

### Running the Full Automated Verification Suites

#### 1. Backend Pytest Suite (38 End-to-End Tests across Phases 1–5 + Multi-LLM Provider Registry)
```bash
pytest -v
```

#### 2. Frontend Vitest Unit Suite, TypeScript Check & Production Build
```bash
cd frontend
npm test
npx tsc --noEmit
npm run build
```
