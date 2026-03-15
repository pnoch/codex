use super::*;
use crate::codex::make_session_configuration_for_tests;
use crate::protocol::RateLimitWindow;
use pretty_assertions::assert_eq;

#[tokio::test]
// Verifies connector merging deduplicates repeated IDs.
async fn merge_connector_selection_deduplicates_entries() {
    let session_configuration = make_session_configuration_for_tests().await;
    let mut state = SessionState::new(session_configuration);
    let merged = state.merge_connector_selection([
        "calendar".to_string(),
        "calendar".to_string(),
        "drive".to_string(),
    ]);

    assert_eq!(
        merged,
        HashSet::from(["calendar".to_string(), "drive".to_string()])
    );
}

#[tokio::test]
// Verifies clearing connector selection removes all saved IDs.
async fn clear_connector_selection_removes_entries() {
    let session_configuration = make_session_configuration_for_tests().await;
    let mut state = SessionState::new(session_configuration);
    state.merge_connector_selection(["calendar".to_string()]);

    state.clear_connector_selection();

    assert_eq!(state.get_connector_selection(), HashSet::new());
}

#[tokio::test]
async fn set_rate_limits_defaults_limit_id_to_codex_when_missing() {
    let session_configuration = make_session_configuration_for_tests().await;
    let mut state = SessionState::new(session_configuration);

    state.set_rate_limits(RateLimitSnapshot {
        limit_id: None,
        limit_name: None,
        primary: Some(RateLimitWindow {
            used_percent: 12.0,
            window_minutes: Some(60),
            resets_at: Some(100),
        }),
        secondary: None,
        credits: None,
        plan_type: None,
    });

    assert_eq!(
        state
            .latest_rate_limits
            .as_ref()
            .and_then(|v| v.limit_id.clone()),
        Some("codex".to_string())
    );
}

#[tokio::test]
async fn set_rate_limits_defaults_to_codex_when_limit_id_missing_after_other_bucket() {
    let session_configuration = make_session_configuration_for_tests().await;
    let mut state = SessionState::new(session_configuration);

    state.set_rate_limits(RateLimitSnapshot {
        limit_id: Some("codex_other".to_string()),
        limit_name: Some("codex_other".to_string()),
        primary: Some(RateLimitWindow {
            used_percent: 20.0,
            window_minutes: Some(60),
            resets_at: Some(200),
        }),
        secondary: None,
        credits: None,
        plan_type: None,
    });
    state.set_rate_limits(RateLimitSnapshot {
        limit_id: None,
        limit_name: None,
        primary: Some(RateLimitWindow {
            used_percent: 30.0,
            window_minutes: Some(60),
            resets_at: Some(300),
        }),
        secondary: None,
        credits: None,
        plan_type: None,
    });

    assert_eq!(
        state
            .latest_rate_limits
            .as_ref()
            .and_then(|v| v.limit_id.clone()),
        Some("codex".to_string())
    );
}

#[tokio::test]
async fn set_rate_limits_carries_credits_and_plan_type_from_codex_to_codex_other() {
    let session_configuration = make_session_configuration_for_tests().await;
    let mut state = SessionState::new(session_configuration);

    state.set_rate_limits(RateLimitSnapshot {
        limit_id: Some("codex".to_string()),
        limit_name: Some("codex".to_string()),
        primary: Some(RateLimitWindow {
            used_percent: 10.0,
            window_minutes: Some(60),
            resets_at: Some(100),
        }),
        secondary: None,
        credits: Some(crate::protocol::CreditsSnapshot {
            has_credits: true,
            unlimited: false,
            balance: Some("50".to_string()),
        }),
        plan_type: Some(codex_protocol::account::PlanType::Plus),
    });

    state.set_rate_limits(RateLimitSnapshot {
        limit_id: Some("codex_other".to_string()),
        limit_name: None,
        primary: Some(RateLimitWindow {
            used_percent: 30.0,
            window_minutes: Some(120),
            resets_at: Some(200),
        }),
        secondary: None,
        credits: None,
        plan_type: None,
    });

    assert_eq!(
        state.latest_rate_limits,
        Some(RateLimitSnapshot {
            limit_id: Some("codex_other".to_string()),
            limit_name: None,
            primary: Some(RateLimitWindow {
                used_percent: 30.0,
                window_minutes: Some(120),
                resets_at: Some(200),
            }),
            secondary: None,
            credits: Some(crate::protocol::CreditsSnapshot {
                has_credits: true,
                unlimited: false,
                balance: Some("50".to_string()),
            }),
            plan_type: Some(codex_protocol::account::PlanType::Plus),
        })
    );
}

