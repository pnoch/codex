# Hybrid Mode: Smart Local + OpenAI Routing

Hybrid mode is a cost-optimization and quality-maximization feature that intelligently routes each Codex turn to one of two models:

- **Local model** (vLLM on your DGX Spark cluster) — handles routine, high-volume tasks at zero token cost.
- **Supervisor model** (e.g., `gpt-5.3-codex` via OpenAI) — handles complex, high-stakes tasks where state-of-the-art reasoning is required.

---

## Why Hybrid Mode?

Running Codex entirely on OpenAI is expensive because the vast majority of turns in a typical session are routine: applying patches, running tests, checking git status, renaming files. These tasks do not need a frontier model. However, some turns genuinely benefit from the best available intelligence: designing a new architecture, debugging a subtle race condition, or performing a security audit.

Hybrid mode gives you the best of both worlds:

| Task Type | Example | Routed To | Cost |
|-----------|---------|-----------|------|
| File edit | "Apply this patch" | Local vLLM | Free |
| Shell command | "Run cargo test" | Local vLLM | Free |
| Git operation | "Commit with message X" | Local vLLM | Free |
| Architecture design | "Design a multi-tenant auth system" | OpenAI supervisor | Tokens |
| Complex debugging | "Why is this causing a deadlock?" | OpenAI supervisor | Tokens |
| Security audit | "Review this for vulnerabilities" | OpenAI supervisor | Tokens |
| Explicit request | "@supervisor review my code" | OpenAI supervisor | Tokens |

In practice, **80–90% of turns are routed locally**, reducing OpenAI token usage by a similar proportion.

---

## How It Works

### 1. Dual Client Initialization

When hybrid mode is enabled, Codex initializes **two** model clients at session start:

- `model_client` — points to your local vLLM cluster (via the `vllm` provider, `192.168.100.10:8000`).
- `supervisor_client` — points to OpenAI (via the `openai` provider, using your `OPENAI_API_KEY`).

### 2. Turn Classification

At the start of every turn, the `HybridRouter` computes a **complexity score** (0.0 – 1.0) for the current prompt using lightweight heuristics:

| Signal | Score Change |
|--------|-------------|
| Escalation keyword detected (e.g., "architect", "debug", "security") | +0.35 |
| Prompt length > 500 tokens | +0.15 |
| Conversation history > 30 turns | +0.10 |
| Local model failed 2+ consecutive turns | +0.30 |
| Routine keyword detected (e.g., "cargo test", "git commit") | −0.20 |
| User explicitly wrote `@supervisor` or `@openai` | Force escalate |

### 3. Routing Decision

If `score ≥ escalation_threshold` (default: `0.65`), the turn is escalated to the supervisor. Otherwise it goes to the local model.

When escalating, the TUI displays:
```
⚡ Hybrid Mode: Escalating architectural/design task to gpt-5.3-codex (score: 0.82, threshold: 0.65).
```

### 4. Failure Recovery

If the local model fails (returns an error or empty response), the failure counter increments. After **2 consecutive failures**, the next turn is automatically escalated to the supervisor regardless of its complexity score. The counter resets on any successful local turn.

---

## Configuration

### `~/.codex/config.toml`

```toml
# Enable hybrid mode
hybrid_mode = true

# The supervisor model for complex tasks (default: "gpt-5.3-codex")
hybrid_supervisor_model = "gpt-5.3-codex"

# Provider for the supervisor model (default: "openai")
hybrid_supervisor_provider_id = "openai"

# Complexity threshold for escalation, 0.0-1.0 (default: 0.65)
# Lower = escalate more often; Higher = escalate less often
hybrid_escalation_threshold = 0.65

# The local model (set via oss_provider + model)
oss_provider = "vllm"
model = "meta-llama/Meta-Llama-3-70B-Instruct"
```

### Environment Variables

```bash
# Required for the supervisor (OpenAI) client
export OPENAI_API_KEY="sk-..."

# Required for the local (vLLM) client
export CODEX_VLLM_BASE_URL="http://192.168.100.10:8000/v1"
# Or for multi-node load balancing:
export CODEX_VLLM_CLUSTER_NODES="192.168.100.10:8000,192.168.100.11:8000,192.168.100.12:8000,192.168.100.13:8000"
```

---

## CLI Usage

```bash
# Enable hybrid mode with defaults
codex --oss --hybrid

# Specify a different supervisor model
codex --oss --hybrid --supervisor-model gpt-4.1

# Lower the threshold to escalate more aggressively (0.5 = escalate ~50% of turns)
codex --oss --hybrid --escalation-threshold 0.5

# Force a specific turn to use the supervisor by mentioning it in your message
codex --oss --hybrid
> @supervisor please review this authentication module for security vulnerabilities
```

---

## Explicit Supervisor Invocation

You can always force a turn to use the supervisor model by including one of these phrases in your message:

- `@supervisor`
- `@openai`
- `@gpt`
- `use openai`
- `use supervisor`
- `use the supervisor`
- `escalate`
- `ask openai`

Example:
```
@supervisor I need you to design the database schema for our multi-tenant SaaS application.
```

---

## DGX Spark Cluster Setup

See [dgx-spark-setup.md](./dgx-spark-setup.md) for instructions on deploying vLLM on your 4 DGX Spark units.

The recommended model for hybrid mode is **Llama 3 70B Instruct** for the local model, which handles routine coding tasks well while being fast enough to not introduce noticeable latency.

For the supervisor, `gpt-5.3-codex` is the default and recommended choice as it has been specifically optimized for software engineering tasks.

---

## Architecture Diagram

```
User Prompt
     │
     ▼
┌─────────────────────────────────────┐
│           HybridRouter              │
│  classify_turn_complexity(prompt)   │
│                                     │
│  score = 0.0 ──────────────── 1.0   │
│                    │                │
│           threshold: 0.65           │
└─────────────────────────────────────┘
          │                    │
    score < 0.65          score ≥ 0.65
          │                    │
          ▼                    ▼
  ┌──────────────┐    ┌──────────────────┐
  │  Local vLLM  │    │  OpenAI          │
  │  DGX Spark   │    │  Supervisor      │
  │  (Free)      │    │  (gpt-5.3-codex) │
  └──────────────┘    └──────────────────┘
          │                    │
          └────────┬───────────┘
                   ▼
            Response to User
```
