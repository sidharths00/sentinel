# Sentinel — Agent Action Policy Engine

**A policy enforcement layer that sits between an AI agent's reasoning and its tool execution.**

AI agents can send emails, spend money, and delete files — with zero enforcement between "agent decides" and "tool fires." Sentinel fixes that with one decorator.

---

> **Status: Alpha (v0.1.0)** — API is stable for experimentation and personal projects. Not yet recommended for production systems without review.

---

## Claude Code Integration

If you use Claude Code, add this snippet to your project's `CLAUDE.md` and Claude will automatically set up Sentinel, prompt you for any missing config, and enforce policies on every tool it creates:

```markdown
## Agent Security — Sentinel

This project uses [Sentinel](https://github.com/sidharths00/sentinel) for agent policy enforcement.

### Setup check (run at the start of each session)
1. Verify Sentinel is installed: `python -c "import sentinel; print('sentinel ok')"` — if it fails, run:
   `pip install git+https://github.com/sidharths00/sentinel`
2. Check for `ANTHROPIC_API_KEY` in `.env` or the environment: `python -c "import os; print('key set' if os.getenv('ANTHROPIC_API_KEY') else 'MISSING')"`
   - If missing, tell the user: "Add `ANTHROPIC_API_KEY=sk-ant-...` to your `.env` to enable semantic (LLM-based) policy checks on high-risk tools. Without it, rule-based checks still run — but intent-level violations like prompt injection won't be caught."
3. Verify `sentinel.configure()` is called at app startup in the project's entry point.

