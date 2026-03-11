# sentinel/core/wrapper.py
from __future__ import annotations

import asyncio
import functools
import inspect
from typing import Any, Callable, Literal

from sentinel.core.models import PolicyDefinition, PolicyViolation


class PolicyWrapper:
    """Provides the @policy.wrap decorator."""

    def _get_config(self) -> Any:
        import sentinel
        return sentinel._config

    def wrap(
        self,
        *,
        intent: str,
        risk_level: Literal["low", "medium", "high", "critical"],
        action_type: Literal["reversible", "irreversible", "destructive"],
        constraints: dict[str, Any] | None = None,
        semantic_check: bool = True,
        semantic_threshold: float = 0.8,
        on_block: Literal["raise", "return", "log_only"] = "return",
        on_modify: Literal["auto", "ask", "block"] = "auto",
        log_level: Literal["all", "blocks_only", "none"] = "all",
        agent_id: str | None = None,
        task_id: str | None = None,
    ) -> Callable[..., Any]:
        policy = PolicyDefinition(
            intent=intent,
            risk_level=risk_level,
            action_type=action_type,
            constraints=constraints or {},
            semantic_check=semantic_check,
            semantic_threshold=semantic_threshold,
            on_block=on_block,
            on_modify=on_modify,
            log_level=log_level,
        )

        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            tool_name = func.__name__

            @functools.wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                sig = inspect.signature(func)
                bound = sig.bind(*args, **kwargs)
                bound.apply_defaults()
                params = dict(bound.arguments)
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        import concurrent.futures
                        with concurrent.futures.ThreadPoolExecutor() as pool:
                            future = pool.submit(
                                asyncio.run,
                                _run(tool_name, policy, params, func, args, kwargs, agent_id, task_id, log_level, self._get_config)
                            )
                            return future.result()
                    else:
                        return loop.run_until_complete(
                            _run(tool_name, policy, params, func, args, kwargs, agent_id, task_id, log_level, self._get_config)
                        )
                except RuntimeError:
                    return asyncio.run(
                        _run(tool_name, policy, params, func, args, kwargs, agent_id, task_id, log_level, self._get_config)
                    )

            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                sig = inspect.signature(func)
                bound = sig.bind(*args, **kwargs)
                bound.apply_defaults()
                params = dict(bound.arguments)
                return await _run(tool_name, policy, params, func, args, kwargs, agent_id, task_id, log_level, self._get_config)

            if inspect.iscoroutinefunction(func):
                return async_wrapper
            return sync_wrapper

        return decorator


async def _run(
    tool_name: str,
    policy: PolicyDefinition,
    params: dict[str, Any],
    func: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    agent_id: str | None,
    task_id: str | None,
    log_level: str,
    get_config: Callable[[], Any],
) -> Any:
    cfg = get_config()
    await cfg._ensure_initialized()

    effective_agent_id = agent_id or cfg.default_agent_id

    result = await cfg.engine.evaluate(
        policy, tool_name, params, cfg.semantic_checker
    )

    if result.outcome == "block":
        violation = PolicyViolation(
            tool_name=tool_name,
            reason=result.reason or "Policy check failed",
            suggestion=f"Review constraints for {tool_name}: {result.checks_failed}",
            what_happened=f"Failed checks: {', '.join(result.checks_failed)}",
        )

        if policy.on_block == "log_only":
            # Execute anyway, log as pass
            from sentinel.core.models import PolicyResult
            log_outcome = PolicyResult(
                outcome="pass",
                checks_run=result.checks_run,
                checks_failed=result.checks_failed,
                reason="log_only mode: executed despite violation",
            )
            if log_level != "none":
                await cfg.logger.log(
                    agent_id=effective_agent_id,
                    tool_name=tool_name,
                    action_type=policy.action_type,
                    risk_level=policy.risk_level,
                    intent=policy.intent,
                    params=params,
                    policy_result=log_outcome,
                    task_id=task_id,
                    log_level=log_level,
                )
            if inspect.iscoroutinefunction(func):
                return await func(*args, **kwargs)
            return func(*args, **kwargs)

        if log_level != "none":
            await cfg.logger.log(
                agent_id=effective_agent_id,
                tool_name=tool_name,
                action_type=policy.action_type,
                risk_level=policy.risk_level,
                intent=policy.intent,
                params=params,
                policy_result=result,
                task_id=task_id,
                log_level=log_level,
            )

        if policy.on_block == "raise":
            raise PermissionError(f"Sentinel blocked {tool_name}: {violation.reason}")
        return violation

    # PASS: execute function
    if inspect.iscoroutinefunction(func):
        execution_result = await func(*args, **kwargs)
    else:
        execution_result = func(*args, **kwargs)

    if log_level != "none":
        await cfg.logger.log(
            agent_id=effective_agent_id,
            tool_name=tool_name,
            action_type=policy.action_type,
            risk_level=policy.risk_level,
            intent=policy.intent,
            params=params,
            policy_result=result,
            execution_result=execution_result if isinstance(execution_result, dict) else None,
            task_id=task_id,
            log_level=log_level,
        )

    return execution_result


policy = PolicyWrapper()
