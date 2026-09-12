"""Guards on the built dataset: run after `evrebate build`. Skipped if not built."""
import json
from pathlib import Path
import pytest
from evrebate.normalize import consistency_issues
from evrebate.rules import load_rules

DS = Path(__file__).parent.parent / "data" / "dataset" / "vehicles.json"
pytestmark = pytest.mark.skipif(not DS.exists(), reason="dataset not built")


def _load():
    return json.loads(DS.read_text())


def test_ids_unique_and_shape():
    d = _load()
    ids = [v["id"] for v in d["vehicles"]]
    assert len(ids) == len(set(ids)) == d["meta"]["counts"]["vehicles"] > 0
    for v in d["vehicles"]:
        assert v["fuel_type"] in {"BEV", "FCEV", "PHEV"}
        assert (v["price_cap_cad"] is None) == v["canadian_made"]


def test_published_amounts_match_rules():
    rules = load_rules()
    bad = {v["id"]: iss for v in _load()["vehicles"] if (iss := consistency_issues(v, rules))}
    assert not bad, bad