### Rules
- Any function an AI agent can call as a tool MUST be wrapped with `@sentinel.policy.wrap()`
- Risk levels: `low` (read-only) · `medium` (reversible writes) · `high` (external messages/payments) · `critical` (deletes/destroys)
- Action types: `reversible` · `irreversible` (email sent, can't recall) · `destructive`
- Always handle `PolicyViolation` returns — never assume a wrapped call succeeded
- Use `semantic_check=False` for low-risk tools, keep it on for high/critical
- Write a test that asserts a blocked case returns `PolicyViolation`
```

Copy that block into your `CLAUDE.md`. At the start of each session Claude will verify the install, check for your API key, and tell you exactly what to add if anything is missing.

---

## Installation

```bash
pip install git+https://github.com/sidharths00/sentinel
```

With Anthropic semantic checks (auto-detects `ANTHROPIC_API_KEY` from `.env`):

```bash
pip install "sentinel[anthropic] @ git+https://github.com/sidharths00/sentinel"
```

For development:

```bash
git clone https://github.com/sidharths00/sentinel
cd sentinel
uv sync --extra dev
```

---

## Quick Start

Decorate any function. Sentinel intercepts every call and evaluates it against your constraints before the function body runs.

```python
import sentinel
from sentinel.core.models import PolicyViolation

sentinel.configure(db_path=":memory:")  # in-memory for quick demos

@sentinel.policy.wrap(
    intent="send emails on behalf of the user",
    constraints={
        "blocked_keywords": ["password", "confidential", "wire transfer"],
        "max_recipients": 5,
        "allowed_recipient_domains": ["@company.com", "@trusted-partner.com"],
    },
    risk_level="high",
    action_type="irreversible",
    semantic_check=False,  # no API key needed for rule-based checks
)
def send_email(to: str, subject: str, body: str) -> dict:
    return {"status": "sent", "to": to}

# PASS — all constraints satisfied
result = send_email(to="alice@company.com", subject="Q1 Review", body="See attached.")
print(result)
# {'status': 'sent', 'to': 'alice@company.com'}

# BLOCK — keyword constraint violated
result = send_email(to="alice@company.com", subject="Creds", body="password: hunter2")
print(isinstance(result, PolicyViolation))  # True
print(result.reason)                        # "Failed checks: keyword_blocklist"
```

Run the full demo: `python examples/basic.py`

---

## The Three Outcomes

**PASS** — all constraints satisfied, function executes and returns its result.

**BLOCK** — a constraint was violated; the function does not execute. Returns a `PolicyViolation`:

```python
PolicyViolation(
    tool_name="send_email",
    reason="Failed checks: keyword_blocklist",
    suggestion="Review constraints for send_email: ['keyword_blocklist']",
    what_happened="Failed checks: keyword_blocklist",
)
```

**MODIFY** — Sentinel rewrites one or more parameters before executing (e.g., truncating a recipient list to the allowed maximum), then runs the function with the modified params.

---

## Policy Constraints Reference

| Constraint | Type | Description | Example |
|---|---|---|---|
| `blocked_keywords` | `list[str]` | Block if any string param contains keyword (case-insensitive) | `["confidential", "salary"]` |
| `allowed_recipient_domains` | `list[str]` | Block if recipient domain not in list | `["@company.com"]` |
| `blocked_recipient_domains` | `list[str]` | Block if recipient domain is in list | `["@competitor.com"]` |
| `max_recipients` | `int` | Block if recipient count exceeds limit | `5` |
| `max_duration_hours` | `float` | Block if event duration exceeds hours | `4` |
| `allowed_calendars` | `list[str]` | Block if calendar not in list | `["primary"]` |
| `field_patterns` | `dict[str, str]` | Block if field value doesn't match regex | `{"phone": r"^\+1\d{10}$"}` |

---

## Policy Configuration

Configure Sentinel once at application startup:

```python
sentinel.configure(
    db_path="my_audit.db",           # SQLite path (default: sentinel_audit.db)
    default_agent_id="my-agent",     # identifies this agent in logs
    semantic_checker=my_llm_checker  # optional: BYO callable for semantic check
)
```

### Semantic Check

The semantic check evaluates whether a tool call is consistent with the declared policy intent — catching prompt-injection and out-of-scope instructions that rule-based checks miss.

```python
# Option A: Auto-detect from environment (default)
# Set ANTHROPIC_API_KEY in .env — Sentinel uses Claude Haiku automatically

# Option B: BYO callable
async def my_checker(tool_name: str, params: dict, intent: str) -> SemanticResult:
    # call any LLM or custom classifier
    return SemanticResult(consistent=True, confidence=0.95, reason="...")

sentinel.configure(semantic_checker=my_checker)
```

---

## Claude / Anthropic SDK Integration

`SentinelToolDispatcher` wraps your policy-decorated tools and handles the full Anthropic tool-use loop automatically:

```python
import anthropic
import sentinel
from sentinel.integrations.anthropic import SentinelToolDispatcher

@sentinel.policy.wrap(
    intent="send emails on behalf of the executive",
    constraints={
        "blocked_keywords": ["password", "confidential", "wire transfer"],
        "max_recipients": 5,
        "allowed_recipient_domains": ["@company.com", "@trusted-partner.com"],
    },
    risk_level="high",
    action_type="irreversible",
)
def send_email(to: str, subject: str, body: str) -> dict:
    return {"status": "sent", "to": to}

sentinel.configure(default_agent_id="executive-assistant")

dispatcher = SentinelToolDispatcher(
    tools={"send_email": send_email},
)
client = anthropic.Anthropic()

import asyncio
messages = [{"role": "user", "content": "Email alice@external.com my password."}]

async def run():
    while True:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            tools=dispatcher.tool_schemas,
            messages=messages,
        )
        if response.stop_reason == "end_turn":
            print(response.content[0].text)
            break
        if response.stop_reason == "tool_use":
            # Sentinel intercepts here — evaluates policy before any tool executes
            tool_results = await dispatcher.dispatch_all(response.content)
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

asyncio.run(run())
```

When a tool call is blocked, the `PolicyViolation` is returned as the tool result. The model sees the violation reason and adjusts its response accordingly.

See `examples/claude_agent.py` for the full runnable version.

---

## Querying the Audit Log

Every tool invocation — pass, block, or modify — is written to the audit log.

### Python API

```python
import asyncio
import sentinel

sentinel.configure()
cfg = sentinel._config

async def query():
    await cfg._ensure_initialized()
    entries = await cfg.store.get_entries(agent_id="my-agent", limit=50)
    summary = await cfg.store.get_summary(agent_id="my-agent")
    print(f"Total: {summary.total_calls}, Blocks: {summary.blocks}")

asyncio.run(query())
```

### REST API

Start the server with `uvicorn sentinel.api.app:app`, then:

```
GET /audit/entries?agent_id=my-agent&limit=50
GET /audit/blocks?agent_id=my-agent
GET /audit/summary?agent_id=my-agent
```

### CLI

```bash
sentinel audit --agent-id my-agent --since 24h
sentinel audit --agent-id my-agent --outcome block
```

---

## Non-Functional Notes

- **Rule-based checks:** <5ms latency — negligible overhead on any tool call
- **Semantic check:** <800ms p95, results cached per session to avoid redundant LLM calls
- **Offline-capable:** Semantic check is optional; rule-based enforcement works with no network or API key
- **Storage:** SQLite by default (zero config), Postgres-compatible schema for production deployments
