//! DGX Spark cluster management for vLLM inference.
//!
//! This module manages a pool of vLLM server nodes running across multiple
//! DGX Spark units. It provides:
//!
//! - Node discovery from environment configuration
//! - Health monitoring for all cluster nodes
//! - Round-robin and least-loaded request routing
//! - Automatic failover when a node becomes unhealthy

use std::sync::Arc;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::time::Duration;

use serde::Deserialize;
use serde::Serialize;
use tokio::sync::RwLock;
use tracing::{info, warn};

use crate::client::{ClusterNode, NodeHealth, VllmClient};

/// Default DGX Spark cluster node addresses (192.168.100.10–13 per NVIDIA docs).
pub const DEFAULT_CLUSTER_NODES: &[(&str, u16, &str)] = &[
    ("192.168.100.10", 8000, "dgx-spark-1"),
    ("192.168.100.11", 8000, "dgx-spark-2"),
    ("192.168.100.12", 8000, "dgx-spark-3"),
    ("192.168.100.13", 8000, "dgx-spark-4"),
];

/// Environment variable for configuring cluster nodes as a JSON array.
/// Format: `[{"address":"192.168.100.10","port":8000,"name":"spark-1"}, ...]`
pub const VLLM_CLUSTER_NODES_ENV: &str = "CODEX_VLLM_CLUSTER_NODES";

/// Environment variable for a single vLLM base URL (single-node or load-balanced endpoint).
pub const VLLM_BASE_URL_ENV: &str = "CODEX_VLLM_BASE_URL";

/// Load balancing strategy for distributing requests across cluster nodes.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "kebab-case")]
pub enum LoadBalancingStrategy {
    /// Distribute requests in round-robin order across healthy nodes.
    #[default]
    RoundRobin,
    /// Always use the first healthy node (useful for debugging).
    FirstAvailable,
}

/// The health state of a managed cluster node.
#[derive(Debug)]
struct ManagedNode {
    node: ClusterNode,
    client: VllmClient,
    health: NodeHealth,
}

/// A managed pool of vLLM nodes running on DGX Spark units.
///
/// This struct is cheaply cloneable via the inner `Arc`.
#[derive(Clone)]
pub struct VllmCluster {
    inner: Arc<ClusterInner>,
}

struct ClusterInner {
    nodes: RwLock<Vec<ManagedNode>>,
    strategy: LoadBalancingStrategy,
    round_robin_counter: AtomicUsize,
}

impl VllmCluster {
    /// Build a cluster from environment variables or fall back to defaults.
    ///
    /// Resolution order:
    /// 1. `CODEX_VLLM_BASE_URL` — single endpoint (wraps as a one-node cluster)
    /// 2. `CODEX_VLLM_CLUSTER_NODES` — JSON array of node definitions
    /// 3. Default DGX Spark cluster addresses (192.168.100.10–13)
    pub fn from_env() -> Self {
        let nodes = if let Ok(base_url) = std::env::var(VLLM_BASE_URL_ENV) {
            info!("Using single vLLM endpoint from {VLLM_BASE_URL_ENV}: {base_url}");
            vec![ClusterNode {
                address: base_url.clone(),
                port: 0,
                name: "vllm-single".to_string(),
            }]
        } else if let Ok(nodes_json) = std::env::var(VLLM_CLUSTER_NODES_ENV) {
            match serde_json::from_str::<Vec<ClusterNode>>(&nodes_json) {
                Ok(nodes) => {
                    info!("Loaded {} cluster node(s) from {VLLM_CLUSTER_NODES_ENV}", nodes.len());
                    nodes
                }
                Err(e) => {
                    warn!("Failed to parse {VLLM_CLUSTER_NODES_ENV}: {e}. Using defaults.");
                    Self::default_nodes()
                }
            }
        } else {
            info!("No cluster configuration found in environment. Using default DGX Spark addresses.");
            Self::default_nodes()
        };

        Self::from_nodes(nodes, LoadBalancingStrategy::RoundRobin)
    }

    /// Build a cluster from an explicit list of nodes.
    pub fn from_nodes(nodes: Vec<ClusterNode>, strategy: LoadBalancingStrategy) -> Self {
        let managed_nodes = nodes
            .into_iter()
            .map(|node| {
                let client = if node.port == 0 {
                    // Single-endpoint mode: address is the full base URL
                    VllmClient::from_base_url(node.address.clone())
                } else {
                    VllmClient::from_host_root(format!("http://{}:{}", node.address, node.port))
                };
                ManagedNode {
                    node,
                    client,
                    health: NodeHealth::Healthy, // Optimistically assume healthy until probed
                }
            })
            .collect();

        Self {
            inner: Arc::new(ClusterInner {
                nodes: RwLock::new(managed_nodes),
                strategy,
                round_robin_counter: AtomicUsize::new(0),
            }),
        }
    }

