# Codex Hybrid Mode Architecture

## Overview

The Hybrid Mode allows Codex to intelligently route tasks between a local, cost-effective model (like vLLM on DGX Spark) and a highly capable remote model (like OpenAI's `gpt-5.3-codex`). 

The goal is to save tokens and improve efficiency by letting the local model handle routine planning, file editing, and shell execution, while escalating complex reasoning, critical architecture decisions, and difficult debugging tasks to the remote supervisor model.

## Core Concepts

1. **Dual Model Clients**: The `SessionServices` will maintain two `ModelClient` instances:
   - `local_client`: The primary client connected to the local DGX Spark cluster (via the `vllm` provider).
   - `remote_client`: The supervisor client connected to OpenAI.

2. **Task Classifier**: A lightweight heuristic engine that analyzes the current `TurnContext` and the user's prompt to determine the complexity of the task.
   - **Low Complexity**: Routine file edits, running tests, simple shell commands, git operations.
   - **High Complexity**: "Design an architecture", "Debug this obscure memory leak", "Refactor the entire module", or when the local model has failed multiple times in a row.

3. **Dynamic Turn Routing**: Inside `run_sampling_request`, before sending the prompt to the model, the router decides which client to use for the current turn.

## Configuration Changes

We will introduce new fields to `ConfigToml` and `ConfigProfile`:

```toml
[profile.default]
# Enable hybrid mode
hybrid_mode = true

# The local model for routine tasks
local_model = "meta-llama/Meta-Llama-3-70B-Instruct"
local_provider = "vllm"

# The remote supervisor model for complex tasks
supervisor_model = "gpt-5.3-codex"
supervisor_provider = "openai"

# Threshold for escalation (0.0 to 1.0)
escalation_threshold = 0.7
```

## Implementation Steps

### 1. Update Configuration Structures
- Add `hybrid_mode`, `local_model`, `local_provider`, `supervisor_model`, and `supervisor_provider` to `ConfigToml` and `ConfigProfile`.
- Update `resolve_oss_provider` to handle hybrid mode resolution.

### 2. Dual Client Initialization
- Modify `SessionServices` to hold `supervisor_client: Option<ModelClient>`.
- In `Session::new`, if `hybrid_mode` is enabled, initialize both the standard `model_client` (pointing to the local provider) and the `supervisor_client` (pointing to OpenAI).

### 3. Task Classifier (`hybrid_router.rs`)
- Create a new module `codex-rs/core/src/hybrid_router.rs`.
- Implement `fn classify_turn_complexity(prompt: &Prompt, history: &[ResponseItem]) -> f32`.
- The classifier will look for keywords (e.g., "design", "architect", "debug", "why is this failing") and analyze the size of the context.

### 4. Intercepting the Turn (`codex.rs`)
- In `try_run_sampling_request`, invoke the classifier.
- If `complexity > escalation_threshold`, swap the `client_session` to use the `supervisor_client` for that specific turn.
- Emit a UI event (`EventMsg::Info`) to notify the user: *"Escalating complex task to supervisor model (gpt-5.3-codex)..."*

### 5. TUI Integration
- Update the TUI to show a "Hybrid" indicator when the mode is active.
- Add a `--hybrid` CLI flag to easily toggle the mode.

## Benefits

- **Cost Savings**: 80-90% of routine turns (like "run cargo test" or "apply this patch") are handled locally for free.
- **High Quality**: Critical decisions still benefit from state-of-the-art reasoning.
- **Seamless Experience**: The user doesn't have to manually switch models; the system adapts dynamically.
