#!/bin/bash
# Setup and start MiroFish locally via Docker.
# Requires: Docker running, OPENAI_API_KEY set.
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MIROFISH_CACHE="$HOME/.cache/mirofish"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.mirofish.yml"

echo "=== MiroFish Setup ==="

# Check Docker
if ! docker info > /dev/null 2>&1; then
    echo "ERROR: Docker is not running. Start Docker Desktop first."
    exit 1
fi
echo "  Docker: OK"

# Check API key
if [ -z "$OPENAI_API_KEY" ]; then
    echo "ERROR: OPENAI_API_KEY is not set."
    echo "  Run: export OPENAI_API_KEY=sk-..."
    exit 1
fi
echo "  OPENAI_API_KEY: set"

if [ -n "$ZEP_API_KEY" ]; then
    echo "  ZEP_API_KEY: set"
else
    echo "  ZEP_API_KEY: not set (some features may be limited)"
fi

# Start MiroFish
echo ""
echo "Starting MiroFish..."
docker compose -f "$COMPOSE_FILE" up -d

# Wait for health check
echo ""
echo "Waiting for MiroFish to be ready..."
for i in $(seq 1 30); do
    if curl -sf http://localhost:5001/health > /dev/null 2>&1; then
        echo "  MiroFish is healthy!"
        echo ""
        echo "=== MiroFish Ready ==="
        echo "  Backend API: http://localhost:5001"
        echo "  Frontend UI: http://localhost:3000"
        echo ""
        echo "  To stop:  docker compose -f $COMPOSE_FILE down"
        echo "  To logs:  docker compose -f $COMPOSE_FILE logs -f"
        exit 0
    fi
    sleep 2
done

echo "ERROR: MiroFish did not become healthy after 60 seconds."
echo "Check logs: docker compose -f $COMPOSE_FILE logs"
exit 1
