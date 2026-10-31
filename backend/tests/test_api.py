"""Real ASGI routing/lifespan + temporary persistence; external I/O is mocked."""

from unittest.mock import Mock

import pytest


@pytest.mark.parametrize("token", [None, "test-admin-token"])
def test_public_api_and_startup_seed_with_auth_on_or_off(client, api_module, db, token, monkeypatch):
    monkeypatch.setattr(api_module.settings, "admin_token", token)
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

    response = client.get("/api/bikes")
    assert response.status_code == 200
    bikes = {bike["id"]: bike for bike in response.json()}
    assert "yamaha-xsr-155" in bikes
    assert bikes["yamaha-xsr-155"]["keywords"]
    response = client.get("/api/bikes/yamaha-xsr-155")
    assert response.status_code == 200
    assert response.json()["id"] == "yamaha-xsr-155"
    response = client.get("/api/bikes/yamaha-xsr-155/sales")
    assert response.status_code == 200
    assert response.json() == db.get_all_sales("yamaha-xsr-155")
    assert response.json(), "Real application startup should seed demo sales"
    response = client.get("/api/brands")
    assert response.status_code == 200
    assert any(brand["id"] == "yamaha" for brand in response.json())
    response = client.get("/api/themes/keyword-defaults")
    assert response.status_code == 200
    assert "Engine & Performance" in response.json()


@pytest.mark.parametrize("path, detail", [
    ("/api/bikes/does-not-exist", "bike not found"),
    ("/api/brands/does-not-exist/models", "brand not found"),
    ("/api/variants/does-not-exist/specs", "no specs for variant"),
    ("/api/variants/does-not-exist/brochures", "no brochures for variant"),
])
def test_missing_resources_return_404(client, path, detail):
    response = client.get(path)
    assert response.status_code == 404
    assert response.json() == {"detail": detail}


@pytest.mark.parametrize("suffix", ["sales", "metrics", "reviews", "reviews/summary", "themes", "themes/status"])
def test_legacy_routes_redirect_to_scoped_routes(client, suffix):
    response = client.get(f"/api/{suffix}", follow_redirects=False)
    assert response.status_code == 308
    assert response.headers["location"] == f"/api/bikes/yamaha-xsr-155/{suffix}"


@pytest.mark.parametrize("method, path, payload", [
    ("POST", "/api/bikes/cleanup", None),
    ("POST", "/api/bikes/discover", None),
    ("POST", "/api/refresh-all", None),
    ("POST", "/api/bikes/test-roadster/refresh", None),
    ("POST", "/api/bikes/test-roadster/reviews/refresh", None),
    ("POST", "/api/bikes/test-roadster/themes/analyze", {"method": "keyword"}),
    ("POST", "/api/ollama/pull/test-model", None),
    ("GET", "/api/hardware", None),
])
@pytest.mark.parametrize("supplied", [None, "wrong-token"])
def test_admin_routes_reject_missing_or_incorrect_token(
    client, api_module, db, bike, monkeypatch, method, path, payload, supplied
):
    monkeypatch.setattr(api_module.settings, "admin_token", "test-admin-token")
    work = Mock(side_effect=AssertionError("Unauthorized work must not start"))
    for name in ("_run_single_bike_refresh", "_run_bike_reviews_scrape", "_do_themes_analysis"):
        monkeypatch.setattr(api_module, name, work)
    monkeypatch.setattr(api_module.hardware_detector, "full_report", work)
    headers = {} if supplied is None else {"X-Admin-Token": supplied}
    response = client.request(method, path, json=payload, headers=headers)
    assert response.status_code == 401
    assert response.json() == {"detail": "admin token required"}
    assert db.get_bike(bike["id"]) is not None
    work.assert_not_called()


@pytest.mark.parametrize("token", [None, "test-admin-token"])
def test_authorized_cleanup_removes_only_non_catalogue_bikes(
    client, api_module, db, bike, monkeypatch, token
):
    monkeypatch.setattr(api_module.settings, "admin_token", token)
    headers = {"X-Admin-Token": token} if token else {}
    response = client.post("/api/bikes/cleanup", headers=headers)
    assert response.status_code == 200
    assert response.json() == {"removed": [bike["id"]], "removed_count": 1}
    assert db.get_bike(bike["id"]) is None
    assert db.get_bike("yamaha-xsr-155") is not None


