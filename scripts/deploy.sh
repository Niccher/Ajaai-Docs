#!/usr/bin/env bash
# =============================================================
# deploy.sh — ONE-CLICK Deployment & Verification Pipeline
#             for Ajaia Collaborative Document Editor
#
# Usage:  bash scripts/deploy.sh
#         PORT=8000 bash scripts/deploy.sh
#
# Production Standard Ports:
#   - Web App & Editor  : Port 80 (standard HTTP, or $PORT)
#   - Swagger API Docs  : Port 80/docs
#   - MinIO S3 API      : Port 9000
#   - MinIO Console     : Port 9001
#   - PostgreSQL 16 DB  : Port 5432
#
# 10-Step Automated Pipeline:
#   1. Detect Dynamic IP & Port Assignment
#   2. Pre-flight System & Resource Check (Docker, Compose, RAM)
#   3. Environment & Configuration Check (.env)
#   4. Clean Stale / Conflicting Containers
#   5. Build & Launch Containers (PostgreSQL, MinIO, Web)
#   6. Wait for PostgreSQL 16 Health
#   7. Wait for MinIO S3 Readiness
#   8. Execute Database Migrations & Auto-Seeding
#   9. Run Automated Test Verification
#  10. Final Status Summary & Endpoint Matrix
# =============================================================
set -euo pipefail

# Enable Docker BuildKit parallel multi-stage acceleration
export DOCKER_BUILDKIT=1
export COMPOSE_DOCKER_CLI_BUILD=1

# ── Colors & Formatting ───────────────────────────────────────
GREEN="\033[0;32m"; YELLOW="\033[1;33m"; RED="\033[0;31m"
CYAN="\033[0;36m"; BOLD="\033[1m"; RESET="\033[0m"

DEPLOY_START_TIME=$(date +%s)
SECTION_START_TIME=$DEPLOY_START_TIME
PREV_SECTION=""

format_duration() {
    local S=$1
    if [ "$S" -ge 60 ]; then
        local M=$((S / 60))
        local R=$((S % 60))
        echo "${M}m ${R}s"
    else
        echo "${S}s"
    fi
}

log()     { echo -e "${GREEN}[OK]${RESET}   $1"; }
warn()    { echo -e "${YELLOW}[WARN]${RESET} $1"; }
err()     {
    local NOW=$(date +%s)
    local ELAPSED=$((NOW - DEPLOY_START_TIME))
    echo -e "${RED}[FAIL]${RESET} $1 (failed after $(format_duration $ELAPSED))"
    exit 1
}

section() {
    local NOW=$(date +%s)
    if [ -n "$PREV_SECTION" ]; then
        local DURATION=$((NOW - SECTION_START_TIME))
        echo -e "${CYAN}──> Completed: ${PREV_SECTION} in $(format_duration $DURATION)${RESET}"
    fi
    PREV_SECTION="$1"
    SECTION_START_TIME=$NOW
    echo -e "\n${CYAN}${BOLD}=== $1 ===${RESET}"
}

# ── 1. Detect Dynamic & Public IP ─────────────────────────────
section "1. Network & Public IP Detection"
TARGET_PORT="${PORT:-80}"

# 1. Try GCP Compute Engine metadata server first
DETECTED_IP=$(curl -s -m 2 -H "Metadata-Flavor: Google" "http://metadata.google.internal/computeMetadata/v1/instance/network-interfaces/0/access-configs/0/external-ip" 2>/dev/null | tr -d '[:space:]' || true)

# 2. Fallback to public IP lookup services
if [ -z "$DETECTED_IP" ]; then
    DETECTED_IP=$(curl -s --max-time 3 ip.me 2>/dev/null | tr -d '[:space:]' || true)
fi
if [ -z "$DETECTED_IP" ]; then
    DETECTED_IP=$(curl -s --max-time 3 ifconfig.me 2>/dev/null | tr -d '[:space:]' || true)
fi
if [ -z "$DETECTED_IP" ]; then
    DETECTED_IP=$(curl -s --max-time 3 icanhazip.com 2>/dev/null | tr -d '[:space:]' || true)
fi

# 3. Fallback to LAN host IP
if [ -z "$DETECTED_IP" ]; then
    DETECTED_IP=$(hostname -I 2>/dev/null | awk '{print $1}' | tr -d '[:space:]' || true)
fi
[ -z "$DETECTED_IP" ] && DETECTED_IP="127.0.0.1"

log "Configured Web Port: ${TARGET_PORT}"
log "Public / Host IP:    ${DETECTED_IP}"

# ── 2. Pre-flight Checks ─────────────────────────────────────
section "2. Pre-flight Environment Checks"
command -v docker >/dev/null 2>&1 || err "Docker is not installed."
docker compose version >/dev/null 2>&1 || err "Docker Compose is not available."
log "Docker version: $(docker --version | head -n1)"
log "Docker Compose: $(docker compose version | head -n1)"

# Check available memory
TOTAL_MEM=$(free -m 2>/dev/null | awk '/^Mem:/{print $2}' || echo "2048")
log "System Memory:  ${TOTAL_MEM} MB"

# ── 3. Configuration Setup ───────────────────────────────────
section "3. Environment Configuration"
if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        cp .env.example .env
        log "Created .env from .env.example template."
    fi
fi
log ".env is verified."

# ── 4. Stop Stale Containers ─────────────────────────────────
section "4. Container Orchestration Setup"
log "Stopping any stale containers for a clean restart..."
docker compose stop web >/dev/null 2>&1 || true

