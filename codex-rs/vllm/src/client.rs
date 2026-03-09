//! HTTP client for communicating with a vLLM server running on DGX Spark.
//!
//! vLLM exposes an OpenAI-compatible REST API at `/v1/models` and
//! `/v1/completions`. This client handles:
//!
//! - Server health probing (with retry and backoff)
//! - Model listing and availability checks
//! - Cluster node discovery for multi-DGX-Spark configurations

use std::time::Duration;

use serde::Deserialize;
use serde::Serialize;
use tracing::warn;

/// Default port that vLLM listens on.
pub const DEFAULT_VLLM_PORT: u16 = 8000;

/// Connection error message shown when the vLLM server is unreachable.
pub const VLLM_CONNECTION_ERROR: &str =
    "Cannot connect to vLLM server. \
     Ensure the vLLM service is running on your DGX Spark cluster and \
     the CODEX_VLLM_BASE_URL environment variable points to the correct address \
     (e.g. http://192.168.100.10:8000/v1). \
     See docs/dgx-spark-setup.md for cluster setup instructions.";

/// A single model entry returned by the `/v1/models` endpoint.
#[derive(Debug, Deserialize)]
pub struct ModelEntry {
    pub id: String,
}

/// The response body from `/v1/models`.
#[derive(Debug, Deserialize)]
struct ModelsResponse {
    data: Vec<ModelEntry>,
}

/// Health status of a vLLM server node.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum NodeHealth {
    Healthy,
    Unhealthy(String),
}

/// Cluster node information.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ClusterNode {
    pub address: String,
    pub port: u16,
    pub name: String,
}

impl ClusterNode {
    pub fn base_url(&self) -> String {
        format!("http://{}:{}/v1", self.address, self.port)
    }
}

/// HTTP client for a single vLLM server node.
#[derive(Clone)]
pub struct VllmClient {
    /// Base URL including the `/v1` path prefix, e.g. `http://192.168.100.10:8000/v1`.
    pub(crate) base_url: String,
    http: reqwest::Client,
}

impl VllmClient {
    /// Create a client from an explicit base URL.
    pub fn from_base_url(base_url: impl Into<String>) -> Self {
        let http = reqwest::Client::builder()
            .timeout(Duration::from_secs(30))
            .build()
            .expect("failed to build reqwest client");
        Self {
            base_url: base_url.into(),
            http,
        }
    }

    /// Create a client from a host root (without the `/v1` suffix).
    pub fn from_host_root(host_root: impl AsRef<str>) -> Self {
        let root = host_root.as_ref().trim_end_matches('/');
        Self::from_base_url(format!("{root}/v1"))
    }

    /// Attempt to connect to the vLLM server, returning an error if it is
    /// unreachable or returns a non-success HTTP status.
    pub async fn probe_server(&self) -> std::io::Result<()> {
        let url = format!("{}/models", self.base_url);
        let response = self
            .http
            .get(&url)
            .send()
            .await
            .map_err(|e| std::io::Error::other(format!("{VLLM_CONNECTION_ERROR}\nDetail: {e}")))?;

        if response.status().is_success() {
            Ok(())
        } else {
            Err(std::io::Error::other(format!(
                "vLLM server returned HTTP {}: {}",
                response.status(),
                url
            )))
        }
    }

    /// Try to create a client by probing the server first.
    /// Returns an error if the server is unreachable.
    pub async fn try_from_base_url(base_url: impl Into<String>) -> std::io::Result<Self> {
        let client = Self::from_base_url(base_url);
        client.probe_server().await?;
        Ok(client)
    }

    /// Fetch the list of model IDs available on this vLLM server.
    pub async fn fetch_models(&self) -> std::io::Result<Vec<String>> {
        let url = format!("{}/models", self.base_url);
        let response = self
            .http
            .get(&url)
            .send()
            .await
            .map_err(|e| std::io::Error::other(format!("Failed to fetch models: {e}")))?;

        if !response.status().is_success() {
            return Err(std::io::Error::other(format!(
                "Failed to fetch models: {}",
                response.status()
            )));
        }

        let body: ModelsResponse = response
            .json()
            .await
            .map_err(|e| std::io::Error::other(format!("Failed to parse models response: {e}")))?;

        Ok(body.data.into_iter().map(|m| m.id).collect())
    }

    /// Check whether a specific model is loaded and available.
    pub async fn is_model_available(&self, model_id: &str) -> std::io::Result<bool> {
        let models = self.fetch_models().await?;
        Ok(models.iter().any(|m| m == model_id))
    }

