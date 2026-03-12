"""
examples/basic.py — Sentinel quickstart, no API key required.

Demonstrates rule-based enforcement (keyword blocklist, domain allowlist)
without any LLM or network call.

Run:
    python examples/basic.py
"""

import sentinel
from sentinel.core.models import PolicyViolation

# Use an in-memory SQLite DB so this demo leaves no files behind.
sentinel.configure(db_path=":memory:", default_agent_id="demo")


@sentinel.policy.wrap(
    intent="send emails on behalf of the user",
    constraints={
        "blocked_keywords": ["password", "confidential", "wire transfer"],
        "max_recipients": 5,
        "allowed_recipient_domains": ["@company.com", "@trusted-partner.com"],
    },
    risk_level="high",
    action_type="irreversible",
    semantic_check=False,  # skip LLM check — no API key needed
)
def send_email(to: str, subject: str, body: str) -> dict:
    # In a real app this would call your email provider.
    return {"status": "sent", "to": to, "subject": subject}


def show(label: str, result: object) -> None:
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    if isinstance(result, PolicyViolation):
        print(f"  BLOCKED")
        print(f"  reason    : {result.reason}")
        print(f"  suggestion: {result.suggestion}")
    else:
        print(f"  PASSED")
        print(f"  result    : {result}")


# --- PASS: all constraints satisfied ---
result = send_email(
    to="alice@company.com",
    subject="Q1 Planning",
    body="See the attached agenda for next week's sync.",
)
show("PASS — internal recipient, clean body", result)

# --- BLOCK: keyword in body ---
result = send_email(
    to="alice@company.com",
    subject="Quick note",
    body="Here is the password: hunter2",
)
show("BLOCK — keyword_blocklist triggered", result)

# --- BLOCK: recipient domain not in allowlist ---
result = send_email(
    to="attacker@evil.com",
    subject="Update",
    body="Everything is fine.",
)
show("BLOCK — recipient domain not allowed", result)

# --- PASS: trusted-partner domain is also allowed ---
result = send_email(
    to="bob@trusted-partner.com",
    subject="Partnership Update",
    body="Sending over the latest figures.",
)
show("PASS — trusted-partner.com is in allowlist", result)

print("\nDone. No API key required — all checks are rule-based.\n")
