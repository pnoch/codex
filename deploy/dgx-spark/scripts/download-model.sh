#!/usr/bin/env bash
# download-model.sh — Pre-download a model to the persistent host model store.
#
# This script MUST be run BEFORE starting the vLLM Docker container.
# It downloads the model to /mnt/models (or $MODEL_STORE) on the HOST filesystem,
# which is then mounted into the container as a read-only volume.
#
# Usage:
#   ./scripts/download-model.sh [MODEL_ID] [MODEL_STORE]
#
# Examples:
#   ./scripts/download-model.sh
#   ./scripts/download-model.sh meta-llama/Meta-Llama-3-70B-Instruct
#   ./scripts/download-model.sh deepseek-ai/DeepSeek-Coder-V2-Instruct /data/models
#
# Environment variables (override defaults):
#   MODEL_ID    - Hugging Face model ID
#   MODEL_STORE - Host directory for model storage
#   HF_TOKEN    - Hugging Face Hub token (required for gated models)

set -euo pipefail

# ─── Configuration ────────────────────────────────────────────────────────────

MODEL_ID="${1:-${MODEL_ID:-meta-llama/Meta-Llama-3-70B-Instruct}}"
MODEL_STORE="${2:-${MODEL_STORE:-/mnt/models}}"
HF_TOKEN="${HF_TOKEN:-}"

# Sanitize model ID for use as a directory name (replace '/' with '--').
MODEL_DIR_NAME="${MODEL_ID//\//-}"
MODEL_DIR_NAME="${MODEL_DIR_NAME//\//--}"
MODEL_LOCAL_PATH="${MODEL_STORE}/${MODEL_ID//\/\/--}"

# ─── Helpers ──────────────────────────────────────────────────────────────────

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

log_info()    { echo -e "${CYAN}[INFO]${NC} $*"; }
log_success() { echo -e "${GREEN}[OK]${NC}   $*"; }
log_warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# ─── Pre-flight Checks ────────────────────────────────────────────────────────

log_info "DGX Spark Model Pre-Download Script"
log_info "======================================"
log_info "Model ID    : ${MODEL_ID}"
log_info "Model Store : ${MODEL_STORE}"
echo

# Check Python and huggingface_hub are available.
if ! command -v python3 &>/dev/null; then
    log_error "python3 is required but not found. Install Python 3.10+."
    exit 1
fi

if ! python3 -c "import huggingface_hub" 2>/dev/null; then
    log_info "Installing huggingface_hub..."
    pip3 install --quiet huggingface_hub hf_transfer
fi

# Create the model store directory if it doesn't exist.
if [[ ! -d "${MODEL_STORE}" ]]; then
    log_info "Creating model store directory: ${MODEL_STORE}"
    sudo mkdir -p "${MODEL_STORE}"
    sudo chown "$(whoami)":"$(whoami)" "${MODEL_STORE}"
fi

# Check available disk space (rough estimate: 2x model size in GB).
AVAILABLE_GB=$(df -BG "${MODEL_STORE}" | awk 'NR==2 {print $4}' | tr -d 'G')
log_info "Available disk space: ${AVAILABLE_GB} GB"

if [[ "${AVAILABLE_GB}" -lt 150 ]]; then
    log_warn "Less than 150 GB available. Large models (70B+) require ~140 GB in fp16."
fi

# ─── Download ─────────────────────────────────────────────────────────────────

# Check if model already exists.
SANITIZED_ID="${MODEL_ID//\/\/--}"
FULL_MODEL_PATH="${MODEL_STORE}/${SANITIZED_ID}"

if [[ -d "${FULL_MODEL_PATH}" ]] && [[ -f "${FULL_MODEL_PATH}/config.json" ]]; then
    log_success "Model '${MODEL_ID}' already exists at ${FULL_MODEL_PATH}"
    log_info "Skipping download. Delete the directory to force re-download."
    exit 0
fi

log_info "Downloading '${MODEL_ID}' to ${MODEL_STORE}..."
log_info "This may take a while for large models. Progress is shown below."
echo

# Use hf_transfer for faster downloads when available.
export HF_HUB_ENABLE_HF_TRANSFER=1

# Download the model using huggingface_hub.
python3 - <<PYTHON
import os
import sys
from pathlib import Path

try:
    from huggingface_hub import snapshot_download
except ImportError:
    print("ERROR: huggingface_hub not installed. Run: pip install huggingface_hub")
    sys.exit(1)

model_id = "${MODEL_ID}"
model_store = Path("${MODEL_STORE}")
local_dir = model_store / model_id.replace("/", "--")
token = "${HF_TOKEN}" or None

print(f"Downloading {model_id} to {local_dir}", flush=True)

try:
    path = snapshot_download(
        repo_id=model_id,
        local_dir=str(local_dir),
        token=token,
        local_dir_use_symlinks=False,
        ignore_patterns=["*.msgpack", "flax_model*", "tf_model*", "rust_model*"],
    )
    print(f"\n✓ Download complete: {path}", flush=True)
except Exception as e:
    print(f"\nERROR: Download failed: {e}", file=sys.stderr)
    sys.exit(1)
PYTHON

# ─── Verification ─────────────────────────────────────────────────────────────

SANITIZED_ID="${MODEL_ID//\/\/--}"
FULL_MODEL_PATH="${MODEL_STORE}/${SANITIZED_ID}"

if [[ -f "${FULL_MODEL_PATH}/config.json" ]]; then
    log_success "Model '${MODEL_ID}' downloaded and verified."
    log_info "Location: ${FULL_MODEL_PATH}"
    log_info "Size: $(du -sh "${FULL_MODEL_PATH}" 2>/dev/null | cut -f1)"
else
    log_error "Model download may have failed — config.json not found at ${FULL_MODEL_PATH}"
    exit 1
fi

echo
log_success "Pre-download complete. You can now start the vLLM service:"
log_info "  docker compose -f docker/docker-compose.yml up -d"
