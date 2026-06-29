import math
import secrets
from contextlib import asynccontextmanager
from typing import Optional
from fastapi import FastAPI, Depends, HTTPException, Query, Path, status

from app.database import verify_db_integrity, get_db_connection
from app.auth import verify_api_key, verify_admin_key
from app.logger import StructuredLoggingMiddleware
from app.schemas import PaginatedResponse, WordSchema, PaginationMetadata, KeyCreateSchema, KeyResponseSchema

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle events manager for the FastAPI application."""
    # Run database integrity checks on startup
    verify_db_integrity()
    yield
    # Cleanup on shutdown (if needed)

app = FastAPI(
    title="Robust HSK Flashcard Wordlist API",
    description=(
        "A highly stable, RAM-efficient REST API providing HSK vocabulary lists. "
        "Built on SQLite with optimized indexing. Authenticate using the `X-API-KEY` header."
    ),
    version="2.0.0",
    lifespan=lifespan
)

# Apply structured logging middleware to all requests
app.add_middleware(StructuredLoggingMiddleware)

# --- SYSTEM ENDPOINTS ---

@app.get("/health", summary="Health Check", tags=["System"])
async def health_check():
    """
    Public health check endpoint.
    Verifies that the application can query the underlying SQLite database.
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM words")
            count = cursor.fetchone()[0]
        return {
            "status": "healthy",
            "database_records": count
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"System unhealthy: Database connection error: {e}"
        )

# --- BUSINESS ENDPOINTS (SECURED) ---

@app.get(
    "/words",
    response_model=PaginatedResponse,
    summary="Get paginated word list",
    tags=["Vocabulary"],
    dependencies=[Depends(verify_api_key)]
)
async def get_words(
    page: int = Query(1, ge=1, description="The active page index (1-based)"),
    per_page: int = Query(100, ge=1, le=1000, description="Count of words to return per page (max 1000)")
):
    """
    Retrieve a paginated list of HSK vocabulary words.
    Requires `X-API-KEY` authorization.
    """
    offset = (page - 1) * per_page
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Get total records count
        cursor.execute("SELECT COUNT(*) FROM words")
        total_records = cursor.fetchone()[0]
        
        # Query matching records
        cursor.execute(
            "SELECT id, word, pinyin, definition, definition_th, level, example_sentence, example_pinyin "
            "FROM words ORDER BY id LIMIT ? OFFSET ?",
            (per_page, offset)
        )
        rows = cursor.fetchall()
        
    total_pages = math.ceil(total_records / per_page) if total_records > 0 else 0
    
    metadata = PaginationMetadata(
        total_records=total_records,
        total_pages=total_pages,
        page=page,
        per_page=per_page,
        has_next=page < total_pages,
        has_previous=page > 1
    )
    
    data = [dict(row) for row in rows]
    return PaginatedResponse(metadata=metadata, data=data)

@app.get(
    "/words/{level}",
    response_model=PaginatedResponse,
    summary="Get words filtered by HSK level",
    tags=["Vocabulary"],
    dependencies=[Depends(verify_api_key)]
)
async def get_words_by_level(
    level: int = Path(..., ge=1, le=6, description="The HSK Level to filter (1 to 6)"),
    page: int = Query(1, ge=1, description="The active page index (1-based)"),
    per_page: int = Query(100, ge=1, le=1000, description="Count of words to return per page (max 1000)")
):
    """
    Retrieve a paginated list of HSK vocabulary words filtered by level (1 to 6).
    Requires `X-API-KEY` authorization.
    """
    offset = (page - 1) * per_page
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Get total records for level
        cursor.execute("SELECT COUNT(*) FROM words WHERE level = ?", (level,))
        total_records = cursor.fetchone()[0]
        
        # Query level-filtered records
        cursor.execute(
            "SELECT id, word, pinyin, definition, definition_th, level, example_sentence, example_pinyin "
            "FROM words WHERE level = ? ORDER BY id LIMIT ? OFFSET ?",
            (level, per_page, offset)
        )
        rows = cursor.fetchall()
        
    total_pages = math.ceil(total_records / per_page) if total_records > 0 else 0
    
    metadata = PaginationMetadata(
        total_records=total_records,
        total_pages=total_pages,
        page=page,
        per_page=per_page,
        has_next=page < total_pages,
        has_previous=page > 1
    )
    
    data = [dict(row) for row in rows]
    return PaginatedResponse(metadata=metadata, data=data)

