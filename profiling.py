"""Lightweight logging + profiling for the Trace Field Notes pipeline.

Everything here writes to the standard logging system, never the UI. Set the log
level with the ``TFN_LOG_LEVEL`` env var (default ``INFO``); use ``DEBUG`` for
per-stage detail. Resource probes (process RSS, system memory, CPU, and
GPU/MPS memory) are best-effort and degrade silently if a dependency is missing
— so the deterministic path, the test suite, and local development never need
``psutil`` or ``torch`` installed.
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager
from typing import Any, Iterator


def get_logger(name: str = "trace_field_notes") -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(name)s] %(levelname)s %(message)s")
        )
        logger.addHandler(handler)
        logger.setLevel(os.getenv("TFN_LOG_LEVEL", "INFO").upper())
        logger.propagate = False
    return logger


logger = get_logger()


def resource_snapshot() -> dict[str, Any]:
    """Best-effort process + system resource probe. Never raises."""

    snap: dict[str, Any] = {}
    try:
        import psutil

        proc = psutil.Process()
        snap["rss_mb"] = round(proc.memory_info().rss / 1024 / 1024, 1)
        vm = psutil.virtual_memory()
        snap["sys_mem_pct"] = vm.percent
        snap["sys_mem_avail_mb"] = round(vm.available / 1024 / 1024, 1)
        snap["cpu_pct"] = psutil.cpu_percent(interval=None)
    except Exception:  # noqa: BLE001 - profiling must never break the request
        pass
    try:
        import torch

        if torch.cuda.is_available():
            snap["accel"] = "cuda"
            snap["accel_mem_mb"] = round(torch.cuda.memory_allocated() / 1024 / 1024, 1)
        elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            snap["accel"] = "mps"
            snap["accel_mem_mb"] = round(
                torch.mps.current_allocated_memory() / 1024 / 1024, 1
            )
    except Exception:  # noqa: BLE001
        pass
    return snap


def format_snapshot(snap: dict[str, Any]) -> str:
    parts = []
    if "rss_mb" in snap:
        parts.append(f"rss={snap['rss_mb']}MB")
    if "sys_mem_pct" in snap:
        parts.append(f"sysmem={snap['sys_mem_pct']}%")
    if "cpu_pct" in snap:
        parts.append(f"cpu={snap['cpu_pct']}%")
    if "accel_mem_mb" in snap:
        parts.append(f"{snap.get('accel', 'accel')}={snap['accel_mem_mb']}MB")
    return " ".join(parts) or "n/a"


class Profiler:
    """Accumulates per-stage timings + counts for one request and logs a summary."""

    def __init__(self, label: str = "analyze") -> None:
        self.label = label
        self._t0 = time.perf_counter()
        self.stages: list[tuple[str, float]] = []
        self.meta: dict[str, Any] = {}

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        start = time.perf_counter()
        logger.debug(
            "%s: stage %r start | %s", self.label, name, format_snapshot(resource_snapshot())
        )
        try:
            yield
        finally:
            dt = time.perf_counter() - start
            self.stages.append((name, dt))
            logger.debug("%s: stage %r done in %.3fs", self.label, name, dt)

    def record(self, name: str, seconds: float) -> None:
        """Record a stage duration measured by the caller (no context manager)."""

        self.stages.append((name, seconds))
        logger.debug("%s: stage %r done in %.3fs", self.label, name, seconds)

    def mark(self, **kwargs: Any) -> None:
        self.meta.update(kwargs)

    def elapsed(self) -> float:
        return time.perf_counter() - self._t0

    def summary(self) -> None:
        total = self.elapsed()
        stage_str = ", ".join(f"{name}={dt * 1000:.0f}ms" for name, dt in self.stages)
        meta_str = " ".join(f"{key}={value}" for key, value in self.meta.items())
        logger.info(
            "%s done in %.3fs | %s | stages: %s | %s",
            self.label,
            total,
            meta_str or "-",
            stage_str or "-",
            format_snapshot(resource_snapshot()),
        )
