"""Bearer isolation, expiring hashed sessions, and legacy hash migration."""
import hashlib
import time
from concurrent.futures import ThreadPoolExecutor
import pytest
import agent.collections as accounts


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    for attr, name in [("_USERS_FILE", "users.json"), ("_COLLECTIONS_FILE", "collections.json"), ("_READ_PAPERS_FILE", "read.json"), ("_PAPER_CACHE_FILE", "cache.json")]:
        monkeypatch.setattr(accounts, attr, tmp_path / name)
    monkeypatch.delenv("SAKURA_ADMIN_PASSWORD", raising=False)
    return tmp_path


def test_register_session_is_valid_hashed_expiring_revocable(isolated):
    result = accounts.register_user("alice", "controlled-password")
    assert accounts.verify_token(result["token"]) == "alice"
    data = accounts._load_users()
    assert result["token"] not in str(data)
    assert data["users"][0]["password_hash"].startswith("pbkdf2-sha256$")
    key = accounts._token_key(result["token"])
    data["users"][0]["tokens"][key] = time.time() - accounts.SESSION_SECONDS - 1
    accounts._save_users(data)
    assert accounts.verify_token(result["token"]) is None
    fresh = accounts.login_user("alice", "controlled-password")["token"]
    accounts.logout_user(fresh)
    assert accounts.verify_token(fresh) is None


def test_legacy_password_upgrades_without_losing_library(isolated):
    salt = "controlled-legacy-salt"
    accounts._save_users({"users": [{"username": "legacy", "salt": salt, "password_hash": hashlib.sha256((salt + "legacy-password").encode()).hexdigest()}]})
    accounts.add_favorite("legacy", "10.1000/legacy", {"title": "Legacy document"})
    result = accounts.login_user("legacy", "legacy-password")
    assert result["status"] == "ok"
    assert accounts._load_users()["users"][0]["password_hash"].startswith("pbkdf2-sha256$")
    assert accounts.list_favorites("legacy")["total"] == 1


def test_reserved_admin_no_default_and_cross_account_api(isolated):
    from fastapi.testclient import TestClient
    from web.app import app
    assert accounts.register_user("admin", "controlled-password")["status"] == "error"
    with TestClient(app) as client:
        assert accounts.login_user("admin", "admin123")["status"] == "error"
        alice = client.post("/api/auth/register", json={"username": "alice", "password": "controlled-password"}).json()
        bob = client.post("/api/auth/register", json={"username": "bob", "password": "controlled-password"}).json()
        headers = {"Authorization": "Bearer " + alice["token"]}
        assert client.get("/api/auth/me", headers=headers).json()["username"] == "alice"
        client.post("/api/favorites/10.1000/private?user_id=bob", headers=headers, json={"paper_meta": {"title": "Alice private library"}})
        client.post("/api/read_papers/10.1000/private?user_id=bob", headers=headers)
        client.post("/api/folders?user_id=bob", headers=headers, json={"name": "Alice folder"})
        bob_headers = {"Authorization": "Bearer " + bob["token"]}
        assert client.get("/api/favorites?user_id=alice", headers=bob_headers).json()["total"] == 0
        assert client.get("/api/read_papers?user_id=alice", headers=bob_headers).json()["papers"] == []
        assert client.get("/api/folders?user_id=alice", headers=bob_headers).json()["total"] == 0
        assert client.get("/api/favorites?user_id=alice").json()["total"] == 0
        assert client.get("/api/favorites", headers={"Authorization": "Bearer invalid"}).status_code == 401


def test_parallel_library_updates_do_not_overwrite(isolated):
    accounts.register_user("alice", "controlled-password")
    def add(i):
        accounts.add_favorite("alice", f"10.1000/concurrent-{i}", {"title": f"Controlled item {i}"})
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(add, range(12)))
    assert accounts.list_favorites("alice")["total"] == 12


def test_model_error_logs_and_api_never_return_provider_credentials(isolated, monkeypatch, caplog):
    from llm.openai_compat import OpenAICompatLLM
    from fastapi.testclient import TestClient
    import web.app as web
    marker = "controlled-sensitive-error-marker"
    llm = OpenAICompatLLM(model="controlled-model", base_url="https://example.org/v1", api_key=marker)
    def fail(*a, **kw): raise RuntimeError(marker)
    monkeypatch.setattr(llm, "_chat_openai_compat", fail)
    assert llm.complete("controlled prompt") == "" and marker not in caplog.text
    monkeypatch.setattr(web, "_get_llm_router", lambda: type("Router", (), {"get": fail})())
    with TestClient(web.app) as client:
        assert client.post("/api/llm/test", json={"name": "controlled-model"}).status_code == 403
        monkeypatch.setattr(web, "_is_admin", lambda token: True)
        result = client.post("/api/llm/test", json={"name": "controlled-model"})
        assert result.json()["status"] == "error" and marker not in result.text and marker not in caplog.text
        monkeypatch.setattr(web, "_get_llm_router", lambda: type("Router", (), {"get": lambda self, name: type("LLM", (), {"complete": lambda self, prompt: "Controlled successful reply"})()})())
        assert client.post("/api/llm/test", json={"name": "controlled-model"}).json()["response"] == "Controlled successful reply"
