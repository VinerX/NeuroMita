"""Bayesian optimization for RAG parameters via Optuna.

Replaces brute-force grid search with efficient sampling for large parameter spaces.
Requires ``pip install optuna``.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

try:
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    HAS_OPTUNA = True
except ImportError:
    HAS_OPTUNA = False


# Default continuous ranges for key RAG parameters
DEFAULT_PARAM_RANGES: Dict[str, tuple[float, float]] = {
    "RAG_WEIGHT_SIMILARITY":  (0.0, 3.0),
    "RAG_WEIGHT_TIME":        (0.0, 1.0),
    "RAG_WEIGHT_PRIORITY":    (0.0, 1.0),
    "RAG_WEIGHT_ENTITY":      (0.0, 1.0),
    "RAG_WEIGHT_KEYWORDS":    (0.0, 2.0),
    "RAG_WEIGHT_LEXICAL":     (0.0, 1.0),
    "RAG_WEIGHT_GRAPH":       (0.0, 3.0),
    "RAG_SIM_THRESHOLD":      (0.05, 0.5),
    "RAG_KEYWORD_MIN_SCORE":  (0.1, 0.7),
    "RAG_TIME_DECAY_RATE":    (0.01, 0.2),
}

DEFAULT_CATEGORICAL_PARAMS: Dict[str, list] = {
    "RAG_COMBINE_MODE": ["union", "two_stage", "intersect"],
}


@dataclass
class OptimizeConfig:
    """Configuration for Optuna-based optimization."""
    param_ranges: Dict[str, tuple[float, float]] = field(default_factory=lambda: dict(DEFAULT_PARAM_RANGES))
    categorical_params: Dict[str, list] = field(default_factory=lambda: dict(DEFAULT_CATEGORICAL_PARAMS))
    fixed_overrides: Dict[str, Any] = field(default_factory=dict)
    limit: int = 10
    n_trials: int = 200
    timeout: Optional[int] = None  # seconds

    @staticmethod
    def from_json_file(path: str) -> "OptimizeConfig":
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        cfg = OptimizeConfig()
        if "param_ranges" in d:
            cfg.param_ranges = {k: tuple(v) for k, v in d["param_ranges"].items()}
        if "categorical_params" in d:
            cfg.categorical_params = d["categorical_params"]
        if "fixed_overrides" in d:
            cfg.fixed_overrides = d["fixed_overrides"]
        if "limit" in d:
            cfg.limit = int(d["limit"])
        if "n_trials" in d:
            cfg.n_trials = int(d["n_trials"])
        if "timeout" in d:
            cfg.timeout = int(d["timeout"]) if d["timeout"] else None
        return cfg


@dataclass
class OptimizeResult:
    """Result of an Optuna optimization run."""
    best_params: Dict[str, Any]
    best_value: float
    target_metric: str
    n_trials: int
    top_trials: List[Dict[str, Any]]  # top-N trial summaries
    convergence: List[Dict[str, Any]] = field(default_factory=list)  # per-trial best
    # Validation result: metrics of best_params evaluated on the val split
    val_metrics: Optional[Dict[str, float]] = None

    def to_dict(self) -> dict:
        d = {
            "best_params": self.best_params,
            "best_value": self.best_value,
            "target_metric": self.target_metric,
            "n_trials": self.n_trials,
            "top_trials": self.top_trials,
            "convergence": self.convergence,
        }
        if self.val_metrics is not None:
            d["val_metrics"] = self.val_metrics
        return d


def run_optuna_sweep(
    svc,
    suite,
    *,
    val_suite=None,
    target_metric: str = "mean_recall",
    config: Optional[OptimizeConfig] = None,
    progress_callback=None,
    progress_file: Optional[str] = None,
) -> OptimizeResult:
    """Run Bayesian optimization over RAG parameters.

    Args:
        svc: RagTesterService instance (scenario already loaded into DB)
        suite: TestSuite to evaluate against
        target_metric: attribute of BatchResult to maximize
        config: OptimizeConfig with parameter ranges
        progress_callback: optional fn(trial_num, n_trials, best_value)

    Returns:
        OptimizeResult with best parameters and trial history
    """
    if not HAS_OPTUNA:
        raise ImportError(
            "Optuna is required for Bayesian optimization. "
            "Install with: pip install optuna"
        )

    cfg = config or OptimizeConfig()
    trial_count = [0]
    best_so_far = [0.0]
    best_params_so_far: Dict[str, Any] = {}
    convergence_log: List[Dict[str, Any]] = []
    start_time = time.time()

    def _write_progress(value: float):
        if not progress_file:
            return
        try:
            elapsed = time.time() - start_time
            data = {
                "status": "running",
                "trial": trial_count[0],
                "total_trials": cfg.n_trials,
                "pct": round(100.0 * trial_count[0] / max(cfg.n_trials, 1), 1),
                "current_value": round(value, 4),
                "best_value": round(best_so_far[0], 4),
                "best_params": best_params_so_far,
                "elapsed_sec": round(elapsed, 1),
                "eta_sec": round(elapsed / max(trial_count[0], 1) * (cfg.n_trials - trial_count[0]), 1),
                "target_metric": target_metric,
            }
            os.makedirs(os.path.dirname(os.path.abspath(progress_file)), exist_ok=True)
            with open(progress_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def objective(trial):
        overrides = dict(cfg.fixed_overrides)

        # Continuous parameters
        for name, (lo, hi) in cfg.param_ranges.items():
            overrides[name] = trial.suggest_float(name, lo, hi)

        # Categorical parameters
        for name, choices in cfg.categorical_params.items():
            overrides[name] = trial.suggest_categorical(name, choices)

        threshold = overrides.get("RAG_SIM_THRESHOLD", 0.3)

        batch = svc.run_batch(
            suite,
            limit=cfg.limit,
            threshold=float(threshold),
            use_overrides=True,
            overrides=overrides,
        )

        value = getattr(batch, target_metric, 0.0)

        trial_count[0] += 1
        if value > best_so_far[0]:
            best_so_far[0] = value
            best_params_so_far.clear()
            best_params_so_far.update(overrides)

        _write_progress(value)
        convergence_log.append({
            "trial": trial_count[0],
            "value": round(value, 5),
            "best": round(best_so_far[0], 5),
        })

        print(
            f"  Trial {trial_count[0]:>4d}/{cfg.n_trials}  "
            f"{target_metric}={value:.4f}  "
            f"best={best_so_far[0]:.4f}",
            flush=True,
        )
        if progress_callback:
            progress_callback(trial_count[0], cfg.n_trials, value)

        return value

    study = optuna.create_study(
        direction="maximize",
        study_name=f"rag_optimize_{target_metric}",
    )
    study.optimize(
        objective,
        n_trials=cfg.n_trials,
        timeout=cfg.timeout,
        show_progress_bar=False,
    )

    # Mark progress as completed
    if progress_file:
        try:
            elapsed = time.time() - start_time
            data = {
                "status": "completed",
                "trial": len(study.trials),
                "total_trials": cfg.n_trials,
                "pct": 100.0,
                "best_value": round(study.best_value, 4),
                "best_params": study.best_params,
                "elapsed_sec": round(elapsed, 1),
                "target_metric": target_metric,
            }
            with open(progress_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    # Collect top trials
    sorted_trials = sorted(study.trials, key=lambda t: t.value or 0.0, reverse=True)
    top_n = min(10, len(sorted_trials))
    top_trials = []
    for t in sorted_trials[:top_n]:
        top_trials.append({
            "number": t.number,
            "value": t.value,
            "params": t.params,
        })

    # Evaluate best params on validation suite (if provided)
    val_metrics: Optional[Dict[str, float]] = None
    if val_suite is not None and len(val_suite.cases) > 0:
        try:
            print(f"\nEvaluating best params on validation set ({len(val_suite.cases)} cases)...", flush=True)
            val_overrides = dict(cfg.fixed_overrides)
            val_overrides.update(study.best_params)
            val_threshold = float(val_overrides.get("RAG_SIM_THRESHOLD", 0.3))
            val_batch = svc.run_batch(
                val_suite,
                limit=cfg.limit,
                threshold=val_threshold,
                use_overrides=True,
                overrides=val_overrides,
            )
            val_metrics = {
                "mean_precision": round(val_batch.mean_precision, 4),
                "mean_recall":    round(val_batch.mean_recall, 4),
                "mrr":            round(val_batch.mrr, 4),
                "mean_ndcg":      round(val_batch.mean_ndcg, 4),
                "n_cases":        len(val_suite.cases),
            }
            print(
                f"  VAL → P={val_metrics['mean_precision']:.4f}  "
                f"R={val_metrics['mean_recall']:.4f}  "
                f"MRR={val_metrics['mrr']:.4f}  "
                f"nDCG={val_metrics['mean_ndcg']:.4f}",
                flush=True,
            )
        except Exception as _val_err:
            print(f"  VAL evaluation failed (ignored): {_val_err}", flush=True)

    return OptimizeResult(
        best_params=study.best_params,
        best_value=study.best_value,
        target_metric=target_metric,
        n_trials=len(study.trials),
        top_trials=top_trials,
        convergence=convergence_log,
        val_metrics=val_metrics,
    )
