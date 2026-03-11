# Sentinel — Agent Action Policy Engine

**A policy enforcement layer that sits between an AI agent's reasoning and its tool execution.**

---

## What It Does

When an agent invokes a tool, Sentinel intercepts the call before execution and evaluates it against declared policy constraints — domain allowlists, keyword blocklists, count limits, and more. Every call returns one of three outcomes: **PASS** (executes normally), **BLOCK** (returns a structured `PolicyViolation`), or **MODIFY** (rewrites parameters before execution). Every invocation is written to a queryable audit log, giving you a full record of what your agent attempted and why it was allowed or denied.

---

## Installation

```bash
uv pip install sentinel
```

For development:

```bash
git clone <repo>
cd sentinel
uv sync --extra dev
```

---

## Quick Start — `@policy.wrap`

Decorate any Python function to enforce policy constraints before the function body executes:

```python
import sentinel

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
    # actual send logic
    ...
```

### The Three Outcomes

**PASS** — all constraints satisfied, function executes and returns its result:

```python
result = send_email(
    to="alice@company.com",
    subject="Q1 Review",
    body="See attached agenda.",
)
# result == {"status": "sent", ...}  (your function's return value)
```

**BLOCK** — a constraint was violated, function does not execute:

```python
result = send_email(
    to="attacker@external.com",
    subject="Credentials",
    body="Here is the password: hunter2",
)
# result == PolicyViolation(
#     outcome="block",
#     rule="blocked_keywords",
#     message="Parameter 'body' contains blocked keyword: 'password'",
#     tool_name="send_email",
#     params={...},
# )
```

**MODIFY** — Sentinel rewrites one or more parameters before executing (e.g., stripping a disallowed BCC field, truncating a recipient list to the allowed maximum):

```python
result = send_email(
    to="alice@company.com",
    subject="Update",
    body="All good.",
    # Sentinel may rewrite params silently, then call the real function
)
# result == {"status": "sent", ...}  (executed with modified params)
```

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
    db_path="my_audit.db",          # SQLite path (default: sentinel_audit.db)
    default_agent_id="my-agent",    # identifies this agent in logs
    semantic_checker=my_llm_checker # optional: BYO callable for semantic check
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

# 1. Declare your policy-wrapped tools
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
    ...

@sentinel.policy.wrap(
    intent="schedule calendar events for the executive",
    constraints={
        "max_duration_hours": 4,
        "allowed_calendars": ["primary", "work"],
    },
    risk_level="medium",
    action_type="reversible",
)
def create_calendar_event(title: str, start: str, end: str, calendar: str) -> dict:
    ...

# 2. Configure Sentinel
sentinel.configure(default_agent_id="executive-assistant")

# 3. Build the dispatcher and client
dispatcher = SentinelToolDispatcher(tools=[send_email, create_calendar_event])
client = anthropic.Anthropic()

# 4. Run the agentic loop
messages = [{"role": "user", "content": "Schedule a 1-hour sync with the team tomorrow."}]

while True:
    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=1024,
        tools=dispatcher.tool_schemas,
        messages=messages,
    )

    if response.stop_reason == "end_turn":
        print(response.content[0].text)
        break

    if response.stop_reason == "tool_use":
        # Sentinel intercepts here — evaluates policy before any tool executes
        tool_results = dispatcher.dispatch(response.content)

        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})
        # loop continues — blocked calls return PolicyViolation as tool result
```

When a tool call is blocked, the `PolicyViolation` is returned as the tool result. The model sees the violation reason and can adjust its behavior or report back to the user.

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
