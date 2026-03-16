# Weather Data Pipeline

Ein vollautomatisiertes ETL-System, das stündliche Wetterdaten für fünf deutsche Städte abruft, bereinigt und in PostgreSQL speichert – alles in Docker verpackt.


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

### Views

```sql
-- Letzter Messwert je Stadt
SELECT * FROM v_latest_readings;

-- Tages-Zusammenfassung (Ø-Temp, Max-Wind, Gesamt-Regen …)
SELECT * FROM v_daily_summary WHERE location = 'Berlin';

-- Pipeline-Gesundheit der letzten 7 Tage
SELECT * FROM v_pipeline_health;
```


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