@pytest.mark.parametrize("token", [None, "test-admin-token"])
def test_sales_refresh_extracts_mock_articles_and_persists(
    client, api_module, db, bike, monkeypatch, token
):
    monkeypatch.setattr(api_module.settings, "admin_token", token)
    scrape = Mock(return_value=[{
        "url": "https://news.example/sales-dec-2025-report",
        "text": "Roadster recorded 1,234 units this month.",
    }])
    monkeypatch.setattr(api_module, "scrape_all", scrape)
    headers = {"X-Admin-Token": token} if token else {}
    response = client.post(f"/api/bikes/{bike['id']}/refresh", headers=headers)
    assert response.status_code == 200
    assert response.json() == {"status": "started"}
    scrape.assert_called_once_with()
    rows = db.get_all_sales(bike["id"])
    assert [(row["month"], row["units_sold"]) for row in rows] == [("2025-12", 1234)]
    assert db.get_last_scrape_log()["urls_success"] == 1
    assert db.get_last_scrape_log()["error_msg"] is None


def test_reviews_refresh_persists_mock_result(client, api_module, db, bike, monkeypatch):
    scrape = Mock(return_value=[{
        "bike_id": bike["id"], "source": "bikewale", "post_id": "offline-review",
        "username": "owner", "review_text": "The engine is smooth on every journey.",
        "overall_rating": 4.5, "thread_url": "https://reviews.example/one",
    }])
    monkeypatch.setattr(api_module, "scrape_reviews_for_bike", scrape)
    response = client.post(f"/api/bikes/{bike['id']}/reviews/refresh")
    assert response.status_code == 200
    scrape.assert_called_once()
    response = client.get(f"/api/bikes/{bike['id']}/reviews")
    assert response.status_code == 200
    assert [(row["post_id"], row["overall_rating"]) for row in response.json()] == [("offline-review", 4.5)]
    assert db.get_last_reviews_log()["total_scraped"] == 1
    assert db.get_last_reviews_log()["error_msg"] is None


def test_keyword_analysis_runs_end_to_end(client, db, bike):
    db.upsert_review(bike["id"], "fixture", "review-one", "owner",
                     "The engine is excellent and smooth on every ride.", 5.0)
    response = client.post(f"/api/bikes/{bike['id']}/themes/analyze", json={
        "method": "keyword", "config": {"keywords": {"Engine": ["engine"]}},
    })
    assert response.status_code == 200
    assert response.json()["status"] == "started"
    response = client.get(f"/api/bikes/{bike['id']}/themes")
    assert response.status_code == 200
    result = response.json()
    assert result["method"] == "keyword"
    assert result["config"]["pool_scope"] == "bike"
    assert result["metrics"]["n_reviews"] == 1
    assert result["themes"][0]["name"] == "Engine"
    assert result["themes"][0]["mention_count"] == 1
    assert result["themes"][0]["sentiment"] == "positive"
    assert client.get(f"/api/bikes/{bike['id']}/themes/status").json()["running"] is False


def test_invalid_theme_scope_has_no_side_effects(client, db, bike):
    response = client.post(f"/api/bikes/{bike['id']}/themes/analyze", json={"pool_scope": "world"})
    assert response.status_code == 400
    assert db.get_latest_themes(bike["id"]) is None
    assert client.get(f"/api/bikes/{bike['id']}/themes/status").json()["running"] is False