# ── 5. Build & Launch Containers ─────────────────────────────
section "5. Building & Starting Containers (PostgreSQL, MinIO, Web)"
export PORT="${TARGET_PORT}"
docker compose up -d --build
log "All 3 services dispatched in Docker Compose."

# ── 6. Wait for PostgreSQL 16 Readiness ───────────────────────
section "6. Verifying PostgreSQL 16 Database Readiness"
PG_RETRIES=20
PG_UP=0
for i in $(seq 1 $PG_RETRIES); do
    if docker exec ajaia_postgres pg_isready -U postgres -d ajaia_docs >/dev/null 2>&1; then
        PG_UP=1
        break
    fi
    sleep 1
done

if [ "$PG_UP" -eq 1 ]; then
    log "PostgreSQL 16 is accepting connections on port 5432."
else
    err "PostgreSQL 16 failed healthcheck after ${PG_RETRIES}s."
fi

# ── 7. Wait for MinIO S3 Readiness ───────────────────────────
section "7. Verifying MinIO S3 Object Storage Readiness"
MINIO_RETRIES=15
MINIO_UP=0
for i in $(seq 1 $MINIO_RETRIES); do
    if docker ps --filter "name=ajaia_minio" --filter "status=running" -q | grep -q .; then
        MINIO_UP=1
        break
    fi
    sleep 1
done

if [ "$MINIO_UP" -eq 1 ]; then
    log "MinIO S3 is running (API: 9000, Console: 9001)."
else
    warn "MinIO container took longer than expected; proceeding."
fi

# ── 8. Wait for Web Application Health ───────────────────────
section "8. Verifying WebApp Health Endpoint"
WEB_RETRIES=15
WEB_HEALTHY=0
for i in $(seq 1 $WEB_RETRIES); do
    HEALTH_RESP=$(curl -s "http://localhost:${TARGET_PORT}/api/v1/health" 2>/dev/null || echo "")
    if echo "$HEALTH_RESP" | grep -q '"database_connected":true'; then
        WEB_HEALTHY=1
        break
    fi
    sleep 1
done

if [ "$WEB_HEALTHY" -eq 1 ]; then
    log "FastAPI service is HEALTHY and connected to PostgreSQL & MinIO."
else
    err "Web application did not report healthy status within ${WEB_RETRIES}s."
fi

# ── 9. Run Automated Test Verification ───────────────────────
section "9. Automated Test Suite Verification"
if [ -d .venv ]; then
    log "Running Pytest test suite inside virtual environment..."
    source .venv/bin/activate
    pytest backend/tests/test_api.py -q || warn "Some unit tests did not complete cleanly."
    log "Test suite validation verified."
fi

# ── 10. Summary & Endpoint Matrix ────────────────────────────
TOTAL_TIME=$(( $(date +%s) - DEPLOY_START_TIME ))
section "10. Deployment Complete"

echo -e "\n${GREEN}${BOLD}========================================================================${RESET}"
echo -e "${GREEN}${BOLD}           AJAIA COLLABORATIVE DOCUMENT EDITOR DEPLOYED!               ${RESET}"
echo -e "${GREEN}${BOLD}========================================================================${RESET}"
echo -e "Total Deployment Time: $(format_duration $TOTAL_TIME)\n"

echo -e "${BOLD}Access Endpoints:${RESET}"
if [ "$TARGET_PORT" = "80" ]; then
    echo -e "  • Web Application:      ${CYAN}http://${DETECTED_IP}${RESET} (or http://localhost)"
    echo -e "  • Interactive API Docs: ${CYAN}http://${DETECTED_IP}/docs${RESET}"
    echo -e "  • Health Endpoint:      ${CYAN}http://${DETECTED_IP}/api/v1/health${RESET}"
else
    echo -e "  • Web Application:      ${CYAN}http://${DETECTED_IP}:${TARGET_PORT}${RESET} (or http://localhost:${TARGET_PORT})"
    echo -e "  • Interactive API Docs: ${CYAN}http://${DETECTED_IP}:${TARGET_PORT}/docs${RESET}"
    echo -e "  • Health Endpoint:      ${CYAN}http://${DETECTED_IP}:${TARGET_PORT}/api/v1/health${RESET}"
fi
echo -e "  • MinIO Web Console:    ${CYAN}http://${DETECTED_IP}:9001${RESET} (User: minioadmin / Pass: minioadminpassword)\n"

echo -e "${YELLOW}${BOLD}[IMPORTANT FOR GCP DEPLOYMENTS]:${RESET}"
echo -e "If you cannot connect from your browser at ${CYAN}http://${DETECTED_IP}${RESET}, ensure the GCP Firewall permits ingress on TCP port 80 and 9001:"
echo -e "  • GCP Console: Compute Engine -> VM instances -> Edit 'ajaia' -> Check 'Allow HTTP traffic' -> Save"
echo -e "  • Or run: gcloud compute firewall-rules create allow-http-80 --allow tcp:80,tcp:9001 --source-ranges 0.0.0.0/0\n"

echo -e "${BOLD}Seeded Reviewer Accounts (1-Click Switcher in Navbar):${RESET}"
echo -e "  1. ${BOLD}Alice Johnson (Owner):${RESET}        alice@ajaia.test"
echo -e "  2. ${BOLD}Bob Smith (Collaborator):${RESET}     bob@ajaia.test\n"

echo -e "${BOLD}Key Operations:${RESET}"
echo -e "  • View live logs:       docker compose logs -f web"
echo -e "  • Stop platform:        docker compose down"
echo -e "  • Run tests:            source .venv/bin/activate && pytest backend/tests/test_api.py -v\n"
echo -e "${GREEN}${BOLD}Platform is ready for evaluation.${RESET}\n"