    /// Wait for the vLLM server to become healthy, with progress reporting.
    /// This does NOT have a premature timeout — it will wait until the server
    /// is ready or until the user interrupts the process.
    pub async fn wait_until_ready(&self, model_id: &str) -> std::io::Result<()> {
        use indicatif::{ProgressBar, ProgressStyle};
        use tokio::time::sleep;

        let pb = ProgressBar::new_spinner();
        pb.set_style(
            ProgressStyle::with_template("{spinner:.green} {msg}")
                .unwrap()
                .tick_strings(&["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]),
        );
        pb.set_message(format!(
            "Waiting for vLLM server at {} to load model '{}'...",
            self.base_url, model_id
        ));

        let mut attempt = 0u32;
        loop {
            attempt += 1;
            pb.tick();

            match self.probe_server().await {
                Ok(()) => {
                    match self.is_model_available(model_id).await {
                        Ok(true) => {
                            pb.finish_with_message(format!(
                                "✓ vLLM server ready — model '{}' loaded after {} attempt(s)",
                                model_id, attempt
                            ));
                            return Ok(());
                        }
                        Ok(false) => {
                            pb.set_message(format!(
                                "Server is up but model '{}' not yet loaded (attempt {})...",
                                model_id, attempt
                            ));
                        }
                        Err(e) => {
                            warn!("Error checking model availability: {e}");
                        }
                    }
                }
                Err(e) => {
                    pb.set_message(format!(
                        "Waiting for vLLM server (attempt {attempt}): {e}"
                    ));
                }
            }

            // Exponential backoff capped at 10 seconds.
            let delay = Duration::from_secs(std::cmp::min(2u64.pow(attempt.min(4)), 10));
            sleep(delay).await;
        }
    }

    /// Check the health of this node.
    pub async fn health(&self) -> NodeHealth {
        match self.probe_server().await {
            Ok(()) => NodeHealth::Healthy,
            Err(e) => NodeHealth::Unhealthy(e.to_string()),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_from_host_root_appends_v1() {
        let client = VllmClient::from_host_root("http://192.168.100.10:8000");
        assert_eq!(client.base_url, "http://192.168.100.10:8000/v1");
    }

    #[test]
    fn test_from_host_root_strips_trailing_slash() {
        let client = VllmClient::from_host_root("http://192.168.100.10:8000/");
        assert_eq!(client.base_url, "http://192.168.100.10:8000/v1");
    }

    #[test]
    fn test_cluster_node_base_url() {
        let node = ClusterNode {
            address: "192.168.100.10".to_string(),
            port: 8000,
            name: "spark-node-1".to_string(),
        };
        assert_eq!(node.base_url(), "http://192.168.100.10:8000/v1");
    }

    #[tokio::test]
    async fn test_probe_server_happy_path() {
        if std::env::var("CODEX_SANDBOX_NETWORK_DISABLED").is_ok() {
            return;
        }
        let server = wiremock::MockServer::start().await;
        wiremock::Mock::given(wiremock::matchers::method("GET"))
            .and(wiremock::matchers::path("/v1/models"))
            .respond_with(
                wiremock::ResponseTemplate::new(200).set_body_raw(
                    serde_json::json!({"data": []}).to_string(),
                    "application/json",
                ),
            )
            .mount(&server)
            .await;
        let client = VllmClient::from_host_root(server.uri());
        client.probe_server().await.expect("probe should succeed");
    }

    #[tokio::test]
    async fn test_probe_server_connection_refused() {
        if std::env::var("CODEX_SANDBOX_NETWORK_DISABLED").is_ok() {
            return;
        }
        let server = wiremock::MockServer::start().await;
        let uri = server.uri();
        drop(server); // Stop the server to simulate connection refused
        let client = VllmClient::from_host_root(&uri);
        let err = client.probe_server().await.unwrap_err();
        assert!(err.to_string().contains("Cannot connect to vLLM server"));
    }

    #[tokio::test]
    async fn test_fetch_models() {
        if std::env::var("CODEX_SANDBOX_NETWORK_DISABLED").is_ok() {
            return;
        }
        let server = wiremock::MockServer::start().await;
        wiremock::Mock::given(wiremock::matchers::method("GET"))
            .and(wiremock::matchers::path("/v1/models"))
            .respond_with(
                wiremock::ResponseTemplate::new(200).set_body_raw(
                    serde_json::json!({
                        "data": [
                            {"id": "meta-llama/Meta-Llama-3-70B-Instruct"},
                            {"id": "deepseek-ai/DeepSeek-Coder-V2-Instruct"}
                        ]
                    })
                    .to_string(),
                    "application/json",
                ),
            )
            .mount(&server)
            .await;
        let client = VllmClient::from_host_root(server.uri());
        let models = client.fetch_models().await.expect("fetch models");
        assert_eq!(models.len(), 2);
        assert!(models.contains(&"meta-llama/Meta-Llama-3-70B-Instruct".to_string()));
    }
}
