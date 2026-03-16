"""
Weather Data Pipeline
Fetches weather data from Open-Meteo API (free, no API key required),
validates and cleans the data, then persists it to PostgreSQL.
"""

import os
import time
import logging
import sys
from datetime import datetime, timezone

import requests
import psycopg2
from psycopg2.extras import execute_batch

# ──────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Config (from environment variables)
# ──────────────────────────────────────────────
DB_HOST     = os.getenv("DB_HOST", "db")
DB_PORT     = int(os.getenv("DB_PORT", "5432"))
DB_NAME     = os.getenv("DB_NAME", "weatherdb")
DB_USER     = os.getenv("DB_USER", "weatheruser")
DB_PASSWORD = os.getenv("DB_PASSWORD", "weatherpass")

# Locations to track
LOCATIONS = [
    {"name": "Berlin",    "lat": 52.52,  "lon": 13.41},
    {"name": "Hamburg",   "lat": 53.55,  "lon": 10.00},
    {"name": "München",   "lat": 48.14,  "lon": 11.58},
    {"name": "Köln",      "lat": 50.94,  "lon": 6.96},
    {"name": "Frankfurt", "lat": 50.11,  "lon": 8.68},
]

API_BASE = "https://api.open-meteo.com/v1/forecast"
API_PARAMS = {
    "hourly": "temperature_2m,relativehumidity_2m,windspeed_10m,precipitation",
    "current_weather": "true",
    "timezone": "Europe/Berlin",
    "forecast_days": 1,
}

# ──────────────────────────────────────────────
# Database
# ──────────────────────────────────────────────
def get_connection():
    """Establish a database connection with retry logic."""
    for attempt in range(1, 11):
        try:
            conn = psycopg2.connect(
                host=DB_HOST,
                port=DB_PORT,
                dbname=DB_NAME,
                user=DB_USER,
                password=DB_PASSWORD,
            )
            log.info("Database connection established.")
            return conn
        except psycopg2.OperationalError as e:
            log.warning(f"DB not ready (attempt {attempt}/10): {e}")
            time.sleep(5)
    raise RuntimeError("Could not connect to the database after 10 attempts.")


def insert_readings(conn, records: list[dict]) -> int:
    """Bulk-insert validated weather records. Returns number of rows inserted."""
    if not records:
        return 0

    sql = """
        INSERT INTO weather_readings
            (location, latitude, longitude, recorded_at,
             temperature_c, humidity_pct, windspeed_kmh, precipitation_mm,
             weather_code, is_day, fetched_at)
        VALUES
            (%(location)s, %(latitude)s, %(longitude)s, %(recorded_at)s,
             %(temperature_c)s, %(humidity_pct)s, %(windspeed_kmh)s, %(precipitation_mm)s,
             %(weather_code)s, %(is_day)s, %(fetched_at)s)
        ON CONFLICT (location, recorded_at) DO UPDATE SET
            temperature_c    = EXCLUDED.temperature_c,
            humidity_pct     = EXCLUDED.humidity_pct,
            windspeed_kmh    = EXCLUDED.windspeed_kmh,
            precipitation_mm = EXCLUDED.precipitation_mm,
            fetched_at       = EXCLUDED.fetched_at;
    """
    with conn.cursor() as cur:
        execute_batch(cur, sql, records, page_size=100)
    conn.commit()
    return len(records)


def log_pipeline_run(conn, location: str, rows_fetched: int,
                     rows_valid: int, rows_inserted: int,
                     status: str, error_msg: str | None = None):
    """Write a summary row to the audit log table."""
    sql = """
        INSERT INTO pipeline_runs
            (location, rows_fetched, rows_valid, rows_inserted, status, error_msg)
        VALUES (%s, %s, %s, %s, %s, %s);
    """
    with conn.cursor() as cur:
        cur.execute(sql, (location, rows_fetched, rows_valid, rows_inserted,
                          status, error_msg))
    conn.commit()


# ──────────────────────────────────────────────
# API fetching
# ──────────────────────────────────────────────
def fetch_weather(location: dict) -> dict | None:
    """Call Open-Meteo API for a single location. Returns raw JSON or None."""
    params = {**API_PARAMS, "latitude": location["lat"], "longitude": location["lon"]}
    try:
        resp = requests.get(API_BASE, params=params, timeout=15)
        resp.raise_for_status()
        log.info(f"Fetched data for {location['name']} (HTTP {resp.status_code})")
        return resp.json()
    except requests.exceptions.Timeout:
        log.error(f"Timeout fetching {location['name']}")
    except requests.exceptions.HTTPError as e:
        log.error(f"HTTP error for {location['name']}: {e}")
    except requests.exceptions.RequestException as e:
        log.error(f"Network error for {location['name']}: {e}")
    return None


