import os
import pytest
from fastapi.testclient import TestClient

# Mock environment variables for testing before loading the app
os.environ["ADMIN_KEY"] = "test_admin_master_secret"
os.environ["WEBHOOK_SECRET"] = "test_webhook_secret_key"
os.environ["SUPABASE_URL"] = "https://mock.supabase.co"
os.environ["SUPABASE_ANON_KEY"] = "mock_anon_key"

from app.main import app

# Use the default dev key fallback for authentication tests
VALID_API_KEY = "hsk_dev_secret_key"
INVALID_API_KEY = "invalid_api_key_test_123"

@pytest.fixture(scope="module")
def client():
    """Test client fixture that triggers FastAPI lifespan startup/shutdown events."""
    with TestClient(app) as c:
        yield c

def test_health_endpoint(client):
    """Verify that the health check endpoint returns 200 and indicates healthy."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "cache_records" in data
    assert data["cache_records"] > 0

def test_secured_endpoint_unauthorized(client):
    """Verify that accessing endpoints without API keys is blocked with 401."""
    response = client.get("/words")
    assert response.status_code == 401
    
    response = client.get("/random")
    assert response.status_code == 401

def test_secured_endpoint_invalid_key(client):
    """Verify that accessing endpoints with incorrect keys is blocked with 401."""
    response = client.get("/words", headers={"X-API-KEY": INVALID_API_KEY})
    assert response.status_code == 401

def test_words_endpoint_success(client):
    """Verify that get_words works successfully with a valid API key."""
    response = client.get("/words", headers={"X-API-KEY": VALID_API_KEY})
    assert response.status_code == 200
    data = response.json()
    assert "data" in data
    assert "metadata" in data
    assert len(data["data"]) > 0
    assert "word" in data["data"][0]

def test_words_level_filtering(client):
    """Verify that filtering by level returns only words of that specific level."""
    # Test level 1
    response = client.get("/words/1", headers={"X-API-KEY": VALID_API_KEY})
    assert response.status_code == 200
    data = response.json()
    assert len(data["data"]) > 0
    for item in data["data"]:
        assert item["level"] == 1

def test_random_endpoint(client):
    """Verify that the /random endpoint returns randomized words with correct structures."""
    response = client.get("/random", headers={"X-API-KEY": VALID_API_KEY})
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, dict)
    assert "word" in data
    assert "level" in data
    assert "pinyin" in data

def test_webhook_supabase_auth(client):
    """Verify that the vocabulary webhook enforces secret query parameter authentication."""
    # Test unauthorized
    response = client.post("/webhook/supabase?secret=wrong_secret")
    assert response.status_code == 401
    
    # Test authorized (doesn't block since debouncer executes async task)
    response = client.post("/webhook/supabase?secret=test_webhook_secret_key")
    assert response.status_code == 200
    assert response.json()["message"] == "Synchronization triggered in background."

def test_webhook_keys_auth(client):
    """Verify that the API key webhook enforces secret query parameter authentication."""
    # Test unauthorized
    response = client.post("/webhook/keys?secret=wrong_secret")
    assert response.status_code == 401
