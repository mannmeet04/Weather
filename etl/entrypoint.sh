#!/bin/sh
# entrypoint.sh – runs inside the ETL container.
# Supports two modes:
#   once   – run the pipeline a single time then exit  (default for one-shot jobs)
#   cron   – loop and run on a schedule (default when RUN_MODE=cron)

set -e

RUN_MODE="${RUN_MODE:-once}"
SCHEDULE_HOURS="${SCHEDULE_HOURS:-24}"

echo "================================================"
echo "  Weather Pipeline Container"
echo "  Mode: ${RUN_MODE}"
echo "================================================"

run_once() {
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Starting pipeline run..."
    python /app/main.py
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Pipeline run finished."
}

if [ "${RUN_MODE}" = "cron" ]; then
    INTERVAL_SECONDS=$(( SCHEDULE_HOURS * 3600 ))
    echo "Running every ${SCHEDULE_HOURS} hour(s) (${INTERVAL_SECONDS}s)"
    while true; do
        run_once
        echo "Sleeping ${INTERVAL_SECONDS}s until next run..."
        sleep "${INTERVAL_SECONDS}"
    done
else
    run_once
fi
