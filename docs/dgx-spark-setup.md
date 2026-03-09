# Codex on DGX Spark Cluster

This guide explains how to deploy and configure OpenAI Codex to run locally on a 4-unit NVIDIA DGX Spark cluster using vLLM.

By running Codex on your own DGX Spark hardware, you can:
- Use state-of-the-art open-source models (like Llama 3 70B or DeepSeek Coder V2)
- Save significantly on API token costs
- Keep all code and intellectual property entirely on-premises
- Leverage the massive 512 GB unified memory of a 4-unit cluster for huge context windows

## Architecture

The integration uses a new `vllm` OSS provider built into Codex. It supports:
- **Single-node deployment**: Running vLLM on one DGX Spark unit.
- **Multi-node cluster**: Load balancing across 4 DGX Spark units.
- **Tensor Parallelism**: Splitting a massive model (like Llama 3.1 405B) across all 4 units using NCCL over CX-7 networking.

## Prerequisites

- 4x NVIDIA DGX Spark units connected via QSFP/CX7 cables.
- Ubuntu 24.04 with NVIDIA drivers installed.
- Docker and Docker Compose installed on all units.
- SSH access between nodes.

## Quick Start Deployment

We provide automated scripts to deploy vLLM across your cluster.

1. **Clone the repository** on your primary DGX Spark node (`spark-1`):
   ```bash
   git clone https://github.com/openai/codex.git
   cd codex/deploy/dgx-spark
   ```

2. **Configure your environment** (optional):
   Edit `scripts/setup-cluster.sh` if your node IPs differ from the defaults (`192.168.100.10` - `13`).

3. **Run the cluster setup script**:
   ```bash
   ./scripts/setup-cluster.sh --model meta-llama/Meta-Llama-3-70B-Instruct
   ```
   This script will:
   - Configure CX-7 networking.
   - Set up passwordless SSH.
   - Pre-download the model to a persistent host directory (`/mnt/models`).
   - Deploy and start the vLLM Docker containers on all nodes.

4. **Verify cluster health**:
   ```bash
   ./scripts/check-cluster.sh
   ```

## Configuring Codex

Once the cluster is running, configure Codex to use it.

1. Copy the example configuration:
   ```bash
   mkdir -p ~/.codex
   cp deploy/dgx-spark/configs/config.toml ~/.codex/config.toml
   ```

2. Set the environment variable to point to your cluster:
   ```bash
   # For a single entry point (e.g., a load balancer or primary node)
   export CODEX_VLLM_BASE_URL="http://192.168.100.10:8000/v1"
   
   # OR for client-side round-robin load balancing across all 4 nodes:
   export CODEX_VLLM_CLUSTER_NODES='[
     {"address":"192.168.100.10","port":8000,"name":"spark-1"},
     {"address":"192.168.100.11","port":8000,"name":"spark-2"},
     {"address":"192.168.100.12","port":8000,"name":"spark-3"},
     {"address":"192.168.100.13","port":8000,"name":"spark-4"}
   ]'
   ```

3. Run Codex in OSS mode:
   ```bash
   codex --oss
   ```

## Performance Optimizations

The deployment configuration includes several optimizations specifically for DGX Spark:

- **Persistent Model Store**: Models are downloaded to `/mnt/models` on the host to prevent redundant downloads when containers restart.
- **Offline Mode**: `HF_HUB_OFFLINE=1` and `VLLM_NO_USAGE_STATS=1` are set to prevent slow network calls during inference.
- **No Premature Timeouts**: The Codex client will wait patiently with a progress bar while the massive models load into GPU memory.
- **Memory Utilization**: Configured to use 90% of available GPU memory (`GPU_MEMORY_UTIL=0.90`), leaving room for the KV cache.

## Recommended Models

| Model | Size | Units Required | Context Window |
|-------|------|----------------|----------------|
| `meta-llama/Meta-Llama-3-70B-Instruct` | ~140 GB | 1-2 | 8K |
| `deepseek-ai/DeepSeek-Coder-V2-Instruct` | ~470 GB | 4 | 32K |
| `Qwen/Qwen2.5-Coder-72B-Instruct` | ~144 GB | 1-2 | 32K |
| `meta-llama/Meta-Llama-3.1-405B-Instruct` | ~810 GB | 4 (FP8) | 128K |

*Note: To run gated models like Llama 3, you must provide a Hugging Face token by setting `export HF_TOKEN=your_token` before running the setup script.*