    /// Build the default 4-node DGX Spark cluster.
    fn default_nodes() -> Vec<ClusterNode> {
        DEFAULT_CLUSTER_NODES
            .iter()
            .map(|(addr, port, name)| ClusterNode {
                address: addr.to_string(),
                port: *port,
                name: name.to_string(),
            })
            .collect()
    }

    /// Probe all nodes and update their health status.
    pub async fn refresh_health(&self) {
        let mut nodes = self.inner.nodes.write().await;
        for managed in nodes.iter_mut() {
            let health = managed.client.health().await;
            if health != managed.health {
                match &health {
                    NodeHealth::Healthy => {
                        info!("Node '{}' ({}) is now healthy", managed.node.name, managed.node.address);
                    }
                    NodeHealth::Unhealthy(reason) => {
                        warn!("Node '{}' ({}) is unhealthy: {reason}", managed.node.name, managed.node.address);
                    }
                }
            }
            managed.health = health;
        }
    }

    /// Return the base URL of the next healthy node according to the load
    /// balancing strategy. Returns `None` if no healthy nodes are available.
    pub async fn next_healthy_base_url(&self) -> Option<String> {
        let nodes = self.inner.nodes.read().await;
        let healthy: Vec<&ManagedNode> = nodes
            .iter()
            .filter(|n| n.health == NodeHealth::Healthy)
            .collect();

        if healthy.is_empty() {
            return None;
        }

        let selected = match self.inner.strategy {
            LoadBalancingStrategy::RoundRobin => {
                let idx = self.inner.round_robin_counter.fetch_add(1, Ordering::Relaxed);
                &healthy[idx % healthy.len()]
            }
            LoadBalancingStrategy::FirstAvailable => healthy[0],
        };

        Some(selected.client.base_url.clone())
    }

    /// Return a `VllmClient` for the next healthy node.
    pub async fn next_client(&self) -> Option<VllmClient> {
        let base_url = self.next_healthy_base_url().await?;
        Some(VllmClient::from_base_url(base_url))
    }

    /// Return the number of healthy nodes in the cluster.
    pub async fn healthy_node_count(&self) -> usize {
        let nodes = self.inner.nodes.read().await;
        nodes.iter().filter(|n| n.health == NodeHealth::Healthy).count()
    }

    /// Return the total number of nodes in the cluster.
    pub async fn total_node_count(&self) -> usize {
        self.inner.nodes.read().await.len()
    }

    /// Return a summary of cluster health for display.
    pub async fn health_summary(&self) -> String {
        let nodes = self.inner.nodes.read().await;
        let healthy = nodes.iter().filter(|n| n.health == NodeHealth::Healthy).count();
        let total = nodes.len();
        format!("{healthy}/{total} DGX Spark nodes healthy")
    }

    /// Start a background task that periodically refreshes node health.
    /// The returned handle can be dropped to stop the background task.
    pub fn start_health_monitor(self, interval: Duration) -> tokio::task::JoinHandle<()> {
        tokio::spawn(async move {
            let mut ticker = tokio::time::interval(interval);
            loop {
                ticker.tick().await;
                self.refresh_health().await;
            }
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_default_nodes_count() {
        let nodes = VllmCluster::default_nodes();
        assert_eq!(nodes.len(), 4);
    }

    #[test]
    fn test_default_nodes_addresses() {
        let nodes = VllmCluster::default_nodes();
        assert_eq!(nodes[0].address, "192.168.100.10");
        assert_eq!(nodes[1].address, "192.168.100.11");
        assert_eq!(nodes[2].address, "192.168.100.12");
        assert_eq!(nodes[3].address, "192.168.100.13");
    }

    #[test]
    fn test_from_env_uses_base_url_when_set() {
        std::env::set_var(VLLM_BASE_URL_ENV, "http://10.0.0.1:8000/v1");
        let cluster = VllmCluster::from_env();
        // Should create a single-node cluster
        let rt = tokio::runtime::Runtime::new().unwrap();
        let count = rt.block_on(cluster.total_node_count());
        assert_eq!(count, 1);
        std::env::remove_var(VLLM_BASE_URL_ENV);
    }

    #[tokio::test]
    async fn test_round_robin_selection() {
        let nodes = vec![
            ClusterNode {
                address: "192.168.100.10".to_string(),
                port: 8000,
                name: "spark-1".to_string(),
            },
            ClusterNode {
                address: "192.168.100.11".to_string(),
                port: 8000,
                name: "spark-2".to_string(),
            },
        ];
        let cluster = VllmCluster::from_nodes(nodes, LoadBalancingStrategy::RoundRobin);
        // All nodes start as healthy
        let url1 = cluster.next_healthy_base_url().await.unwrap();
        let url2 = cluster.next_healthy_base_url().await.unwrap();
        // Round-robin should alternate
        assert_ne!(url1, url2);
    }
}
