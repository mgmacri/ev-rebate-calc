# evrebate — federal EV rebate dataset pipeline (Canada, EVAP)

Maintains the dataset behind an EV rebate calculator for consumers, sales staff and
EV pricers. Covers Canada's federal **Electric Vehicle Affordability Program (EVAP)**,
the successor to iZEV, in force for transactions on or after 2026-02-16.

The dataset has two halves:

| Half | Where | How it's maintained |
|---|---|---|
| Eligible vehicle list (make/model/trim/fuel type/Canadian-made) | `data/dataset/vehicles.{json,csv}` | Scraped from Transport Canada's paginated list, snapshotted, diffed |
| Program rules (amounts by year, cap, lease proration, limits, FTV inclusions) | `rules/federal_evap.yaml` → `data/dataset/rules.json` | Hand-transcribed from TC pages, versioned, cross-checked against the scraped amounts on every build |

`data/dataset/dataset.json` bundles both plus metadata; `changelog.json` records
vehicles added/removed/changed per refresh.

## Run

```bash
uv venv && uv pip install -e ".[dev]"
.venv/bin/evrebate refresh          # fetch a dated raw snapshot + build outputs
.venv/bin/evrebate status
.venv/bin/pytest -q
.venv/bin/evrebate calc --fuel BEV --msrp 48200 --fees 1200 --freight-pdi 2100 --lease 36
```

`refresh` exits 3 when TC's published amounts disagree with the rules file. That
means the program changed (new year, new caps) and a human must update
`rules/federal_evap.yaml` and bump `rules_version`. The GitHub workflow commits
data changes automatically and opens an issue on exit 3.

## What the calculator can answer (see `evrebate/calc.py`)

- **Consumer:** am I eligible, how much, what counts toward the $50,000 cap, when does
  the amount step down (Jan 1 each year), lease proration `(full ÷ 48) × months`.
- **Sales:** the `reasons` list explains the outcome in plain words; `warnings` flags
  near-cap deals; `next_step_down` gives the urgency date.
- **Pricer:** `cap_headroom_cad` / `max_eligible_addons()` say how much fee, option or
  accessory room a configuration has before it loses the incentive; Canadian-made
  rows are cap-exempt (`price_cap_cad: null`).

## Key rules encoded (as of rules_version 2026-09-12)

- BEV/FCEV $5,000 (2026) → $4,000 (2027) → $3,000 (2028-29) → $2,000 (2030-31); PHEV is half.
- Amount year is the **portal submission date**, calendar year.
- Cap is **final transaction value ≤ $50,000**, pre-tax: MSRP after discounts + options
  + accessories + dealer fees. Excludes freight/PDI, warranties, insurance, one set of
  winter tires, L2 charger, taxes, trade-in, incentives. No partial incentive above cap.
- Canadian-made vehicles have no cap.
- Leases ≥ 12 months, full amount at ≥ 48 months, linear proration below.
- New only; demonstrators < 10,000 km OK. Made in Canada or an FTA country.
- Limits: 1 per individual for the whole program, 10 per organization/government.
- Stacks on top of provincial programs (provincial data is out of scope for this repo).

## Layout

```
rules/federal_evap.yaml        curated rules with source URLs
evrebate/sources/tc_evap.py    fetch + parse TC list (header-drift guard, maple-leaf flag)
evrebate/normalize.py          canonical records, stable ids, rules cross-check
evrebate/build.py              snapshot → dataset, lineage (first/last seen), diff, changelog
evrebate/calc.py               reference calculator = executable spec of the rules
data/raw/<source>/<date>/      immutable raw HTML snapshots + meta.json
data/dataset/                  published outputs
data/schema/                   JSON Schema for vehicles.json
tests/                         parser fixtures, calculator pins, dataset guards
.github/workflows/refresh.yml  Mon/Thu scheduled refresh
```

## Sources

- Overview: https://tc.canada.ca/en/road-transportation/innovative-technologies/electric-vehicles/electric-vehicle-affordability-program/overview
- Q&A (FTV definition, lease formula): https://tc.canada.ca/en/road-transportation/innovative-technologies/electric-vehicles/electric-vehicle-affordability-program/questions-answers
- Vehicle list: https://tc.canada.ca/en/road-transportation/innovative-technologies/electric-vehicles/electric-vehicle-affordability-program-evap/electric-vehicle-affordability-program-vehicle-list

## Calculator (GitHub Pages)

`site/index.html` is a single static page that reads `site/dataset.json` (copied by
`evrebate build`) and reimplements the rules from `calc.py` in JS. The
`deploy-pages` workflow publishes `site/` on every push to `main` that touches it,
so each scheduled data refresh redeploys the calculator automatically.

## Deals branch (real prices)

- `prices/msrp_ca.csv`: curated Canadian MSRP + freight per TC-listed trim, each row with
  source URL, as-of date and confidence. No open MSRP dataset exists for Canada, so this
  is transcribed from OEM releases and pricing pages. Rows older than 90 days are flagged
  `stale` in the build output so they get re-verified.
- `evrebate/sources/nrcan.py`: NRCan fuel consumption ratings (open data) for range,
  efficiency, body class and recharge time, matched heuristically to TC trims with a
  per-row match confidence. Raw CSVs snapshot under `data/raw/nrcan_fuel_consumption/`.
- `evrebate/deals.py`: runs every priced trim through the rules at sticker (no add-ons,
  no dealer fees) for purchase and each lease term. Output `data/dataset/deals.json`
  and bundled in `dataset.json` for the site.
- Site: Deals tab (filters, sortable columns, click-through to the calculator with the
  selection remembered on return) and Compare tab (up to 4 side by side).
