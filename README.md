# HSK Flashcard Wordlist API (V3 - RAM Cache Edition)

A robust, ultra-fast, and stateless REST API providing HSK (Hanyu Shuiping Kaoshi) vocabulary lists. Built on **FastAPI (Python)**, optimized for high performance, and runs entirely in memory (RAM).

---

## ⚡ RAM Cache & Stateless Architecture

In V3, the API operates as a fully **stateless service**, bypassing disk-write delays and database locking during client requests:

- **In-Memory Caches**: Active API keys and the entire HSK vocabulary dataset are pulled from Supabase and cached in RAM (as Python sets and dictionaries) during the startup lifecycle.
- **Zero-Latency Authentication & Queries**: All vocabulary lookups, level filters, and client API key verifications are performed in sub-milliseconds ($< 0.5\text{ms}$) directly in RAM.
- **Real-time Webhook Synchronization**:
  - `/webhook/supabase`: Receives dataset change notifications from Supabase and refreshes the vocabulary RAM cache in-place (with a 10-second debounce window to prevent duplicate writes).
  - `/webhook/keys`: Receives API key status changes (creation, revocation) and reloads active keys in memory instantly.
- **Robust Fallback**: If Supabase is unreachable at startup, the system automatically falls back to loading vocabulary from the pre-packaged static `hsk_vocab.csv` file to guarantee 100% uptime.

---

## 🛠️ Technology Stack

- **Core Framework**: FastAPI (Python 3.11+)
- **Memory Engine**: Python in-memory data structures (Sets / Dictionaries)
- **Unit Testing**: Pytest & HTTPX
- **Automation Pipeline**: GitHub Actions
- **Containerization**: Docker (optimized Multi-stage builds)

---

## 📁 Repository Structure

```text
├── .github/workflows/
│   ├── ci.yml            # CI: runs tests on every push and PR
│   └── keep_alive.yml    # Cron: pings server every 10m to prevent Render sleep
├── app/
│   ├── auth.py           # In-memory API Keys cache and verification
│   ├── database.py       # Local SQLite schema & connection utility
│   ├── logger.py         # JSON structured logging middleware
│   ├── main.py           # Core endpoints, webhooks, and lifecycles
│   ├── schemas.py        # Pydantic schemas and response metadata
│   └── vocab_cache.py    # Vocabulary RAM cache & loader utilities
├── scripts/
│   ├── build_db.py       # CSV-to-SQLite compiler (build-time check)
│   └── update_git_backup.py # Supabase-to-Git backup sync script
├── tests/
│   └── test_api.py       # Integration & endpoint test suite
├── Dockerfile            # Multi-stage production Docker build
├── hsk_vocab.csv         # Local vocabulary fallback (5,343 rows)
├── requirements.txt      # Production & development dependencies
└── WIKI.md               # Detailed system documentation
```

---

## 💻 Local Setup & Testing

### 1. Prerequisites
- Python 3.11+
- Git

### 2. Installation
Copy the environment variables template:
```bash
cp .env.example .env
```

Install dependencies:
```bash
pip install -r requirements.txt
```

Compile the local database backup:
```bash
python scripts/build_db.py
```

### 3. Run Development Server
```bash
python -m uvicorn app.main:app --reload --port 8080
```
- Interactive Swagger Docs: [http://127.0.0.1:8080/docs](http://127.0.0.1:8080/docs)
- Public Health Check: [http://127.0.0.1:8080/health](http://127.0.0.1:8080/health)

### 4. Run Automated Tests
Execute the local pytest suite to verify endpoint integrity:
```bash
python -m pytest
```

---

## 🤖 Automated CI/CD & Maintenance (GitHub Actions)

1. **FastAPI Test CI (`ci.yml`)**: Runs `pytest` on every push/PR to `main`. Deployments are blocked if tests fail.
2. **Weekly Sync & Backup (`sync_backup.yml`)**: Runs every Sunday at 00:00 UTC to pull data from Supabase, export to CSV/SQLite, and commit back to Git as a fresh static fallback.
3. **Keep Alive (`keep_alive.yml`)**: Pings the `/health` endpoint every 10 minutes to prevent the Render Free Tier instance from spinning down.

---

## ☁️ Deployment on Render.com

Because all dynamic operations execute in RAM, **Render persistent disks are NOT required**. The API runs on a fully stateless Docker web service:

1. Create a **Web Service** on Render and choose runtime: **Docker**.
2. **Environment Variables**:
   - `ADMIN_KEY`: Set your master secret for `/admin` endpoints.
   - `WEBHOOK_SECRET`: Set your webhook validation token.
   - `SUPABASE_URL`: Your Supabase REST API URL.
   - `SUPABASE_ANON_KEY`: Your Supabase anonymous public key.
3. **Single Worker Process**: The application is explicitly configured to run as a single Uvicorn worker process (`--workers 1`) to guarantee RAM cache consistency across web requests.
