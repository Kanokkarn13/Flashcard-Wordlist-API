import os
import time
import logging
from typing import Optional
import requests
from fastapi import Security, HTTPException, status
from fastapi.security.api_key import APIKeyHeader

logger = logging.getLogger("api")

API_KEY_NAME = "X-API-KEY"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

ADMIN_KEY_NAME = "X-ADMIN-KEY"
admin_key_header = APIKeyHeader(name=ADMIN_KEY_NAME, auto_error=False)

# Master key to access admin API key management functions
ADMIN_KEY = os.getenv("ADMIN_KEY", "hsk_admin_master_secret")


class SimpleTTLCache:
    """Lightweight in-memory TTL Cache to store API Key validation states."""
    def __init__(self, ttl_seconds: float = 30.0):
        self.ttl = ttl_seconds
        self.cache = {}

    def get(self, key: str) -> Optional[dict]:
        """Returns the cached dictionary response if valid, otherwise None."""
        if key in self.cache:
            exp_time, data = self.cache[key]
            if time.time() < exp_time:
                return data
            else:
                del self.cache[key]
        return None

    def set(self, key: str, data: dict):
        """Caches key states for the configured TTL window."""
        self.cache[key] = (time.time() + self.ttl, data)

    def invalidate(self, key: str):
        """Invalidates a specific cached key (e.g. on revocation)."""
        if key in self.cache:
            del self.cache[key]


# Instantiate global credentials cache
keys_cache = SimpleTTLCache(ttl_seconds=30.0)


async def verify_api_key(api_key_header_value: str = Security(api_key_header)):
    """
    Dependency to verify the client's X-API-KEY header against Supabase keys table.
    Uses in-memory caching to bypass remote database calls on active routes.
    """
    if not api_key_header_value:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API Key is missing. Provide 'X-API-KEY' in request headers."
        )
    
    # 1. Check in-memory cache
    cached_data = keys_cache.get(api_key_header_value)
    if cached_data is not None:
        if not cached_data.get("is_active"):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=cached_data.get("error_detail", "Unauthorized: The provided 'X-API-KEY' is invalid.")
            )
        return cached_data

    # 2. Cache miss: Query Supabase REST API
    url_base = os.getenv("SUPABASE_URL") or os.getenv("EXPO_PUBLIC_SUPABASE_URL")
    anon_key = os.getenv("SUPABASE_ANON_KEY") or os.getenv("EXPO_PUBLIC_SUPABASE_ANON_KEY")

    if not url_base or not anon_key:
        logger.error("Auth: Supabase credentials are not configured in environment.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Configuration error: Supabase credentials missing."
        )

    url = f"{url_base}/rest/v1/api_keys?key=eq.{api_key_header_value}&limit=1"
    headers = {
        "apikey": anon_key,
        "Authorization": f"Bearer {anon_key}"
    }

    try:
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            logger.error(f"Auth: Supabase key verification request failed: {response.text}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Authentication server error."
            )
            
        data = response.json()
        
        # If key is completely missing in Supabase
        if not data:
            error_msg = "Unauthorized: The provided 'X-API-KEY' is invalid."
            keys_cache.set(api_key_header_value, {"is_active": False, "error_detail": error_msg})
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=error_msg)

        record = data[0]
        
        # Check active status
        if not record.get("is_active"):
            error_msg = "Unauthorized: The provided 'X-API-KEY' has been revoked."
            keys_cache.set(api_key_header_value, {"is_active": False, "error_detail": error_msg})
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=error_msg)

        # Store positive validation state
        success_data = {
            "id": record.get("id"),
            "key": record.get("key"),
            "name": record.get("name"),
            "is_active": True
        }
        keys_cache.set(api_key_header_value, success_data)
        return success_data

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Auth: Unexpected error during Supabase verification: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected authentication error."
        )


async def verify_admin_key(admin_key_header_value: str = Security(admin_key_header)):
    """
    Dependency to verify the master X-ADMIN-KEY header.
    Allows access to administrative key creation and revocation endpoints.
    """
    if not admin_key_header_value:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin Key is missing. Provide 'X-ADMIN-KEY' in request headers."
        )
        
    if admin_key_header_value != ADMIN_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: The provided 'X-ADMIN-KEY' is invalid."
        )
        
    return admin_key_header_value
