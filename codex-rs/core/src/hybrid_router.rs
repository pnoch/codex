//! Hybrid routing: intelligently routes each turn to either the local vLLM
//! model (DGX Spark) or the remote OpenAI supervisor model.
//!
//! # Design
//!
//! The [`HybridRouter`] is consulted at the start of every turn when hybrid
//! mode is enabled.  It assigns a **complexity score** (0.0 – 1.0) to the
//! current prompt and compares it against a configurable
//! `escalation_threshold`.  Turns that exceed the threshold are escalated to
//! the remote supervisor model; all others are handled locally.
//!
//! ## Complexity signals
//!
//! The classifier is intentionally lightweight — it must run synchronously
//! before the first token is sent — so it relies on heuristics rather than a
//! second model call:
//!
//! | Signal | Weight |
//! |--------|--------|
//! | Escalation keyword present in prompt | +0.35 |
//! | Prompt length > 500 tokens (chars/4) | +0.15 |
//! | Conversation history > 20 turns | +0.10 |
//! | Local model consecutive failure count ≥ 2 | +0.30 |
//! | User explicitly requested supervisor | +1.00 (force) |
//! | Routine keyword present in prompt | −0.20 |
//!
//! The final score is clamped to [0.0, 1.0].

use std::sync::atomic::AtomicU32;
use std::sync::atomic::Ordering;
use std::sync::Arc;

use codex_protocol::ResponseItem;
use serde::Deserialize;
use serde::Serialize;

// ─── Routing Decision ────────────────────────────────────────────────────────

/// Which model client should handle the current turn.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RoutingDecision {
    /// Use the local vLLM model on the DGX Spark cluster.
    Local,
    /// Escalate to the remote OpenAI supervisor model.
    Supervisor {
        /// Human-readable reason surfaced to the user in the TUI.
        reason: String,
    },
}

impl RoutingDecision {
    /// Returns `true` if this decision routes to the supervisor.
    pub fn is_supervisor(&self) -> bool {
        matches!(self, RoutingDecision::Supervisor { .. })
    }
}

// ─── Hybrid Router ───────────────────────────────────────────────────────────

/// Configuration for the hybrid router, derived from the user's `config.toml`.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HybridRouterConfig {
    /// Complexity score threshold above which turns are escalated.
    /// Range: 0.0 (always escalate) – 1.0 (never escalate).
    /// Default: 0.65
    pub escalation_threshold: f32,

    /// Name of the local model (used for display purposes).
    pub local_model: String,

    /// Name of the supervisor model (used for display purposes).
    pub supervisor_model: String,
}

impl Default for HybridRouterConfig {
    fn default() -> Self {
        Self {
            escalation_threshold: 0.65,
            local_model: "local (vLLM)".to_string(),
            supervisor_model: "gpt-5.3-codex".to_string(),
        }
    }
}

/// The hybrid router tracks per-session state (consecutive local failures) and
/// exposes the [`HybridRouter::route`] method.
#[derive(Debug)]
pub struct HybridRouter {
    config: HybridRouterConfig,
    /// Number of consecutive turns where the local model failed or produced an
    /// empty/error response.  Reset to 0 on any successful local turn.
    consecutive_local_failures: Arc<AtomicU32>,
}

impl HybridRouter {
    pub fn new(config: HybridRouterConfig) -> Self {
        Self {
            config,
            consecutive_local_failures: Arc::new(AtomicU32::new(0)),
        }
    }

    /// Record that the local model succeeded on the last turn.
    pub fn record_local_success(&self) {
        self.consecutive_local_failures.store(0, Ordering::Relaxed);
    }

    /// Record that the local model failed on the last turn (error or empty
    /// response).
    pub fn record_local_failure(&self) {
        self.consecutive_local_failures
            .fetch_add(1, Ordering::Relaxed);
    }

    /// Determine how to route the current turn.
    ///
    /// `prompt_text` is the raw user prompt string.
    /// `history_len` is the number of response items in the conversation history.
    pub fn route(&self, prompt_text: &str, history_len: usize) -> RoutingDecision {
        // --- Force escalation if the user explicitly asked for the supervisor ---
        if contains_supervisor_request(prompt_text) {
            return RoutingDecision::Supervisor {
                reason: "User explicitly requested the supervisor model.".to_string(),
            };
        }

        let score = self.compute_complexity_score(prompt_text, history_len);

        if score >= self.config.escalation_threshold {
            let reason = build_escalation_reason(prompt_text, score, &self.config);
            RoutingDecision::Supervisor { reason }
        } else {
            RoutingDecision::Local
        }
    }

