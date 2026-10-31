"""Offline tests: every test gets a new SQLite file, never backend/sales.db.

Run from either the repository root or backend/ with ``python -m pytest``.
Import the API through api_module/client so isolation precedes app startup.
"""

import importlib
import os
from pathlib import Path
import socket
import sqlite3
import sys
import tempfile
from urllib.parse import unquote, urlsplit

import pytest


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR.parent))
sys.path.insert(0, str(BACKEND_DIR))


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Fail loudly even when production code catches ordinary exceptions.

    In-process TestClient and explicitly mocked HTTP transports still work.
    Socket guards also cover urllib, SDKs, and accidentally unmocked clients.
    """
    import httpx
    import requests

    def blocked(*args, **kwargs):
        pytest.fail("Real network access is forbidden; mock the external boundary")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket.socket, "sendto", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    monkeypatch.setattr(requests.sessions.Session, "request", blocked)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", blocked)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", blocked)


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch, no_network):
    """Use a fresh schema; reject SQLite files outside this test's directory.

    The connect guard also protects against hardcoded paths and URI filenames.
    Migration tests may create additional SQLite files within tmp_path.
    """
    import database

    original_connect = sqlite3.connect

    def connect(database, *args, **kwargs):
        filename = os.fsdecode(database)
        if filename.startswith("file:"):
            filename = unquote(urlsplit(filename).path)
        if filename not in ("", ":memory:"):
            path = Path(filename).resolve()
            if not path.is_relative_to(tmp_path.resolve()):
                pytest.fail(f"SQLite access outside test tmp_path is forbidden: {path}")
        return original_connect(database, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", connect)
    # unittest-based suites can still create their own TemporaryDirectory;
    # keep those files inside the same guarded sandbox as pytest fixtures.
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "test-sales.db")
    database.init_db()
    yield database


@pytest.fixture
def db(isolated_db):
    """Short alias for tests that exercise the real persistence helpers."""
    return isolated_db


@pytest.fixture
def bike_factory(db):
    def create(bike_id="test-roadster", **overrides):
        fields = {
            "brand": "Test",
            "model": "Roadster",
            "display_name": "Test Roadster",
            "keywords": ["Roadster"],
            "launch_month": "2025-11",
        }
        fields.update(overrides)
        db.upsert_bike(bike_id=bike_id, **fields)
        return db.get_bike(bike_id)

    return create


@pytest.fixture
def bike(bike_factory):
    return bike_factory()


@pytest.fixture
def api_module(isolated_db, monkeypatch, tmp_path):
    from config import settings

    # Local .env values must not change authentication or enable real services.
    monkeypatch.setattr(settings, "admin_token", None)
    for name in ("anthropic_api_key", "groq_api_key", "openai_compat_api_key"):
        monkeypatch.setattr(settings, name, None)
    main = importlib.import_module("main")
    monkeypatch.setattr(main, "_themes_running", {})
    monkeypatch.setattr(main, "_themes_errors", {})
    monkeypatch.setattr(main.brochure_utils, "BROCHURE_CACHE_DIR", tmp_path / "brochures")
    return main


@pytest.fixture
def client(api_module):
    from fastapi.testclient import TestClient

    # Exercise the real lifespan, including init_db and catalogue seeding.
    with TestClient(api_module.app) as test_client:
        yield test_client
