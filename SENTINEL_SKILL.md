# Sentinel Skill — Instrument Any Python Agent with Policy Enforcement

## What Sentinel Does

Sentinel is a policy enforcement layer for AI agent tool calls. Wrap any Python function with `@sentinel.policy.wrap()` and every invocation is automatically:
1. **Evaluated** against declared constraints (domain allowlists, keyword blocklists, count limits, etc.)
2. **Blocked or passed** before the function body executes
3. **Logged** to a queryable SQLite audit store

The agent receives a structured `PolicyViolation` on block — not an exception — so it can handle it gracefully.

---

## Installation

```bash
# In any Python project using uv:
uv add sentinel

# Or with pip:
pip install sentinel

# For projects that use the Anthropic SDK semantic check:
# Set ANTHROPIC_API_KEY in .env — Sentinel auto-discovers it
```

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
        "field_patterns": {"path": r"^/tmp/build/"},  # Only /tmp/build/ allowed
        "blocked_keywords": ["production", "prod", ".env"],
    },
    risk_level="critical",
    action_type="destructive",
    on_block="raise",     # Raise exception instead of returning violation
    semantic_check=True,
)
def delete_files(path: str) -> dict:
    ...
```

### Pattern 4: Read-only tool (no enforcement needed, just audit)

```python
@sentinel.policy.wrap(
    intent="read files from the project directory",
    risk_level="low",
    action_type="reversible",
    semantic_check=False,
    log_level="blocks_only",  # Only log if somehow blocked
)
def read_file(path: str) -> str:
    ...
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

    # OPTIONAL: rule-based constraints (dict)
    constraints={
        # String scanning (case-insensitive, across ALL string params)
        "blocked_keywords": ["confidential", "salary", "wire transfer"],

        # Email/domain checks (applied to fields named: to, cc, bcc, recipient, email)
        "allowed_recipient_domains": ["@company.com"],   # allowlist
        "blocked_recipient_domains": ["@competitor.com"],  # blocklist

        # Count limits (applied to list fields named: to, cc, bcc, recipients, attendees)
        "max_recipients": 5,

        # Duration (requires start and end params in ISO 8601 format)
        "max_duration_hours": 4,

        # Calendar (applied to calendar param)
        "allowed_calendars": ["primary"],

        # Regex on specific fields
        "field_patterns": {
            "phone": r"^\+1\d{10}$",
            "path": r"^/home/user/",
        },
    },

    # OPTIONAL: semantic (LLM) check
    semantic_check=True,        # default True; disable for low-risk tools
    semantic_threshold=0.8,     # confidence required to block (0.0-1.0)

    # OPTIONAL: behavior on block
    on_block="return",          # default: return PolicyViolation to caller
    # on_block="raise"          # raise PermissionError
    # on_block="log_only"       # execute anyway, but log the violation

    # OPTIONAL: behavior on modify (V2, not yet implemented)
    on_modify="auto",

    # OPTIONAL: logging
    log_level="all",            # default: log all invocations
    # log_level="blocks_only"   # only log blocks
    # log_level="none"          # no logging
)
```

---

## Decision Rules: risk_level and action_type

### risk_level

| Level | When to use | Examples |
|---|---|---|
| `"low"` | Read-only, no side effects, fully reversible | read_file, search_web, list_files |
| `"medium"` | Write operations with easy undo | create_event, write_draft, update_record |
| `"high"` | Sends external messages, charges money, hard to undo | send_email, post_slack, charge_card |
| `"critical"` | Deletes data, touches production, mass operations | delete_files, push_to_prod, bulk_email |

**Rule of thumb:** If a mistake requires human intervention to fix → `"high"`. If it can't be fixed → `"critical"`.

### action_type

| Type | When to use |
|---|---|
| `"reversible"` | Can be undone programmatically (delete event, edit document) |
| `"irreversible"` | Cannot be recalled once sent (email sent, payment processed) |
| `"destructive"` | Deletes or overwrites data, no undo |

**Rule of thumb:** Anything external (email, API call to third party, payment) is `"irreversible"`. Anything that deletes state is `"destructive"`.

---

## Handling the Three Outcomes

```python
result = send_email(to="user@company.com", subject="Hi", body="Hello")

# Outcome 1: PASS — result is whatever the function returned
if isinstance(result, dict) and "status" in result:
    print(f"Sent: {result}")

# Outcome 2: BLOCK — result is a PolicyViolation
from sentinel.core.models import PolicyViolation
if isinstance(result, PolicyViolation):
    print(f"Blocked: {result.reason}")
    print(f"Suggestion: {result.suggestion}")
    # Pass back to agent as a tool_result with blocked=True
    return {"blocked": True, "reason": result.reason, "suggestion": result.suggestion}

# Outcome 3: RAISE (when on_block="raise")
try:
    result = delete_files(path="/prod/database")
except PermissionError as e:
    print(f"Sentinel blocked: {e}")
```

---

## Integration Pattern: Claude Tool Use (Anthropic SDK)

Use `SentinelToolDispatcher` to intercept Claude's `tool_use` blocks:

```python
import anthropic
import sentinel
from sentinel.integrations.anthropic import SentinelToolDispatcher
from sentinel.core.models import PolicyDefinition

