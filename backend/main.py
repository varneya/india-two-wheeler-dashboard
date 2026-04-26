from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
import json as _json
import threading
import time
import requests as http_requests

import database
import seed_data
from extractor import extract_sales_for_bike
from scraper import scrape_all
from reviews_scraper import scrape_reviews_for_bike
from bikedekho_scraper import scrape_bikedekho_for_bike
from zigwheels_scraper import scrape_zigwheels_for_bike
from reddit_scraper import scrape_reddit_for_bike
import forecast as forecast_mod
import hardware_detector
import themes_runner
import themes_keyword
import bike_registry
import bike_catalogue
import fada_scraper


LEGACY_BIKE_ID = "yamaha-xsr-155"


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.init_db()
    seed_data.seed_if_empty()
    yield


app = FastAPI(title="Bike Sales Miner", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "https://varneya.github.io",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ===========================================================================
# Health
# ===========================================================================

@app.get("/api/health")
def health():
    return {"status": "ok"}


# ===========================================================================
# Bikes catalogue
# ===========================================================================

# Discovery state — single global flag (only one discovery at a time)
_discovery_running: bool = False
_discovery_progress: dict = {
    "running": False,
    "stage": "idle",
    "urls_total": 0,
    "urls_done": 0,
    "bikes_found": 0,
    "error": None,
}
_discovery_lock = threading.Lock()


@app.get("/api/brands")
def list_brands():
    """Return all known brands plus how many bikes each has in the catalogue
    AND in the live database."""
    brands = bike_catalogue.all_brands()
    db_bikes = database.get_all_bikes()
    counts: dict[str, int] = {}
    for b in db_bikes:
        # bike_id is "<brand_id>-<model-slug>"; first segment is brand_id
        bid = b["id"].split("-", 1)[0] if "-" in b["id"] else b["id"]
        # Multi-word brand_id like "royal-enfield" needs special handling
        for brand_id in bike_catalogue.BRANDS:
            if b["id"].startswith(brand_id + "-") or b["id"] == brand_id:
                bid = brand_id
                break
        counts[bid] = counts.get(bid, 0) + 1
    for entry in brands:
        entry["db_bike_count"] = counts.get(entry["id"], 0)
    return brands


@app.get("/api/brands/{brand_id}/models")
def list_brand_models(brand_id: str):
    """Return catalogue models for a brand merged with live DB stats so the
    frontend can show 'units sold / months tracked' on the model picker."""
    if brand_id not in bike_catalogue.CATALOGUE:
        raise HTTPException(404, detail="brand not found")
    catalogue_models = bike_catalogue.get_brand_models(brand_id)
    db_bikes = {b["id"]: b for b in database.get_all_bikes()}
    out = []
    for entry in catalogue_models:
        bike_id = bike_catalogue.make_bike_id(brand_id, entry["canonical"])
        db = db_bikes.get(bike_id)
        out.append({
            "id": bike_id,
            "canonical": entry["canonical"],
            "display_name": f"{bike_catalogue.BRANDS[brand_id]['display']} {entry['canonical']}",
            "bikewale_slug": entry.get("bikewale"),
            # Live-data flags
            "in_db": db is not None,
            "total_units": db["total_units"] if db else 0,
            "months_tracked": db["months_tracked"] if db else 0,
            "has_reviews": (db and db.get("has_reviews")) or False,
        })
    return out


@app.get("/api/brands/{brand_id}/wholesale-vs-retail")
def wholesale_vs_retail(brand_id: str):
    """Side-by-side monthly comparison for a brand from two data sources.

    Note: the route name is historical. The actual data is "RushLane reported"
    vs "FADA retail (Vahan registrations)". RushLane's source varies by brand,
    so we no longer interpret the difference as inventory build/draw.

    - wholesale (kept name for backwards-compat): SUM of model-level RushLane
      rows for the brand, per month.
    - retail: FADA brand-level retail rows, per month.
    - source_gap: signed difference (RushLane − FADA). The frontend renders the
      absolute value with neutral framing.
    """
    if brand_id not in bike_catalogue.CATALOGUE:
        raise HTTPException(404, detail="brand not found")

    wholesale = database.get_wholesale_brand_totals(brand_id)
    retail = database.get_retail_brand_sales(brand_id=brand_id, source="fada_retail")

    months = sorted(set([w["month"] for w in wholesale] + [r["month"] for r in retail]))
    w_by_month = {w["month"]: w["units"] for w in wholesale}
    r_by_month = {r["month"]: r["units"] for r in retail}

    series = []
    for m in months:
        w = w_by_month.get(m)
        r = r_by_month.get(m)
        gap = (w - r) if (w is not None and r is not None) else None
        series.append({
            "month": m,
            "wholesale": w,
            "retail": r,
            "source_gap": gap,
        })

    return {
        "brand_id": brand_id,
        "brand_display": bike_catalogue.BRANDS[brand_id]["display"],
        "series": series,
    }


@app.get("/api/bikes")
def list_bikes():
    return database.get_all_bikes()


@app.post("/api/bikes/cleanup")
def cleanup_bikes():
    """Remove bikes (and their sales/reviews/themes rows) that aren't in the
    curated catalogue. Useful after a parser change or schema migration."""
    valid_ids: set[str] = set()
    for brand_id, entries in bike_catalogue.CATALOGUE.items():
        for e in entries:
            valid_ids.add(bike_catalogue.make_bike_id(brand_id, e["canonical"]))

    removed: list[str] = []
    for b in database.get_all_bikes():
        if b["id"] not in valid_ids:
            database.delete_bike(b["id"])
            removed.append(b["id"])
    return {"removed": removed, "removed_count": len(removed)}


@app.get("/api/bikes/{bike_id}")
def get_bike_detail(bike_id: str):
    bike = database.get_bike(bike_id)
    if not bike:
        raise HTTPException(status_code=404, detail="bike not found")
    return bike


def _do_discovery_pass(progress: dict, lock: threading.Lock) -> set[str]:
    """
    Shared discovery body. Updates `progress` (a dict shaped like
    `_discovery_progress`) and returns the set of bike_ids that were upserted.
    Raises on fatal errors so the caller can record them in its own state.
    """
    with lock:
        progress.update({
            "stage": "discovering URLs",
            "urls_total": 0, "urls_done": 0, "bikes_found": 0, "error": None,
        })

    articles = scrape_all()
    with lock:
        progress.update({
            "stage": "parsing articles",
            "urls_total": len(articles), "urls_done": 0,
        })

    from extractor import month_from_url

    new_bike_ids: set[str] = set()
    for article in articles:
        url = article["url"]
        text = article["text"]
        month = month_from_url(url)
        brand = bike_registry.brand_from_url(url)
        parsed = bike_registry.parse_bikes_from_article(text, url, brand_hint=brand)
        for entry in parsed:
            bike_id = entry["bike_id"]
            display = f"{bike_registry.BRAND_DISPLAY[entry['brand']]} {entry['canonical']}"
            database.upsert_bike(
                bike_id=bike_id,
                brand=bike_registry.BRAND_DISPLAY[entry["brand"]],
                model=entry["canonical"],
                display_name=display,
                keywords=entry["keywords"],
                bikewale_slug=entry.get("bikewale_slug"),
                launch_month=month,
            )
            if entry.get("bikewale_slug"):
                database.set_bikewale_ok(bike_id, True, slug=entry["bikewale_slug"])
            if month:
                database.upsert_sale(
                    bike_id=bike_id,
                    month=month,
                    units_sold=entry["units"],
                    source_url=url,
                    confidence="medium",
                )
            new_bike_ids.add(bike_id)
        with lock:
            progress["urls_done"] = progress.get("urls_done", 0) + 1
            progress["bikes_found"] = len(new_bike_ids)

    # Verify BikeWale slugs for bikes that don't have one yet
    with lock:
        progress["stage"] = "verifying BikeWale slugs"
    for bike_id in list(new_bike_ids):
        bike = database.get_bike(bike_id)
        if not bike or bike.get("bikewale_slug"):
            continue
        slug = bike_registry.verify_bikewale_slug(
            brand=bike["brand"].lower().replace(" ", "-"),
            model=bike["model"],
        )
        if slug:
            database.set_bikewale_ok(bike_id, True, slug=slug)

    database.log_scrape_run(len(articles), len(new_bike_ids), None)
    return new_bike_ids


def _run_discovery():
    """Standalone discovery — called by /api/bikes/discover."""
    global _discovery_running
    with _discovery_lock:
        _discovery_progress.update({"running": True, "error": None})
    try:
        _do_discovery_pass(_discovery_progress, _discovery_lock)
    except Exception as e:
        print(f"[discovery] ERROR: {e}")
        with _discovery_lock:
            _discovery_progress["error"] = str(e)
        database.log_scrape_run(0, 0, str(e))
    finally:
        with _discovery_lock:
            _discovery_progress["running"] = False
            _discovery_progress["stage"] = "done"
        _discovery_running = False


@app.post("/api/bikes/discover")
def trigger_discovery():
    global _discovery_running
    with _discovery_lock:
        if _discovery_running:
            return {"status": "already_running"}
        _discovery_running = True
    threading.Thread(target=_run_discovery, daemon=True).start()
    return {"status": "started"}


@app.get("/api/bikes/discover/status")
def discovery_status():
    with _discovery_lock:
        return dict(_discovery_progress)


# ===========================================================================
# Refresh-all orchestrator (discovery + reviews for every catalogued bike)
# ===========================================================================

_refresh_all_lock = threading.Lock()
_refresh_all_running: bool = False
_refresh_all_state: dict = {
    "running": False,
    "stage": "idle",            # idle | discovering | reviews | other_sources | retail | done | error
    "started_at": None,
    "finished_at": None,
    "discovery": {
        "stage": "", "urls_total": 0, "urls_done": 0, "bikes_found": 0,
    },
    "reviews": {
        "bikes_total": 0, "bikes_done": 0,
        "current_bike": None, "current_bike_id": None,
        "reviews_added": 0,
    },
    "other_sources": {          # BikeDekho + ZigWheels + Reddit
        "bikes_total": 0, "bikes_done": 0,
        "current_bike": None, "current_bike_id": None,
        "bikedekho_added": 0, "zigwheels_added": 0, "reddit_added": 0,
    },
    "retail": {                 # FADA monthly retail PDFs
        "pdfs_total": 0, "pdfs_done": 0, "rows_added": 0,
    },
    "error": None,
}


def _run_refresh_all():
    global _refresh_all_running
    started = time.time()
    started_iso = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()

    with _refresh_all_lock:
        _refresh_all_state.update({
            "running": True,
            "stage": "discovering",
            "started_at": started_iso,
            "finished_at": None,
            "error": None,
        })
        _refresh_all_state["discovery"] = {
            "stage": "", "urls_total": 0, "urls_done": 0, "bikes_found": 0,
        }
        _refresh_all_state["reviews"] = {
            "bikes_total": 0, "bikes_done": 0,
            "current_bike": None, "current_bike_id": None,
            "reviews_added": 0,
        }
        _refresh_all_state["other_sources"] = {
            "bikes_total": 0, "bikes_done": 0,
            "current_bike": None, "current_bike_id": None,
            "bikedekho_added": 0, "zigwheels_added": 0, "reddit_added": 0,
        }
        _refresh_all_state["retail"] = {
            "pdfs_total": 0, "pdfs_done": 0, "rows_added": 0,
        }

    total_reviews = 0
    total_retail_rows = 0
    try:
        # Stage 1 — discovery
        _do_discovery_pass(_refresh_all_state["discovery"], _refresh_all_lock)

        # Stage 2 — reviews per catalogued bike
        with _refresh_all_lock:
            _refresh_all_state["stage"] = "reviews"
        bikes = [b for b in database.get_all_bikes() if b.get("bikewale_slug")]
        with _refresh_all_lock:
            _refresh_all_state["reviews"]["bikes_total"] = len(bikes)

        for bike in bikes:
            with _refresh_all_lock:
                _refresh_all_state["reviews"]["current_bike"] = bike["display_name"]
                _refresh_all_state["reviews"]["current_bike_id"] = bike["id"]
            try:
                reviews = scrape_reviews_for_bike(bike)
                for r in reviews:
                    database.upsert_review(
                        bike_id=r["bike_id"],
                        source=r["source"],
                        post_id=r["post_id"],
                        username=r.get("username"),
                        review_text=r.get("review_text", ""),
                        overall_rating=r.get("overall_rating"),
                        thread_url=r.get("thread_url"),
                    )
                total_reviews += len(reviews)
            except Exception as bike_err:
                # Don't blow up the whole refresh if one bike fails
                print(f"[refresh-all] {bike['id']} review scrape failed: {bike_err}")
            with _refresh_all_lock:
                _refresh_all_state["reviews"]["bikes_done"] += 1
                _refresh_all_state["reviews"]["reviews_added"] = total_reviews

        database.log_reviews_run(total_reviews, None)

        # Stage 3 — additional review sources (BikeDekho, ZigWheels, Reddit)
        # All three reuse the same `bikes` set as the BikeWale stage. Each
        # scraper is wrapped in its own try/except so a single failing source
        # never aborts the rest.
        with _refresh_all_lock:
            _refresh_all_state["stage"] = "other_sources"
            _refresh_all_state["other_sources"]["bikes_total"] = len(bikes)

        for bike in bikes:
            with _refresh_all_lock:
                _refresh_all_state["other_sources"]["current_bike"] = bike["display_name"]
                _refresh_all_state["other_sources"]["current_bike_id"] = bike["id"]

            for source_key, scraper in (
                ("bikedekho_added", scrape_bikedekho_for_bike),
                ("zigwheels_added", scrape_zigwheels_for_bike),
                ("reddit_added",    scrape_reddit_for_bike),
            ):
                try:
                    new_reviews = scraper(bike)
                    for r in new_reviews:
                        database.upsert_review(
                            bike_id=r["bike_id"],
                            source=r["source"],
                            post_id=r["post_id"],
                            username=r.get("username"),
                            review_text=r.get("review_text", ""),
                            overall_rating=r.get("overall_rating"),
                            thread_url=r.get("thread_url"),
                        )
                    with _refresh_all_lock:
                        _refresh_all_state["other_sources"][source_key] += len(new_reviews)
                    total_reviews += len(new_reviews)
                except Exception as src_err:
                    print(f"[refresh-all] {bike['id']} {source_key.split('_')[0]} failed: {src_err}")

            with _refresh_all_lock:
                _refresh_all_state["other_sources"]["bikes_done"] += 1

        # Stage 4 — FADA monthly retail PDFs (brand-level)
        with _refresh_all_lock:
            _refresh_all_state["stage"] = "retail"
        try:
            pdfs = fada_scraper.discover_monthly_pdfs(limit=24)
            with _refresh_all_lock:
                _refresh_all_state["retail"]["pdfs_total"] = len(pdfs)
            for pdf in pdfs:
                oems = fada_scraper.fetch_and_parse_pdf(pdf["url"], pdf["month"])
                for entry in oems:
                    brand_id = fada_scraper._oem_to_brand_id(entry["oem"])
                    if not brand_id:
                        continue
                    database.upsert_retail_brand_sale(
                        brand_id=brand_id,
                        month=pdf["month"],
                        units=entry["units"],
                        source_url=pdf["url"],
                    )
                    total_retail_rows += 1
                with _refresh_all_lock:
                    _refresh_all_state["retail"]["pdfs_done"] += 1
                    _refresh_all_state["retail"]["rows_added"] = total_retail_rows
        except Exception as fe:
            # Don't fail the whole refresh if FADA breaks; just record it
            print(f"[refresh-all] FADA stage failed: {fe}")

        finished_iso = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
        with _refresh_all_lock:
            _refresh_all_state.update({
                "stage": "done",
                "finished_at": finished_iso,
                "duration_seconds": round(time.time() - started, 1),
            })
    except Exception as e:
        print(f"[refresh-all] ERROR: {e}")
        with _refresh_all_lock:
            _refresh_all_state.update({
                "stage": "error",
                "error": str(e),
                "finished_at": __import__("datetime").datetime.now(
                    __import__("datetime").timezone.utc).isoformat(),
            })
        database.log_reviews_run(total_reviews, str(e))
    finally:
        with _refresh_all_lock:
            _refresh_all_state["running"] = False
        _refresh_all_running = False


@app.post("/api/refresh-all")
def trigger_refresh_all():
    global _refresh_all_running
    with _refresh_all_lock:
        if _refresh_all_running:
            return {"status": "already_running"}
        _refresh_all_running = True
    threading.Thread(target=_run_refresh_all, daemon=True).start()
    return {"status": "started"}


@app.get("/api/refresh-all/status")
def refresh_all_status():
    with _refresh_all_lock:
        # Deep-copy nested dicts so the response is a snapshot
        return {
            "running": _refresh_all_state["running"],
            "stage": _refresh_all_state["stage"],
            "started_at": _refresh_all_state["started_at"],
            "finished_at": _refresh_all_state["finished_at"],
            "duration_seconds": _refresh_all_state.get("duration_seconds"),
            "discovery": dict(_refresh_all_state["discovery"]),
            "reviews": dict(_refresh_all_state["reviews"]),
            "other_sources": dict(_refresh_all_state.get("other_sources") or {}),
            "retail": dict(_refresh_all_state.get("retail") or {}),
            "error": _refresh_all_state["error"],
        }


# ===========================================================================
# Bike-scoped sales
# ===========================================================================

@app.get("/api/bikes/{bike_id}/sales")
def get_bike_sales(bike_id: str):
    return database.get_all_sales(bike_id=bike_id)


@app.get("/api/bikes/{bike_id}/metrics")
def get_bike_metrics(bike_id: str):
    return database.get_metrics(bike_id=bike_id)


def _run_single_bike_refresh(bike_id: str):
    bike = database.get_bike(bike_id)
    if not bike:
        return
    articles = scrape_all()
    success = 0
    try:
        for article in articles:
            r = extract_sales_for_bike(article["text"], article["url"], bike)
            if r:
                database.upsert_sale(
                    bike_id=r["bike_id"],
                    month=r["month"],
                    units_sold=r["units_sold"],
                    source_url=r["source_url"],
                    confidence=r["confidence"],
                )
                success += 1
        database.log_scrape_run(len(articles), success, None)
    except Exception as e:
        database.log_scrape_run(len(articles), success, str(e))


@app.post("/api/bikes/{bike_id}/refresh")
def trigger_bike_refresh(bike_id: str, background_tasks: BackgroundTasks):
    background_tasks.add_task(_run_single_bike_refresh, bike_id)
    return {"status": "started"}


@app.get("/api/refresh/status")
def refresh_status():
    log = database.get_last_scrape_log()
    return log or {"run_at": None, "urls_tried": 0, "urls_success": 0, "error_msg": None}


# ===========================================================================
# Bike-scoped forecast (Prophet) + missing-value imputation + anomalies
# ===========================================================================

# Module-global in-memory cache keyed by (bike_id, horizon, interval_width).
# 24h TTL — Prophet fit is 5-30s per bike on this data so re-fitting on
# every page load would be wasteful. Loss on backend restart is fine.
_FORECAST_CACHE_TTL_SECONDS = 24 * 60 * 60
_forecast_cache: dict[tuple, dict] = {}
_forecast_cache_meta: dict[tuple, float] = {}    # cache_key -> stored_at (epoch s)
_forecast_state: dict[str, dict] = {}            # bike_id -> {stage, error, started_at}
_forecast_lock = threading.Lock()


def _forecast_cache_key(bike_id: str, horizon: int, interval_width: float) -> tuple:
    return (bike_id, horizon, round(interval_width, 3))


def _forecast_cached(bike_id: str, horizon: int, interval_width: float) -> dict | None:
    key = _forecast_cache_key(bike_id, horizon, interval_width)
    stored = _forecast_cache_meta.get(key)
    if stored is None:
        return None
    if time.time() - stored > _FORECAST_CACHE_TTL_SECONDS:
        _forecast_cache.pop(key, None)
        _forecast_cache_meta.pop(key, None)
        return None
    return _forecast_cache.get(key)


def _do_forecast(bike_id: str, horizon: int, interval_width: float):
    with _forecast_lock:
        _forecast_state[bike_id] = {
            "stage": "fitting",
            "started_at": time.time(),
            "error": None,
        }
    try:
        result = forecast_mod.run_forecast(
            bike_id, horizon=horizon, interval_width=interval_width
        )
        key = _forecast_cache_key(bike_id, horizon, interval_width)
        _forecast_cache[key] = result
        _forecast_cache_meta[key] = time.time()
        with _forecast_lock:
            _forecast_state[bike_id] = {
                "stage": "done",
                "started_at": _forecast_state[bike_id]["started_at"],
                "finished_at": time.time(),
                "error": None,
            }
    except Exception as e:
        print(f"[forecast] {bike_id} failed: {e}")
        with _forecast_lock:
            _forecast_state[bike_id] = {
                "stage": "error",
                "started_at": _forecast_state.get(bike_id, {}).get("started_at"),
                "finished_at": time.time(),
                "error": str(e),
            }


@app.get("/api/bikes/{bike_id}/forecast")
def get_bike_forecast(
    bike_id: str,
    horizon: int = Query(6, ge=1, le=24),
    interval_width: float = Query(0.95, gt=0, lt=1),
    refresh: bool = Query(False, description="Force re-fit even if cached"),
):
    """Returns the cached forecast if fresh; otherwise kicks off a background
    fit and returns 202 with `pending: true`. Poll `/forecast/status` to know
    when it's done."""
    if not refresh:
        cached = _forecast_cached(bike_id, horizon, interval_width)
        if cached:
            return cached
    # Kick off background fit unless one's already in flight for this bike
    with _forecast_lock:
        in_flight = _forecast_state.get(bike_id, {}).get("stage") == "fitting"
    if not in_flight:
        threading.Thread(
            target=_do_forecast,
            args=(bike_id, horizon, interval_width),
            daemon=True,
        ).start()
    return {
        "pending": True,
        "bike_id": bike_id,
        "message": "Forecast fitting in background — poll /forecast/status",
    }


@app.post("/api/bikes/{bike_id}/forecast/refresh")
def trigger_bike_forecast(
    bike_id: str,
    horizon: int = Query(6, ge=1, le=24),
    interval_width: float = Query(0.95, gt=0, lt=1),
):
    with _forecast_lock:
        if _forecast_state.get(bike_id, {}).get("stage") == "fitting":
            return {"status": "already_running"}
    threading.Thread(
        target=_do_forecast,
        args=(bike_id, horizon, interval_width),
        daemon=True,
    ).start()
    return {"status": "started", "bike_id": bike_id, "horizon": horizon}


@app.get("/api/bikes/{bike_id}/forecast/status")
def get_bike_forecast_status(bike_id: str):
    with _forecast_lock:
        state = dict(_forecast_state.get(bike_id) or {})
    return {
        "bike_id": bike_id,
        "stage": state.get("stage", "idle"),
        "error": state.get("error"),
        "started_at": state.get("started_at"),
        "finished_at": state.get("finished_at"),
    }


@app.get("/api/bikes/{bike_id}/anomalies")
def get_bike_anomalies(bike_id: str):
    """Standalone anomaly endpoint — runs imputation + anomaly detection
    only (no Prophet fit), so it's cheap to call from any tab."""
    series = forecast_mod.build_complete_index(bike_id)
    if series.empty:
        return {"bike_id": bike_id, "anomalies": []}
    imputed, _meta = forecast_mod.impute(series)
    return {
        "bike_id": bike_id,
        "anomalies": forecast_mod.detect_anomalies(imputed),
    }


@app.get("/api/bikes/{bike_id}/sales/series")
def get_bike_sales_series(bike_id: str):
    """Cheap, no-Prophet enriched history: imputed monthly series with
    inline anomaly flags. Used by the unified Sales view as its always-on
    layer; the forecast endpoint sits on top of it lazily."""
    return forecast_mod.build_series_payload(bike_id)


# ===========================================================================
# Bike-scoped reviews
# ===========================================================================

@app.get("/api/bikes/{bike_id}/reviews")
def get_bike_reviews(bike_id: str):
    return database.get_all_reviews(bike_id=bike_id)


@app.get("/api/bikes/{bike_id}/reviews/summary")
def get_bike_reviews_summary(bike_id: str):
    return database.get_review_summary(bike_id=bike_id)


def _run_bike_reviews_scrape(bike_id: str):
    error_msg = None
    total = 0
    try:
        bike = database.get_bike(bike_id)
        if not bike:
            return
        reviews = scrape_reviews_for_bike(bike)
        for r in reviews:
            database.upsert_review(
                bike_id=r["bike_id"],
                source=r["source"],
                post_id=r["post_id"],
                username=r.get("username"),
                review_text=r.get("review_text", ""),
                overall_rating=r.get("overall_rating"),
                thread_url=r.get("thread_url"),
            )
        total = len(reviews)
    except Exception as e:
        error_msg = str(e)
    database.log_reviews_run(total, error_msg)


@app.post("/api/bikes/{bike_id}/reviews/refresh")
def trigger_bike_reviews_refresh(bike_id: str, background_tasks: BackgroundTasks):
    background_tasks.add_task(_run_bike_reviews_scrape, bike_id)
    return {"status": "started"}


@app.get("/api/reviews/refresh/status")
def reviews_refresh_status():
    log = database.get_last_reviews_log()
    return log or {"run_at": None, "total_scraped": 0, "error_msg": None}


# ===========================================================================
# Bike-scoped themes
# ===========================================================================

# Per-bike running flag
_themes_running: dict[str, bool] = {}


class ThemesRequest(BaseModel):
    method: str = "keyword"
    config: dict = {}
    pool_scope: str = "bike"   # "bike" | "brand"


def _do_themes_analysis(bike_id: str, method: str, config: dict, pool_scope: str):
    try:
        themes_runner.run_analysis(method, config, bike_id=bike_id, pool_scope=pool_scope)
    except Exception as e:
        print(f"[themes] {bike_id} error: {e}")
    finally:
        _themes_running[bike_id] = False


@app.post("/api/bikes/{bike_id}/themes/analyze")
def run_bike_themes(bike_id: str, req: ThemesRequest, background_tasks: BackgroundTasks):
    if _themes_running.get(bike_id):
        return {"status": "already_running"}
    if req.pool_scope not in ("bike", "brand"):
        raise HTTPException(status_code=400, detail=f"pool_scope must be 'bike' or 'brand'")
    _themes_running[bike_id] = True
    background_tasks.add_task(
        _do_themes_analysis, bike_id, req.method, req.config, req.pool_scope
    )
    return {
        "status": "started",
        "method": req.method,
        "bike_id": bike_id,
        "pool_scope": req.pool_scope,
    }


@app.get("/api/bikes/{bike_id}/themes")
def get_bike_themes(bike_id: str):
    result = database.get_latest_themes(bike_id=bike_id)
    if not result:
        return {"themes": None, "error": "No analysis run yet."}
    return result


@app.get("/api/bikes/{bike_id}/themes/status")
def bike_themes_status(bike_id: str):
    db_status = database.get_themes_status(bike_id=bike_id)
    return {"running": _themes_running.get(bike_id, False), **db_status}


# ===========================================================================
# Compare
# ===========================================================================

@app.get("/api/compare")
def compare_bikes(ids: str = Query(..., description="comma-separated bike ids, max 4")):
    bike_ids = [b.strip() for b in ids.split(",") if b.strip()][:4]
    if len(bike_ids) < 2:
        raise HTTPException(status_code=400, detail="Provide at least 2 bike ids")

    bikes_meta: list[dict] = []
    series: list[dict] = []
    for bid in bike_ids:
        bike = database.get_bike(bid)
        if not bike:
            continue
        sales = database.get_all_sales(bike_id=bid)
        total = sum(s["units_sold"] for s in sales)
        peak = max(sales, key=lambda s: s["units_sold"]) if sales else None
        bikes_meta.append({
            "id": bid,
            "display_name": bike["display_name"],
            "brand": bike["brand"],
            "total_units": total,
            "months_tracked": len(sales),
            "peak_month": peak["month"] if peak else None,
            "peak_units": peak["units_sold"] if peak else 0,
            "avg_per_month": (total // len(sales)) if sales else 0,
        })
        for s in sales:
            series.append({
                "bike_id": bid,
                "month": s["month"],
                "units_sold": s["units_sold"],
            })
    return {"bikes": bikes_meta, "series": series}


# ===========================================================================
# Legacy redirects (so old clients still work)
# ===========================================================================

@app.get("/api/sales")
def legacy_sales():
    return RedirectResponse(f"/api/bikes/{LEGACY_BIKE_ID}/sales", status_code=308)


@app.get("/api/metrics")
def legacy_metrics():
    return RedirectResponse(f"/api/bikes/{LEGACY_BIKE_ID}/metrics", status_code=308)


@app.get("/api/reviews")
def legacy_reviews():
    return RedirectResponse(f"/api/bikes/{LEGACY_BIKE_ID}/reviews", status_code=308)


@app.get("/api/reviews/summary")
def legacy_reviews_summary():
    return RedirectResponse(f"/api/bikes/{LEGACY_BIKE_ID}/reviews/summary", status_code=308)


@app.get("/api/themes")
def legacy_themes():
    return RedirectResponse(f"/api/bikes/{LEGACY_BIKE_ID}/themes", status_code=308)


@app.get("/api/themes/keyword-defaults")
def themes_keyword_defaults():
    """Return the default theme→keywords mapping used by the Keyword Rules
    method. The frontend uses this to show users what's matched against and
    to compute their per-bucket overrides."""
    return themes_keyword.get_default_keywords()


@app.get("/api/themes/status")
def legacy_themes_status():
    return RedirectResponse(f"/api/bikes/{LEGACY_BIKE_ID}/themes/status", status_code=308)


# ===========================================================================
# Hardware & Ollama (unchanged from previous deployment)
# ===========================================================================

@app.get("/api/hardware")
def get_hardware():
    return hardware_detector.full_report()


_pull_state: dict[str, dict] = {}
_pull_lock = threading.Lock()


def _stream_pull(model_name: str):
    with _pull_lock:
        _pull_state[model_name] = {
            "status": "starting", "completed": 0, "total": 0, "percent": 0,
            "error": None, "finished": False, "started_at": time.time(),
        }
    try:
        with http_requests.post(
            "http://localhost:11434/api/pull",
            json={"name": model_name, "stream": True},
            stream=True, timeout=None,
        ) as resp:
            resp.raise_for_status()
            for raw in resp.iter_lines(decode_unicode=True):
                if not raw:
                    continue
                try:
                    evt = _json.loads(raw)
                except Exception:
                    continue
                completed = evt.get("completed", 0)
                total = evt.get("total", 0)
                percent = round(100 * completed / total, 1) if total else 0
                with _pull_lock:
                    _pull_state[model_name].update({
                        "status": evt.get("status", "downloading"),
                        "completed": completed, "total": total, "percent": percent,
                    })
                if evt.get("error"):
                    with _pull_lock:
                        _pull_state[model_name]["error"] = evt["error"]
                    break
        with _pull_lock:
            _pull_state[model_name]["finished"] = True
            _pull_state[model_name]["percent"] = 100
            _pull_state[model_name]["status"] = "success"
    except Exception as e:
        with _pull_lock:
            _pull_state[model_name]["error"] = str(e)
            _pull_state[model_name]["finished"] = True
            _pull_state[model_name]["status"] = "error"


@app.post("/api/ollama/pull/{model_name:path}")
def pull_ollama_model(model_name: str):
    with _pull_lock:
        existing = _pull_state.get(model_name)
        if existing and not existing.get("finished"):
            return {"status": "already_running", "model": model_name}
    threading.Thread(target=_stream_pull, args=(model_name,), daemon=True).start()
    return {"status": "started", "model": model_name}


@app.get("/api/ollama/pull/status")
def ollama_pull_status(model: str | None = None):
    with _pull_lock:
        if model:
            return _pull_state.get(model, {"status": "idle", "finished": True, "percent": 0})
        return dict(_pull_state)
