"""
Sales forecasting + missing-value imputation + anomaly detection.

Pipeline overview
-----------------

1. compute_launch_month(bike_id)
   The "launch month" is the floor for the imputed series: months earlier than
   that are *correctly absent* (the bike wasn't selling yet), not missing data.
   We use bikes.launch_month if populated, but override with the first observed
   month from sales_data if that's later (handles stale catalogue entries).

2. build_complete_index(bike_id) -> pd.Series
   Returns a month-indexed (PeriodIndex, freq='M') float Series spanning
   launch_month -> max(observed month). Months without an observation are NaN.

3. impute(series) -> (pd.Series, list[dict])
   Fills NaNs in priority order:
     - seasonal_naive : same calendar month from a prior year, when ≥12 months
                        of history exist and the prior-year value is known.
     - linear         : linear interpolation between the nearest known
                        neighbours (best for gaps of 1-2 months).
     - ffill          : forward-fill last known value (used when there's no
                        future anchor).
     - median         : median of the surrounding ±3 known months (rare
                        fallback, only when all the above failed).
   Returns the filled series plus a per-month metadata list:
     [{month: 'YYYY-MM', imputed: bool, impute_method: str | None}, ...]

4. fit_and_forecast(series, horizon, interval_width) -> dict
   Trains a Prophet model on the imputed series with monthly frequency and
   yearly seasonality (no daily/weekly — they're aggregated away). Returns
   `horizon` future months with point forecasts and confidence bounds.

5. detect_anomalies(series, z_thresh) -> list[dict]
   For each month, compute the z-score of its month-over-month delta against
   the rolling 12-month std of MoM deltas. Flags |z| > z_thresh. Returns one
   entry per flagged month with month, z_score, and a short reason.

The Prophet fit is intentionally quiet — its STAN backend is chatty and would
spam stdout otherwise.
"""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from typing import Iterable

import numpy as np
import pandas as pd

import database


# ---------------------------------------------------------------------------
# Launch-month resolution
# ---------------------------------------------------------------------------

def _month_to_period(s: str) -> pd.Period:
    return pd.Period(s, freq="M")


def compute_launch_month(bike_id: str) -> str | None:
    """Returns the launch month as 'YYYY-MM', or None if the bike has no
    sales rows AND no catalogue launch_month."""
    bike = database.get_bike(bike_id)
    catalogue_launch = (bike or {}).get("launch_month")  # may be None
    sales = database.get_all_sales(bike_id=bike_id)
    if not sales:
        return catalogue_launch
    earliest_observed = min(s["month"] for s in sales)
    # If the catalogue launch is *earlier* than the earliest observed,
    # something's odd (we missed data) — trust the observation as the floor.
    if catalogue_launch and _month_to_period(catalogue_launch) < _month_to_period(earliest_observed):
        return earliest_observed
    return catalogue_launch or earliest_observed


# ---------------------------------------------------------------------------
# Build the complete monthly index
# ---------------------------------------------------------------------------

def build_complete_index(bike_id: str) -> pd.Series:
    """Returns a Period-indexed (freq='M') float Series from launch_month
    through the most recent observed month. Missing months are NaN. Empty
    Series if there are no sales rows.

    When a month has multiple source rows (e.g. RushLane wholesale +
    AutoPunditz dispatch + an OCR'd infographic), the **median** is used as
    the canonical value. Median is robust to outliers and treats sources as
    independent estimates of truth. Use `build_distribution_payload()` if
    you need the full per-source breakdown for visualisation.
    """
    sales = database.get_all_sales(bike_id=bike_id)
    if not sales:
        return pd.Series(dtype="float64")
    launch = compute_launch_month(bike_id)
    if not launch:
        return pd.Series(dtype="float64")

    end = max(s["month"] for s in sales)
    idx = pd.period_range(start=_month_to_period(launch), end=_month_to_period(end), freq="M")

    by_month: dict[pd.Period, list[float]] = {}
    for s in sales:
        p = _month_to_period(s["month"])
        by_month.setdefault(p, []).append(float(s["units_sold"]))

    def _consolidate(vals: list[float]) -> float:
        return float(np.median(vals)) if vals else float("nan")

    values = [_consolidate(by_month.get(p, [])) if p in by_month else np.nan for p in idx]
    return pd.Series(values, index=idx, dtype="float64")


