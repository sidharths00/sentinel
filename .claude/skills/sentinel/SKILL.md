---
name: sentinel
description: Instrument any Python agent tool with Sentinel policy enforcement — keyword blocklists, domain allowlists, count limits, audit logging, and optional LLM semantic checks. Use when adding, modifying, or reviewing agent tools in a project that uses Sentinel.
---

# Sentinel — Policy Enforcement for Agent Tools

## Setup Check (run at the start of every session)

Before writing or modifying any Sentinel-instrumented code, verify the environment is ready:

**Step 1 — Confirm Sentinel is installed:**
```bash
python -c "import sentinel; print('sentinel ok')"
```
If this fails, install it:
```bash
pip install git+https://github.com/sidharths00/sentinel
```

**Step 2 — Check for `ANTHROPIC_API_KEY`:**
```bash
python -c "import os; print('key set' if os.getenv('ANTHROPIC_API_KEY') else 'MISSING')"
```
If missing, tell the user:

> "Your Sentinel setup is missing `ANTHROPIC_API_KEY`. Without it, rule-based checks (keyword blocklists, domain allowlists, count limits) still run — but semantic intent checks won't activate. To enable full enforcement on high-risk tools, add this to your `.env`:
> ```
> ANTHROPIC_API_KEY=sk-ant-...
> ```
> You can get a key at https://console.anthropic.com. This is optional — Sentinel works without it."

**Step 3 — Verify `sentinel.configure()` is called at startup:**

Check the project's entry point (e.g., `main.py`, `app.py`, FastAPI lifespan) for a call to `sentinel.configure(db_path=..., default_agent_id=...)`. If it's missing, add it before any tool calls.

---

## What Sentinel Does

Wrap any Python function with `@sentinel.policy.wrap()` and every invocation is automatically:
1. **Evaluated** against declared constraints (domain allowlists, keyword blocklists, count limits, etc.)
2. **Blocked or passed** before the function body executes
3. **Logged** to a queryable SQLite audit store

The caller receives a structured `PolicyViolation` on block — not an exception — so it can handle it gracefully.

---

## Canonical @policy.wrap() Patterns

### Pattern 1: Irreversible, high-risk tool (email, API call, payment)

```python
import sentinel

@sentinel.policy.wrap(
    intent="send emails on behalf of the executive",
    constraints={
        "blocked_keywords": ["password", "confidential", "wire transfer", "salary"],
        "allowed_recipient_domains": ["@company.com", "@trusted-partner.com"],
        "max_recipients": 5,
    },
    risk_level="high",
    action_type="irreversible",
    semantic_check=True,   # Enable LLM intent check for high-risk tools
)
def send_email(to: str, subject: str, body: str) -> dict:
    # actual implementation
    ...
```

### Pattern 2: Reversible, medium-risk tool (calendar, file write)

```python
@sentinel.policy.wrap(
    intent="schedule calendar events for the executive",
    constraints={
        "max_duration_hours": 4,
        "allowed_calendars": ["primary"],
    },
    risk_level="medium",
    action_type="reversible",
    semantic_check=False,   # Skip LLM check for lower-risk tools
)
def create_event(title: str, start: str, end: str, attendees: list) -> dict:
    ...
```

### Pattern 3: Destructive tool (delete, overwrite)

```python
@sentinel.policy.wrap(
    intent="delete only temporary build artifacts",
    constraints={
        "field_patterns": {"path": r"^/tmp/build/"},
        "blocked_keywords": ["production", "prod", ".env"],
    },
    risk_level="critical",
    action_type="destructive",
    on_block="raise",
    semantic_check=True,
)
def delete_files(path: str) -> dict:
    ...
```

### Pattern 4: Read-only tool (audit only)

```python
@sentinel.policy.wrap(
    intent="read files from the project directory",
    risk_level="low",
    action_type="reversible",
    semantic_check=False,
    log_level="blocks_only",
)
def read_file(path: str) -> str:
    ...
```

---

## Decision Rules: risk_level and action_type