@app.get(
    "/word/{word}",
    response_model=WordSchema,
    summary="Get details of a specific word",
    tags=["Vocabulary"],
    dependencies=[Depends(verify_api_key)]
)
async def get_word_detail(
    word: str = Path(..., description="The Chinese characters of the word to query")
):
    """
    Retrieve detailed parameters (HSK Level, translations, example sentences) for a specific word.
    Requires `X-API-KEY` authorization.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, word, pinyin, definition, definition_th, level, example_sentence, example_pinyin "
            "FROM words WHERE word = ? LIMIT 1",
            (word,)
        )
        row = cursor.fetchone()
        
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Word '{word}' not found in HSK vocabulary list."
        )
        
    return dict(row)

@app.get(
    "/random",
    response_model=WordSchema,
    summary="Get a random word",
    tags=["Vocabulary"],
    dependencies=[Depends(verify_api_key)]
)
async def get_random_word(
    level: Optional[int] = Query(None, ge=1, le=6, description="Optionally filter random word by HSK Level (1-6)")
):
    """
    Retrieve a random word from the HSK vocabulary pool.
    Optionally narrow the selection to a specific HSK level (1 to 6).
    Requires `X-API-KEY` authorization.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        if level is not None:
            cursor.execute(
                "SELECT id, word, pinyin, definition, definition_th, level, example_sentence, example_pinyin "
                "FROM words WHERE level = ? ORDER BY RANDOM() LIMIT 1",
                (level,)
            )
        else:
            cursor.execute(
                "SELECT id, word, pinyin, definition, definition_th, level, example_sentence, example_pinyin "
                "FROM words ORDER BY RANDOM() LIMIT 1"
            )
        row = cursor.fetchone()
        
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No words found matching selection criteria."
        )
        
    return dict(row)


# --- ADMIN KEY MANAGEMENT ENDPOINTS (SECURED WITH X-ADMIN-KEY) ---

@app.post(
    "/admin/keys",
    response_model=KeyResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new client API Key",
    tags=["Admin Key Management"],
    dependencies=[Depends(verify_admin_key)]
)
async def create_api_key(body: KeyCreateSchema):
    """
    Generate a new unique API key.
    Requires `X-ADMIN-KEY` authorization.
    """
    new_key = f"hsk_key_{secrets.token_hex(16)}"
    
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO api_keys (key, name, is_active) VALUES (?, ?, 1)",
                (new_key, body.name)
            )
            key_id = cursor.lastrowid
            conn.commit()
            
            # Fetch generated details to return
            cursor.execute(
                "SELECT id, key, name, is_active, created_at, revoked_at FROM api_keys WHERE id = ?",
                (key_id,)
            )
            row = cursor.fetchone()
            
        return dict(row)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate API Key: {e}"
        )

@app.get(
    "/admin/keys",
    response_model=list[KeyResponseSchema],
    summary="List all generated API Keys",
    tags=["Admin Key Management"],
    dependencies=[Depends(verify_admin_key)]
)
async def list_api_keys():
    """
    Retrieve all client API keys stored in SQLite.
    Requires `X-ADMIN-KEY` authorization.
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, key, name, is_active, created_at, revoked_at FROM api_keys ORDER BY id DESC"
            )
            rows = cursor.fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to query API keys database: {e}"
        )

@app.post(
    "/admin/keys/{key_id}/revoke",
    summary="Revoke an existing API Key",
    tags=["Admin Key Management"],
    dependencies=[Depends(verify_admin_key)]
)
async def revoke_api_key(
    key_id: int = Path(..., description="The unique database ID of the API Key to revoke")
):
    """
    Revoke a client API key. The key will immediately become unusable.
    Requires `X-ADMIN-KEY` authorization.
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Verify it exists
            cursor.execute("SELECT id, is_active FROM api_keys WHERE id = ?", (key_id,))
            row = cursor.fetchone()
            if not row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"API Key with ID {key_id} not found."
                )
                
            if not row["is_active"]:
                return {"message": f"API Key with ID {key_id} is already revoked."}
                
            # Perform revocation
            cursor.execute(
                "UPDATE api_keys SET is_active = 0, revoked_at = CURRENT_TIMESTAMP WHERE id = ?",
                (key_id,)
            )
            conn.commit()
            
        return {"message": f"Successfully revoked API Key with ID {key_id}."}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to revoke API Key: {e}"
        )
