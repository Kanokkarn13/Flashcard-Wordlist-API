import math
import secrets
import asyncio
from contextlib import asynccontextmanager
from typing import Optional
import os
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv

# Load local environment variables
load_dotenv()

import logging
from fastapi import FastAPI, Depends, HTTPException, Query, Path, status
from fastapi.responses import HTMLResponse

from app.database import verify_db_integrity, get_db_connection
from app.auth import verify_api_key, verify_admin_key, api_keys_cache, load_api_keys_cache
from app.vocab_cache import vocab_cache, load_vocab_cache, load_vocab_from_csv

logger = logging.getLogger("api")
from app.logger import StructuredLoggingMiddleware
from app.schemas import PaginatedResponse, WordSchema, PaginationMetadata, KeyCreateSchema, KeyResponseSchema
from app.sync import debouncer

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle events manager for the FastAPI application."""
    import asyncio
    loop = asyncio.get_running_loop()

    # Load API keys from Supabase to RAM cache on startup
    await loop.run_in_executor(None, load_api_keys_cache)

    # Load vocabulary from Supabase to RAM cache on startup (with fallback to CSV)
    success = await loop.run_in_executor(None, load_vocab_cache)
    if not success:
        logger.warning("Startup: Failed to load vocabulary from Supabase. Attempting fallback to local CSV...")
        fallback_success = await loop.run_in_executor(None, load_vocab_from_csv)
        if not fallback_success:
            logger.critical("Startup CRITICAL: Failed to load vocabulary from both Supabase and CSV cache. Exiting.")
            import sys
            sys.exit(1)
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
    Verifies that the application in-memory cache is loaded.
    """
    count = vocab_cache.count()
    if count == 0:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="System unhealthy: In-memory vocabulary cache is empty."
        )
    return {
        "status": "healthy",
        "cache_records": count
    }

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
    all_words = vocab_cache.get_all()
    total_records = len(all_words)
    
    rows = all_words[offset:offset + per_page]
        
    total_pages = math.ceil(total_records / per_page) if total_records > 0 else 0
    
    metadata = PaginationMetadata(
        total_records=total_records,
        total_pages=total_pages,
        page=page,
        per_page=per_page,
        has_next=page < total_pages,
        has_previous=page > 1
    )
    
    return PaginatedResponse(metadata=metadata, data=rows)

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
    level_words = vocab_cache.get_by_level(level)
    total_records = len(level_words)
    
    rows = level_words[offset:offset + per_page]
        
    total_pages = math.ceil(total_records / per_page) if total_records > 0 else 0
    
    metadata = PaginationMetadata(
        total_records=total_records,
        total_pages=total_pages,
        page=page,
        per_page=per_page,
        has_next=page < total_pages,
        has_previous=page > 1
    )
    
    return PaginatedResponse(metadata=metadata, data=rows)

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
    row = vocab_cache.get_by_word(word)
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Word '{word}' not found in HSK vocabulary list."
        )
        
    return row

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
    row = vocab_cache.get_random(level)
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No words found matching selection criteria."
        )
        
    return row


