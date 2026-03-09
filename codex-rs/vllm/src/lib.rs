//! `codex-vllm` — vLLM integration for OpenAI Codex on DGX Spark clusters.
//!
//! This crate provides the glue between Codex's OSS provider system and a
//! [vLLM](https://github.com/vllm-project/vllm) server running on one or more
//! NVIDIA DGX Spark units. It mirrors the structure of `codex-ollama` and
//! `codex-lmstudio` so that the vLLM provider can be selected via the same
//! `oss_provider` configuration key.
//!
//! ## Quick Start
//!
//! Add the following to your `~/.codex/config.toml`:
//!
//! ```toml
//! [profile.default]
//! oss_provider = "vllm"
//! model = "meta-llama/Meta-Llama-3-70B-Instruct"
//! ```
//!
//! Then set the cluster address (or let Codex use the default DGX Spark
//! subnet addresses):
//!
//! ```sh
//! export CODEX_VLLM_BASE_URL="http://192.168.100.10:8000/v1"
//! codex --oss
//! ```
//!
//! ## Multi-Node Cluster
//!
//! For a 4-unit DGX Spark cluster with tensor parallelism, set:
//!
//! ```sh
//! export CODEX_VLLM_CLUSTER_NODES='[
//!   {"address":"192.168.100.10","port":8000,"name":"spark-1"},
//!   {"address":"192.168.100.11","port":8000,"name":"spark-2"},
//!   {"address":"192.168.100.12","port":8000,"name":"spark-3"},
//!   {"address":"192.168.100.13","port":8000,"name":"spark-4"}
//! ]'
//! ```

pub mod client;
pub mod cluster;
pub mod model_manager;

pub use client::VllmClient;
pub use client::DEFAULT_VLLM_PORT;
pub use cluster::LoadBalancingStrategy;
pub use cluster::VllmCluster;
pub use cluster::VLLM_BASE_URL_ENV;
pub use cluster::VLLM_CLUSTER_NODES_ENV;
pub use model_manager::prepare_model;
pub use model_manager::resolve_model_store;

use codex_core::config::Config;

/// Default OSS model to use when `--oss` is passed without an explicit `-m`.
///
/// This is a capable coding model that fits comfortably within the 128 GB
/// unified memory of a single DGX Spark unit.
pub const DEFAULT_OSS_MODEL: &str = "meta-llama/Meta-Llama-3-70B-Instruct";

/// Prepare the local vLLM environment when `--oss` is selected with the
/// `vllm` provider.
///
/// This function:
/// 1. Resolves the model to use (from config or the default).
/// 2. Pre-downloads the model to the persistent model store if not present.
/// 3. Probes the vLLM cluster to verify at least one node is reachable.
/// 4. Waits (without a premature timeout) until the model is fully loaded.
pub async fn ensure_oss_ready(config: &Config) -> std::io::Result<()> {
    let model = config
        .model
        .as_deref()
        .unwrap_or(DEFAULT_OSS_MODEL);

    // Step 1: Pre-download the model to the persistent host store.
    model_manager::prepare_model(model).await?;

    // Step 2: Build the cluster from environment configuration.
    let cluster = VllmCluster::from_env();

    // Step 3: Refresh health to discover which nodes are reachable.
    cluster.refresh_health().await;

    let healthy = cluster.healthy_node_count().await;
    let total = cluster.total_node_count().await;

    if healthy == 0 {
        return Err(std::io::Error::other(format!(
            "No vLLM nodes are reachable ({total} configured). \
             Ensure the vLLM service is running on your DGX Spark cluster. \
             See docs/dgx-spark-setup.md for setup instructions."
        )));
    }

    tracing::info!(
        "vLLM cluster: {healthy}/{total} nodes healthy. Using model '{model}'."
    );

    // Step 4: Wait for the model to be fully loaded on at least one node.
    if let Some(client) = cluster.next_client().await {
        client.wait_until_ready(model).await?;
    }

    Ok(())
}
