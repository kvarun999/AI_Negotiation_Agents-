# 🤝 AI Trade Negotiation Agent

A **multi-agent system** where two AI agents — representing the **USA** and **China** — negotiate a bilateral trade agreement over configurable rounds. Built with [FastAPI](https://fastapi.tiangolo.com/), [Ollama](https://ollama.ai/) (local LLM), and [Docker](https://www.docker.com/).

---

## ✨ Features

| Feature | Details |
|---|---|
| **Multi-Agent Negotiation** | USA & China AI agents take turns making proposals and counter-proposals |
| **Chain-of-Thought Prompting** | Each agent reasons step-by-step before generating a proposal |
| **Local LLM (Privacy-First)** | Powered by Ollama + Llama 3 — no data leaves your machine |
| **Configurable Rounds** | 1–20 negotiation rounds per request |
| **Compromise Scoring** | Heuristic scorer analyses keyword signals, topic coverage & history depth |
| **State Persistence** | Every negotiation is appended to `negotiation_log.json` |
| **Fully Containerised** | Single `docker compose up` brings up everything |
| **Zero Hardcodes** | All settings are driven by environment variables |

---

## 🏗️ Architecture

```
Client (curl / Postman)
        │
        ▼
┌───────────────────────────────────────────────────────┐
│  FastAPI Orchestrator (port 8000)                     │
│                                                       │
│  POST /negotiate                                      │
│    ├── Load trade_positions.json  (volume mount)      │
│    ├── Round loop (1 … N):                            │
│    │     ├── USA Agent  ──► Ollama /api/generate      │
│    │     └── China Agent ──► Ollama /api/generate     │
│    ├── calculate_compromise(history, positions)       │
│    └── Append to negotiation_log.json (volume mount)  │
└───────────────────────┬───────────────────────────────┘
                        │ HTTP (internal Docker network)
                        ▼
         ┌──────────────────────────┐
         │  Ollama Service (11434)  │
         │  Model: llama3           │
         └──────────────────────────┘
```

---

## 📁 Project Structure

```
.
├── agents/
│   ├── __init__.py
│   └── negotiator.py         # Negotiator class — prompt engineering & LLM calls
├── data/
│   └── trade_positions.json  # Declarative priorities, flexibility, red-lines
├── tests/
│   ├── __init__.py
│   └── test_negotiation.py   # Pytest suite (unit + integration)
├── conftest.py               # Root pytest config — fixtures, markers, env setup
├── .dockerignore
├── .env.example              # Template for all environment variables
├── docker-compose.yml        # Orchestrates api + ollama services
├── Dockerfile                # FastAPI service image (python:3.11-slim)
├── main.py                   # FastAPI app — routing, orchestration, logging
├── requirements.txt          # Pinned Python dependencies
└── scoring.py                # Heuristic compromise scorer (0.0 – 1.0)
```

---

## 🚀 Quick Start (One Command)

### Prerequisites

| Requirement | Version |
|---|---|
| Docker Engine | ≥ 24 |
| Docker Compose | ≥ 2.20 (bundled with Docker Desktop) |

> **No Python installation required on your host.** Everything runs inside containers.

### 1. Clone and configure

```bash
git clone <your-repo-url> ai-negotiation-agent
cd ai-negotiation-agent
cp .env.example .env          # Review defaults — no changes needed for local use
```

### 2. Start all services

```bash
docker compose up --build
```

This single command:
- Builds the FastAPI API image from `Dockerfile`
- Pulls `ollama/ollama:latest`
- Starts both containers on an isolated Docker network
- Waits for Ollama to pass its health-check before starting the API

> ⏱️ **First run:** The build takes ~2 minutes. Subsequent starts are instant.

### 3. Pull the language model (first time only)

In a **new terminal**, while the containers are running:

```bash
docker compose exec ollama ollama pull llama3
```

> This downloads ~4.7 GB. Once pulled, the model is cached in the `ollama_data` Docker volume and does not need to be re-downloaded.

### 4. Verify the API is healthy

```bash
curl http://localhost:8000/health
# → {"status":"ok","service":"AI Trade Negotiation API"}
```

---

## 🔌 API Reference

### `POST /negotiate`

Starts a multi-round AI negotiation between the USA and China agents.

**Request body**

```json
{
  "issue": "Technology Tariffs",
  "rounds": 3
}
```

| Field | Type | Required | Default | Constraints |
|---|---|---|---|---|
| `issue` | string | ✅ | — | 3–512 characters |
| `rounds` | integer | ❌ | `3` | 1–20 |

**Success response `200 OK`**

```json
{
  "rounds": [
    {
      "round": 1,
      "usa_proposal": "The United States proposes reducing tariffs on technology products...",
      "china_response": "China accepts the framework and requests greater market access..."
    },
    ...
  ],
  "outcome": {
    "agreement_reached": true,
    "final_terms": "After 3 round(s) on 'Technology Tariffs': USA final position — ...",
    "compromise_score": 0.7241
  }
}
```

| Field | Type | Description |
|---|---|---|
| `rounds` | array | One object per negotiation round |
| `rounds[n].round` | integer | 1-indexed round number |
| `rounds[n].usa_proposal` | string | USA agent's proposal text |
| `rounds[n].china_response` | string | China agent's response text |
| `outcome.agreement_reached` | boolean | `true` if `compromise_score ≥ AGREEMENT_THRESHOLD` |
| `outcome.final_terms` | string | Human-readable summary of final positions |
| `outcome.compromise_score` | float | Normalised score in `[0.0, 1.0]` |

### Example `curl` calls

```bash
# 3-round negotiation on technology tariffs
curl -X POST http://localhost:8000/negotiate \
  -H "Content-Type: application/json" \
  -d '{"issue": "Technology Tariffs", "rounds": 3}'

# Single-round negotiation on agricultural subsidies
curl -X POST http://localhost:8000/negotiate \
  -H "Content-Type: application/json" \
  -d '{"issue": "Agricultural Subsidies", "rounds": 1}'

# Health check
curl http://localhost:8000/health
```

### Interactive API docs

FastAPI's auto-generated docs are available at:

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

---

## ⚙️ Configuration

All configuration is supplied via environment variables. Copy `.env.example` to `.env` and adjust as needed.

| Variable | Default | Description |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://ollama:11434` | Ollama service URL (use service name inside Docker) |
| `OLLAMA_MODEL` | `llama3` | Ollama model identifier |
| `LLM_TEMPERATURE` | `0.3` | Sampling temperature (`0.0` = deterministic, `1.0` = creative) |
| `OLLAMA_TIMEOUT` | `120` | HTTP timeout in seconds for each LLM call |
| `AGREEMENT_THRESHOLD` | `0.5` | Minimum `compromise_score` for `agreement_reached: true` |
| `LOG_FILE_PATH` | `/app/logs/negotiation_log.json` | Path where negotiation log is written inside the container |
| `TRADE_POSITIONS_PATH` | `data/trade_positions.json` | Path to the trade positions data file |

> **Security note:** Never commit your `.env` file. The `.gitignore` / `.dockerignore` exclude it.  
> `.env.example` contains only placeholder values — no secrets.

---

## 🧪 Running Tests

### Unit tests (no Ollama required)

```bash
# Inside the running container
docker compose exec api pytest tests/ -v

# Or locally (requires Python 3.11+ and dependencies installed)
pip install -r requirements.txt
pytest tests/ -v
```

### Integration tests (requires live Ollama + model)

```bash
docker compose exec api pytest tests/ -v --integration
```

### Test coverage summary

| Test Class | What it validates |
|---|---|
| `TestNegotiateEndpointSchema` | HTTP 200, `rounds` and `outcome` keys present |
| `TestRoundsCount` | `len(rounds) == requested_rounds` for 1, 3, 5 rounds |
| `TestRoundObjectSchema` | Each round has `round` (int), `usa_proposal` (str), `china_response` (str) |
| `TestOutcomeSchema` | `agreement_reached` (bool), `final_terms` (str), `compromise_score` (float) |
| `TestPriorityKeywordCoverage` | USA proposals contain tariff/IP terms; China proposals contain market-access/tech-transfer terms |
| `TestCalculateCompromise` | Pure unit tests for the scoring heuristic |
| `TestHealthEndpoint` | `GET /health` returns `{"status": "ok"}` |
| `TestInputValidation` | Missing `issue` → 422; `rounds=0` → 422; `rounds=25` → 422 |
| `TestLiveNegotiation` *(integration)* | End-to-end negotiation against a real Ollama instance |

---

## 🔬 Implementation Details

### Agent Prompting Strategy

Each `Negotiator` agent is given:
- A **persona** (`You are the chief trade negotiator for USA/CHINA`)
- **Priorities** — loaded dynamically from `data/trade_positions.json`
- **Red lines** — items that must never be conceded
- **Flexibility scores** — per-topic willingness to move
- **Chain-of-Thought instruction** — agents output `REASONING:` then `PROPOSAL:`

The `_extract_proposal()` method strips the reasoning section, ensuring only clean diplomatic text enters the negotiation history.

### Compromise Scoring (`scoring.py`)

| Factor | Weight | Description |
|---|---|---|
| Concession keyword ratio | 45% | Ratio of concession words (agree, accept, reduce…) to combative words (reject, insist, ultimatum…) |
| Priority topic coverage | 35% | Fraction of each country's priority topics mentioned across their proposals |
| History length bonus | 20% | Logarithmic bonus — longer negotiations have more opportunity to converge |

Final score is clamped to `[0.0, 1.0]`.

### Resilience

- **3-attempt exponential back-off** for Ollama timeouts, connection errors, and 5xx responses
- **4xx errors are non-retriable** (bad request — retrying won't help)
- Log write failures are caught and logged but never abort the API response

---

## 🐳 Docker Commands Reference

```bash
# Start (build on first run)
docker compose up --build

# Start in background
docker compose up -d

# View logs
docker compose logs -f api
docker compose logs -f ollama

# Run tests
docker compose exec api pytest tests/ -v

# Inspect the negotiation log
docker compose exec api cat /app/logs/negotiation_log.json

# Stop and remove containers (volumes preserved)
docker compose down

# Stop and remove everything including volumes
docker compose down -v

# Pull a different model
docker compose exec ollama ollama pull mistral
```

---

## 🔄 Changing the Negotiation Topic or Positions

All agent behaviour is driven by `data/trade_positions.json`. To switch from *Technology Tariffs* to *Agricultural Subsidies*, simply update the JSON file — no code changes required:

```json
{
  "usa": {
    "priorities": ["Increase soybean exports", "Remove agricultural tariff barriers"],
    "flexibility": { "soybean_exports": 0.8, "ag_tariffs": 0.6 },
    "red_lines": ["No restrictions on GMO product exports"]
  },
  "china": { ... }
}
```

Then restart the API container:

```bash
docker compose restart api
```

---

## 📜 License

MIT — see `LICENSE` for details.