# Configure Sentinel
sentinel.configure(
    db_path="audit.db",
    default_agent_id="my-agent",
    # semantic_checker auto-discovers ANTHROPIC_API_KEY from .env
)

# Define your tools with policies
def send_email(to: str, subject: str, body: str) -> dict:
    """Send an email."""
    return {"status": "sent"}

def create_event(title: str, start: str, end: str, attendees: list) -> dict:
    """Create a calendar event."""
    return {"status": "created"}

policies = {
    "send_email": PolicyDefinition(
        intent="send emails on behalf of the executive",
        risk_level="high",
        action_type="irreversible",
        constraints={
            "blocked_keywords": ["confidential", "password"],
            "max_recipients": 5,
        },
        semantic_check=False,  # set True for production
    ),
    "create_event": PolicyDefinition(
        intent="schedule calendar events",
        risk_level="medium",
        action_type="reversible",
        constraints={"max_duration_hours": 8},
        semantic_check=False,
    ),
}

# Create dispatcher
dispatcher = SentinelToolDispatcher(
    tools={"send_email": send_email, "create_event": create_event},
    policies=policies,
)

# Agent loop
client = anthropic.Anthropic()
messages = [{"role": "user", "content": "Schedule a meeting with sarah@company.com tomorrow at 2pm"}]

while True:
    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=1024,
        tools=dispatcher.tool_schemas,   # Sentinel-generated schemas
        messages=messages,
    )
    if response.stop_reason == "end_turn":
        break
    if response.stop_reason == "tool_use":
        import asyncio
        tool_results = asyncio.run(dispatcher.dispatch_all(response.content))
        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})
```

---

## Integration Pattern: Direct Function Wrapping (Framework-Agnostic)

Works with any framework — LangChain, AutoGen, custom loops:

```python
import sentinel

# One-time config (at app startup)
sentinel.configure(
    db_path="sentinel_audit.db",
    default_agent_id="my-agent",
)

# Decorate your tools at definition time
@sentinel.policy.wrap(
    intent="post messages to Slack",
    constraints={"blocked_keywords": ["@here", "@channel", "confidential"]},
    risk_level="high",
    action_type="irreversible",
    semantic_check=False,
)
def post_slack(channel: str, message: str) -> dict:
    ...

# Call normally — Sentinel intercepts transparently
result = post_slack(channel="#general", message="Hello everyone!")
```

---

## Integration Pattern: LangChain (V1.1)

```python
from sentinel.integrations.langchain import SentinelTool
from langchain.tools import Tool
from sentinel.core.models import PolicyDefinition

send_email_tool = SentinelTool(
    tool=Tool(name="send_email", func=send_email, description="Send an email"),
    policy=PolicyDefinition(
        intent="send emails on behalf of the user",
        risk_level="high",
        action_type="irreversible",
        constraints={"blocked_keywords": ["confidential"]},
    ),
)
```

---

## Querying the Audit Log

```python
import asyncio
import sentinel

sentinel.configure(db_path="sentinel_audit.db", default_agent_id="my-agent")

async def audit():
    cfg = sentinel._config
    await cfg._ensure_initialized()
    store = cfg.store

    # All entries for agent in last 24h
    entries = await store.get_entries(agent_id="my-agent", limit=100)

    # Only blocked calls
    blocks = await store.get_blocks(agent_id="my-agent")

    # Summary stats
    summary = await store.get_summary(agent_id="my-agent")
    print(f"Total: {summary.total_calls}, Blocks: {summary.blocks}, Passes: {summary.passes}")
    print(f"Most-blocked tools: {summary.top_blocked_tools}")

asyncio.run(audit())
```

**REST API** (run with `uvicorn sentinel.api.app:app`):
```
GET /audit/entries?agent_id=my-agent&limit=50
GET /audit/blocks?agent_id=my-agent
GET /audit/summary?agent_id=my-agent
```

**CLI:**
```bash
sentinel audit --agent-id my-agent --since 24h
sentinel audit --agent-id my-agent --outcome block
```

---

## Semantic Check Configuration

```python
# Option A: Auto (default) — set ANTHROPIC_API_KEY in .env
# Sentinel uses Claude Haiku for semantic intent checks automatically
sentinel.configure()

# Option B: Custom callable (BYO LLM, any provider)
from sentinel.core.semantic import SemanticResult

async def my_openai_checker(tool_name: str, params: dict, intent: str) -> SemanticResult:
    # call OpenAI, Ollama, or any other LLM
    response = await openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": f"Is {tool_name}({params}) consistent with: {intent}? JSON only: {{consistent, confidence, reason}}"}],
    )
    import json
    data = json.loads(response.choices[0].message.content)
    return SemanticResult(consistent=data["consistent"], confidence=data["confidence"], reason=data["reason"])

sentinel.configure(semantic_checker=my_openai_checker)

