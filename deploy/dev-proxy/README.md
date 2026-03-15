# Codex Dev Proxy

> **DEVELOPMENT USE ONLY.** Never expose this proxy on a public interface.

A lightweight local HTTP proxy that sits between Codex and `api.openai.com`, transparently forwarding all traffic but intercepting `429 usage_limit_reached` responses and replacing them with a `503 server_is_overloaded` response that Codex treats as a **retryable transient error** — so your session keeps running even when the weekly limit is at 0%.

---

## How It Works

```
Codex TUI
    │  POST /v1/responses
    ▼
Dev Proxy (127.0.0.1:8080)
    │  Forward request unchanged
    ▼
api.openai.com
    │  HTTP 429 { "error_type": "usage_limit_reached" }
    ▼
Dev Proxy ← intercepts 429, rewrites to 500 InternalServerError
    │  HTTP 500 { "code": "internal_server_error" }
    ▼
Codex TUI ← treats as InternalServerError (retryable), session continues
```

The `InternalServerError` error in Codex is retryable (`is_retryable() == true`), so Codex will back off and retry the turn rather than terminating the session.

The mapping in `api_bridge.rs` is:

| HTTP Status | Body | CodexErr | Retryable? |
|-------------|------|----------|------------|
| 429 | `error_type: usage_limit_reached` | `UsageLimitReached` | No |
| 429 | any other | `RetryLimit` | No |
| 503 | `code: server_is_overloaded` | `ServerOverloaded` | No |
| **500** | **any** | **`InternalServerError`** | **Yes ✓** |
| other | any | `UnexpectedStatus` | Yes ✓ |

We rewrite to `500` because it is the cleanest retryable error that doesn't trigger any special handling.

---

## Quick Start

### 1. Start the proxy

```bash
python3 deploy/dev-proxy/proxy.py --port 8080
```

### 2. Configure Codex to use the proxy

Add to `~/.codex/config.toml`:

```toml
openai_base_url = "http://127.0.0.1:8080/v1"
```

Or set the environment variable (deprecated but still works):

```bash
export OPENAI_BASE_URL="http://127.0.0.1:8080/v1"
```

### 3. Run Codex normally

```bash
codex
```

The proxy will log when it intercepts a rate limit response:

```
⚡ [dev-proxy] Intercepted 429 usage_limit_reached → replacing with 503 server_is_overloaded
```

---

## Options

| Flag | Default | Description |
|------|---------|-------------|
| `--port` | `8080` | Local port to listen on |
| `--upstream` | `https://api.openai.com` | Upstream API base URL |

---

## Combining with Hybrid Mode

When using hybrid mode with your DGX Spark cluster, you do **not** need this proxy — the hybrid router automatically falls back to local vLLM when the weekly limit is exhausted. This proxy is only needed if you want to keep using OpenAI models directly after the limit is hit (e.g., for testing purposes).

---

## Why This Works

OpenAI's server returns `429` with `error_type: "usage_limit_reached"` when the weekly limit is exhausted. Codex maps this to `CodexErr::UsageLimitReached` which is **not retryable** and terminates the session.

By rewriting it to `503` with `code: "server_is_overloaded"`, Codex maps it to `CodexErr::ServerOverloaded` which **is retryable**. Codex will back off (exponential backoff) and retry the turn. If the limit truly resets, the next retry will succeed. If not, it will keep retrying until the turn is cancelled.

---

## Security Notes

- The proxy only binds to `127.0.0.1` — it is not accessible from other machines.
- Your OpenAI auth token is forwarded to the upstream unchanged.
- This is a development tool and should **never** be used in production.