// ─── Weekly limit bypass tests ────────────────────────────────────────────────

/// Helper: build a SessionState whose secondary (weekly) window is at 100 %.
async fn make_exhausted_state() -> SessionState {
    let session_configuration = make_session_configuration_for_tests().await;
    let mut state = SessionState::new(session_configuration);
    state.set_rate_limits(RateLimitSnapshot {
        limit_id: Some("codex".to_string()),
        limit_name: None,
        primary: Some(RateLimitWindow {
            used_percent: 50.0,
            window_minutes: Some(300),
            resets_at: None,
        }),
        secondary: Some(RateLimitWindow {
            used_percent: 100.0,
            window_minutes: Some(10_080), // 1 week in minutes
            resets_at: Some(9_999_999),
        }),
        credits: None,
        plan_type: None,
    });
    state
}

#[tokio::test]
// Verifies that is_weekly_limit_exhausted returns true when secondary
// used_percent == 100 in a release-equivalent code path (env var absent).
async fn weekly_limit_exhausted_returns_true_when_at_100_percent() {
    // Make sure the env var is NOT set for this test.
    // SAFETY: test-only env var mutation

    unsafe { std::env::remove_var("CODEX_BYPASS_RATE_LIMIT"); }
    let state = make_exhausted_state().await;

    // In debug builds the gate is always open, so we can only assert the
    // env-var path here.  The cfg(not(debug_assertions)) branch is tested
    // by the release-build CI job.
    #[cfg(not(debug_assertions))]
    assert!(
        state.is_weekly_limit_exhausted(),
        "Expected is_weekly_limit_exhausted() == true when secondary.used_percent == 100"
    );

    // In debug builds the gate is always open — confirm it returns false.
    #[cfg(debug_assertions)]
    assert!(
        !state.is_weekly_limit_exhausted(),
        "Expected is_weekly_limit_exhausted() == false in debug builds (gate always open)"
    );
}

#[tokio::test]
// Verifies that setting CODEX_BYPASS_RATE_LIMIT bypasses the gate even when
// the weekly limit is fully exhausted.
async fn weekly_limit_bypass_env_var_skips_gate() {
    // SAFETY: test-only env var mutation

    unsafe { std::env::set_var("CODEX_BYPASS_RATE_LIMIT", "1"); }
    let state = make_exhausted_state().await;

    assert!(
        !state.is_weekly_limit_exhausted(),
        "Expected is_weekly_limit_exhausted() == false when CODEX_BYPASS_RATE_LIMIT is set"
    );

    // Clean up so other tests are not affected.
    // SAFETY: test-only env var mutation

    unsafe { std::env::remove_var("CODEX_BYPASS_RATE_LIMIT"); }
}

#[tokio::test]
// Verifies that a session with < 100 % weekly usage is never considered
// exhausted, regardless of the env var.
async fn weekly_limit_not_exhausted_when_below_100_percent() {
    // SAFETY: test-only env var mutation

    unsafe { std::env::remove_var("CODEX_BYPASS_RATE_LIMIT"); }
    let session_configuration = make_session_configuration_for_tests().await;
    let mut state = SessionState::new(session_configuration);
    state.set_rate_limits(RateLimitSnapshot {
        limit_id: Some("codex".to_string()),
        limit_name: None,
        primary: None,
        secondary: Some(RateLimitWindow {
            used_percent: 99.9,
            window_minutes: Some(10_080),
            resets_at: None,
        }),
        credits: None,
        plan_type: None,
    });

    assert!(
        !state.is_weekly_limit_exhausted(),
        "Expected is_weekly_limit_exhausted() == false when secondary.used_percent < 100"
    );
}
