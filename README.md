# Weather Data Pipeline

Ein vollautomatisiertes ETL-System, das stündliche Wetterdaten für fünf deutsche Städte abruft, bereinigt und in PostgreSQL speichert – alles in Docker verpackt.

```
┌─────────────────────────────────────────────────────────────┐
│                        Docker Network                        │
│                                                             │
│   ┌──────────────┐   HTTP    ┌─────────────────────────┐   │
│   │ Open-Meteo   │ ◄──────── │  ETL Container (Python) │   │
│   │ Public API   │           │                         │   │
│   └──────────────┘           │  1. Fetch               │   │
│                              │  2. Validate & Clean     │   │
│                              │  3. Upsert               │   │
│                              └────────────┬────────────┘   │
│                                           │ psycopg2        │
│                              ┌────────────▼────────────┐   │
│                              │  PostgreSQL Container   │   │
│                              │                         │   │
│                              │  weather_readings       │   │
│                              │  pipeline_runs          │   │
│                              └─────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

## Tech-Stack

| Schicht       | Technologie               |
|---------------|---------------------------|
| Sprache       | Python 3.12               |
| HTTP-Client   | `requests`                |
| Datenbank     | PostgreSQL 16             |
| DB-Adapter    | `psycopg2`                |
| Container     | Docker + Docker Compose   |
| Daten-API     | Open-Meteo (kostenlos, kein API-Key) |

---

## Schnellstart

```bash
# 1. Repository klonen / Projekt-Ordner betreten
cd weather-pipeline

# 2. .env anlegen
make setup          # oder: cp .env.example .env

# 3. Datenbank starten (führt Migrationen automatisch aus)
make up

# 4. Pipeline einmalig ausführen
make run
```

Das war's. Die Daten liegen jetzt in PostgreSQL.

---

## Datenbankstruktur

### Tabelle `weather_readings` – Haupttabelle

| Spalte             | Typ           | Beschreibung                              |
|--------------------|---------------|-------------------------------------------|
| `id`               | BIGSERIAL     | Primärschlüssel                           |
| `location`         | VARCHAR(100)  | Stadtname                                 |
| `latitude`         | NUMERIC(8,5)  | Breitengrad                               |
| `longitude`        | NUMERIC(8,5)  | Längengrad                                |
| `recorded_at`      | TIMESTAMPTZ   | Messzeitpunkt (von der API)               |
| `temperature_c`    | NUMERIC(5,2)  | Temperatur in °C (NULL = ungültig)        |
| `humidity_pct`     | NUMERIC(5,2)  | Relative Luftfeuchtigkeit in %            |
| `windspeed_kmh`    | NUMERIC(6,2)  | Windgeschwindigkeit in km/h               |
| `precipitation_mm` | NUMERIC(6,2)  | Niederschlag in mm                        |
| `weather_code`     | SMALLINT      | WMO-Wettercode                            |
| `fetched_at`       | TIMESTAMPTZ   | Zeitpunkt des API-Abrufs                  |

Ein `UNIQUE`-Constraint auf `(location, recorded_at)` stellt sicher, dass wiederholte Läufe **idempotent** sind (Upsert statt Duplikate).

### Tabelle `pipeline_runs` – Audit-Log

Jeder Lauf schreibt eine Zeile mit `rows_fetched`, `rows_valid`, `rows_inserted` und `status ∈ {success, partial, error}`.

### Views

```sql
-- Letzter Messwert je Stadt
SELECT * FROM v_latest_readings;

-- Tages-Zusammenfassung (Ø-Temp, Max-Wind, Gesamt-Regen …)
SELECT * FROM v_daily_summary WHERE location = 'Berlin';

-- Pipeline-Gesundheit der letzten 7 Tage
SELECT * FROM v_pipeline_health;
```

---

## Fehlerbehandlung & Datenqualität

```
Validierungsgrenzen
───────────────────
Temperatur     -60 … +60 °C
Luftfeuchtigkeit  0 … 100 %
Windgeschwindigkeit 0 … 400 km/h
Niederschlag      0 … 500 mm
```

* **Ungültige Felder** werden auf `NULL` gesetzt (nicht verworfen), damit die Zeile erhalten bleibt.
* **Fehlende Temperatur** → Zeile wird komplett verworfen (Mindestvoraussetzung).
* **API-Fehler** → werden geloggt, `pipeline_runs.status = 'error'`, Pipeline läuft für andere Städte weiter.
* **DB-Fehler** → `ROLLBACK` pro Stadt, Rest der Pipeline ist nicht betroffen.

---

## Deployment-Modi

### Einmaliger Lauf (CI/CD, Cron-Job auf dem Host)

```bash
# In docker-compose.yml: restart: "no"  (Standard)
docker compose run --rm etl
```

Dann einen externen Cron-Job einrichten:

```cron
0 6 * * *  cd /opt/weather-pipeline && docker compose run --rm etl >> /var/log/weather.log 2>&1
```

### Dauerbetrieb im Container

```bash
RUN_MODE=cron SCHEDULE_HOURS=24 docker compose up etl
```

---

## Nützliche Befehle

```bash
make help          # Alle verfügbaren Befehle
make db-shell      # psql-Shell öffnen
make logs          # ETL-Logs streamen
make pgadmin       # pgAdmin im Browser (http://localhost:5050)
make down          # Container stoppen
make clean         # Container + Daten-Volume löschen
```

---

## Daten abfragen

```sql
-- Aktuelle Temperaturen aller Städte
SELECT location, recorded_at, temperature_c, weather_code
FROM v_latest_readings
ORDER BY temperature_c DESC;

-- Berlin – letzte 48 Stunden
SELECT recorded_at, temperature_c, humidity_pct, windspeed_kmh
FROM weather_readings
WHERE location = 'Berlin'
  AND recorded_at >= now() - INTERVAL '48 hours'
ORDER BY recorded_at DESC;

-- Wärmste Tage 2025
SELECT location, day, max_temp_c
FROM v_daily_summary
WHERE EXTRACT(YEAR FROM day) = 2025
ORDER BY max_temp_c DESC
LIMIT 10;

-- Fehlerquote der Pipeline
SELECT location,
       error_runs::FLOAT / NULLIF(total_runs, 0) * 100 AS error_rate_pct
FROM v_pipeline_health;
```

---

## Sicherheitshinweise für Produktion

- Passwort in `.env` ändern (niemals `.env` committen – ist in `.gitignore`!)
- Port `5432` in `docker-compose.yml` schließen (nur intern benötigt)
- Nicht-Root-User im ETL-Container ist bereits konfiguriert ✓
- Named Volume verhindert Datenverlust bei Container-Neustarts ✓
