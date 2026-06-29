# --- Stage 1: Build SQLite DB and compile dependencies ---
FROM python:3.11-slim AS builder

WORKDIR /app

# Install build dependencies if needed
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Install dependencies in user space to easily copy them to the next stage
RUN pip install --no-cache-dir --user -r requirements.txt

# Copy dataset and database construction scripts
COPY hsk_vocab.csv .
COPY scripts/build_db.py scripts/

# Execute database conversion and check row integrity (aborts build if failed)
RUN python scripts/build_db.py

# --- Stage 2: Production runner ---
FROM python:3.11-slim AS runner

WORKDIR /app

# Copy the verified database and application code
COPY --from=builder /app/hsk_vocab.db .
COPY --from=builder /root/.local /root/.local
COPY app/ app/

# Configure paths and system environment
ENV PATH=/root/.local/bin:$PATH
ENV PYTHONUNBUFFERED=1

# Expose port (Render exposes dynamically, but 8000 is default local fallback)
EXPOSE 8000

# Run uvicorn server, dynamically mapping port from PORT environment variable
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
