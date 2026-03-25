#!/usr/bin/env python
"""Headless CLI for RAG testing, parameter sweeps, and data export.

Designed to be invoked by an LLM agent or CI pipeline — all output is
JSON (``--format json``) or human-readable text (``--format text``).

Usage examples::

    # Run a test suite
    python rag_tester_cli.py run --scenario s.json --suite t.json --format json

    # Grid-sweep over RAG parameters
    python rag_tester_cli.py sweep --scenario s.json --suite t.json \\
        --sweep-config sweep.json --metric mean_recall --format json

    # Export scenario from a live DB
    python rag_tester_cli.py export --db world.db --character Crazy \\
        --output fixtures/crazy_scenario.json

    # Print example JSON templates
    python rag_tester_cli.py template --type scenario
"""
from __future__ import annotations

import argparse
import json
import os
import sys

# ── bootstrap: make project root importable ──────────────────────────────
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(THIS_DIR, "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
if THIS_DIR not in sys.path:
    sys.path.insert(0, THIS_DIR)

from rag_tester_core import (  # noqa: E402
    RagTesterService,
    Scenario,
    TestSuite,
)
from sweep import SweepConfig, run_sweep  # noqa: E402


# ── helpers ──────────────────────────────────────────────────────────────

def _parse_overrides(raw: str | None) -> dict:
    """Parse overrides from a JSON string or a path to a JSON file."""
    if not raw:
        return {}
    raw = raw.strip()
    if raw.startswith("{"):
        return json.loads(raw)
    # treat as file path
    with open(raw, "r", encoding="utf-8") as f:
        return json.load(f)


def _output(data, fmt: str, output_path: str | None):
    """Write *data* as JSON or text to stdout / file."""
    if fmt == "json":
        text = json.dumps(data, ensure_ascii=False, indent=2)
    else:
        text = str(data)

    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"Written to {output_path}", file=sys.stderr)
    else:
        print(text)


# ── subcommands ──────────────────────────────────────────────────────────

def cmd_run(args):
    """Run a test suite against a scenario and report metrics."""
    from rag_tester_core import SettingsOverride, setup_test_db
    from managers.rag.rag_manager import RAGManager
    from handlers.embedding_handler import EmbeddingModelHandler

    if getattr(args, 'db', None):
        setup_test_db(args.db)

    overrides = _parse_overrides(args.overrides)

    # If overrides contain embed model settings, apply them BEFORE embedding the scenario
    # and reset cached singletons so the right model is used.
    _embed_keys = {"RAG_EMBED_MODEL", "RAG_EMBED_MODEL_CUSTOM", "RAG_EMBED_QUERY_PREFIX"}
    _embed_overridden = bool(overrides) and bool(_embed_keys & set(overrides))
    if _embed_overridden:
        # Reset fallback handler singleton so it re-initialises with overridden model
        RAGManager._fallback_handler = None
        EmbeddingModelHandler._unload_shared()

    ctx = SettingsOverride(overrides) if overrides else None
    if ctx:
        ctx.__enter__()
    try:
        svc = RagTesterService()
        scenario = svc.load_scenario_file(args.scenario, fallback_character_id="RAG_TEST")
        suite = TestSuite.from_json(open(args.suite, "r", encoding="utf-8").read())

        # Load scenario into DB (uses current/overridden model for embeddings)
        print("Loading scenario into DB…", file=sys.stderr)
        if overrides:
            print(f"  overrides: {overrides}", file=sys.stderr)
        stats = svc.apply_scenario_to_db(scenario, clear_before=True, embed_now=True, smart_embed=True)
        print(f"  context={stats['context']} history={stats['history']} memories={stats['memories']}", file=sys.stderr)

        # Pre-flight: verify that embeddings were actually stored.
        # If 0 embeddings → embedding model failed to load silently (wrong Python env, missing torch, etc.)
        try:
            from handlers.embedding_presets import resolve_model_settings
            _model_hf = resolve_model_settings().get("hf_name", "")
            from managers.database_manager import DatabaseManager
            with DatabaseManager().connection() as _conn:
                _emb_count = _conn.execute(
                    "SELECT COUNT(*) FROM embeddings WHERE model_name=?", (_model_hf,)
                ).fetchone()[0]
            print(f"  embed_model={_model_hf}  stored_embeddings={_emb_count}", file=sys.stderr)
            if _emb_count == 0:
                print(
                    "\n⚠ FATAL: 0 embeddings stored for this model.\n"
                    "  Embedding model failed to load (missing torch/transformers?).\n"
                    "  Vector search will be DISABLED — test results are INVALID.\n"
                    "  Use a Python environment with the required ML libraries.\n",
                    file=sys.stderr,
                )
                sys.exit(1)
        except SystemExit:
            raise
        except Exception as _pf_err:
            print(f"  [pre-flight check failed: {_pf_err}]", file=sys.stderr)

        # Index graph entity embeddings when vector graph search is enabled.
        if overrides and overrides.get("RAG_GRAPH_VECTOR_SEARCH"):
            try:
                from managers.rag.rag_manager import RAGManager
                _rag_mgr = RAGManager(character_id=scenario.character_id or "RAG_TEST")
                _n_ge = _rag_mgr.index_graph_entity_embeddings()
                print(f"  graph entity embeddings indexed: {_n_ge}", file=sys.stderr)
            except Exception as _ge_err:
                print(f"  [graph entity embed failed: {_ge_err}]", file=sys.stderr)

        print(f"Running {len(suite.cases)} test cases…", file=sys.stderr)
        result = svc.run_batch(
            suite,
            limit=args.limit,
            threshold=args.threshold,
            use_overrides=bool(overrides),
            overrides=overrides or None,
            diagnose_miss=getattr(args, "diagnose_miss", False),
        )
    finally:
        if ctx:
            ctx.__exit__(None, None, None)

    if args.format == "json":
        _output(result.to_dict(), "json", args.output)
    else:
        _output(result.summary_text(), "text", args.output)


