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


# Global RAM cache storing active API keys: { "key_string": { "id": id, "name": name, "is_active": True } }
api_keys_cache: dict = {}


def load_api_keys_cache() -> bool:
    """
    Fetches all active API keys from Supabase REST API and loads them into memory.
    Also seeds the local developer API key fallback.
    """
    url_base = os.getenv("SUPABASE_URL") or os.getenv("EXPO_PUBLIC_SUPABASE_URL")
    anon_key = os.getenv("SUPABASE_ANON_KEY") or os.getenv("EXPO_PUBLIC_SUPABASE_ANON_KEY")

    dev_key = os.getenv("API_KEY", "hsk_dev_secret_key")
    fallback_records = {
        dev_key: {
            "id": 9999,
            "key": dev_key,
            "name": "Local Developer API Key",
            "is_active": True
        }
    }

    if not url_base or not anon_key:
        logger.warning("Auth: Supabase credentials not found. Seeding local developer API key only.")
        global api_keys_cache
        api_keys_cache.clear()
        api_keys_cache.update(fallback_records)
        return True

    url = f"{url_base}/rest/v1/api_keys?is_active=eq.true"
    headers = {
        "apikey": anon_key,
        "Authorization": f"Bearer {anon_key}"
    }

    try:
        logger.info("Auth: Fetching active API keys from Supabase...")
        res = requests.get(url, headers=headers)
        if res.status_code != 200:
            logger.error(f"Auth: Failed to fetch API keys from Supabase: {res.text}")
            # Ensure fallback key is loaded
            api_keys_cache.clear()
            api_keys_cache.update(fallback_records)
            return False

        data = res.json()
        new_cache = {}
        for record in data:
            key_str = record.get("key")
            if key_str:
                new_cache[key_str] = {
                    "id": record.get("id"),
                    "key": key_str,
                    "name": record.get("name"),
                    "is_active": True
                }

        # Seed local developer key
        if dev_key:
            new_cache[dev_key] = {
                "id": 9999,
                "key": dev_key,
                "name": "Local Developer API Key",
                "is_active": True
            }

        api_keys_cache.clear()
        api_keys_cache.update(new_cache)
        logger.info(f"Auth: Loaded {len(api_keys_cache)} active API keys into RAM cache.")
        return True
    except Exception as e:
        logger.error(f"Auth: Failed to update API keys cache: {e}")
        # Ensure fallback key is loaded
        api_keys_cache.clear()
        api_keys_cache.update(fallback_records)
        return False


async def verify_api_key(api_key_header_value: str = Security(api_key_header)):
    """
    Dependency to verify the client's X-API-KEY header against the RAM cache.
    Does not make remote database calls, reducing query latency to 0.
    """
    if not api_key_header_value:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API Key is missing. Provide 'X-API-KEY' in request headers."
        )
    
    # Verify key using the fast local RAM cache
    cached_data = api_keys_cache.get(api_key_header_value)
    if cached_data is None or not cached_data.get("is_active"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: The provided 'X-API-KEY' is invalid or has been revoked."
        )
    
    return cached_data


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
