import os
from fastapi import Security, HTTPException, status
from fastapi.security.api_key import APIKeyHeader

from app.database import get_db_connection

API_KEY_NAME = "X-API-KEY"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

ADMIN_KEY_NAME = "X-ADMIN-KEY"
admin_key_header = APIKeyHeader(name=ADMIN_KEY_NAME, auto_error=False)

# Master key to access admin API key management functions
ADMIN_KEY = os.getenv("ADMIN_KEY", "hsk_admin_master_secret")

async def verify_api_key(api_key_header_value: str = Security(api_key_header)):
    """
    Dependency to verify the X-API-KEY header against database keys.
    Raises 401 Unauthorized if the header is missing, incorrect, or revoked.
    """
    if not api_key_header_value:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API Key is missing. Provide 'X-API-KEY' in request headers."
        )
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, key, name, is_active FROM api_keys WHERE key = ? LIMIT 1",
            (api_key_header_value,)
        )
        row = cursor.fetchone()
    
    if not row:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: The provided 'X-API-KEY' is invalid."
        )
        
    if not row["is_active"]:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: The provided 'X-API-KEY' has been revoked."
        )
        
    return dict(row)

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
