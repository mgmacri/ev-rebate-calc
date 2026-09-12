"""Source adapter: Transport Canada EVAP eligible-vehicle list.

The list is a paginated Drupal Views table (25 rows/page). Canadian-made vehicles are
flagged with a maple-leaf icon inside the model-year cell that links to #cdn_mde.
"""
from __future__ import annotations

import hashlib
import html
import re
import urllib.request
from dataclasses import dataclass, asdict
from datetime import date

LIST_URL = (
    "https://tc.canada.ca/en/road-transportation/innovative-technologies/electric-vehicles/"
    "electric-vehicle-affordability-program-evap/electric-vehicle-affordability-program-vehicle-list"
)
USER_AGENT = "evrebate-pipeline/0.1 (+https://github.com/; dataset refresh bot)"
MAX_PAGES = 50  # safety valve

EXPECTED_HEADERS = [
    "model year", "make", "model", "trim", "fuel type",
    "incentive for purchase or 48 month lease", "incentive for 36 month lease",
    "incentive for 24 month lease", "incentive for 12 month lease",
]


@dataclass(frozen=True)
class RawVehicle:
    model_year: int
    make: str
    model: str
    trim: str
    fuel_type: str
    canadian_made: bool
    incentive_purchase_or_48mo: int
    incentive_36mo: int
    incentive_24mo: int
    incentive_12mo: int
    page: int
    row_hash: str

    def to_dict(self) -> dict:
        return asdict(self)


class ParseError(RuntimeError):
    pass


def fetch_page(page: int, url: str = LIST_URL) -> str:
    req = urllib.request.Request(f"{url}?page={page}", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8", errors="replace")


def fetch_all_pages(url: str = LIST_URL) -> list[str]:
    """Fetch every page of the list. Stops when a page repeats the previous page (Drupal
    Views clamps out-of-range ?page= to the last page) or when it has no data rows."""
    pages: list[str] = []
    prev_rows: list | None = None
    for p in range(MAX_PAGES):
        body = fetch_page(p, url)
        rows = parse_page(body, page=p)
        if not rows or (prev_rows is not None and rows == prev_rows):
            break
        pages.append(body)
        prev_rows = rows
    if not pages:
        raise ParseError("no pages with data rows fetched")
    return pages


def _strip(cell_html: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", cell_html)).replace("\xa0", " ").strip()


def _money(s: str) -> int:
    m = re.search(r"\$?\s*([\d,]+)", s)
    if not m:
        raise ParseError(f"cannot parse money: {s!r}")
    return int(m.group(1).replace(",", ""))


def parse_headers(body: str) -> list[str]:
    return [_strip(h).lower() for h in re.findall(r"<th\b[^>]*>(.*?)</th>", body, re.S)]


def validate_headers(body: str) -> None:
    got = parse_headers(body)
    if len(got) != len(EXPECTED_HEADERS):
        raise ParseError(f"header count changed: {got}")
    for g, e in zip(got, EXPECTED_HEADERS):
        if not g.startswith(e):
            raise ParseError(f"header drift: expected {e!r}, got {g!r}")


def parse_page(body: str, page: int = 0) -> list[RawVehicle]:
    m = re.search(r"<table.*?</table>", body, re.S)
    if not m:
        return []  # out-of-range page or list temporarily empty
    validate_headers(m.group(0))
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", m.group(0), re.S)
    out: list[RawVehicle] = []
    for r in rows:
        cells = re.findall(r"<td[^>]*>(.*?)</td>", r, re.S)
        if len(cells) != 9:
            if cells:
                raise ParseError(f"row has {len(cells)} cells: {cells}")
            continue  # header row
        year_cell = cells[0]
        canadian = "cdn_mde" in year_cell or "canadian-maple-leaf" in year_cell
        text = [_strip(c) for c in cells]
        year = int(re.search(r"(20\d\d)", text[0]).group(1))
        fuel = text[4].upper()
        if fuel not in {"BEV", "FCEV", "PHEV"}:
            raise ParseError(f"unknown fuel type {fuel!r} in row {text}")
        rec = dict(
            model_year=year, make=text[1], model=text[2], trim=text[3], fuel_type=fuel,
            canadian_made=canadian,
            incentive_purchase_or_48mo=_money(text[5]), incentive_36mo=_money(text[6]),
            incentive_24mo=_money(text[7]), incentive_12mo=_money(text[8]),
        )
        key = "|".join(str(rec[k]) for k in rec)
        out.append(RawVehicle(**rec, page=page, row_hash=hashlib.sha256(key.encode()).hexdigest()[:16]))
    return out


def parse_date_modified(body: str) -> str | None:
    m = re.search(r'Date modified.*?<time[^>]*datetime="([^"]+)"', body, re.S) or \
        re.search(r"Date modified.*?(\d{4}-\d{2}-\d{2})", body, re.S)
    return m.group(1)[:10] if m else None


def parse_all(pages: list[str]) -> list[RawVehicle]:
    seen: dict[str, RawVehicle] = {}
    for i, body in enumerate(pages):
        for v in parse_page(body, page=i):
            seen.setdefault(v.row_hash, v)   # dedupe identical rows across pages
    return list(seen.values())


def snapshot_name(today: date | None = None) -> str:
    return (today or date.today()).isoformat()
