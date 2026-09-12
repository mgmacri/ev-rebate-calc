from __future__ import annotations

from pathlib import Path
import yaml

RULES_DIR = Path(__file__).resolve().parent.parent / "rules"


def load_rules(path: Path | None = None) -> dict:
    path = path or RULES_DIR / "federal_evap.yaml"
    with open(path) as f:
        rules = yaml.safe_load(f)
    _validate(rules)
    return rules


def _validate(r: dict) -> None:
    sched = r["incentive_schedule"]["amounts"]
    years = sorted(int(y) for y in sched)
    assert years, "empty schedule"
    for y in years:
        for ft in r["vehicle_eligibility"]["fuel_types"]:
            assert ft in sched[y], f"schedule {y} missing {ft}"
    assert r["lease"]["full_incentive_term_months"] > r["lease"]["minimum_term_months"]
    assert r["price_cap"]["max_cad"] > 0


def full_amount(rules: dict, fuel_type: str, year: int) -> int | None:
    """Full incentive for a fuel type in a calendar year; None if outside the program."""
    sched = rules["incentive_schedule"]["amounts"]
    row = sched.get(year) or sched.get(str(year))
    return None if row is None else row.get(fuel_type)
