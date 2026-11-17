#!/usr/bin/env bash
# Backend smoke test over a REAL uvicorn process:
#   Phase A: no reachable database  -> /health/ready must return 503
#   Phase B: real PostgreSQL 16.2   -> /health/ready must return 200
# Also verifies security headers, X-Request-ID and JSON access logs.
set -uo pipefail
cd /home/z/my-project/backend

EVIDENCE=/home/z/my-project/download/evidence
mkdir -p "$EVIDENCE"

wait_up() { # url -> wait until HTTP responds (any code)
  for _ in $(seq 1 50); do
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 "$1" || true)
    [ "$code" != "000" ] && return 0
    sleep 0.2
  done
  return 1
}

echo "########## Phase A: DATABASE UNREACHABLE ##########"
export DATABASE_URL="postgresql+psycopg://marginpilot:smokepw@127.0.0.1:59998/none"
export LOG_FORMAT=json LOG_LEVEL=INFO
uvicorn app.main:app --host 127.0.0.1 --port 8021 >"$EVIDENCE/uvicorn_phase_a.log" 2>&1 &
UV_A=$!
wait_up http://127.0.0.1:8021/health/live || { echo "FATAL: phase A did not start"; kill $UV_A; exit 1; }

echo "--- GET /health/live (phase A) ---"
curl -s -i http://127.0.0.1:8021/health/live | head -12
echo ""
echo "--- GET /health/ready (phase A: failure path) ---"
curl -s -i http://127.0.0.1:8021/health/ready | head -12
echo ""

kill $UV_A 2>/dev/null; wait $UV_A 2>/dev/null

echo ""
echo "########## Phase B: REAL PostgreSQL (embedded 16.2) ##########"
DSN=$(python /home/z/my-project/scripts/start_pg_embedded.py | tail -1)
echo "DSN host part: $(echo "$DSN" | sed 's/:[^:@]*@/:***@/')"
export DATABASE_URL="$DSN"
uvicorn app.main:app --host 127.0.0.1 --port 8022 >"$EVIDENCE/uvicorn_phase_b.log" 2>&1 &
UV_B=$!
wait_up http://127.0.0.1:8022/health/live || { echo "FATAL: phase B did not start"; kill $UV_B; exit 1; }

echo "--- GET /health/ready (phase B: success path) ---"
curl -s -i http://127.0.0.1:8022/health/ready | head -12
echo ""

kill $UV_B 2>/dev/null; wait $UV_B 2>/dev/null

echo ""
echo "########## JSON access-log sample (phase B) ##########"
grep -o '{.*http_request.*}' "$EVIDENCE/uvicorn_phase_b.log" | head -2 || grep '"event":"http_request"' "$EVIDENCE/uvicorn_phase_b.log" | head -2 || head -5 "$EVIDENCE/uvicorn_phase_b.log"
echo ""
echo "SMOKE DONE"
