#!/usr/bin/env bash
# check-cluster.sh — Check the health of all vLLM nodes in the DGX Spark cluster.
#
# Usage:
#   ./scripts/check-cluster.sh [--port PORT]
#
# Environment variables:
#   NODE_1_IP through NODE_4_IP - Override default node IP addresses
#   VLLM_PORT                   - Override default port (8000)

set -euo pipefail

NODE_1_IP="${NODE_1_IP:-192.168.100.10}"
NODE_2_IP="${NODE_2_IP:-192.168.100.11}"
NODE_3_IP="${NODE_3_IP:-192.168.100.12}"
NODE_4_IP="${NODE_4_IP:-192.168.100.13}"
ALL_NODES=("${NODE_1_IP}" "${NODE_2_IP}" "${NODE_3_IP}" "${NODE_4_IP}")
VLLM_PORT="${VLLM_PORT:-8000}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --port) VLLM_PORT="$2"; shift 2 ;;
        *) echo "Unknown argument: $1"; exit 1 ;;
    esac
done

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

echo -e "${BOLD}${CYAN}DGX Spark vLLM Cluster Health Check${NC}"
echo -e "${CYAN}=====================================${NC}"
echo

HEALTHY_COUNT=0
TOTAL=${#ALL_NODES[@]}

for i in "${!ALL_NODES[@]}"; do
    node="${ALL_NODES[$i]}"
    name="spark-$((i + 1))"

    # Check /health endpoint
    if curl -sf --max-time 5 "http://${node}:${VLLM_PORT}/health" &>/dev/null; then
        STATUS="${GREEN}HEALTHY${NC}"
        HEALTHY_COUNT=$((HEALTHY_COUNT + 1))

        # Fetch loaded models
        MODELS=$(curl -sf --max-time 5 "http://${node}:${VLLM_PORT}/v1/models" 2>/dev/null \
            | python3 -c "import sys,json; d=json.load(sys.stdin); print(', '.join(m['id'] for m in d.get('data',[])))" 2>/dev/null \
            || echo "unknown")
        echo -e "  ${BOLD}${name}${NC} (${node}:${VLLM_PORT})  ${STATUS}"
        echo -e "    Models: ${YELLOW}${MODELS}${NC}"
    else
        STATUS="${RED}UNREACHABLE${NC}"
        echo -e "  ${BOLD}${name}${NC} (${node}:${VLLM_PORT})  ${STATUS}"
    fi
done

echo
echo -e "  Healthy nodes: ${BOLD}${HEALTHY_COUNT}/${TOTAL}${NC}"

if [[ "${HEALTHY_COUNT}" -eq "${TOTAL}" ]]; then
    echo -e "  ${GREEN}All nodes are healthy.${NC}"
    exit 0
elif [[ "${HEALTHY_COUNT}" -gt 0 ]]; then
    echo -e "  ${YELLOW}Partial cluster available (${HEALTHY_COUNT}/${TOTAL} nodes).${NC}"
    exit 0
else
    echo -e "  ${RED}No nodes are reachable. Check that vLLM is running.${NC}"
    exit 1
fi