def cmd_sweep(args):
    """Grid-sweep over RAG parameters and rank by target metric."""
    from rag_tester_core import setup_test_db
    if getattr(args, 'db', None):
        setup_test_db(args.db)
    svc = RagTesterService()
    scenario = svc.load_scenario_file(args.scenario, fallback_character_id="RAG_TEST")
    suite = TestSuite.from_json(open(args.suite, "r", encoding="utf-8").read())
    config = SweepConfig.from_json_file(args.sweep_config)

    # Load scenario into DB once
    print("Loading scenario into DB…", file=sys.stderr)
    stats = svc.apply_scenario_to_db(scenario, clear_before=True, embed_now=True, smart_embed=True)
    print(f"  context={stats['context']} history={stats['history']} memories={stats['memories']}", file=sys.stderr)

    # Count grid size
    import itertools
    param_names = list(config.parameters.keys())
    param_values = [config.parameters[k] for k in param_names]
    grid_size = 1
    for v in param_values:
        grid_size *= len(v)
    effective = min(grid_size, config.max_evaluations) if config.max_evaluations > 0 else grid_size
    print(f"Sweep: {grid_size} combinations, running {effective}, metric={args.metric}", file=sys.stderr)

    def progress(cur, total, best):
        print(f"  [{cur}/{total}] best {args.metric}={best:.4f}", file=sys.stderr)

    results = run_sweep(
        svc, suite, config,
        target_metric=args.metric,
        progress_callback=progress,
    )

    if args.format == "json":
        data = {
            "metric": args.metric,
            "total_evaluated": len(results),
            "results": [r.to_dict() for r in results[:args.top_n] if args.top_n == 0 or True],
        }
        # top_n filtering
        if args.top_n > 0:
            data["results"] = [r.to_dict() for r in results[:args.top_n]]
        else:
            data["results"] = [r.to_dict() for r in results]
        _output(data, "json", args.output)
    else:
        lines = [f"=== Sweep Results (sorted by {args.metric} desc) ===", ""]
        show = results[:args.top_n] if args.top_n > 0 else results
        for i, r in enumerate(show):
            swept = {k: v for k, v in r.overrides.items() if k in config.parameters}
            lines.append(
                f"  #{i+1} {args.metric}={r.target_metric:.4f} | "
                f"P={r.batch_result.mean_precision:.3f} R={r.batch_result.mean_recall:.3f} "
                f"MRR={r.batch_result.mrr:.3f} nDCG={r.batch_result.mean_ndcg:.3f} | "
                f"{swept}"
            )
        _output("\n".join(lines), "text", args.output)