# Option C: Disable entirely (rules-only mode)
sentinel.configure()  # No ANTHROPIC_API_KEY set = rules-only automatically
# Or per-tool: semantic_check=False in @policy.wrap()
```

---

## Worked Example: Executive Assistant

Full working implementation covering all acceptance criteria from the Sentinel PRD:

```python
import sentinel
from sentinel.integrations.anthropic import SentinelToolDispatcher
from sentinel.core.models import PolicyDefinition
import anthropic
import asyncio

# Setup
sentinel.configure(db_path="exec_assistant.db", default_agent_id="exec-assistant")

# Tool 1: Send email (high-risk, irreversible)
def send_email(to: str, subject: str, body: str) -> dict:
    """Send an email on behalf of the executive."""
    print(f"SENDING: {subject} → {to}")
    return {"status": "sent", "message_id": "msg_123"}

# Tool 2: Create calendar event (medium-risk, reversible)
def create_event(title: str, start: str, end: str, attendees: list) -> dict:
    """Create a calendar event."""
    print(f"CREATING EVENT: {title}")
    return {"status": "created", "event_id": "evt_456"}

# Policies
policies = {
    "send_email": PolicyDefinition(
        intent="send emails on behalf of the executive",
        risk_level="high",
        action_type="irreversible",
        constraints={
            "blocked_keywords": ["password", "confidential", "wire transfer", "salary"],
            "max_recipients": 5,
            "allowed_recipient_domains": ["@company.com", "@trusted-partner.com"],
        },
        semantic_check=True,  # Requires ANTHROPIC_API_KEY
    ),
    "create_event": PolicyDefinition(
        intent="schedule calendar events for the executive",
        risk_level="medium",
        action_type="reversible",
        constraints={"max_duration_hours": 4, "allowed_calendars": ["primary"]},
        semantic_check=False,
    ),
}

# Dispatcher
dispatcher = SentinelToolDispatcher(
    tools={"send_email": send_email, "create_event": create_event},
    policies=policies,
)

# Agent loop
async def run_agent(user_message: str) -> None:
    client = anthropic.Anthropic()
    messages = [{"role": "user", "content": user_message}]

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
            tool_results = await dispatcher.dispatch_all(response.content)
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

# Test: Legitimate request — passes policy
asyncio.run(run_agent(
    "Schedule a 1hr meeting with sarah@company.com tomorrow at 2pm and send her a confirmation"
))

# Test: Blocked request — keyword violation
asyncio.run(run_agent(
    "Send an email to all@company.com with the confidential salary data attached"
))
```

---

## Common Mistakes to Avoid

### 1. Setting `semantic_check=True` without an API key
Sentinel degrades gracefully (rules-only), but you'll miss intent-level violations. Always set `ANTHROPIC_API_KEY` in `.env` or configure a checker explicitly.

### 2. Forgetting to call `sentinel.configure()` before tool calls
The default config uses `"sentinel_audit.db"` in the current directory. Call `sentinel.configure(db_path=...)` at app startup to control where the DB lives.

### 3. Using `on_block="raise"` without catching `PermissionError` in the agent loop
If an agent loop doesn't catch `PermissionError`, Sentinel will crash the whole loop. Use `on_block="return"` (default) and check for `PolicyViolation` in the result, or wrap the agent loop in a try/except.

### 4. Wrapping async tools as sync
If your tool function is `async def`, Sentinel automatically uses the async wrapper. Don't call `asyncio.run()` inside a Sentinel-wrapped async function — it will deadlock.

### 5. Over-using `blocked_keywords` for structured data
Keywords scan ALL string values in params. If your API returns JSON strings with legitimate uses of a word, use `field_patterns` with regex on specific fields instead.

### 6. Not testing blocked cases
Always test that your constraints actually block what they should. Create a test that passes a blocked keyword and asserts `isinstance(result, PolicyViolation)`.

```python
def test_keyword_blocked():
    result = send_email(to="user@co.com", subject="Hi", body="wire transfer details")
    from sentinel.core.models import PolicyViolation
    assert isinstance(result, PolicyViolation)
    assert "keyword" in result.what_happened.lower()
```

### 7. Using `allowed_recipient_domains` without also adding `blocked_keywords`
Domain allowlists protect against external recipients, but an attacker can still inject malicious content in the body. Use both constraints for high-risk email tools.

---

## How to Instrument an Existing Codebase

When a user asks to add Sentinel to their agent project:

1. **Identify all tool functions** — functions decorated with `@tool`, passed to `Tool()`, or listed in a tool registry. These are the intercept points.

2. **Classify each tool** — assign `risk_level` and `action_type` using the decision rules above.

3. **Define constraints per tool** — check what the tool does with external resources (emails → domain + keyword, files → path regex, APIs → endpoint allowlist).

4. **Add `@sentinel.policy.wrap()` to each tool** — or, for Claude tool_use, build a `SentinelToolDispatcher`.

5. **Call `sentinel.configure()` at app startup** — with a stable `db_path` and `default_agent_id`.

6. **Write tests for each blocked case** — confirm that your policy constraints actually enforce what you intend.

7. **Add `ANTHROPIC_API_KEY` to `.env`** for semantic checks on high-risk tools.