# ---------------------------------------------------------------------------
# Imputation
# ---------------------------------------------------------------------------

def _seasonal_naive(series: pd.Series, idx: pd.Period) -> float | None:
    """Return the value from the same calendar month one year earlier, if
    known. Falls back to two years earlier if that's known and last year's
    is missing."""
    for lag_years in (1, 2):
        prev = idx - 12 * lag_years
        if prev in series.index and not pd.isna(series.loc[prev]):
            return float(series.loc[prev])
    return None


def _median_window(series: pd.Series, idx: pd.Period, window: int = 3) -> float | None:
    """Median of known values in the ±window months around `idx`."""
    pos = series.index.get_loc(idx)
    lo = max(0, pos - window)
    hi = min(len(series), pos + window + 1)
    nearby = series.iloc[lo:hi].dropna()
    if nearby.empty:
        return None
    return float(nearby.median())


def impute(series: pd.Series) -> tuple[pd.Series, list[dict]]:
    """Fill NaNs in the input series. Returns (filled_series, metadata_list)
    where metadata_list is one dict per month in the original index order:
    {"month": "YYYY-MM", "imputed": bool, "impute_method": str | None}."""
    out = series.copy()
    meta: list[dict] = []
    if out.empty:
        return out, meta

    # Snapshot of which positions are missing — we detect this BEFORE any
    # interpolation so the metadata is honest.
    missing_mask = out.isna()
    has_history_for_seasonal = len(out) >= 12

    # Phase 1 — try seasonal naive (touches missing slots only)
    if has_history_for_seasonal:
        for i, idx in enumerate(out.index):
            if missing_mask.iloc[i] and pd.isna(out.iloc[i]):
                v = _seasonal_naive(out, idx)
                if v is not None:
                    out.iloc[i] = v

    # Phase 2 — linear interpolation for remaining interior gaps.
    # `interpolate(method='linear')` only fills between known values, not at
    # the edges, which is exactly what we want here.
    out = out.interpolate(method="linear", limit_direction="both" if False else "forward")
    # Note: limit_direction='forward' won't fill leading-edge NaNs; we handle
    # those + trailing edge separately so we can record the method correctly.

    # Phase 3 — forward-fill any trailing NaNs (no future anchor).
    out = out.ffill()

    # Phase 4 — back-fill leading NaNs (rare: would mean launch month itself
    # has no observation but the catalogue still pegged launch there).
    # Fall back to median window so we record `median` rather than `bfill`.
    leading_missing_idx = []
    for i in range(len(out)):
        if pd.isna(out.iloc[i]):
            leading_missing_idx.append(out.index[i])
        else:
            break
    for idx in leading_missing_idx:
        v = _median_window(out, idx) or 0.0
        out.loc[idx] = v

    # Build metadata: which method filled each previously-missing slot
    # We re-run the priority ladder against the ORIGINAL series to record the
    # method, then accept whatever value `out` ended up holding.
    for i, idx in enumerate(out.index):
        was_missing = bool(missing_mask.iloc[i])
        if not was_missing:
            meta.append({"month": str(idx), "imputed": False, "impute_method": None})
            continue
        method: str
        if has_history_for_seasonal and _seasonal_naive(series, idx) is not None:
            method = "seasonal_naive"
        else:
            # Determine if this slot had known neighbours on both sides
            prev_known = series.iloc[:i].last_valid_index()
            next_known = series.iloc[i + 1:].first_valid_index()
            if prev_known is not None and next_known is not None:
                method = "linear"
            elif prev_known is not None:
                method = "ffill"
            else:
                method = "median"
        meta.append({"month": str(idx), "imputed": True, "impute_method": method})

    return out, meta


# ---------------------------------------------------------------------------
# Forecasting
# ---------------------------------------------------------------------------

