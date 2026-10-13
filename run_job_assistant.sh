#!/bin/bash
# ============================================================
#  Job Assistant — Auto Runner
#  Runs the full pipeline: Fetch → Score → Tailor → PDF → Telegram
#
#  Usage:
#    ./run_job_assistant.sh           # process up to 3 matching jobs
#    ./run_job_assistant.sh 5         # process up to 5 jobs
#    ./run_job_assistant.sh 3 55      # up to 3 jobs, score threshold 55%
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"
LOG_FILE="$LOG_DIR/run_$(date +%Y%m%d_%H%M%S).log"

MAX_JOBS="${1:-3}"
MIN_SCORE="${2:-60}"

mkdir -p "$LOG_DIR"

echo "=============================="
echo " Job Assistant  — $(date)"
echo " Max jobs  : $MAX_JOBS"
echo " Min score : $MIN_SCORE%"
echo "=============================="

cd "$SCRIPT_DIR"

# Run and tee output to both console and log file
node scrapers/multi_job_scraper.js "$MAX_JOBS" "$MIN_SCORE" 2>&1 | tee "$LOG_FILE"

echo ""
echo "✅ Run complete. Log saved: $LOG_FILE"

# Clean up logs older than 30 days to save disk space
find "$LOG_DIR" -name "run_*.log" -mtime +30 -delete 2>/dev/null || true