    /// Compute a complexity score in [0.0, 1.0].
    fn compute_complexity_score(&self, prompt_text: &str, history_len: usize) -> f32 {
        let lower = prompt_text.to_lowercase();
        let mut score: f32 = 0.0;

        // --- Escalation keywords (+0.35) ---
        let escalation_keywords = [
            "architect",
            "design a",
            "design the",
            "design an",
            "refactor",
            "redesign",
            "why is this failing",
            "root cause",
            "debug",
            "investigate",
            "memory leak",
            "race condition",
            "deadlock",
            "security vulnerability",
            "performance bottleneck",
            "optimize",
            "explain why",
            "how does this work",
            "what is the best way",
            "best practice",
            "trade-off",
            "tradeoff",
            "compare",
            "evaluate",
            "review my",
            "code review",
            "audit",
        ];
        if escalation_keywords.iter().any(|kw| lower.contains(kw)) {
            score += 0.35;
        }

        // --- Long prompt (+0.15) ---
        let approx_tokens = prompt_text.len() / 4;
        if approx_tokens > 500 {
            score += 0.15;
        } else if approx_tokens > 200 {
            score += 0.07;
        }

        // --- Long conversation history (+0.10) ---
        if history_len > 30 {
            score += 0.10;
        } else if history_len > 15 {
            score += 0.05;
        }

        // --- Consecutive local failures (+0.30) ---
        let failures = self.consecutive_local_failures.load(Ordering::Relaxed);
        if failures >= 2 {
            score += 0.30;
        } else if failures == 1 {
            score += 0.15;
        }

        // --- Routine keywords (−0.20) ---
        let routine_keywords = [
            "run tests",
            "cargo test",
            "cargo build",
            "cargo check",
            "cargo fmt",
            "cargo clippy",
            "git status",
            "git add",
            "git commit",
            "git push",
            "git pull",
            "ls ",
            "cat ",
            "echo ",
            "mkdir",
            "touch ",
            "apply this patch",
            "fix the typo",
            "rename",
            "move file",
            "delete file",
        ];
        if routine_keywords.iter().any(|kw| lower.contains(kw)) {
            score -= 0.20;
        }

        score.clamp(0.0, 1.0)
    }
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

/// Returns `true` if the prompt contains an explicit request to use the
/// supervisor/remote model.
fn contains_supervisor_request(prompt: &str) -> bool {
    let lower = prompt.to_lowercase();
    [
        "use openai",
        "use gpt",
        "use supervisor",
        "use the supervisor",
        "use remote model",
        "escalate",
        "ask openai",
        "@supervisor",
        "@openai",
        "@gpt",
    ]
    .iter()
    .any(|kw| lower.contains(kw))
}

/// Build a human-readable escalation reason for the TUI notification.
fn build_escalation_reason(
    prompt: &str,
    score: f32,
    config: &HybridRouterConfig,
) -> String {
    let lower = prompt.to_lowercase();

    let trigger = if lower.contains("debug")
        || lower.contains("root cause")
        || lower.contains("why is this failing")
    {
        "complex debugging task"
    } else if lower.contains("architect")
        || lower.contains("design")
        || lower.contains("refactor")
    {
        "architectural/design task"
    } else if lower.contains("security") || lower.contains("vulnerability") {
        "security-sensitive task"
    } else if lower.contains("optimize") || lower.contains("performance") {
        "performance optimization task"
    } else {
        "high-complexity task"
    };

    format!(
        "Escalating {} to {} (complexity score: {:.2}, threshold: {:.2}).",
        trigger,
        config.supervisor_model,
        score,
        config.escalation_threshold
    )
}

// ─── Complexity Score for Prompt (public helper) ─────────────────────────────

/// Compute a complexity score for a given prompt text and history, without
/// needing a full `HybridRouter` instance.  Useful for tests.
pub fn score_prompt(prompt_text: &str, history_len: usize) -> f32 {
    let router = HybridRouter::new(HybridRouterConfig::default());
    router.compute_complexity_score(prompt_text, history_len)
}

// ─── Tests ───────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn routine_task_routes_local() {
        let router = HybridRouter::new(HybridRouterConfig::default());
        let decision = router.route("run cargo test and show me the output", 5);
        assert_eq!(decision, RoutingDecision::Local);
    }

    #[test]
    fn architecture_task_escalates() {
        let router = HybridRouter::new(HybridRouterConfig::default());
        let decision = router.route(
            "Design a new architecture for the authentication module that handles \
             multi-tenant isolation and supports OAuth2 and SAML.",
            10,
        );
        assert!(decision.is_supervisor());
    }

    #[test]
    fn debug_task_escalates() {
        let router = HybridRouter::new(HybridRouterConfig::default());
        let decision = router.route(
            "Why is this failing? I'm getting a segfault in the memory allocator.",
            8,
        );
        assert!(decision.is_supervisor());
    }

    #[test]
    fn explicit_supervisor_request_always_escalates() {
        let router = HybridRouter::new(HybridRouterConfig::default());
        let decision = router.route("@supervisor please review this code", 2);
        assert!(decision.is_supervisor());
    }

    #[test]
    fn consecutive_failures_escalate() {
        let router = HybridRouter::new(HybridRouterConfig::default());
        router.record_local_failure();
        router.record_local_failure();
        let decision = router.route("apply this patch to the file", 3);
        // Even a routine task escalates after 2 consecutive failures.
        assert!(decision.is_supervisor());
    }

    #[test]
    fn failure_reset_on_success() {
        let router = HybridRouter::new(HybridRouterConfig::default());
        router.record_local_failure();
        router.record_local_failure();
        router.record_local_success();
        let decision = router.route("run cargo test", 3);
        assert_eq!(decision, RoutingDecision::Local);
    }
}
