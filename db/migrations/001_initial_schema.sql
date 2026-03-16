-- =============================================================
-- Migration: 001_initial_schema.sql
-- Creates the core tables for the weather data pipeline.
-- =============================================================

-- Enable the uuid extension (handy for future expansion)
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- -------------------------------------------------------------
-- 1.  weather_readings  – the main fact table
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS weather_readings (
    id               BIGSERIAL PRIMARY KEY,

    -- Location metadata
    location         VARCHAR(100)     NOT NULL,
    latitude         NUMERIC(8, 5)    NOT NULL,
    longitude        NUMERIC(8, 5)    NOT NULL,

    -- Time of the actual measurement (from the API)
    recorded_at      TIMESTAMPTZ      NOT NULL,

    -- Weather measurements (nullable: invalid values are stored as NULL)
    temperature_c    NUMERIC(5, 2),           -- °C,  range validated: -60 … +60
    humidity_pct     NUMERIC(5, 2),           -- %,   range validated:   0 … 100
    windspeed_kmh    NUMERIC(6, 2),           -- km/h, range validated:  0 … 400
    precipitation_mm NUMERIC(6, 2),           -- mm,  range validated:   0 … 500
    weather_code     SMALLINT,                -- WMO weather interpretation code
    is_day           BOOLEAN,

    -- Pipeline bookkeeping
    fetched_at       TIMESTAMPTZ      NOT NULL DEFAULT now(),

    -- Idempotency: one row per location per timestamp
    CONSTRAINT uq_location_time UNIQUE (location, recorded_at)
);

COMMENT ON TABLE  weather_readings IS
    'Hourly weather measurements fetched from the Open-Meteo API.';
COMMENT ON COLUMN weather_readings.temperature_c IS
    'Air temperature at 2 m height in degrees Celsius. NULL = failed validation.';
COMMENT ON COLUMN weather_readings.weather_code IS
    'WMO Weather interpretation code (https://open-meteo.com/en/docs#weathervariables).';

-- Indexes for the most common query patterns
CREATE INDEX IF NOT EXISTS idx_wr_location     ON weather_readings (location);
CREATE INDEX IF NOT EXISTS idx_wr_recorded_at  ON weather_readings (recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_wr_loc_time     ON weather_readings (location, recorded_at DESC);

-- -------------------------------------------------------------
-- 2.  pipeline_runs  – audit / observability table
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id             BIGSERIAL    PRIMARY KEY,
    run_at         TIMESTAMPTZ  NOT NULL DEFAULT now(),
    location       VARCHAR(100) NOT NULL,
    rows_fetched   INTEGER      NOT NULL DEFAULT 0,
    rows_valid     INTEGER      NOT NULL DEFAULT 0,
    rows_inserted  INTEGER      NOT NULL DEFAULT 0,
    status         VARCHAR(20)  NOT NULL
                   CHECK (status IN ('success', 'partial', 'error')),
    error_msg      TEXT
);

COMMENT ON TABLE  pipeline_runs IS
    'One row per location per pipeline execution – used for monitoring and alerting.';

CREATE INDEX IF NOT EXISTS idx_pr_run_at   ON pipeline_runs (run_at DESC);
CREATE INDEX IF NOT EXISTS idx_pr_location ON pipeline_runs (location);
CREATE INDEX IF NOT EXISTS idx_pr_status   ON pipeline_runs (status);

-- -------------------------------------------------------------
-- 3.  Convenience views
-- -------------------------------------------------------------

-- Latest reading per location
CREATE OR REPLACE VIEW v_latest_readings AS
SELECT DISTINCT ON (location)
    location,
    recorded_at,
    temperature_c,
    humidity_pct,
    windspeed_kmh,
    precipitation_mm,
    weather_code,
    is_day,
    fetched_at
FROM weather_readings
ORDER BY location, recorded_at DESC;

COMMENT ON VIEW v_latest_readings IS
    'Most recent validated measurement for each location.';

-- Daily summary per location
CREATE OR REPLACE VIEW v_daily_summary AS
SELECT
    location,
    DATE(recorded_at AT TIME ZONE 'Europe/Berlin')  AS day,
    ROUND(AVG(temperature_c)::NUMERIC, 2)           AS avg_temp_c,
    ROUND(MIN(temperature_c)::NUMERIC, 2)           AS min_temp_c,
    ROUND(MAX(temperature_c)::NUMERIC, 2)           AS max_temp_c,
    ROUND(AVG(humidity_pct)::NUMERIC, 1)            AS avg_humidity_pct,
    ROUND(MAX(windspeed_kmh)::NUMERIC, 1)           AS max_wind_kmh,
    ROUND(SUM(precipitation_mm)::NUMERIC, 2)        AS total_precipitation_mm,
    COUNT(*)                                         AS data_points
FROM weather_readings
WHERE temperature_c IS NOT NULL
GROUP BY location, day
ORDER BY location, day DESC;

COMMENT ON VIEW v_daily_summary IS
    'Aggregated daily weather statistics per location.';

-- Pipeline health: last 7 days
CREATE OR REPLACE VIEW v_pipeline_health AS
SELECT
    location,
    COUNT(*)                              AS total_runs,
    SUM(rows_inserted)                    AS total_rows_written,
    SUM(CASE WHEN status = 'error'   THEN 1 ELSE 0 END) AS error_runs,
    SUM(CASE WHEN status = 'partial' THEN 1 ELSE 0 END) AS partial_runs,
    MAX(run_at)                           AS last_run_at
FROM pipeline_runs
WHERE run_at >= now() - INTERVAL '7 days'
GROUP BY location
ORDER BY location;

COMMENT ON VIEW v_pipeline_health IS
    'Aggregated pipeline health metrics for the last 7 days.';