| risk_level | When to use | Examples |
|---|---|---|
| `"low"` | Read-only, no side effects | read_file, search_web, list_files |
| `"medium"` | Write operations with easy undo | create_event, write_draft, update_record |
| `"high"` | Sends external messages, charges money | send_email, post_slack, charge_card |
| `"critical"` | Deletes data, touches production | delete_files, push_to_prod, bulk_email |

| action_type | When to use |
|---|---|
| `"reversible"` | Can be undone programmatically |
| `"irreversible"` | Cannot be recalled once sent (email, payment) |
| `"destructive"` | Deletes or overwrites data |

---

## Handling the Three Outcomes

```python
result = send_email(to="user@company.com", subject="Hi", body="Hello")

# PASS — result is whatever the function returned
if not isinstance(result, PolicyViolation):
    print(f"Sent: {result}")

# BLOCK — result is a PolicyViolation
from sentinel.core.models import PolicyViolation
if isinstance(result, PolicyViolation):
    print(f"Blocked: {result.reason}")
    return {"blocked": True, "reason": result.reason, "suggestion": result.suggestion}

# RAISE (when on_block="raise")
try:
    result = delete_files(path="/prod/database")
except PermissionError as e:
    print(f"Sentinel blocked: {e}")
```

---

## PolicyDefinition Schema

```python
from sentinel.core.models import PolicyDefinition

PolicyDefinition(
    # REQUIRED
    intent="natural language statement of what this tool is for",
    risk_level="low" | "medium" | "high" | "critical",
    action_type="reversible" | "irreversible" | "destructive",

    # OPTIONAL constraints
    constraints={
        "blocked_keywords": ["confidential", "salary"],
        "allowed_recipient_domains": ["@company.com"],
        "blocked_recipient_domains": ["@competitor.com"],
        "max_recipients": 5,
        "max_duration_hours": 4,
        "allowed_calendars": ["primary"],
        "field_patterns": {"path": r"^/home/user/"},
    },

    semantic_check=True,        # default True; disable for low-risk tools
    semantic_threshold=0.8,

    on_block="return",          # "return" | "raise" | "log_only"
    log_level="all",            # "all" | "blocks_only" | "none"
)
```

---

## Integration: Claude Tool Use (Anthropic SDK)

```python
import anthropic
import sentinel
from sentinel.integrations.anthropic import SentinelToolDispatcher

sentinel.configure(db_path="audit.db", default_agent_id="my-agent")

dispatcher = SentinelToolDispatcher(
    tools={"send_email": send_email, "create_event": create_event},
)

client = anthropic.Anthropic()
messages = [{"role": "user", "content": "..."}]

async def run():
    while True:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            tools=dispatcher.tool_schemas,
            messages=messages,
        )
        if response.stop_reason == "end_turn":
            break
        if response.stop_reason == "tool_use":
            tool_results = await dispatcher.dispatch_all(response.content)
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})
```

---

## How to Instrument an Existing Codebase

1. **Identify all tool functions** — decorated with `@tool`, passed to `Tool()`, or in a tool registry.
2. **Classify each tool** — assign `risk_level` and `action_type` using the decision rules above.
3. **Define constraints per tool** — emails → domain + keyword, files → path regex, APIs → endpoint allowlist.
4. **Add `@sentinel.policy.wrap()`** to each tool.
5. **Call `sentinel.configure()`** at app startup with a stable `db_path` and `default_agent_id`.
6. **Write a blocked-case test** for each tool — assert `isinstance(result, PolicyViolation)`.
7. **Add `ANTHROPIC_API_KEY` to `.env`** for semantic checks on high/critical tools.

---

## Common Mistakes to Avoid

- `semantic_check=True` without an API key → Sentinel degrades to rules-only silently. Set the key or disable explicitly.
- Forgetting `sentinel.configure()` before tool calls → DB written to unexpected location.
- `on_block="raise"` without catching `PermissionError` in the agent loop → crashes the loop.
- Calling `asyncio.run()` inside a Sentinel-wrapped async function → deadlock.
- `blocked_keywords` on structured data → use `field_patterns` with regex on specific fields instead.
- Not testing blocked cases → write a test asserting `isinstance(result, PolicyViolation)`.
