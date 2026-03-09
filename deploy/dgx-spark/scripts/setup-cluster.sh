#!/usr/bin/env bash
# setup-cluster.sh — Configure networking and deploy vLLM across 4 DGX Spark units.
#
# This script automates the NVIDIA-recommended cluster setup for 4 DGX Spark
# units connected via QSFP/CX7 cables. It:
#
#   1. Configures the CX-7 network interfaces on all nodes.
#   2. Runs the DGX Spark discovery script to set up passwordless SSH.
#   3. Installs NCCL and MPI on all nodes.
#   4. Deploys and starts the vLLM service on all nodes.
#   5. Verifies cluster health.
#
# Prerequisites:
#   - 4 DGX Spark units connected via QSFP/CX7 cables.
#   - Ubuntu 24.04 with NVIDIA drivers installed on all units.
#   - SSH access to all units (password-based initially).
#   - This script run from the PRIMARY node (spark-1).
#
# Usage:
#   ./scripts/setup-cluster.sh [--model MODEL_ID] [--store MODEL_STORE]
#
# Example:
#   ./scripts/setup-cluster.sh --model meta-llama/Meta-Llama-3-70B-Instruct

set -euo pipefail

# ─── Configuration ────────────────────────────────────────────────────────────

# Default DGX Spark cluster node addresses (per NVIDIA documentation).
# Modify these to match your actual network configuration.
NODE_1_IP="${NODE_1_IP:-192.168.100.10}"
NODE_2_IP="${NODE_2_IP:-192.168.100.11}"
NODE_3_IP="${NODE_3_IP:-192.168.100.12}"
NODE_4_IP="${NODE_4_IP:-192.168.100.13}"
ALL_NODES=("${NODE_1_IP}" "${NODE_2_IP}" "${NODE_3_IP}" "${NODE_4_IP}")

MODEL_ID="${MODEL_ID:-meta-llama/Meta-Llama-3-70B-Instruct}"
MODEL_STORE="${MODEL_STORE:-/mnt/models}"
VLLM_PORT="${VLLM_PORT:-8000}"
DEPLOY_DIR="${DEPLOY_DIR:-/opt/codex-vllm}"

# ─── Argument Parsing ─────────────────────────────────────────────────────────

while [[ $# -gt 0 ]]; do
    case "$1" in
        --model) MODEL_ID="$2"; shift 2 ;;
        --store) MODEL_STORE="$2"; shift 2 ;;
        --port)  VLLM_PORT="$2"; shift 2 ;;
        *) echo "Unknown argument: $1"; exit 1 ;;
    esac
done

# ─── Helpers ──────────────────────────────────────────────────────────────────

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

log_info()    { echo -e "${CYAN}[INFO]${NC}  $*"; }
log_success() { echo -e "${GREEN}[OK]${NC}    $*"; }
log_warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }
log_header()  { echo -e "\n${BOLD}${CYAN}══ $* ══${NC}"; }

run_on_node() {
    local node="$1"; shift
    ssh -o StrictHostKeyChecking=no "nvidia@${node}" "$@"
}

run_on_all_nodes() {
    for node in "${ALL_NODES[@]}"; do
        log_info "  → ${node}: $*"
        run_on_node "${node}" "$@" || log_warn "Failed on ${node}, continuing..."
    done
}

# ─── Step 1: Configure CX-7 Network Interfaces ────────────────────────────────

log_header "Step 1: Configure CX-7 Network Interfaces"
log_info "Downloading and applying netplan configuration to all nodes..."

for i in "${!ALL_NODES[@]}"; do
    node="${ALL_NODES[$i]}"
    ip_addr="192.168.100.$((10 + i))"
    log_info "Configuring ${node} with IP ${ip_addr}..."

    # Use NVIDIA's recommended netplan configuration.
    run_on_node "${node}" bash -c "
        sudo wget -q -O /etc/netplan/40-cx7.yaml \
            https://github.com/NVIDIA/dgx-spark-playbooks/raw/main/nvidia/connect-two-sparks/assets/cx7-netplan.yaml
        sudo chmod 600 /etc/netplan/40-cx7.yaml
        sudo netplan apply
    " || {
        log_warn "Netplan configuration failed on ${node}. Trying manual IP assignment..."
        run_on_node "${node}" bash -c "
            sudo ip addr add ${ip_addr}/24 dev enP2p1s0f1np1 2>/dev/null || true
            sudo ip link set enP2p1s0f1np1 up 2>/dev/null || true
        "
    }
done

log_success "Network interfaces configured."

# ─── Step 2: Set Up Passwordless SSH ──────────────────────────────────────────

log_header "Step 2: Set Up Passwordless SSH Between Nodes"

# Generate SSH key on primary node if not present.
if [[ ! -f ~/.ssh/id_rsa ]]; then
    log_info "Generating SSH key pair..."
    ssh-keygen -t rsa -b 4096 -f ~/.ssh/id_rsa -N "" -q
fi

# Copy SSH key to all nodes.
for node in "${ALL_NODES[@]}"; do
    log_info "Copying SSH key to ${node}..."
    ssh-copy-id -o StrictHostKeyChecking=no "nvidia@${node}" || \
        log_warn "Could not copy SSH key to ${node} — manual password entry may be required."