@pytest.mark.parametrize("failure_kind", ["returned-error", "exception"])
def test_failed_analysis_exposes_error_despite_cached_result_and_retry_clears_it(
    client, api_module, db, bike, monkeypatch, failure_kind
):
    bike_id = bike["id"]
    db.save_themes_analysis(bike_id, "keyword", {}, [{"name": "Previously saved"}])
    previous = db.get_latest_themes(bike_id)
    error = "Fixture provider unavailable"
    runner = Mock()
    if failure_kind == "exception":
        runner.side_effect = RuntimeError(error)
    else:
        runner.return_value = {"themes": None, "error": error}
    monkeypatch.setattr(api_module.themes_runner, "run_analysis", runner)

    response = client.post(f"/api/bikes/{bike_id}/themes/analyze", json={"method": "llm"})
    assert response.status_code == 200
    runner.assert_called_once_with("llm", {}, bike_id=bike_id, pool_scope="bike")
    status = client.get(f"/api/bikes/{bike_id}/themes/status").json()
    assert status["running"] is False
    assert status["error"] == error
    assert status["total_analyses"] == 1
    assert status["last_run_at"] == previous["run_at"]
    assert client.get(f"/api/bikes/{bike_id}/themes").json() == previous

    def succeed(method, config, *, bike_id, pool_scope):
        # The old error must clear when the retry starts, before completion.
        assert api_module._themes_errors[bike_id] is None
        assert api_module._themes_running[bike_id] is True
        themes = [{"name": "Successful retry"}]
        db.save_themes_analysis(bike_id, method, config, themes)
        return {"themes": themes, "error": None}

    runner.side_effect = succeed
    response = client.post(f"/api/bikes/{bike_id}/themes/analyze", json={"method": "keyword"})
    assert response.status_code == 200
    assert response.json()["status"] == "started"
    status = client.get(f"/api/bikes/{bike_id}/themes/status").json()
    assert status["running"] is False
    assert status["error"] is None
    assert status["total_analyses"] == 2
    assert client.get(f"/api/bikes/{bike_id}/themes").json()["themes"] == [{"name": "Successful retry"}]


def test_duplicate_theme_request_does_not_schedule_second_job(client, api_module, bike, monkeypatch):
    # Leave the first job pending to exercise duplicate requests without sleeps.
    work = Mock()
    monkeypatch.setattr(api_module, "_do_themes_analysis", work)
    url = f"/api/bikes/{bike['id']}/themes/analyze"
    first = client.post(url, json={"method": "keyword"})
    second = client.post(url, json={"method": "keyword"})
    assert first.status_code == second.status_code == 200
    assert first.json()["status"] == "started"
    assert second.json() == {"status": "already_running"}
    work.assert_called_once_with(bike["id"], "keyword", {}, "bike")
    status = client.get(f"/api/bikes/{bike['id']}/themes/status").json()
    assert status["running"] is True
    assert status["error"] is None


def test_hardware_report_accepts_correct_token(client, api_module, monkeypatch):
    monkeypatch.setattr(api_module.settings, "admin_token", "test-admin-token")
    report = Mock(return_value={"cpu": {"cores": 4}, "offline_fixture": True})
    monkeypatch.setattr(api_module.hardware_detector, "full_report", report)
    response = client.get("/api/hardware", headers={"X-Admin-Token": "test-admin-token"})
    assert response.status_code == 200
    assert response.json()["offline_fixture"] is True
    report.assert_called_once_with()


def test_non_ascii_admin_header_is_unauthorized_not_server_error(client, api_module, monkeypatch):
    monkeypatch.setattr(api_module.settings, "admin_token", "test-admin-token")
    response = client.get("/api/hardware", headers=[(b"X-Admin-Token", b"wrong-\xff-token")])
    assert response.status_code == 401


@pytest.mark.parametrize("digest, expected", [("invalid", 400), ("a" * 63, 400), ("g" * 64, 400), ("a" * 64, 404)])
def test_brochure_download_validates_digest_and_missing_file(client, digest, expected):
    assert client.get(f"/api/brochures/{digest}.pdf").status_code == expected


def test_compare_requires_at_least_two_bikes(client):
    assert client.get("/api/compare", params={"ids": "yamaha-xsr-155"}).status_code == 400


@pytest.mark.parametrize("params", [{"horizon": 0}, {"horizon": 25}, {"interval_width": 0}, {"interval_width": 1}])
def test_forecast_rejects_invalid_bounds_before_starting_work(client, params):
    assert client.get("/api/bikes/yamaha-xsr-155/forecast", params=params).status_code == 422