def cmd_export(args):
    """Export a scenario from a live SQLite database."""
    from managers.database_manager import DatabaseManager

    # Point DatabaseManager to the specified DB file
    db = DatabaseManager()
    db.db_path = args.db

    svc = RagTesterService()
    scenario = svc.load_scenario_from_db(
        args.character,
        hist_limit=args.hist_limit,
        mem_limit=args.mem_limit,
    )

    text = scenario.to_pretty_json()
    if args.output:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"Exported scenario to {args.output}", file=sys.stderr)
        print(f"  character={args.character} context={len(scenario.context)} "
              f"history={len(scenario.history)} memories={len(scenario.memories)}", file=sys.stderr)
    else:
        print(text)


def cmd_validate(args):
    """Validate a test suite against a scenario — check for orphaned expected_ids."""
    svc = RagTesterService()
    scenario = svc.load_scenario_file(args.scenario, fallback_character_id="RAG_TEST")
    suite = TestSuite.from_json(open(args.suite, "r", encoding="utf-8").read())

    known_ids = scenario.all_message_ids()
    total_expected = 0
    orphaned_ids: list[str] = []
    cases_with_orphans: list[str] = []

    for i, tc in enumerate(suite.cases):
        for eid in tc.expected_ids:
            eid_s = str(eid)
            total_expected += 1
            if eid_s not in known_ids:
                orphaned_ids.append(eid_s)
                case_label = f"Q{i+1}: {tc.query[:50]}"
                if case_label not in cases_with_orphans:
                    cases_with_orphans.append(case_label)

    result = {
        "valid": len(orphaned_ids) == 0,
        "total_expected_ids": total_expected,
        "orphaned_count": len(orphaned_ids),
        "orphaned_ids": orphaned_ids,
        "cases_with_orphans": cases_with_orphans,
        "scenario_message_count": len(known_ids),
        "suite_case_count": len(suite.cases),
    }

    if args.format == "json":
        _output(result, "json", args.output)
    else:
        lines = [f"=== Validation: {suite.name} ==="]
        lines.append(f"Scenario messages: {len(known_ids)}")
        lines.append(f"Suite cases: {len(suite.cases)}")
        lines.append(f"Total expected IDs: {total_expected}")
        lines.append(f"Orphaned IDs: {len(orphaned_ids)}")
        if orphaned_ids:
            lines.append(f"\nVerdict: INVALID — {len(orphaned_ids)} orphaned IDs")
            lines.append("\nOrphaned:")
            for oid in orphaned_ids:
                lines.append(f"  - {oid}")
            lines.append("\nAffected cases:")
            for cl in cases_with_orphans:
                lines.append(f"  - {cl}")
        else:
            lines.append(f"\nVerdict: VALID — all expected IDs found in scenario")
        _output("\n".join(lines), "text", args.output)


def cmd_generate_suite(args):
    """Generate a test suite from scenario data using an LLM."""
    from suite_generator import GeneratorConfig, generate_suite

    config = GeneratorConfig(
        api_base=args.api_base,
        model=args.model,
        api_key=args.api_key,
        window_size=args.window_size,
        window_overlap=args.window_overlap,
        num_cases=args.num_cases,
    )

    def progress(win, total, cases):
        print(f"  Window {win}/{total}, cases so far: {cases}", file=sys.stderr)

    print(f"Generating suite from {args.scenario}…", file=sys.stderr)
    print(f"  model={args.model} api_base={args.api_base}", file=sys.stderr)

    suite = generate_suite(args.scenario, config, progress_callback=progress)

    text = json.dumps(suite, ensure_ascii=False, indent=2)
    if args.output:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"Generated {len(suite['cases'])} test cases → {args.output}", file=sys.stderr)
    else:
        print(text)


