"""Ray runtime helpers for local and RunPod execution."""

from __future__ import annotations

import os
from typing import Any

try:
    import ray as _ray
except ModuleNotFoundError:  # pragma: no cover - exercised in local smoke tests
    _ray = None


class _LocalRemoteFunction:
    """Tiny Ray-compatible wrapper for developer machines without Ray installed."""

    def __init__(self, func: Any) -> None:
        self._func = func

    def remote(self, *args: Any, **kwargs: Any) -> Any:
        return self._func(*args, **kwargs)


class _LocalRay:
    """Local fallback that keeps Ray task modules importable without Ray."""

    @staticmethod
    def remote(*decorator_args: Any, **decorator_kwargs: Any) -> Any:
        _ = decorator_kwargs
        if decorator_args and callable(decorator_args[0]):
            return _LocalRemoteFunction(decorator_args[0])

        def decorator(func: Any) -> _LocalRemoteFunction:
            return _LocalRemoteFunction(func)

        return decorator

    @staticmethod
    def get(value: Any) -> Any:
        return value

    @staticmethod
    def is_initialized() -> bool:
        return True

    @staticmethod
    def init(**kwargs: Any) -> None:
        _ = kwargs


ray = _ray if _ray is not None else _LocalRay()
RAY_AVAILABLE = _ray is not None


def ensure_ray_initialized(**kwargs: Any) -> None:
    """Connect to Ray when a module is launched directly.

    Production RunPod jobs normally run under `ray job submit` or Ray Serve, where
    Ray is already initialized. Local smoke commands can set `RAY_ADDRESS`; if it
    is absent we start an in-process Ray runtime.
    """
    if not RAY_AVAILABLE:
        return

    if ray.is_initialized():
        return

    address = os.environ.get("RAY_ADDRESS")
    if address:
        ray.init(address=address, **kwargs)
        return

    ray.init(**kwargs)
