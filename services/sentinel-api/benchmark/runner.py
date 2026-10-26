from __future__ import annotations

import json
import platform
from datetime import datetime, timezone

from .metrics import aggregate, per_scenario, score_run
from .scenarios import SCENARIOS, make_events, make_post_action_events
from .systems import SYSTEMS


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
                result = SYSTEMS[name](events, post)
                if result is None:
                    not_run[name] = "ANTHROPIC_API_KEY is not set"
                    continue
                rows.append(score_run(name, scn, seed, result))
    return {
        "meta": {"seeds": seeds, "scenarios": [s.id for s in SCENARIOS if not scenarios or s.id in scenarios],
                 "systems": [n for n in chosen if n not in not_run], "not_run": not_run,
                 "generated_at": datetime.now(timezone.utc).isoformat(), "python": platform.python_version()},
        "aggregate": aggregate(rows), "per_scenario": per_scenario(rows), "runs": rows,
    }


def write_json(result: dict, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=1, default=str)