def fit_and_forecast(
    series: pd.Series,
    horizon: int = 6,
    interval_width: float = 0.95,
) -> dict:
    """Fit Prophet on the (already-imputed) monthly series and return the
    next `horizon` months with point + bounds. The series MUST be free of
    NaNs and have a PeriodIndex with freq='M'."""
    if series.empty or series.isna().any():
        raise ValueError("fit_and_forecast: series must be non-empty and fully imputed")

    # Prophet wants a 2-col DataFrame {ds: datetime, y: float}
    df = pd.DataFrame({
        "ds": series.index.to_timestamp(),
        "y": series.values,
    })

    # Lazy import: prophet pulls cmdstanpy + matplotlib (~200 MB), so don't
    # block module import for callers that only need imputation.
    from prophet import Prophet  # noqa: WPS433

    n = len(series)
    yearly_ok = n >= 24  # need ≥2 yearly cycles before yearly seasonality is meaningful
    model = Prophet(
        yearly_seasonality=yearly_ok,
        weekly_seasonality=False,
        daily_seasonality=False,
        interval_width=interval_width,
    )
    # Silence STAN's chatty stdout/stderr
    sink = io.StringIO()
    with redirect_stdout(sink), redirect_stderr(sink):
        model.fit(df)

    future = model.make_future_dataframe(periods=horizon, freq="MS")
    pred = model.predict(future)

    forecast_rows = pred.tail(horizon)[["ds", "yhat", "yhat_lower", "yhat_upper"]]
    out = []
    for _, row in forecast_rows.iterrows():
        out.append({
            "month": row["ds"].strftime("%Y-%m"),
            "yhat": max(0.0, float(row["yhat"])),  # clip at 0 (can't sell negative units)
            "yhat_lower": max(0.0, float(row["yhat_lower"])),
            "yhat_upper": max(0.0, float(row["yhat_upper"])),
        })

    # Heuristic: short-history forecasts are wide and unreliable. Surface
    # this so the UI can banner it.
    low_confidence = n < 12
    return {
        "horizon": horizon,
        "interval_width": interval_width,
        "low_confidence": low_confidence,
        "n_observed": n,
        "forecast": out,
    }


# ---------------------------------------------------------------------------
# Anomaly detection
# ---------------------------------------------------------------------------

def detect_anomalies(series: pd.Series, z_thresh: float = 2.5) -> list[dict]:
    """Flag months whose MoM delta is far from the rolling 12-month MoM std.
    Returns [{month, z_score, units, prev_units, reason}, ...] for the months
    that exceed the threshold. Uses the imputed series so synthetic gaps
    don't trip the z-score."""
    if len(series) < 4:
        return []

    deltas = series.diff()  # NaN at index 0
    rolling_std = deltas.rolling(window=12, min_periods=4).std()
    rolling_mean = deltas.rolling(window=12, min_periods=4).mean()

    out: list[dict] = []
    for i in range(1, len(series)):
        d = deltas.iloc[i]
        s = rolling_std.iloc[i]
        m = rolling_mean.iloc[i]
        if pd.isna(d) or pd.isna(s) or s == 0:
            continue
        z = (d - m) / s
        if abs(z) >= z_thresh:
            out.append({
                "month": str(series.index[i]),
                "units": float(series.iloc[i]),
                "prev_units": float(series.iloc[i - 1]),
                "z_score": float(z),
                "reason": f"month-over-month delta {d:+.0f} is {z:+.1f}σ vs trailing 12-mo norm",
            })
    return out


# ---------------------------------------------------------------------------
# Public end-to-end drivers
# ---------------------------------------------------------------------------