def cmd_split_suite(args):
    """Assign train/val splits to a test suite (stratified by positive/negative)."""
    suite = TestSuite.from_json(open(args.suite, "r", encoding="utf-8").read())
    split_suite = suite.assign_splits(val_ratio=args.val_ratio, seed=args.seed)

    train = split_suite.by_split("train")
    val   = split_suite.by_split("val")
    print(
        f"Split '{suite.name}': {len(suite.cases)} total → "
        f"{len(train.cases)} train / {len(val.cases)} val  (val_ratio={args.val_ratio}, seed={args.seed})",
        file=sys.stderr,
    )
    pos_train = sum(1 for c in train.cases if not c.is_negative)
    pos_val   = sum(1 for c in val.cases   if not c.is_negative)
    print(f"  train: {pos_train} positive, {len(train.cases)-pos_train} negative", file=sys.stderr)
    print(f"  val:   {pos_val} positive,   {len(val.cases)-pos_val} negative", file=sys.stderr)

    text = split_suite.to_json()
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"Written to {args.output}", file=sys.stderr)
    else:
        print(text)


def cmd_optimize(args):
    """Bayesian optimization of RAG parameters via Optuna."""
    from optuna_sweep import OptimizeConfig, run_optuna_sweep
    from rag_tester_core import SettingsOverride, setup_test_db

    if getattr(args, 'db', None):
        setup_test_db(args.db)
    from managers.rag.rag_manager import RAGManager
    from handlers.embedding_handler import EmbeddingModelHandler

    config = OptimizeConfig()
    if args.optimize_config:
        config = OptimizeConfig.from_json_file(args.optimize_config)
    config.n_trials = args.n_trials
    if args.timeout:
        config.timeout = args.timeout

    # Apply fixed_overrides (including embed model) during scenario embedding AND each trial
    cli_overrides = _parse_overrides(args.overrides) if hasattr(args, 'overrides') and args.overrides else {}
    if cli_overrides:
        config.fixed_overrides.update(cli_overrides)  # ensure per-trial runs also use correct embed model
    # RAG_ENABLED must survive the embedding-phase SettingsOverride closing before trials start
    config.fixed_overrides.setdefault("RAG_ENABLED", True)
    # Disable verbose candidate logging during sweeps — dramatically reduces output and speeds up trials
    config.fixed_overrides.setdefault("RAG_DETAILED_LOGS", False)
    embed_overrides = dict(config.fixed_overrides)

    _embed_keys = {"RAG_EMBED_MODEL", "RAG_EMBED_MODEL_CUSTOM", "RAG_EMBED_QUERY_PREFIX"}
    if embed_overrides and bool(_embed_keys & set(embed_overrides)):
        RAGManager._fallback_handler = None
        EmbeddingModelHandler._unload_shared()

    ctx = SettingsOverride(embed_overrides) if embed_overrides else None
    if ctx:
        ctx.__enter__()
    try:
        svc = RagTesterService()
        scenario = svc.load_scenario_file(args.scenario, fallback_character_id="RAG_TEST")
        suite = TestSuite.from_json(open(args.suite, "r", encoding="utf-8").read())

        # Load scenario into DB once (uses overridden model for embeddings)
        print("Loading scenario into DB…", file=sys.stderr)
        if embed_overrides:
            print(f"  fixed_overrides: {embed_overrides}", file=sys.stderr)
        stats = svc.apply_scenario_to_db(scenario, clear_before=True, embed_now=True, smart_embed=True)
        print(f"  context={stats['context']} history={stats['history']} memories={stats['memories']}", file=sys.stderr)
    finally:
        if ctx:
            ctx.__exit__(None, None, None)

    # Resolve validation suite: explicit file > "val" split from train suite > None
    val_suite = None
    val_suite_path = getattr(args, "val_suite", None)
    if val_suite_path:
        val_suite = TestSuite.from_json(open(val_suite_path, "r", encoding="utf-8").read())
        print(f"Val suite: {val_suite_path} ({len(val_suite.cases)} cases)", file=sys.stderr)
    elif any(c.split == "val" for c in suite.cases):
        # Suite already has split annotations — use them
        train_suite = suite.by_split("train")
        val_suite   = suite.by_split("val")
        print(
            f"Using embedded splits: {len(train_suite.cases)} train / {len(val_suite.cases)} val",
            file=sys.stderr,
        )
        suite = train_suite  # optimize on train only

    def progress(cur, total, val):
        print(f"  [{cur}/{total}] current {args.metric}={val:.4f}", file=sys.stderr)

    print(f"Optimizing {args.metric} with {args.n_trials} trials…", file=sys.stderr)

    # Progress file: strip any extension, append _progress.json
    if args.output:
        base = os.path.splitext(args.output)[0]
        progress_file = base + "_progress.json"
    else:
        progress_file = os.path.join("results", "optuna_progress.json")

    result = run_optuna_sweep(
        svc, suite,
        val_suite=val_suite,
        target_metric=args.metric,
        config=config,
        progress_callback=progress,
        progress_file=progress_file,
    )

    if args.format == "json":
        _output(result.to_dict(), "json", args.output)
    else:
        lines = [
            f"=== Optimization Results ===",
            f"Metric: {result.target_metric}",
            f"Best value: {result.best_value:.4f}",
            f"Trials: {result.n_trials}",
            f"",
            f"Best parameters:",
        ]
        for k, v in sorted(result.best_params.items()):
            lines.append(f"  {k}: {v}")
        lines.append("")
        lines.append("Top trials:")
        for t in result.top_trials[:5]:
            lines.append(f"  #{t['number']} value={t['value']:.4f}")
        if result.val_metrics:
            vm = result.val_metrics
            lines.append("")
            lines.append(f"Validation ({vm.get('n_cases',0)} cases):")
            lines.append(
                f"  P={vm.get('mean_precision',0):.4f}  "
                f"R={vm.get('mean_recall',0):.4f}  "
                f"MRR={vm.get('mrr',0):.4f}  "
                f"nDCG={vm.get('mean_ndcg',0):.4f}"
            )
            train_val_gap = result.best_value - vm.get(args.metric, 0.0)
            lines.append(f"  Train/Val gap ({args.metric}): {train_val_gap:+.4f}"
                         + (" ⚠ overfit?" if train_val_gap > 0.05 else " ✓"))
        _output("\n".join(lines), "text", args.output)


