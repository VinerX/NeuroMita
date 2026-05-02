"""Grid-sweep engine for RAG parameter optimisation.

Iterates over a cartesian product of parameter values, runs a test suite
for each combination via ``RagTesterService.run_batch``, and returns
results sorted by a target metric.
"""
from __future__ import annotations

import itertools
import json
import random
from dataclasses import dataclass, field
from typing import Any, Callable

try:
    from rag_tester_core import BatchResult, RagTesterService, TestSuite
except ImportError:
    from .rag_tester_core import BatchResult, RagTesterService, TestSuite


@dataclass
class SweepConfig:
    """Describes a parameter grid to sweep over."""

    # param_name → list of values to try
    parameters: dict[str, list] = field(default_factory=dict)

    # settings applied to every combination (not swept)
    fixed_overrides: dict[str, Any] = field(default_factory=dict)

    limit: int = 10
    max_evaluations: int = 0  # 0 = run all combinations

    @staticmethod
    def from_dict(d: dict) -> "SweepConfig":
        return SweepConfig(
            parameters=dict(d.get("parameters") or {}),
            fixed_overrides=dict(d.get("fixed_overrides") or {}),
            limit=int(d.get("limit", 10)),
            max_evaluations=int(d.get("max_evaluations", 0)),
        )

    @staticmethod
    def from_json_file(path: str) -> "SweepConfig":
        with open(path, "r", encoding="utf-8") as f:
            return SweepConfig.from_dict(json.load(f))


@dataclass
class SweepResult:
    """One evaluated parameter combination."""

    overrides: dict[str, Any]
    batch_result: BatchResult
    target_metric: float

    def to_dict(self) -> dict:
        return {
            "overrides": self.overrides,
            "target_metric": self.target_metric,
            "mean_precision": self.batch_result.mean_precision,
            "mean_recall": self.batch_result.mean_recall,
            "mrr": self.batch_result.mrr,
            "mean_ndcg": self.batch_result.mean_ndcg,
            "total_elapsed_ms": self.batch_result.total_elapsed_ms,
        }


_VALID_METRICS = ("mean_precision", "mean_recall", "mrr", "mean_ndcg")


def run_sweep(
    svc: RagTesterService,
    suite: TestSuite,
    config: SweepConfig,
    target_metric: str = "mean_recall",
    progress_callback: Callable[[int, int, float], None] | None = None,
) -> list[SweepResult]:
    """Run a grid sweep and return results sorted by *target_metric* (desc).

    Parameters
    ----------
    svc : RagTesterService
        Initialised service (scenario must already be loaded into the DB).
    suite : TestSuite
        Test cases to evaluate.
    config : SweepConfig
        Grid definition + fixed overrides.
    target_metric : str
        Which ``BatchResult`` attribute to optimise.
    progress_callback : callable, optional
        ``(current_idx, total, best_so_far)`` called after each evaluation.
    """
    if target_metric not in _VALID_METRICS:
        raise ValueError(f"target_metric must be one of {_VALID_METRICS}, got {target_metric!r}")

    # Build cartesian product
    param_names = list(config.parameters.keys())
    param_values = [config.parameters[k] for k in param_names]

    if not param_names:
        # No parameters to sweep — run once with fixed overrides
        combos: list[tuple] = [()]
    else:
        combos = list(itertools.product(*param_values))

    # Optionally cap evaluations via random sampling
    if config.max_evaluations > 0 and len(combos) > config.max_evaluations:
        combos = random.sample(combos, config.max_evaluations)

    total = len(combos)
    results: list[SweepResult] = []
    best_metric = -1.0

    for idx, combo in enumerate(combos):
        # Merge swept params with fixed overrides
        overrides = dict(config.fixed_overrides)
        for name, value in zip(param_names, combo):
            overrides[name] = value

        # Determine threshold: use swept RAG_SIM_THRESHOLD if present, else fixed, else 0.3
        threshold = float(overrides.get("RAG_SIM_THRESHOLD", 0.3))

        batch = svc.run_batch(
            suite,
            limit=config.limit,
            threshold=threshold,
            use_overrides=True,
            overrides=overrides,
        )

        metric_val = getattr(batch, target_metric, 0.0)
        results.append(SweepResult(
            overrides=overrides,
            batch_result=batch,
            target_metric=metric_val,
        ))

        if metric_val > best_metric:
            best_metric = metric_val

        if progress_callback:
            progress_callback(idx + 1, total, best_metric)

    # Sort by target metric descending
    results.sort(key=lambda r: r.target_metric, reverse=True)
    return results