def build_series_payload(bike_id: str) -> dict:
    """Cheap, no-Prophet helper: imputed monthly history + anomalies + per-
    source breakdown. Used by the unified Sales view for its always-on layer
    (the forecast layer is fetched lazily on top).

    Each row in `history` carries:
      - `units` (the median across reporting sources, or the imputed value)
      - `imputed` + `impute_method` (whether and how this month was filled)
      - `anomaly` (null or `{is_anomaly: true, z_score}`)
      - `n_sources` (how many sources reported this month — 0 if imputed)
      - `stddev` (sample std of the reporting sources, or null)
      - `sources` ([{source, units_sold, source_url}, ...]) — full
        breakdown so the UI can render a distribution popover on click.
    """
    raw = build_complete_index(bike_id)
    if raw.empty:
        return {
            "bike_id": bike_id,
            "history": [],
            "anomalies": [],
        }

    imputed_series, meta = impute(raw)
    anomalies = detect_anomalies(imputed_series)
    anomaly_by_month = {a["month"]: a for a in anomalies}

    # Per-month per-source breakdown
    by_month_sources = {
        row["month"]: row["sources"]
        for row in database.get_sales_by_month_with_sources(bike_id)
    }

    history_payload: list[dict] = []
    for i, m in enumerate(meta):
        v = imputed_series.iloc[i]
        anomaly_entry = anomaly_by_month.get(m["month"])
        sources = by_month_sources.get(m["month"], [])
        units_only = [s["units_sold"] for s in sources]
        stddev: float | None
        if len(units_only) >= 2:
            stddev = float(np.std(units_only, ddof=1))
        else:
            stddev = None
        history_payload.append({
            "month": m["month"],
            "units": float(v),
            "imputed": m["imputed"],
            "impute_method": m["impute_method"],
            "anomaly": (
                {"is_anomaly": True, "z_score": anomaly_entry["z_score"]}
                if anomaly_entry else None
            ),
            "n_sources": len(sources),
            "stddev": stddev,
            "sources": sources,
        })

    return {
        "bike_id": bike_id,
        "history": history_payload,
        "anomalies": anomalies,
    }


# ---------------------------------------------------------------------------
# Brand-level helpers — used by the "All models" view. Same pipeline shape
# as the per-bike helpers above; the only difference is the input series is
# RushLane sums across every bike in the brand.
# ---------------------------------------------------------------------------

def _brand_launch_month(brand_id: str) -> str | None:
    """Earliest observed sales month across all bikes in the brand."""
    sales = database.get_wholesale_brand_totals(brand_id)
    if not sales:
        return None
    return min(s["month"] for s in sales)


def build_brand_complete_index(brand_id: str) -> pd.Series:
    """Brand-summed Period-indexed (freq='M') float Series spanning the
    earliest observed brand-month → most recent. Missing months are NaN.

    Sums the RushLane (wholesale) values across every bike whose brand
    matches. FADA brand-level retail values are NOT folded in here — they
    surface separately in the chart as a secondary line and as a second row
    in the per-month distribution dialog. This keeps the imputation +
    Prophet pipeline driven by a single coherent source.
    """
    summed = database.get_wholesale_brand_totals(brand_id)
    if not summed:
        return pd.Series(dtype="float64")
    launch = _brand_launch_month(brand_id)
    if not launch:
        return pd.Series(dtype="float64")
    end = max(s["month"] for s in summed)
    idx = pd.period_range(
        start=_month_to_period(launch), end=_month_to_period(end), freq="M"
    )
    by_month = {_month_to_period(s["month"]): float(s["units"]) for s in summed}
    values = [by_month.get(p, np.nan) for p in idx]
    return pd.Series(values, index=idx, dtype="float64")