def cmd_compare(args):
    """Compare two batch result JSON files for regression detection."""
    with open(args.baseline, "r", encoding="utf-8") as f:
        baseline = json.load(f)
    with open(args.current, "r", encoding="utf-8") as f:
        current = json.load(f)

    metrics = ["mean_precision", "mean_recall", "mrr", "mean_ndcg"]
    deltas = {}
    for m in metrics:
        b_val = float(baseline.get(m, 0))
        c_val = float(current.get(m, 0))
        deltas[m] = {"baseline": b_val, "current": c_val, "delta": c_val - b_val}

    # Per-query comparison
    b_results = baseline.get("results", [])
    c_results = current.get("results", [])
    query_changes = []
    for i, (br, cr) in enumerate(zip(b_results, c_results)):
        b_recall = float(br.get("recall", 0))
        c_recall = float(cr.get("recall", 0))
        if b_recall != c_recall:
            b_status = "PASS" if b_recall >= 1.0 else ("PARTIAL" if b_recall > 0 else "MISS")
            c_status = "PASS" if c_recall >= 1.0 else ("PARTIAL" if c_recall > 0 else "MISS")
            query_changes.append({
                "query": br.get("query", f"Q{i+1}")[:60],
                "baseline_recall": b_recall,
                "current_recall": c_recall,
                "change": f"{b_status} → {c_status}",
            })

    # Verdict
    recall_delta = deltas["mean_recall"]["delta"]
    if recall_delta > 0.01:
        verdict = "IMPROVED"
    elif recall_delta < -0.01:
        verdict = "REGRESSED"
    else:
        verdict = "NEUTRAL"

    result = {
        "verdict": verdict,
        "metrics": deltas,
        "query_changes": query_changes,
    }

    if args.format == "json":
        _output(result, "json", args.output)
    else:
        lines = [f"=== Comparison: {verdict} ===", ""]
        for m, d in deltas.items():
            sign = "+" if d["delta"] >= 0 else ""
            lines.append(f"  {m}: {d['baseline']:.4f} → {d['current']:.4f} ({sign}{d['delta']:.4f})")
        if query_changes:
            lines.append("")
            lines.append("Per-query changes:")
            for qc in query_changes:
                lines.append(f"  {qc['change']}: {qc['query']}")
        _output("\n".join(lines), "text", args.output)


