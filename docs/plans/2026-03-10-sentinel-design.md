# Sentinel — Agent Action Policy Engine
## Design Document v0.1 | 2026-03-10

## Overview

Sentinel is a policy enforcement layer that intercepts AI agent tool calls before execution, evaluates them against declared policies, and either passes, blocks, or modifies them. Every invocation is logged to a queryable audit store.

## Architecture

```
sentinel/
├── __init__.py              # exports: policy, SentinelConfig
├── core/
│   ├── wrapper.py           # @policy.wrap decorator
│   ├── engine.py            # PolicyEngine — evaluates actions
│   ├── rules.py             # rule-based checks
│   ├── semantic.py          # LLM-based intent check (provider-agnostic)
│   └── models.py            # Pydantic models
├── audit/
│   ├── logger.py            # writes AuditEntry to store
│   └── store.py             # SQLite / Postgres abstraction
├── integrations/
│   ├── anthropic.py         # Claude tool use dispatcher
│   ├── langchain.py         # LangChain tool wrapper (V1.1)
│   └── mcp.py               # MCP middleware (V1.1)
├── api/
│   ├── app.py               # FastAPI app
│   └── routes/
│       ├── audit.py         # GET /audit/entries, /audit/summary
│       └── policies.py      # GET/POST /policies
└── tests/
    ├── test_engine.py
    ├── test_wrapper.py
    └── test_audit.py
```

## Key Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Package manager | `uv` with `pyproject.toml` | Fastest, modern standard |
| Database | SQLite default, Postgres-compatible schema | Local dev, no SQLite-specific syntax |
| Semantic check | Provider-agnostic async callable | Not locked to Anthropic |
| Default semantic provider | Auto-init from `ANTHROPIC_API_KEY` env var | Zero config common case |
| LLM fallback | Degrade to rules-only if LLM fails or no key | Graceful degradation |
| Testing | pytest, mocked LLM responses | No real API calls in unit tests |
| Python | 3.10+, fully typed, mypy clean | As specified in PRD |

## Semantic Checker Design

Provider-agnostic: accepts any `async callable(tool_name, params, intent) -> SemanticResult`.

- If `SentinelConfig.semantic_checker` is set: use it
- Else if `ANTHROPIC_API_KEY` in environment: auto-init Anthropic/Haiku adapter
- Else: rules-only mode (semantic check skipped with warning)

## Build Phases

1. **Core**: Models, rule engine, `@policy.wrap`, audit log + SQLite
2. **Semantic**: SemanticChecker, in-memory cache, integration with engine
3. **Integrations**: Anthropic SDK dispatcher, FastAPI audit API, end-to-end test
4. **DX**: CLI, README, LangChain integration