def build_brand_series_payload(brand_id: str) -> dict:
    """Mirror of build_series_payload but for brand-summed series. Adds a
    `secondary_series` block with FADA retail values per month so the chart
    can draw the cross-source comparison as a second line. Each history row
    also lists the per-source values (RushLane sum + FADA retail) so the
    distribution dialog opens with the same shape as bike-level."""
    raw = build_brand_complete_index(brand_id)
    if raw.empty:
        return {
            "brand_id": brand_id,
            "history": [],
            "anomalies": [],
            "secondary_series": [],
        }
    imputed_series, meta = impute(raw)
    anomalies = detect_anomalies(imputed_series)
    anomaly_by_month = {a["month"]: a for a in anomalies}

    rushlane_summed = {
        s["month"]: int(s["units"])
        for s in database.get_wholesale_brand_totals(brand_id)
    }
    fada_rows = {
        r["month"]: int(r["units"])
        for r in database.get_retail_brand_sales(brand_id=brand_id)
    }
    # AutoPunditz brand totals come from the monthly aggregate posts
    # (wholesale_brand_sales table). We treat the explicit brand-total as
    # authoritative for the brand chart — model-level autopunditz coverage
    # from per-brand posts is partial, so summing it would understate.
    autopunditz_rows = {
        r["month"]: int(r["units"])
        for r in database.get_wholesale_brand_sales(
            brand_id=brand_id, source="autopunditz"
        )
    }

    history_payload: list[dict] = []
    for i, m in enumerate(meta):
        v = imputed_series.iloc[i]
        sources = []
        rl = rushlane_summed.get(m["month"])
        if rl is not None:
            sources.append({
                "source": "rushlane",
                "units_sold": rl,
                "source_url": None,
            })
        ap = autopunditz_rows.get(m["month"])
        if ap is not None:
            sources.append({
                "source": "autopunditz",
                "units_sold": ap,
                "source_url": None,
            })
        fada = fada_rows.get(m["month"])
        if fada is not None:
            sources.append({
                "source": "fada_retail",
                "units_sold": fada,
                "source_url": None,
            })
        units_only = [s["units_sold"] for s in sources]
        stddev = float(np.std(units_only, ddof=1)) if len(units_only) >= 2 else None
        anomaly_entry = anomaly_by_month.get(m["month"])
        history_payload.append({
            "month": m["month"],
            "units": float(v),
            "imputed": m["imputed"],
            "impute_method": m["impute_method"],
            "anomaly": (
                {"is_anomaly": True, "z_score": anomaly_entry["z_score"]}
                if anomaly_entry else None
            ),
            "n_sources": len(sources),
            "stddev": stddev,
            "sources": sources,
        })

    secondary_payload = [
        {"month": m, "units": int(u)}
        for m, u in sorted(fada_rows.items())
    ]

    return {
        "brand_id": brand_id,
        "history": history_payload,
        "anomalies": anomalies,
        "secondary_series": secondary_payload,
    }


def run_brand_forecast(
    brand_id: str, horizon: int = 6, interval_width: float = 0.95
) -> dict:
    """Brand-level Prophet forecast — fits on the brand-summed RushLane
    series. Returns the same payload shape as run_forecast (history, forecast,
    anomalies, low_confidence) so the frontend can reuse the per-bike chart
    layer wholesale."""
    raw = build_brand_complete_index(brand_id)
    if raw.empty:
        return {
            "error": f"No sales data for brand {brand_id}",
            "history": [],
            "forecast": [],
        }

    imputed_series, meta = impute(raw)
    history_payload = []
    for i, m in enumerate(meta):
        v = imputed_series.iloc[i]
        history_payload.append({
            "month": m["month"],
            "units": float(v),
            "imputed": m["imputed"],
            "impute_method": m["impute_method"],
        })

    forecast_payload = fit_and_forecast(
        imputed_series, horizon=horizon, interval_width=interval_width
    )
    anomalies = detect_anomalies(imputed_series)

    return {
        "brand_id": brand_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "history": history_payload,
        "anomalies": anomalies,
        **forecast_payload,
    }


def run_forecast(bike_id: str, horizon: int = 6, interval_width: float = 0.95) -> dict:
    """Build the imputed series, fit Prophet, return the full payload."""
    raw = build_complete_index(bike_id)
    if raw.empty:
        return {"error": f"No sales data for {bike_id}", "history": [], "forecast": []}

    imputed_series, meta = impute(raw)
    history_payload = []
    for i, m in enumerate(meta):
        v = imputed_series.iloc[i]
        history_payload.append({
            "month": m["month"],
            "units": float(v),
            "imputed": m["imputed"],
            "impute_method": m["impute_method"],
        })

    forecast_payload = fit_and_forecast(
        imputed_series, horizon=horizon, interval_width=interval_width
    )
    anomalies = detect_anomalies(imputed_series)

    return {
        "bike_id": bike_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "history": history_payload,
        "anomalies": anomalies,
        **forecast_payload,
    }
