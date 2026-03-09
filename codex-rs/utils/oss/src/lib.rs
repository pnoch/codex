//! OSS provider utilities shared between TUI and exec.

use codex_core::LMSTUDIO_OSS_PROVIDER_ID;
use codex_core::OLLAMA_OSS_PROVIDER_ID;
use codex_core::VLLM_OSS_PROVIDER_ID;
use codex_core::config::Config;

/// Returns the default model for a given OSS provider.
pub fn get_default_model_for_oss_provider(provider_id: &str) -> Option<&'static str> {
    match provider_id {
        LMSTUDIO_OSS_PROVIDER_ID => Some(codex_lmstudio::DEFAULT_OSS_MODEL),
        OLLAMA_OSS_PROVIDER_ID => Some(codex_ollama::DEFAULT_OSS_MODEL),
        VLLM_OSS_PROVIDER_ID => Some(codex_vllm::DEFAULT_OSS_MODEL),
        _ => None,
    }
}

/// Ensures the specified OSS provider is ready (models downloaded, service reachable).
///
/// For the `vllm` provider this will:
/// 1. Pre-download the requested model to the persistent model store.
/// 2. Probe the DGX Spark cluster to verify at least one node is reachable.
/// 3. Wait (without a premature timeout) until the model is fully loaded.
pub async fn ensure_oss_provider_ready(
    provider_id: &str,
    config: &Config,
) -> Result<(), std::io::Error> {
    match provider_id {
        LMSTUDIO_OSS_PROVIDER_ID => {
            codex_lmstudio::ensure_oss_ready(config)
                .await
                .map_err(|e| std::io::Error::other(format!("OSS setup failed: {e}")))?;
        }
        OLLAMA_OSS_PROVIDER_ID => {
            codex_ollama::ensure_responses_supported(&config.model_provider).await?;
            codex_ollama::ensure_oss_ready(config)
                .await
                .map_err(|e| std::io::Error::other(format!("OSS setup failed: {e}")))?;
        }
        VLLM_OSS_PROVIDER_ID => {
            codex_vllm::ensure_oss_ready(config)
                .await
                .map_err(|e| std::io::Error::other(format!("vLLM DGX Spark setup failed: {e}")))?;
        }
        _ => {
            // Unknown provider — skip setup; the provider may be a custom
            // user-defined entry in config.toml that manages its own lifecycle.
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_get_default_model_for_provider_lmstudio() {
        let result = get_default_model_for_oss_provider(LMSTUDIO_OSS_PROVIDER_ID);
        assert_eq!(result, Some(codex_lmstudio::DEFAULT_OSS_MODEL));
    }

    #[test]
    fn test_get_default_model_for_provider_ollama() {
        let result = get_default_model_for_oss_provider(OLLAMA_OSS_PROVIDER_ID);
        assert_eq!(result, Some(codex_ollama::DEFAULT_OSS_MODEL));
    }

    #[test]
    fn test_get_default_model_for_provider_vllm() {
        let result = get_default_model_for_oss_provider(VLLM_OSS_PROVIDER_ID);
        assert_eq!(result, Some(codex_vllm::DEFAULT_OSS_MODEL));
    }

    #[test]
    fn test_get_default_model_for_provider_unknown() {
        let result = get_default_model_for_oss_provider("unknown-provider");
        assert_eq!(result, None);
    }
}
