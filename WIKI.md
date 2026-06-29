# Project Wiki: Robust HSK Flashcard Wordlist API (V2)

Welcome to the HSK Flashcard Wordlist API project wiki. This documentation details the system design, database structures, integration workflows, security policies, and deployment instructions.

---

## 📖 Table of Contents
1. [System Overview & Architecture](#-system-overview--architecture)
2. [Database Schema Specification](#-database-schema-specification)
3. [API Endpoint Reference](#-api-endpoint-reference)
   - [System Endpoints](#system-endpoints)
   - [Vocabulary Endpoints](#vocabulary-endpoints)
   - [Admin Key Management](#admin-key-management-endpoints)
   - [Real-Time Sync Webhook](#real-time-sync-webhook)
4. [Security & Access Control](#-security--access-control)
5. [Data Sync Pipeline Workflows](#-data-sync-pipeline-workflows)
6. [Deployment Guide (Render.com + Docker)](#-deployment-guide-rendercom--docker)

---

## 🏗️ System Overview & Architecture

The system functions as a high-performance **Middleware/Data Pipeline (ETL)** and **API Hub**. It extracts raw, bilingual vocabulary records from a remote database (Supabase), compiles them into an optimized local cache (SQLite), and serves this data to third-party clients via secured, paginated REST endpoints.

```text
    ┌────────────────┐
    │  Supabase DB   │  (Remote master dataset)
    └───────┬────────┘
            │ 1. ETL Extraction (export_csv.py / webhook sync)
            ▼
    ┌───────────────┐
    │ hsk_vocab.csv │  (Intermediate CSV file)
    └───────┬───────┘
            │ 2. Compile & Optimize (build_db.py)
            ▼
    ┌───────────────┐
    │ hsk_vocab.db  │  (Indexed SQLite database)
    └───────┬───────┘
            │ 3. Query & Serve (FastAPI)
            ▼
   Third-Party Clients (Authorized via header: X-API-KEY)
```

### Key Architectural Benefits
- **Zero-Latency Queries**: By querying a local SQLite database (compiled with unique index mappings) instead of calling remote databases, query execution durations average under **3ms**.
- **Supabase API Protection**: Saves Supabase cloud bandwidth and database connection pools.
- **Dynamic Key Management**: Clients are authorized individually using keys stored in the database, allowing admins to revoke or generate keys in real-time.

---

## 🗄️ Database Schema Specification

The SQLite database (`hsk_vocab.db`) contains three main tables:

### 1. `words` Table
Stores HSK vocabulary records and their translations.
- `id` (INTEGER, Primary Key): Unique word ID.
- `word` (TEXT, Unique Index): The Chinese characters.
- `pinyin` (TEXT): Pronunciation guide.
- `definition` (TEXT): English translation.
- `definition_th` (TEXT): Thai translation.
- `level` (INTEGER, Indexed): HSK Level (1 to 6). Nullable for anomalous entries.
- `example_sentence` (TEXT): Example Chinese sentence.
- `example_pinyin` (TEXT): Pinyin for the example sentence.

### 2. `metadata` Table
Stores compiled metrics for data integrity checks.
- `key` (TEXT, Primary Key): e.g., `'expected_records'`.
- `value` (TEXT): Value of the metric (e.g., target row count `'5343'`).

### 3. `api_keys` Table
Stores dynamic client access credentials.
- `id` (INTEGER, Primary Key, Auto-increment)
- `key` (TEXT, Unique Index): Secure key string (e.g., `hsk_key_...`).
- `name` (TEXT): Identifier for the client app (e.g., `"iOS App Client"`).
- `is_active` (INTEGER): `1` for active, `0` for revoked.
- `created_at` (DATETIME, default current timestamp)
- `revoked_at` (DATETIME): Timestamp when key was deactivated.

---

## 📡 API Endpoint Reference

### System Endpoints

#### `GET /health`
Public endpoint checking API and database connectivity.
- **Request Headers**: None required.
- **Response (200 OK)**:
  ```json
  {
    "status": "healthy",
    "database_records": 5343
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
Create a new API Key for a third-party client.
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
List all generated API keys.
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
Immediately revoke a key, blocking all future queries from that client.
- **Path Parameters**:
  - `key_id` (int): Database ID of the key to revoke.
- **Response (200 OK)**:
  ```json
  {
    "message": "Successfully revoked API Key with ID 2."
  }
  ```

---

### Real-Time Sync Webhook

#### `POST /webhook/supabase`
Triggers a background task to sync vocab and translations from Supabase in real-time.
- **Query Parameters**:
  - `secret` (str, required): Valid webhook secret token.
- **Trigger event**: Connect this to Supabase Database Webhooks.
- **Response (200 OK)**:
  ```json
  {
    "message": "Synchronization triggered in background."
  }
  ```
  *(The sync runs safely in the background using FastAPI's background workers, preventing Supabase webhook connection timeouts).*

---

## 🔒 Security & Access Control

1. **Supabase Protection (RLS)**: The remote database is secured using Postgres Row-Level Security (RLS). The public anon key is restricted to read-only (`SELECT`) actions. Write or delete commands are blocked.
2. **Administrative Access**: Admin endpoints are locked under the `X-ADMIN-KEY` master secret, configurable via environmental variables.
3. **Client Authentication**: Vocab endpoints query the SQLite database dynamically. Revoked keys immediately block access.
4. **Data Integrity Checks**: Enforces a safety threshold (at least `5,300` records). If a corrupted or truncated export occurs, the server blocks compilation and prevents deployment crashes.

---

## 🔄 Data Sync Pipeline Workflows

When wordlists are updated on Supabase:

```text
    Supabase DB Update
            │
            ▼  (Triggered automatically)
    Supabase Webhook calls POST /webhook/supabase?secret=...
            │
            ▼
    FastAPI Webhook verified -> spawns Background Task
            │
            ▼
    Background Task:
      1. Downloads all vocab_hsk records
      2. Downloads all vocab_translations (EN & TH)
      3. Performs dataset merge in memory
      4. Rewrites hsk_vocab.csv & hsk_vocab.db (words & metadata tables)
            │
            ▼
    Database dynamically updated in-place (Zero-Downtime)
```

---

## ☁️ Deployment Guide (Render.com + Docker)

To deploy the API Hub on Render:

1. Create a **Web Service** and choose **Runtime**: `Docker`.
2. Connect your Git repository.
3. **Environment Variables**:
   - `ADMIN_KEY`: Set your master admin key (locks `/admin` endpoints).
   - `WEBHOOK_SECRET`: Set your webhook secret key (used for Supabase webhook triggers).
   - `DB_PATH`: `/data/hsk_vocab.db` (Target path on the persistent disk).
4. **Persistent Disk (Required)**:
   - Go to **Disks** in Render dashboard.
   - Click **Add Disk**: Name: `sqlite-data`, Mount Path: `/data`, Size: `1 GB`.
   - *This ensures API keys generated dynamically in SQLite persist across server restarts.*
