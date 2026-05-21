"""Ray runtime helpers for local and RunPod execution."""

from __future__ import annotations

import os
from typing import Any

import ray


def ensure_ray_initialized(**kwargs: Any) -> None:
    """Connect to Ray when a module is launched directly.

    Production RunPod jobs normally run under `ray job submit` or Ray Serve, where
    Ray is already initialized. Local smoke commands can set `RAY_ADDRESS`; if it
    is absent we start an in-process Ray runtime.
    """
    if ray.is_initialized():
        return

    address = os.environ.get("RAY_ADDRESS")
    if address:
        ray.init(address=address, **kwargs)
        return

    ray.init(**kwargs)
