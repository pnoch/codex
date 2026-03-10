use std::collections::HashMap;
use std::sync::Arc;

use crate::AuthManager;
use crate::RolloutRecorder;
use crate::agent::AgentControl;
use crate::analytics_client::AnalyticsEventsClient;
use crate::client::ModelClient;
use crate::config::StartedNetworkProxy;
use crate::exec_policy::ExecPolicyManager;
use crate::file_watcher::FileWatcher;
use crate::hybrid_router::HybridRouter;
use crate::mcp::McpManager;
use crate::mcp_connection_manager::McpConnectionManager;
use crate::models_manager::manager::ModelsManager;
use crate::plugins::PluginsManager;
use crate::skills::SkillsManager;
use crate::state_db::StateDbHandle;
use crate::tools::code_mode::CodeModeService;
use crate::tools::network_approval::NetworkApprovalService;
use crate::tools::runtimes::ExecveSessionApproval;
use crate::tools::sandboxing::ApprovalStore;
use crate::unified_exec::UnifiedExecProcessManager;
use codex_hooks::Hooks;
use codex_otel::SessionTelemetry;
use codex_utils_absolute_path::AbsolutePathBuf;
use std::path::PathBuf;
use tokio::sync::Mutex;
use tokio::sync::RwLock;
use tokio::sync::watch;
use tokio_util::sync::CancellationToken;

pub(crate) struct SessionServices {
    pub(crate) mcp_connection_manager: Arc<RwLock<McpConnectionManager>>,
    pub(crate) mcp_startup_cancellation_token: Mutex<CancellationToken>,
    pub(crate) unified_exec_manager: UnifiedExecProcessManager,
    #[cfg_attr(not(unix), allow(dead_code))]
    pub(crate) shell_zsh_path: Option<PathBuf>,
    #[cfg_attr(not(unix), allow(dead_code))]
    pub(crate) main_execve_wrapper_exe: Option<PathBuf>,
    pub(crate) analytics_events_client: AnalyticsEventsClient,
    pub(crate) hooks: Hooks,
    pub(crate) rollout: Mutex<Option<RolloutRecorder>>,
    pub(crate) user_shell: Arc<crate::shell::Shell>,
    pub(crate) shell_snapshot_tx: watch::Sender<Option<Arc<crate::shell_snapshot::ShellSnapshot>>>,
    pub(crate) show_raw_agent_reasoning: bool,
    pub(crate) exec_policy: ExecPolicyManager,
    pub(crate) auth_manager: Arc<AuthManager>,
    pub(crate) models_manager: Arc<ModelsManager>,
    pub(crate) session_telemetry: SessionTelemetry,
    pub(crate) tool_approvals: Mutex<ApprovalStore>,
    #[cfg_attr(not(unix), allow(dead_code))]
    pub(crate) execve_session_approvals: RwLock<HashMap<AbsolutePathBuf, ExecveSessionApproval>>,
    pub(crate) skills_manager: Arc<SkillsManager>,
    pub(crate) plugins_manager: Arc<PluginsManager>,
    pub(crate) mcp_manager: Arc<McpManager>,
    pub(crate) file_watcher: Arc<FileWatcher>,
    pub(crate) agent_control: AgentControl,
    pub(crate) network_proxy: Option<StartedNetworkProxy>,
    pub(crate) network_approval: Arc<NetworkApprovalService>,
    pub(crate) state_db: Option<StateDbHandle>,
    /// Session-scoped model client shared across turns.
    /// In hybrid mode this is the **local** client (vLLM on DGX Spark).
    pub(crate) model_client: ModelClient,
    pub(crate) code_mode_service: CodeModeService,
    /// Optional supervisor model client used in hybrid mode.
    ///
    /// When `Some`, the [`HybridRouter`] may redirect complex turns to this
    /// client (backed by an OpenAI model) while routine turns use
    /// `model_client`.  `None` when hybrid mode is disabled.
    ///
    /// Wrapped in `Mutex` so it can be mutated through `Arc<Session>`.
    pub(crate) supervisor_client: Mutex<Option<ModelClient>>,
    /// Hybrid router that classifies turn complexity and decides which client
    /// to use.  `None` when hybrid mode is disabled.
    ///
    /// Wrapped in `Mutex` so it can be mutated through `Arc<Session>` from
    /// the Op dispatch loop.
    pub(crate) hybrid_router: Mutex<Option<HybridRouter>>,
}