# ──────────────────────────────────────────────
# Validation & Cleaning
# ──────────────────────────────────────────────
VALID_TEMP_RANGE   = (-60.0, 60.0)   # °C
VALID_HUMID_RANGE  = (0.0,  100.0)   # %
VALID_WIND_RANGE   = (0.0,  400.0)   # km/h
VALID_PRECIP_RANGE = (0.0,  500.0)   # mm

def _in_range(value, lo, hi) -> bool:
    return value is not None and lo <= value <= hi

def validate_and_clean(raw: dict, location: dict) -> list[dict]:
    """
    Parse the hourly arrays from the API response into individual records.
    Each record is validated; invalid fields are set to None and flagged.
    Returns only records that pass the minimum validity check.
    """
    hourly       = raw.get("hourly", {})
    current_w    = raw.get("current_weather", {})
    fetched_at   = datetime.now(timezone.utc)

    times        = hourly.get("time", [])
    temperatures = hourly.get("temperature_2m", [])
    humidities   = hourly.get("relativehumidity_2m", [])
    windspeeds   = hourly.get("windspeed_10m", [])
    precipitations = hourly.get("precipitation", [])

    records = []
    errors  = 0

    for i, ts_str in enumerate(times):
        try:
            recorded_at = datetime.fromisoformat(ts_str).replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            log.debug(f"Invalid timestamp at index {i}: {ts_str!r} — skipped")
            errors += 1
            continue

        temp   = temperatures[i]   if i < len(temperatures)   else None
        humid  = humidities[i]     if i < len(humidities)     else None
        wind   = windspeeds[i]     if i < len(windspeeds)     else None
        precip = precipitations[i] if i < len(precipitations) else None

        # ── field-level validation ──
        field_errors = []
        if not _in_range(temp,   *VALID_TEMP_RANGE):
            field_errors.append(f"temp={temp}")
            temp = None
        if not _in_range(humid,  *VALID_HUMID_RANGE):
            field_errors.append(f"humid={humid}")
            humid = None
        if not _in_range(wind,   *VALID_WIND_RANGE):
            field_errors.append(f"wind={wind}")
            wind = None
        if not _in_range(precip, *VALID_PRECIP_RANGE):
            field_errors.append(f"precip={precip}")
            precip = None

        if field_errors:
            log.warning(f"[{location['name']}] {ts_str} – invalid fields set to NULL: {', '.join(field_errors)}")
            errors += 1

        # ── minimum validity: at least temperature must be present ──
        if temp is None:
            log.debug(f"[{location['name']}] {ts_str} – no valid temperature, row dropped")
            continue

        records.append({
            "location":        location["name"],
            "latitude":        location["lat"],
            "longitude":       location["lon"],
            "recorded_at":     recorded_at,
            "temperature_c":   temp,
            "humidity_pct":    humid,
            "windspeed_kmh":   wind,
            "precipitation_mm": precip,
            "weather_code":    current_w.get("weathercode"),
            "is_day":          bool(current_w.get("is_day", 1)),
            "fetched_at":      fetched_at,
        })

    log.info(f"[{location['name']}] Parsed {len(times)} rows → "
             f"{len(records)} valid, {errors} with issues")
    return records, len(times), errors


# ──────────────────────────────────────────────
# Main pipeline
# ──────────────────────────────────────────────
def run_pipeline():
    log.info("═" * 60)
    log.info("  Weather Data Pipeline — START")
    log.info("═" * 60)

    conn = get_connection()
    total_inserted = 0

    for loc in LOCATIONS:
        log.info(f"\n── Processing: {loc['name']} ──")
        raw = fetch_weather(loc)

        if raw is None:
            log_pipeline_run(conn, loc["name"], 0, 0, 0,
                             "error", "API fetch failed")
            continue

        records, rows_fetched, error_count = validate_and_clean(raw, loc)

        try:
            inserted = insert_readings(conn, records)
            total_inserted += inserted
            status = "success" if error_count == 0 else "partial"
            log_pipeline_run(conn, loc["name"], rows_fetched,
                             len(records), inserted, status)
            log.info(f"[{loc['name']}] ✓ {inserted} rows upserted into DB")
        except Exception as e:
            conn.rollback()
            log.error(f"[{loc['name']}] DB insert failed: {e}")
            log_pipeline_run(conn, loc["name"], rows_fetched,
                             len(records), 0, "error", str(e))

    conn.close()
    log.info("\n" + "═" * 60)
    log.info(f"  Pipeline complete — {total_inserted} total rows written")
    log.info("═" * 60)


if __name__ == "__main__":
    run_pipeline()
