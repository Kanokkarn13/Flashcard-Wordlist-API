# Project Wiki: In-Memory HSK Flashcard Wordlist API (V2)

Welcome to the HSK Flashcard Wordlist API project wiki. This documentation details the system design, in-memory structures, API endpoints, security configurations, and stateless deployment workflows.

---

## 📖 Table of Contents
1. [System Overview & Architecture](#-system-overview--architecture)
2. [Data Schema & Caching Specification](#-data-schema--caching-specification)
3. [API Endpoint Reference](#-api-endpoint-reference)
   - [System Endpoints](#system-endpoints)
   - [Vocabulary Endpoints](#vocabulary-endpoints)
   - [Admin Key Management](#admin-key-management-endpoints)
   - [Real-Time Sync Webhooks](#real-time-sync-webhooks)
4. [Security & Access Control](#-security--access-control)
5. [Data Sync Pipeline Workflows](#-data-sync-pipeline-workflows)
6. [Deployment Guide (Stateless Docker)](#-deployment-guide-stateless-docker)

---

## 🏗️ System Overview & Architecture

The system functions as a high-performance **In-Memory Middleware & API Hub**. Instead of querying SQLite or external databases on every request, the application loads the complete vocabulary dataset and active API keys directly into FastAPI's memory (RAM) cache on startup.

```text
                             ┌────────────────┐
                             │  Supabase DB   │  (Master Vocabulary & Keys)
                             └───────┬────────┘
                                     │
                    ┌────────────────┴────────────────┐
                    │ 1. Startup Event / Webhooks     │ (Pulls active keys & vocabulary)
                    ▼                                 ▼
         ┌─────────────────────┐           ┌─────────────────────┐
         │ Vocabulary Cache    │           │   API Keys Cache    │ (In-memory RAM Cache)
         │ (Dict / List in RAM)│           │ (Dict / Set in RAM) │
         └──────────┬──────────┘           └──────────┬──────────┘
                    │                                 │
                    └────────────────┬────────────────┘
                                     │ 2. O(1) Memory Verification & Query
                                     ▼
                            ┌────────────────┐
                            │    FastAPI     │
                            └───────┬────────┘
                                    │ 3. Instant responses
                                    ▼
                           Third-Party Clients (Authorized via header: X-API-KEY)
```

### Key Architectural Benefits
- **Zero-Latency Queries**: By querying in-memory caches (using Python dictionary lookups and pre-built level index arrays), query execution durations average under **0.5ms**.
- **Supabase Bandwidth Protection**: Saves Supabase cloud bandwidth and database connection pools by loading keys and vocabulary only once at startup or on explicit webhook reload triggers.
- **Dynamic Key Cache Management**: Active API keys are verified locally against RAM cache (reducing authentication latency and Supabase select calls to **zero**).
- **Stateless & Robust**: The server can run in fully stateless containers. If Supabase is unreachable at startup, the system automatically falls back to loading vocabulary from the local `hsk_vocab.csv` file.

### ⚠️ Single-Worker Process Constraint
Because all vocabulary and API key caches are stored in the local FastAPI application process RAM, **the server must run as a single worker process (`--workers 1`)**. 

If you run Gunicorn/Uvicorn with multiple workers, each worker will run in an isolated process with its own separate memory space. A webhook signal to reload caches would only update one worker, leaving the other workers with stale data. 

If scaling to multi-instance/multi-worker is required in the future, the memory caches should be migrated to a centralized store like Redis.

---

## 🗄️ Data Schema & Caching Specification

Although the SQLite database (`hsk_vocab.db`) is compiled during the Docker build stage as a dataset sanity check, the live API application loads all vocabulary and active API keys directly into RAM caches:

### 1. In-Memory Vocabulary Cache (`vocab_cache`)
Stores vocabulary records for fast queries:
- **`_words`**: List of all words sorted by `id` (facilitates fast `O(1)` list pagination).
- **`_words_by_word`**: Dictionary mapping characters to word details (provides `O(1)` detail lookup).
- **`_words_by_level`**: Dictionary mapping HSK levels (1-6) to their lists of words.

### 2. In-Memory API Keys Cache (`api_keys_cache`)
Stores authorized credentials for zero-latency client authentication:
- Maps the API key string directly to key metadata: `{"id": id, "key": key, "name": name, "is_active": True}`.
- Allows developer-friendly local verification via seeded development credentials (e.g. `hsk_dev_secret_key`).

### 3. Fallback CSV Cache (`hsk_vocab.csv`)
An intermediate local CSV cache file that is bundled with the Docker runner image. If the remote Supabase API is offline during server boot, the lifespan event automatically reads this file to populate the memory cache, guaranteeing server startup success.

---

## 📡 API Endpoint Reference

### System Endpoints

#### `GET /health`
Public health status checker.
- **Request Headers**: None required.
- **Response (200 OK)**:
  ```json
  {
    "status": "healthy",
    "cache_records": 5343
  }
  ```

---

### Vocabulary Endpoints
*All vocabulary endpoints require the client header: `X-API-KEY: <your_key_here>`*

#### `GET /words`
Retrieve paginated HSK words.
- **Query Parameters**:
  - `page` (int, default: 1): Active page.
  - `per_page` (int, default: 100, max: 1000): Items per page.
- **Response (200 OK)**:
  ```json
  {
    "metadata": {
      "total_records": 5343,
      "total_pages": 54,
      "page": 1,
      "per_page": 100,
      "has_next": true,
      "has_previous": false
    },
    "data": [
      {
        "id": 1,
        "word": "包",
        "pinyin": "Bāo, bāo",
        "definition": "bag; package; to wrap; to include",
        "definition_th": "กระเป๋า; ห่อ; รวม",
        "level": 1,
        "example_sentence": "我有一个包。",
        "example_pinyin": "Wǒ yǒu yī gè bāo."
      }
    ]
  }
  ```

#### `GET /words/{level}`
Retrieve paginated vocabulary matching an HSK level.
- **Path Parameters**:
  - `level` (int, 1-6): The HSK level.
- **Query Parameters**:
  - `page` (int, default: 1)
  - `per_page` (int, default: 100)

#### `GET /word/{word}`
Search details for a specific word. Returns `404` if not found.
- **Path Parameters**:
  - `word` (str): Chinese characters to query.

#### `GET /random`
Fetch a random HSK word.
- **Query Parameters**:
  - `level` (int, optional): Restrict random selection to a specific level (1-6).

---

### Admin Key Management Endpoints
*All key management endpoints require the header: `X-ADMIN-KEY: <master_secret_here>`*

#### `POST /admin/keys`
Create a new API Key for a third-party client. Generates a key, writes to Supabase, and reloads the API keys RAM cache in the background.
- **Request Body**:
  ```json
  {
    "name": "iOS Mobile Application"
  }
  ```
- **Response (201 Created)**:
  ```json
  {
    "id": 2,
    "key": "hsk_key_5d2a3f789abcde...",
    "name": "iOS Mobile Application",
    "is_active": true,
    "created_at": "2026-06-30 02:44:00",
    "revoked_at": null
  }
  ```

#### `GET /admin/keys`
List all generated API keys stored in Supabase.
- **Response (200 OK)**:
  ```json
  [
    {
      "id": 1,
      "key": "hsk_dev_secret_key",
      "name": "Default Developer Key",
      "is_active": true,
      "created_at": "2026-06-30 02:00:00",
      "revoked_at": null
    }
  ]
  ```

#### `POST /admin/keys/{key_id}/revoke`
Immediately revoke a key in Supabase, and trigger a background RAM keys cache refresh to apply deactivation instantly.
- **Path Parameters**:
  - `key_id` (int): Database ID of the key to revoke.
- **Response (200 OK)**:
  ```json
  {
    "message": "Successfully revoked API Key with ID 2."
  }
  ```

#### `POST /admin/keys/reload`
Manually trigger a reload of all active API keys from Supabase REST API into the memory cache.
- **Response (200 OK)**:
  ```json
  {
    "message": "Successfully reloaded API keys. Currently cached: 1 keys."
  }
  ```

---

### Real-Time Sync Webhooks

#### `POST /webhook/supabase`
Receives database change notifications for vocabulary tables from Supabase, and triggers a 10-second debounced sync process to rewrite file caches and update the in-memory vocabulary RAM cache.
- **Query Parameters**:
  - `secret` (str, required): Valid webhook secret token.

#### `POST /webhook/keys`
Receives API keys change notifications from Supabase, triggering an instant reload of active API keys into the RAM cache.
- **Query Parameters**:
  - `secret` (str, required): Valid webhook secret token.

---

## 🔒 Security & Access Control

1. **Supabase Protection (RLS)**: The remote database is secured using Postgres Row-Level Security (RLS). The public anon key is restricted to read-only (`SELECT`) actions.
2. **Administrative Access**: Admin endpoints are locked under the `X-ADMIN-KEY` master secret, configurable via environment variables.
3. **Client Authentication**: Client requests check API keys inside the RAM dictionary first. No database requests are performed during authentication. Invalid keys are rejected instantly.
4. **Data Integrity Checks**: Enforces a safety threshold (at least `5,300` records). If the remote dataset is invalid or Supabase is unreachable, it logs a warning and falls back to loading from `hsk_vocab.csv` to prevent startup crashes.
5. **Race Condition Prevention**: Uses a global async lock (`sync_lock`) in the sync pipeline to prevent concurrent write tasks, ensuring RAM caches are updated sequentially even if overlapping webhooks trigger.

---

## 🔄 Data Sync Pipeline Workflows

When wordlists or keys are updated on Supabase:

```text
     Supabase DB Update
             │
             ▼  (Triggered automatically)
     Supabase Webhook calls POST /webhook/supabase?secret=... or POST /webhook/keys?secret=...
             │
             ▼
     FastAPI Webhook verified -> spawns Background Task
             │
             ▼
     Background Task:
       1. Downloads all vocab_hsk & vocab_translations records (or active keys list)
       2. Performs dataset merge in memory
       3. Dynamically updates vocabulary/keys RAM cache in place
             │
             ▼
     RAM Cache dynamically updated (Zero-Downtime, Instant reflection)
```

---

## ☁️ Deployment Guide (Stateless Docker)

To deploy the API Hub on Render:

1. Create a **Web Service** and choose **Runtime**: `Docker`.
2. Connect your Git repository.
3. **Environment Variables**:
   - `ADMIN_KEY`: Set your master admin key (locks `/admin` endpoints).
   - `WEBHOOK_SECRET`: Set your webhook secret key (used for Supabase webhook triggers).
   - `SUPABASE_URL`: Supabase URL endpoint.
   - `SUPABASE_ANON_KEY`: Supabase client anonymous public key.
4. **No Persistent Disk Required**:
   - Because the keys and wordlists are loaded dynamically from Supabase into memory, Render persistent disks are **NOT** required. The application can run on fully stateless web services.
5. **Single-Worker Process**:
   - The application must run as a single Uvicorn worker process to ensure in-memory cache consistency (this is explicitly configured inside the Dockerfile with `--workers 1`). Do not configure multi-worker orchestration on the server unless using a shared external cache like Redis.