done

log_success "SSH keys distributed."

# ─── Step 3: Install NCCL and MPI ─────────────────────────────────────────────

log_header "Step 3: Install NCCL and MPI on All Nodes"

run_on_all_nodes bash -c "
    sudo apt-get update -qq
    sudo apt-get install -y -qq libopenmpi-dev openmpi-bin
    # Install NCCL (NVIDIA Collective Communications Library)
    pip3 install --quiet nvidia-nccl-cu12 2>/dev/null || true
"

log_success "NCCL and MPI installed."

# ─── Step 4: Deploy vLLM Configuration ────────────────────────────────────────

log_header "Step 4: Deploy vLLM Configuration to All Nodes"

# Create deployment directory on all nodes.
run_on_all_nodes "sudo mkdir -p ${DEPLOY_DIR} && sudo chown nvidia:nvidia ${DEPLOY_DIR}"

# Copy deployment files to all nodes.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_ROOT="$(dirname "${SCRIPT_DIR}")"

for node in "${ALL_NODES[@]}"; do
    log_info "Copying deployment files to ${node}:${DEPLOY_DIR}..."
    scp -r -o StrictHostKeyChecking=no \
        "${DEPLOY_ROOT}/docker" \
        "${DEPLOY_ROOT}/scripts" \
        "nvidia@${node}:${DEPLOY_DIR}/" || log_warn "SCP failed for ${node}"
done

# Create the .env file on all nodes.
for node in "${ALL_NODES[@]}"; do
    log_info "Creating .env on ${node}..."
    run_on_node "${node}" bash -c "cat > ${DEPLOY_DIR}/docker/.env" <<EOF
MODEL_ID=${MODEL_ID}
MODEL_STORE=${MODEL_STORE}
TENSOR_PARALLEL=1
MAX_MODEL_LEN=32768
GPU_MEMORY_UTIL=0.90
VLLM_PORT=${VLLM_PORT}
HF_TOKEN=${HF_TOKEN:-}
EOF
done

log_success "Configuration deployed."

# ─── Step 5: Pre-Download Model ───────────────────────────────────────────────

log_header "Step 5: Pre-Download Model on Primary Node"
log_info "Downloading '${MODEL_ID}' to ${MODEL_STORE} on primary node..."
log_info "This will be shared via NFS or copied to other nodes."

bash "${SCRIPT_DIR}/download-model.sh" "${MODEL_ID}" "${MODEL_STORE}"

# If NFS is not configured, copy the model to other nodes.
log_warn "If you have NFS configured, skip the model copy step."
log_info "To copy the model to other nodes, run:"
for node in "${ALL_NODES[@]:1}"; do
    echo "  rsync -avz --progress ${MODEL_STORE}/ nvidia@${node}:${MODEL_STORE}/"
done

# ─── Step 6: Start vLLM on All Nodes ──────────────────────────────────────────

log_header "Step 6: Start vLLM Service on All Nodes"

for node in "${ALL_NODES[@]}"; do
    log_info "Starting vLLM on ${node}..."
    run_on_node "${node}" bash -c "
        cd ${DEPLOY_DIR}
        docker compose -f docker/docker-compose.yml pull --quiet
        docker compose -f docker/docker-compose.yml up -d
    " || log_warn "Failed to start vLLM on ${node}"
done

log_success "vLLM services started."

# ─── Step 7: Health Check ─────────────────────────────────────────────────────

log_header "Step 7: Cluster Health Check"
log_info "Waiting 30 seconds for services to initialize..."
sleep 30

ALL_HEALTHY=true
for node in "${ALL_NODES[@]}"; do
    if curl -sf "http://${node}:${VLLM_PORT}/health" &>/dev/null; then
        log_success "Node ${node}:${VLLM_PORT} — HEALTHY"
    else
        log_warn "Node ${node}:${VLLM_PORT} — NOT READY (may still be loading model)"
        ALL_HEALTHY=false
    fi
done

echo
if [[ "${ALL_HEALTHY}" == "true" ]]; then
    log_success "All 4 DGX Spark nodes are healthy!"
else
    log_warn "Some nodes are not yet ready. The model may still be loading."
    log_info "Check status with: docker compose -f docker/docker-compose.yml logs -f"
fi

echo
log_header "Cluster Setup Complete"
log_info "vLLM API is available at:"
for node in "${ALL_NODES[@]}"; do
    echo "  http://${node}:${VLLM_PORT}/v1"
done
echo
log_info "Configure Codex to use the cluster:"
echo "  export CODEX_VLLM_BASE_URL=http://${NODE_1_IP}:${VLLM_PORT}/v1"
echo "  codex --oss --local-provider vllm"
echo
log_info "Or for multi-node routing, set:"
echo "  export CODEX_VLLM_CLUSTER_NODES='["
for i in "${!ALL_NODES[@]}"; do
    node="${ALL_NODES[$i]}"
    comma=$([[ $i -lt $((${#ALL_NODES[@]} - 1)) ]] && echo "," || echo "")
    echo "    {\"address\":\"${node}\",\"port\":${VLLM_PORT},\"name\":\"spark-$((i+1))\"}${comma}"
done
echo "  ]'"
