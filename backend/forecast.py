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
    Series if there are no sales rows."""
    sales = database.get_all_sales(bike_id=bike_id)
    if not sales:
        return pd.Series(dtype="float64")
    launch = compute_launch_month(bike_id)
    if not launch:
        return pd.Series(dtype="float64")

    end = max(s["month"] for s in sales)
    idx = pd.period_range(start=_month_to_period(launch), end=_month_to_period(end), freq="M")

    # Sum units across multiple sources for the same month (rushlane vs fada)
    by_month: dict[pd.Period, float] = {}
    for s in sales:
        p = _month_to_period(s["month"])
        if p in by_month:
            by_month[p] = max(by_month[p], float(s["units_sold"]))  # take the larger of the two
        else:
            by_month[p] = float(s["units_sold"])

    values = [by_month.get(p, np.nan) for p in idx]
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
# Public end-to-end driver — convenience for the API endpoint
# ---------------------------------------------------------------------------

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
