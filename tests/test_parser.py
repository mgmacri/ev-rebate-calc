from pathlib import Path
from evrebate.sources import tc_evap

FIX = Path(__file__).parent / "fixtures"


def test_parse_fixture_page():
    body = (FIX / "tc_page0.html").read_text()
    rows = tc_evap.parse_page(body, page=0)
    assert len(rows) == 25
    r = rows[0]
    assert (r.model_year, r.make, r.model, r.trim, r.fuel_type) == (2027, "Chevrolet", "Bolt", "RS", "BEV")
    assert (r.incentive_purchase_or_48mo, r.incentive_36mo, r.incentive_24mo, r.incentive_12mo) == (5000, 3750, 2500, 1250)
    assert not r.canadian_made


def test_canadian_made_flag_from_maple_leaf():
    body = (FIX / "tc_page0.html").read_text()
    rows = tc_evap.parse_page(body, page=0)
    pacifica = [r for r in rows if r.model == "Pacifica"]
    assert pacifica and all(r.canadian_made for r in pacifica)
    bolt = [r for r in rows if r.model == "Bolt"]
    assert bolt and not any(r.canadian_made for r in bolt)


def test_header_drift_raises():
    body = (FIX / "tc_page0.html").read_text().replace("Fuel type*", "Powertrain")
    try:
        tc_evap.parse_page(body)
    except tc_evap.ParseError as e:
        assert "header drift" in str(e)
    else:
        raise AssertionError("expected ParseError")


def test_page_without_table_is_empty():
    assert tc_evap.parse_page("<html><body>nothing</body></html>") == []


def test_date_modified():
    assert tc_evap.parse_date_modified((FIX / "tc_page0.html").read_text()) == "2026-03-10"