def cmd_template(args):
    """Print example JSON for scenario, suite, or sweep config."""
    if args.type == "scenario":
        print(Scenario.template("RAG_TEST").to_pretty_json())
    elif args.type == "suite":
        print(TestSuite.template().to_json())
    elif args.type == "sweep":
        print(json.dumps({
            "parameters": {
                "RAG_WEIGHT_SIMILARITY": [0.5, 1.0, 1.5],
                "RAG_WEIGHT_KEYWORDS": [0.3, 0.6, 0.9],
                "RAG_SIM_THRESHOLD": [0.2, 0.3, 0.4],
            },
            "fixed_overrides": {
                "RAG_COMBINE_MODE": "union",
                "RAG_SEARCH_GRAPH": False,
            },
            "limit": 10,
            "max_evaluations": 0,
        }, ensure_ascii=False, indent=2))
    else:
        print(f"Unknown template type: {args.type}", file=sys.stderr)
        sys.exit(1)


# ── argparse ─────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rag_tester_cli",
        description="Headless RAG testing & parameter optimisation CLI",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # --- run ---
    p_run = sub.add_parser("run", help="Run a test suite against a scenario")
    p_run.add_argument("--scenario", required=True, help="Path to scenario JSON file")
    p_run.add_argument("--suite", required=True, help="Path to test suite JSON file")
    p_run.add_argument("--limit", type=int, default=10, help="RAG max results (default: 10)")
    p_run.add_argument("--threshold", type=float, default=0.2, help="Similarity threshold (default: 0.2)")
    p_run.add_argument("--overrides", default=None, help="JSON string or path to overrides file")
    p_run.add_argument("--db", default=None, help="Custom SQLite DB path (default: Histories/world.db)")
    p_run.add_argument("--format", choices=["json", "text"], default="text", help="Output format")
    p_run.add_argument("--output", default=None, help="Write output to file instead of stdout")
    p_run.add_argument("--diagnose-miss", action="store_true",
                       help="For MISS/PARTIAL cases run a wide search to diagnose why docs were not found")

    # --- sweep ---
    p_sweep = sub.add_parser("sweep", help="Grid-sweep over RAG parameters")
    p_sweep.add_argument("--scenario", required=True, help="Path to scenario JSON file")
    p_sweep.add_argument("--suite", required=True, help="Path to test suite JSON file")
    p_sweep.add_argument("--sweep-config", required=True, help="Path to sweep config JSON file")
    p_sweep.add_argument("--metric", default="mean_recall",
                         choices=["mean_precision", "mean_recall", "mrr", "mean_ndcg"],
                         help="Metric to optimise (default: mean_recall)")
    p_sweep.add_argument("--top-n", type=int, default=10, help="Show top N results (0=all)")
    p_sweep.add_argument("--db", default=None, help="Custom SQLite DB path")
    p_sweep.add_argument("--format", choices=["json", "text"], default="text", help="Output format")
    p_sweep.add_argument("--output", default=None, help="Write output to file")

    # --- export ---
    p_export = sub.add_parser("export", help="Export scenario from a live SQLite DB")
    p_export.add_argument("--db", required=True, help="Path to SQLite database file")
    p_export.add_argument("--character", required=True, help="character_id to export")
    p_export.add_argument("--hist-limit", type=int, default=0, help="Max history rows (0=all)")
    p_export.add_argument("--mem-limit", type=int, default=0, help="Max memory rows (0=all)")
    p_export.add_argument("--output", default=None, help="Write scenario JSON to file")

    # --- validate ---
    p_val = sub.add_parser("validate", help="Validate suite against scenario (check orphaned IDs)")
    p_val.add_argument("--scenario", required=True, help="Path to scenario JSON file")
    p_val.add_argument("--suite", required=True, help="Path to test suite JSON file")
    p_val.add_argument("--format", choices=["json", "text"], default="text", help="Output format")
    p_val.add_argument("--output", default=None, help="Write output to file")

    # --- generate-suite ---
    p_gen = sub.add_parser("generate-suite", help="Auto-generate test suite via LLM")
    p_gen.add_argument("--scenario", required=True, help="Path to scenario JSON file")
    p_gen.add_argument("--output", default=None, help="Write suite JSON to file")
    p_gen.add_argument("--num-cases", type=int, default=40, help="Target number of test cases")
    p_gen.add_argument("--api-base", default="http://localhost:11434/v1",
                       help="OpenAI-compatible API base URL (default: Ollama)")
    p_gen.add_argument("--model", default="gemma2:9b", help="Model name")
    p_gen.add_argument("--api-key", default="dummy", help="API key (default: dummy for local)")
    p_gen.add_argument("--window-size", type=int, default=20, help="Messages per LLM window")
    p_gen.add_argument("--window-overlap", type=int, default=5, help="Window overlap")

    # --- optimize ---
    p_opt = sub.add_parser("optimize", help="Bayesian optimization of RAG parameters (Optuna)")
    p_opt.add_argument("--scenario", required=True, help="Path to scenario JSON file")
    p_opt.add_argument("--suite", required=True, help="Path to test suite JSON file")
    p_opt.add_argument("--metric", default="mean_recall",
                       choices=["mean_precision", "mean_recall", "mrr", "mean_ndcg"],
                       help="Metric to maximize")
    p_opt.add_argument("--n-trials", type=int, default=200, help="Number of Optuna trials")
    p_opt.add_argument("--timeout", type=int, default=None, help="Timeout in seconds")
    p_opt.add_argument("--optimize-config", default=None, help="Path to optimize config JSON")
    p_opt.add_argument("--overrides", default=None, help="JSON string or path to overrides (e.g. embed model)")
    p_opt.add_argument("--val-suite", default=None,
                       help="Path to validation suite JSON. If omitted and --suite has split annotations, "
                            "val split is used automatically.")
    p_opt.add_argument("--db", default=None, help="Custom SQLite DB path")
    p_opt.add_argument("--format", choices=["json", "text"], default="text", help="Output format")
    p_opt.add_argument("--output", default=None, help="Write output to file")

    # --- split-suite ---
    p_split = sub.add_parser("split-suite", help="Assign train/val splits to a test suite (stratified)")
    p_split.add_argument("--suite", required=True, help="Path to input suite JSON file")
    p_split.add_argument("--val-ratio", type=float, default=0.25,
                         help="Fraction of cases to assign as val (default: 0.25)")
    p_split.add_argument("--seed", type=int, default=42, help="Random seed (default: 42)")
    p_split.add_argument("--output", default=None, help="Write annotated suite to file (default: stdout)")

    # --- compare ---
    p_cmp = sub.add_parser("compare", help="Compare two batch results for regression")
    p_cmp.add_argument("--baseline", required=True, help="Path to baseline results JSON")
    p_cmp.add_argument("--current", required=True, help="Path to current results JSON")
    p_cmp.add_argument("--format", choices=["json", "text"], default="text", help="Output format")
    p_cmp.add_argument("--output", default=None, help="Write output to file")

    # --- template ---
    p_tmpl = sub.add_parser("template", help="Print example JSON templates")
    p_tmpl.add_argument("--type", required=True, choices=["scenario", "suite", "sweep"],
                        help="Template type to generate")

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.command == "run":
            cmd_run(args)
        elif args.command == "sweep":
            cmd_sweep(args)
        elif args.command == "export":
            cmd_export(args)
        elif args.command == "validate":
            cmd_validate(args)
        elif args.command == "generate-suite":
            cmd_generate_suite(args)
        elif args.command == "optimize":
            cmd_optimize(args)
        elif args.command == "split-suite":
            cmd_split_suite(args)
        elif args.command == "compare":
            cmd_compare(args)
        elif args.command == "template":
            cmd_template(args)
    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
