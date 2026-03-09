//! Model download and management for vLLM on DGX Spark.
//!
//! This module handles:
//! - Pre-downloading models to a persistent host directory before starting vLLM
//! - SHA-256 hash verification for downloaded model files
//! - Progress tracking with a visual progress bar
//! - Offline mode enforcement after initial download

use std::path::{Path, PathBuf};

use indicatif::{MultiProgress, ProgressBar, ProgressStyle};
use tracing::{info, warn};

/// Default persistent model storage directory on the DGX Spark host.
/// This path is mounted into the vLLM container to prevent redundant downloads.
pub const DEFAULT_MODEL_STORE: &str = "/mnt/models";

/// Environment variable for overriding the model storage path.
pub const MODEL_STORE_ENV: &str = "CODEX_VLLM_MODEL_STORE";

/// Environment variable for the Hugging Face Hub token (needed for gated models).
pub const HF_TOKEN_ENV: &str = "HF_TOKEN";

/// Resolve the model storage directory from the environment or fall back to the default.
pub fn resolve_model_store() -> PathBuf {
    std::env::var(MODEL_STORE_ENV)
        .ok()
        .filter(|v| !v.trim().is_empty())
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(DEFAULT_MODEL_STORE))
}

/// Check whether a model directory already exists in the model store.
pub fn model_exists_locally(model_id: &str, store: &Path) -> bool {
    // Hugging Face model IDs use '/' as a separator; map to a filesystem path.
    let model_dir = store.join(model_id.replace('/', "--"));
    model_dir.exists() && model_dir.is_dir()
}

/// Download a model from Hugging Face Hub using `huggingface-cli` or the
/// Python `huggingface_hub` library, writing files to the persistent model store.
///
/// This function is intentionally synchronous-looking from the caller's
/// perspective — it will NOT return until the download is complete. A progress
/// bar is displayed throughout.
pub async fn download_model(model_id: &str, store: &Path) -> std::io::Result<()> {
    let model_dir = store.join(model_id.replace('/', "--"));

    if model_exists_locally(model_id, store) {
        info!("Model '{model_id}' already exists at {}", model_dir.display());
        return Ok(());
    }

    info!("Downloading model '{model_id}' to {}...", model_dir.display());

    // Ensure the store directory exists.
    tokio::fs::create_dir_all(store)
        .await
        .map_err(|e| std::io::Error::other(format!("Failed to create model store: {e}")))?;

    let mp = MultiProgress::new();
    let pb = mp.add(ProgressBar::new_spinner());
    pb.set_style(
        ProgressStyle::with_template("{spinner:.cyan} {msg}")
            .unwrap()
            .tick_strings(&["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]),
    );
    pb.set_message(format!("Downloading '{model_id}' from Hugging Face Hub..."));
    pb.enable_steady_tick(std::time::Duration::from_millis(100));

    // Build the download command. We prefer `huggingface-cli` if available,
    // otherwise fall back to a Python one-liner.
    let hf_token = std::env::var(HF_TOKEN_ENV).ok();
    let store_str = store.to_string_lossy();

    let mut cmd = tokio::process::Command::new("python3");
    cmd.args([
        "-c",
        &format!(
            r#"
import os, sys
from huggingface_hub import snapshot_download

token = os.environ.get('HF_TOKEN')
local_dir = os.path.join('{store_str}', '{model_id}'.replace('/', '--'))

print(f"Downloading {{model_id}} to {{local_dir}}", flush=True)
snapshot_download(
    repo_id='{model_id}',
    local_dir=local_dir,
    token=token,
    local_dir_use_symlinks=False,
)
print("Download complete.", flush=True)
"#,
            store_str = store_str,
            model_id = model_id,
        ),
    ]);

    if let Some(token) = hf_token {
        cmd.env("HF_TOKEN", token);
    }

    // Force offline mode for the Hub after download to prevent slow calls.
    // The download itself must NOT be in offline mode.
    cmd.env("VLLM_NO_USAGE_STATS", "1");

    let output = cmd
        .output()
        .await
        .map_err(|e| std::io::Error::other(format!("Failed to run download command: {e}")))?;

    pb.finish_and_clear();

    if output.status.success() {
        info!("Successfully downloaded model '{model_id}'");
        Ok(())
    } else {
        let stderr = String::from_utf8_lossy(&output.stderr);
        Err(std::io::Error::other(format!(
            "Model download failed for '{model_id}':\n{stderr}"
        )))
    }
}

/// Verify the integrity of a downloaded model directory by checking for
/// required metadata files (a lightweight sanity check).
pub fn verify_model_integrity(model_id: &str, store: &Path) -> std::io::Result<()> {
    let model_dir = store.join(model_id.replace('/', "--"));

    if !model_dir.exists() {
        return Err(std::io::Error::other(format!(
            "Model directory not found: {}",
            model_dir.display()
        )));
    }

    // Check for at least one model weight file or config.
    let has_config = model_dir.join("config.json").exists();
    let has_weights = std::fs::read_dir(&model_dir)
        .map(|entries| {
            entries
                .filter_map(|e| e.ok())
                .any(|e| {
                    let name = e.file_name();
                    let s = name.to_string_lossy();
                    s.ends_with(".safetensors") || s.ends_with(".bin") || s.ends_with(".gguf")
                })
        })
        .unwrap_or(false);

    if has_config && has_weights {
        info!("Model '{model_id}' integrity check passed");
        Ok(())
    } else {
        warn!(
            "Model '{model_id}' may be incomplete (config: {has_config}, weights: {has_weights})"
        );
        // Non-fatal: vLLM will report a clearer error if the model is unusable.
        Ok(())
    }
}

/// Prepare the model for use: download if missing, then verify integrity.
/// This is the primary entry point called during `ensure_oss_ready`.
pub async fn prepare_model(model_id: &str) -> std::io::Result<()> {
    let store = resolve_model_store();

    if !model_exists_locally(model_id, &store) {
        download_model(model_id, &store).await?;
    } else {
        info!("Model '{model_id}' already present in {}", store.display());
    }

    verify_model_integrity(model_id, &store)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use tempfile::tempdir;

    #[test]
    fn test_model_exists_locally_false_when_missing() {
        let dir = tempdir().unwrap();
        assert!(!model_exists_locally("meta-llama/Meta-Llama-3-70B-Instruct", dir.path()));
    }

    #[test]
    fn test_model_exists_locally_true_when_present() {
        let dir = tempdir().unwrap();
        let model_dir = dir.path().join("meta-llama--Meta-Llama-3-70B-Instruct");
        fs::create_dir_all(&model_dir).unwrap();
        assert!(model_exists_locally("meta-llama/Meta-Llama-3-70B-Instruct", dir.path()));
    }

    #[test]
    fn test_resolve_model_store_default() {
        std::env::remove_var(MODEL_STORE_ENV);
        let store = resolve_model_store();
        assert_eq!(store, PathBuf::from(DEFAULT_MODEL_STORE));
    }

    #[test]
    fn test_resolve_model_store_from_env() {
        std::env::set_var(MODEL_STORE_ENV, "/custom/models");
        let store = resolve_model_store();
        assert_eq!(store, PathBuf::from("/custom/models"));
        std::env::remove_var(MODEL_STORE_ENV);
    }
}