@app.get("/admin", response_class=HTMLResponse, include_in_schema=False)
async def get_admin_dashboard():
    """Serve the Web Admin Dashboard to manage client API keys."""
    template_path = os.path.join(os.path.dirname(__file__), "templates", "dashboard.html")
    if not os.path.exists(template_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Admin dashboard template not found."
        )
    try:
        with open(template_path, "r", encoding="utf-8") as f:
            html_content = f.read()
        return HTMLResponse(content=html_content)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to read dashboard template: {e}"
        )


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
    Generate a new unique API key and store it on Supabase.
    Requires `X-ADMIN-KEY` authorization.
    """
    new_key = f"hsk_key_{secrets.token_hex(16)}"
    
    url_base = os.getenv("SUPABASE_URL") or os.getenv("EXPO_PUBLIC_SUPABASE_URL")
    auth_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY") or os.getenv("EXPO_PUBLIC_SUPABASE_ANON_KEY")
    
    if not url_base or not auth_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Configuration error: Supabase credentials missing."
        )
        
    url = f"{url_base}/rest/v1/api_keys"
    headers = {
        "apikey": auth_key,
        "Authorization": f"Bearer {auth_key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }
    payload = {
        "key": new_key,
        "name": body.name,
        "is_active": True
    }
    
    try:
        res = requests.post(url, json=payload, headers=headers)
        if res.status_code != 201:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to generate API Key in Supabase: {res.text}"
            )
        record = res.json()[0]
        
        # Reload API keys cache in background
        loop = asyncio.get_running_loop()
        loop.run_in_executor(None, load_api_keys_cache)
        
        return record
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error generating API Key: {e}"
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
    Retrieve all client API keys stored in Supabase.
    Requires `X-ADMIN-KEY` authorization.
    """
    url_base = os.getenv("SUPABASE_URL") or os.getenv("EXPO_PUBLIC_SUPABASE_URL")
    auth_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY") or os.getenv("EXPO_PUBLIC_SUPABASE_ANON_KEY")
    
    if not url_base or not auth_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Configuration error: Supabase credentials missing."
        )
        
    url = f"{url_base}/rest/v1/api_keys?order=id.desc"
    headers = {
        "apikey": auth_key,
        "Authorization": f"Bearer {auth_key}"
    }
    
    try:
        res = requests.get(url, headers=headers)
        if res.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to query API keys from Supabase: {res.text}"
            )
        return res.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error listing API Keys: {e}"
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
    Revoke a client API key in Supabase. The key will immediately become unusable.
    Requires `X-ADMIN-KEY` authorization.
    """
    url_base = os.getenv("SUPABASE_URL") or os.getenv("EXPO_PUBLIC_SUPABASE_URL")
    auth_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY") or os.getenv("EXPO_PUBLIC_SUPABASE_ANON_KEY")
    
    if not url_base or not auth_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Configuration error: Supabase credentials missing."
        )
        
    headers = {
        "apikey": auth_key,
        "Authorization": f"Bearer {auth_key}",
        "Content-Type": "application/json"
    }
    
    try:
        # Check if the key exists
        url_check = f"{url_base}/rest/v1/api_keys?id=eq.{key_id}"
        res_check = requests.get(url_check, headers=headers)
        if res_check.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to verify API key presence: {res_check.text}"
            )
            
        data = res_check.json()
        if not data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"API Key with ID {key_id} not found."
            )
            
        record = data[0]
        if not record.get("is_active"):
            return {"message": f"API Key with ID {key_id} is already revoked."}
            
        # Perform revocation
        url_patch = f"{url_base}/rest/v1/api_keys?id=eq.{key_id}"
        payload = {
            "is_active": False,
            "revoked_at": datetime.now(timezone.utc).isoformat()
        }
        res_patch = requests.patch(url_patch, json=payload, headers=headers)
        if res_patch.status_code not in (200, 204):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to revoke API key in Supabase: {res_patch.text}"
            )
            
        # Reload API keys cache in background to apply deactivation instantly
        loop = asyncio.get_running_loop()
        loop.run_in_executor(None, load_api_keys_cache)
        
        return {"message": f"Successfully revoked API Key with ID {key_id}."}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to revoke API Key: {e}"
        )


@app.get(
    "/health",
    summary="Get API health status",
    tags=["System"],
)
async def get_health_status():
    """Check in-memory cache connection and return record count."""
    count = vocab_cache.count()
    if count == 0:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="In-memory vocabulary cache is empty."
        )
    return {"status": "healthy", "cache_records": count}


# Load Webhook Secret Configuration
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "hsk_webhook_secret_default_key")

@app.post(
    "/webhook/supabase",
    summary="Supabase database synchronization webhook",
    tags=["System"],
)
async def supabase_webhook(
    secret: str = Query(..., description="Secure webhook authentication token")
):
    """
    Receives database change notifications from Supabase.
    Triggers an asynchronous, 10-second debounced sync process in the background.
    """
    if secret != WEBHOOK_SECRET:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Invalid webhook secret token."
        )
        
    # Trigger the debouncer (non-blocking asyncio task)
    await debouncer.trigger()
    
    return {"message": "Synchronization triggered in background."}


@app.post(
    "/admin/keys/reload",
    summary="Manually reload API keys cache from Supabase",
    tags=["Admin Key Management"],
    dependencies=[Depends(verify_admin_key)]
)
async def reload_api_keys():
    """
    Manually triggers a reload of the API keys cache from Supabase.
    Requires `X-ADMIN-KEY` authorization.
    """
    import asyncio
    loop = asyncio.get_running_loop()
    success = await loop.run_in_executor(None, load_api_keys_cache)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to reload API keys from Supabase."
        )
    return {"message": f"Successfully reloaded API keys. Currently cached: {len(api_keys_cache)} keys."}


@app.post(
    "/webhook/keys",
    summary="Supabase API keys synchronization webhook",
    tags=["System"],
)
async def webhook_reload_keys(
    secret: str = Query(..., description="Secure webhook authentication token")
):
    """
    Receives database change notifications for API keys from Supabase.
    Triggers an instant reload of API keys into RAM cache.
    """
    if secret != WEBHOOK_SECRET:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Invalid webhook secret token."
        )
        
    import asyncio
    loop = asyncio.get_running_loop()
    success = await loop.run_in_executor(None, load_api_keys_cache)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to reload API keys from Supabase."
        )
    return {"message": "API keys cache reloaded successfully in response to webhook."}
