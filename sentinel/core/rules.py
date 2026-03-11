# sentinel/core/rules.py
from __future__ import annotations

import re
from typing import Any

from sentinel.core.models import PolicyDefinition, PolicyResult


class RuleEngine:
    """Evaluates rule-based constraints against proposed tool parameters."""

    def check_domain_allowlist(self, value: str, allowed: list[str]) -> bool:
        """Return True if value ends with any allowed domain suffix."""
        return any(value.lower().endswith(d.lower()) for d in allowed)

    def check_domain_blocklist(self, value: str, blocked: list[str]) -> bool:
        """Return True (allowed) if value does NOT end with any blocked domain."""
        return not any(value.lower().endswith(d.lower()) for d in blocked)

    def check_keyword_blocklist(self, text: str, blocked: list[str]) -> bool:
        """Return True (allowed) if text contains none of the blocked keywords."""
        text_lower = text.lower()
        return not any(kw.lower() in text_lower for kw in blocked)

    def check_numeric_bounds(
        self,
        value: float | int,
        min_val: float | int | None = None,
        max_val: float | int | None = None,
    ) -> bool:
        if min_val is not None and value < min_val:
            return False
        if max_val is not None and value > max_val:
            return False
        return True

    def check_count_limit(self, items: list[Any], max_count: int) -> bool:
        return len(items) <= max_count

    def check_regex(self, value: str, pattern: str) -> bool:
        return bool(re.match(pattern, value))

    def _scan_strings(self, params: dict[str, Any]) -> list[str]:
        """Recursively collect all string values from params."""
        strings: list[str] = []
        for v in params.values():
            if isinstance(v, str):
                strings.append(v)
            elif isinstance(v, list):
                strings.extend(i for i in v if isinstance(i, str))
        return strings

    def _collect_emails(self, params: dict[str, Any]) -> list[str]:
        """Collect values that look like emails or are in email-like fields."""
        emails: list[str] = []
        email_keys = {"to", "cc", "bcc", "recipient", "recipients", "email"}
        for k, v in params.items():
            if k.lower() in email_keys:
                if isinstance(v, str):
                    emails.append(v)
                elif isinstance(v, list):
                    emails.extend(i for i in v if isinstance(i, str))
        return emails

    def evaluate(self, policy: PolicyDefinition, params: dict[str, Any]) -> PolicyResult:
        """Run all applicable rule checks. Return first block or pass."""
        constraints = policy.constraints
        checks_run: list[str] = []
        checks_failed: list[str] = []

        all_strings = self._scan_strings(params)
        email_values = self._collect_emails(params)

        # --- blocked_keywords ---
        if "blocked_keywords" in constraints:
            checks_run.append("keyword_blocklist")
            keywords = constraints["blocked_keywords"]
            for s in all_strings:
                if not self.check_keyword_blocklist(s, keywords):
                    checks_failed.append("keyword_blocklist")
                    break

        # --- allowed_recipient_domains ---
        if "allowed_recipient_domains" in constraints and email_values:
            checks_run.append("domain_allowlist")
            allowed = constraints["allowed_recipient_domains"]
            for email in email_values:
                if not self.check_domain_allowlist(email, allowed):
                    checks_failed.append("domain_allowlist")
                    break

        # --- blocked_recipient_domains ---
        if "blocked_recipient_domains" in constraints and email_values:
            checks_run.append("domain_blocklist")
            blocked_domains = constraints["blocked_recipient_domains"]
            for email in email_values:
                if not self.check_domain_blocklist(email, blocked_domains):
                    checks_failed.append("domain_blocklist")
                    break

        # --- max_recipients ---
        if "max_recipients" in constraints:
            checks_run.append("max_recipients")
            max_r = constraints["max_recipients"]
            # Check list fields
            for k, v in params.items():
                list_fields = {"to", "cc", "bcc", "recipients", "attendees"}
                if isinstance(v, list) and k.lower() in list_fields:
                    if not self.check_count_limit(v, max_r):
                        checks_failed.append("max_recipients")
                        break
            # Check comma-separated string
            for k, v in params.items():
                if isinstance(v, str) and k.lower() in {"to", "cc", "bcc"}:
                    parts = [p.strip() for p in v.split(",") if p.strip()]
                    if len(parts) > max_r:
                        checks_failed.append("max_recipients")

        # --- max_duration_hours (numeric) ---
        if "max_duration_hours" in constraints and "end" in params and "start" in params:
            checks_run.append("max_duration_hours")
            try:
                from datetime import datetime
                start = datetime.fromisoformat(params["start"])
                end = datetime.fromisoformat(params["end"])
                hours = (end - start).total_seconds() / 3600
                if hours > constraints["max_duration_hours"]:
                    checks_failed.append("max_duration_hours")
            except Exception:
                pass  # Skip if unparseable

        # --- allowed_calendars ---
        if "allowed_calendars" in constraints and "calendar" in params:
            checks_run.append("allowed_calendars")
            if params["calendar"] not in constraints["allowed_calendars"]:
                checks_failed.append("allowed_calendars")

        # --- regex constraints ---
        if "field_patterns" in constraints:
            for field, pattern in constraints["field_patterns"].items():
                if field in params and isinstance(params[field], str):
                    checks_run.append(f"regex:{field}")
                    if not self.check_regex(params[field], pattern):
                        checks_failed.append(f"regex:{field}")

        if checks_failed:
            return PolicyResult(
                outcome="block",
                checks_run=checks_run,
                checks_failed=checks_failed,
                reason=f"Failed checks: {', '.join(checks_failed)}",
            )

        return PolicyResult(
            outcome="pass",
            checks_run=checks_run,
            checks_failed=[],
        )
