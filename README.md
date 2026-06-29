# HSK Flashcard Wordlist API (V2)

A robust, highly stable, and RAM-efficient REST API providing HSK (Hanyu Shuiping Kaoshi) vocabulary lists. Built on **FastAPI (Python)** and backed by an optimized **SQLite** database.

## 🔑 Dynamic API Key Management

V2 features **database-backed dynamic API Key Management**. Instead of checking against a single static environment variable, client keys are generated, verified, and revoked dynamically from the SQLite database.

- **Client Authorization**: Standard vocab endpoints check the HTTP header `X-API-KEY` against keys stored in SQLite. If a key is invalid or revoked, requests fail with a `401 Unauthorized` response.
- **Admin Control**: Creating, listing, and revoking keys is restricted to administrators using the `X-ADMIN-KEY` header.
- **Out-of-the-box Access**: For convenience, a Default Developer Key (`hsk_dev_secret_key`) is seeded automatically if the keys table is empty on startup.

---

## 🛠️ Technology Stack

- **Framework**: FastAPI (Python)
- **Database**: SQLite (Standard library `sqlite3` driver)
- **Log Engine**: Custom JSON structured middleware
- **Containerization**: Docker (optimized Multi-stage builds)

---

## 📁 Repository Structure

```text
├── app/
│   ├── __init__.py
│   ├── auth.py         # Dynamic authentication dependencies (X-API-KEY and X-ADMIN-KEY)
│   ├── database.py     # SQLite connection & database integrity lifecycle checks
│   ├── logger.py       # JSON structured logging and requests middleware
│   ├── main.py         # Core endpoints (Vocabulary endpoints and admin endpoints)
│   └── schemas.py      # Pydantic response models, pagination metadata, and admin request schemas
├── scripts/
│   └── build_db.py     # HSK vocab CSV-to-SQLite compiler
├── Dockerfile          # Multi-stage Docker build pipeline
├── hsk_vocab.csv       # Dataset (5,343 rows)
├── requirements.txt    # Python dependencies
├── .env.example        # Reference environment variables setup
└── README.md           # Documentation
```

---

## 💻 Local Setup

### 1. Prerequisites
- Python 3.11+
- [Optional] Docker

### 2. Run Locally
Copy the environment template:
```bash
cp .env.example .env
```

Install requirements:
```bash
pip install -r requirements.txt
```

Compile the vocabulary database:
```bash
python scripts/build_db.py
```

Run the development web server:
```bash
python -m uvicorn app.main:app --reload --port 8080
```
- Open Swagger Web Docs: [http://127.0.0.1:8080/docs](http://127.0.0.1:8080/docs)
- Public health check: [http://127.0.0.1:8080/health](http://127.0.0.1:8080/health)

---

## 🔒 Security Configurations

1. **Client Headers**: Send `X-API-KEY` header for all vocab endpoints.
   - Default local dev key: `hsk_dev_secret_key`
2. **Admin Headers**: Send `X-ADMIN-KEY` header to manage keys.
   - Configured via `ADMIN_KEY` environment variable (defaults to `hsk_admin_master_secret` in local dev).

---

## 📡 API Reference

### 1. Vocabulary Endpoints (Secured with client `X-API-KEY`)
- `GET /words`: Paginated retrieval of the entire wordlist (`?page=1&per_page=100`).
- `GET /words/{level}`: Paginated HSK vocabulary filtered by HSK Level (1-6).
- `GET /word/{word}`: Single word details search. Returns `404` if not found.
- `GET /random`: Returns a random word, optionally filtered by level (`?level=6`).

### 2. Admin Key Management (Secured with `X-ADMIN-KEY`)
- **Create Key**: `POST /admin/keys`
  - Body: `{"name": "Client App Name"}`
  - Returns the generated API key (starts with `hsk_key_...`).
- **List Keys**: `GET /admin/keys`
  - Returns all registered keys, active state, and timestamps.
- **Revoke Key**: `POST /admin/keys/{key_id}/revoke`
  - Instantly revokes a client key, blocking its future API access.

---

## ☁️ Deployment on Render.com

Since the platform manages API keys dynamically in SQLite:

1. Create a **Web Service** on Render and select the runtime as **Docker**.
2. **Environment Variables**:
   - Add `ADMIN_KEY`: Choose a secure master password (used in the `X-ADMIN-KEY` header).
3. **Database Persistence**:
   - Because Render containers have an ephemeral filesystem, SQLite writes will reset on redeployment or restart.
   - **Recommended**: Attach a **Persistent Disk** on Render (e.g., Mount Path `/data`). Set the `DB_PATH` environment variable to `/data/hsk_vocab.db` so database changes and API keys persist permanently.
