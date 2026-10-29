from __future__ import annotations

import json
import platform
from datetime import datetime, timezone

import httpx

from .metrics import aggregate, per_scenario, score_run
from .scenarios import SCENARIOS, make_events, make_post_action_events
from .systems import SYSTEMS, llm_provider


def run_benchmark(seeds: int = 10, systems: list[str] | None = None, scenarios: list[str] | None = None) -> dict:
    chosen = systems or list(SYSTEMS)
    rows: list[dict] = []
    not_run: dict[str, str] = {}
    for scn in SCENARIOS:
        if scenarios and scn.id not in scenarios:
            continue
        for seed in range(seeds):
            events = make_events(scn, seed)  # identical telemetry for every system
            post = lambda action, scn=scn, seed=seed: make_post_action_events(scn, seed, action)
            for name in chosen:
                if name in not_run:
                    continue
                try:
                    result = SYSTEMS[name](events, post)
                except httpx.HTTPError as exc:  # e.g. an LLM quota: report it as not run, never half-run
                    code = f"HTTP {exc.response.status_code}" if isinstance(exc, httpx.HTTPStatusError) else type(exc).__name__
                    not_run[name] = f"the API call failed ({code}); rerun to resume from LLM_CACHE"
                    rows = [r for r in rows if r["system"] != name]
                    continue
                if result is None:
                    not_run[name] = "no ANTHROPIC_API_KEY or GEMINI_API_KEY is set"
                    continue
                rows.append(score_run(name, scn, seed, result))
    return {
        "meta": {"seeds": seeds, "scenarios": [s.id for s in SCENARIOS if not scenarios or s.id in scenarios],
                 "systems": [n for n in chosen if n not in not_run], "not_run": not_run,
                 "generated_at": datetime.now(timezone.utc).isoformat(), "python": platform.python_version(),
                 "llm": "{}: {}".format(*llm_provider()[:2]) if "llm_only" in chosen and llm_provider() else None},
        "aggregate": aggregate(rows), "per_scenario": per_scenario(rows), "runs": rows,
    }


def write_json(result: dict, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=1, default=str)
