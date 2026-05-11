"""
ONS EAR/ENA pipeline — fetches 3-year history (2024, 2025, current year)
from ONS Dados Abertos and writes data/ear_ena.json.

Run: python pipelines/ons_ear_ena.py

Data dictionary references:
- EAR: https://dados.ons.org.br/dataset/ear-diario-por-subsistema
- ENA: https://dados.ons.org.br/dataset/ena-diario-por-subsistema

Output JSON structure:
{
  "generated_at_utc": "2026-05-11T13:00:00Z",
  "source": {...},
  "ear_now":   {"SECO": {"pct": 65.6, "mwmes": 134297, "max": 204615, "date": "..."}},
  "ena_now":   {"SECO": {"mwmed": 31098, "pct_mlt_bruta": 84, "pct_mlt_armaz": 73}},
  "ear_monthly_pct": {"SECO": {"2024": [...12 vals...], "2025": [...], "2026": [...nullable...]}},
  "ena_monthly_mwmed": {"SECO": {"2024": [...], "2025": [...], "2026": [...nullable...]}},
  "ena_monthly_pct_mlt_bruta": {...same structure...}
}
"""
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone, date
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).parent))
from common import (
    fetch_text,
    parse_csv,
    find_col,
    parse_date_flex,
    to_float,
    normalize_sub,
)

EAR_URL_TEMPLATE = (
    "https://ons-aws-prod-opendata.s3.amazonaws.com/"
    "dataset/ear_subsistema_di/EAR_DIARIO_SUBSISTEMA_{year}.csv"
)
ENA_URL_TEMPLATE = (
    "https://ons-aws-prod-opendata.s3.amazonaws.com/"
    "dataset/ena_subsistema_di/ENA_DIARIO_SUBSISTEMA_{year}.csv"
)


def years_to_fetch() -> list[int]:
    """Return the years we want to keep: previous 2 + current."""
    now_year = datetime.now(timezone.utc).year
    return [now_year - 2, now_year - 1, now_year]


def fetch_ear_year(year: int) -> list[dict]:
    """Fetch EAR for one year, returns list of normalized records."""
    url = EAR_URL_TEMPLATE.format(year=year)
    print(f"  EAR {year}: {url}")
    text = fetch_text(url)
    rows = parse_csv(text)
    if not rows:
        return []
    keys = list(rows[0].keys())

    col_date = (
        find_col(keys, "ear", "data")
        or find_col(keys, "data")
        or find_col(keys, "dia")
    )
    col_sub = (
        find_col(keys, "nom", "subsistema")
        or find_col(keys, "id", "subsistema")
        or find_col(keys, "subsistema")
    )
    col_pct = (
        find_col(keys, "verif", "percentual")
        or find_col(keys, "ear", "percentual")
        or find_col(keys, "percentual")
    )
    col_mw = (
        find_col(keys, "verif", "mwmes")
        or find_col(keys, "ear", "verif", "mwmes")
        or find_col(keys, "mwmes")
    )
    col_max = find_col(keys, "max", "subsistema") or find_col(keys, "max")

    print(
        f"    columns: date={col_date!r}, sub={col_sub!r}, "
        f"pct={col_pct!r}, mwmes={col_mw!r}, max={col_max!r}"
    )
    if not all([col_date, col_sub, col_pct]):
        raise RuntimeError(
            f"Could not resolve required EAR columns in {year}. Available: {keys}"
        )

    out = []
    for r in rows:
        d = parse_date_flex(r.get(col_date, ""))
        sub = normalize_sub(r.get(col_sub, ""))
        pct = to_float(r.get(col_pct))
        mw = to_float(r.get(col_mw)) if col_mw else None
        mx = to_float(r.get(col_max)) if col_max else None
        if d and sub and pct is not None:
            out.append({"date": d, "sub": sub, "pct": pct, "mwmes": mw, "max": mx})
    return out


def fetch_ena_year(year: int) -> list[dict]:
    """Fetch ENA for one year, returns list of normalized records."""
    url = ENA_URL_TEMPLATE.format(year=year)
    print(f"  ENA {year}: {url}")
    text = fetch_text(url)
    rows = parse_csv(text)
    if not rows:
        return []
    keys = list(rows[0].keys())

    col_date = (
        find_col(keys, "ena", "data")
        or find_col(keys, "data")
        or find_col(keys, "dia")
    )
    col_sub = (
        find_col(keys, "nom", "subsistema")
        or find_col(keys, "id", "subsistema")
        or find_col(keys, "subsistema")
    )
    col_bruta_mw = (
        find_col(keys, "bruta", "mwmed")
        or find_col(keys, "ena", "bruta")
    )
    col_armaz_mw = (
        find_col(keys, "armaz", "mwmed")
        or find_col(keys, "ena", "armaz")
    )
    col_bruta_pct = find_col(keys, "bruta", "percentual") or find_col(keys, "bruta", "mlt")
    col_armaz_pct = find_col(keys, "armaz", "percentual") or find_col(keys, "armaz", "mlt")

    print(
        f"    columns: date={col_date!r}, sub={col_sub!r}, "
        f"bruta_mw={col_bruta_mw!r}, armaz_mw={col_armaz_mw!r}, "
        f"bruta_pct={col_bruta_pct!r}, armaz_pct={col_armaz_pct!r}"
    )
    if not all([col_date, col_sub, col_bruta_mw]):
        raise RuntimeError(
            f"Could not resolve required ENA columns in {year}. Available: {keys}"
        )

    out = []
    for r in rows:
        d = parse_date_flex(r.get(col_date, ""))
        sub = normalize_sub(r.get(col_sub, ""))
        bm = to_float(r.get(col_bruta_mw))
        am = to_float(r.get(col_armaz_mw)) if col_armaz_mw else None
        bp = to_float(r.get(col_bruta_pct)) if col_bruta_pct else None
        ap = to_float(r.get(col_armaz_pct)) if col_armaz_pct else None
        if d and sub and bm is not None:
            out.append(
                {
                    "date": d,
                    "sub": sub,
                    "bruta_mwmed": bm,
                    "armaz_mwmed": am,
                    "pct_mlt_bruta": bp,
                    "pct_mlt_armaz": ap,
                }
            )
    return out


def build_ear_now(records: list[dict]) -> dict:
    """From all EAR records, find latest day's snapshot per subsystem."""
    latest_by_sub: dict[str, dict] = {}
    for r in records:
        sub = r["sub"]
        if sub not in latest_by_sub or r["date"] > latest_by_sub[sub]["date"]:
            latest_by_sub[sub] = r
    out = {}
    for sub, r in latest_by_sub.items():
        if sub not in ("SECO", "SUL", "NE", "N", "SIN"):
            continue
        out[sub] = {
            "pct": round(r["pct"], 2),
            "mwmes": round(r["mwmes"]) if r["mwmes"] else None,
            "max": round(r["max"]) if r["max"] else None,
            "date": r["date"].isoformat(),
        }
    return out


def build_ena_now(records: list[dict]) -> dict:
    """From all ENA records, find latest day's snapshot per subsystem."""
    latest_by_sub: dict[str, dict] = {}
    for r in records:
        sub = r["sub"]
        if sub not in latest_by_sub or r["date"] > latest_by_sub[sub]["date"]:
            latest_by_sub[sub] = r
    out = {}
    for sub, r in latest_by_sub.items():
        if sub not in ("SECO", "SUL", "NE", "N"):
            continue
        out[sub] = {
            "mwmed": round(r["bruta_mwmed"]) if r["bruta_mwmed"] else None,
            "pct_mlt_bruta": round(r["pct_mlt_bruta"], 1) if r["pct_mlt_bruta"] is not None else None,
            "pct_mlt_armaz": round(r["pct_mlt_armaz"], 1) if r["pct_mlt_armaz"] is not None else None,
            "date": r["date"].isoformat(),
        }
    return out


def build_monthly(records: list[dict], value_key: str, agg: str = "last") -> dict:
    """
    Aggregate records by (sub, year, month) using either 'last' (end-of-month
    value) or 'mean' (monthly average). Returns dict[sub][year_str] = [12 values].
    """
    bucket: dict = defaultdict(lambda: defaultdict(list))
    for r in records:
        if r["sub"] not in ("SECO", "SUL", "NE", "N"):
            continue
        v = r.get(value_key)
        if v is None:
            continue
        key = (r["sub"], r["date"].year, r["date"].month)
        bucket[key]["records"].append((r["date"], v))

    monthly: dict = defaultdict(lambda: defaultdict(lambda: [None] * 12))
    for (sub, year, month), data in bucket.items():
        recs = sorted(data["records"], key=lambda x: x[0])
        if agg == "last":
            value = recs[-1][1]
        elif agg == "mean":
            value = mean(r[1] for r in recs)
        else:
            raise ValueError(f"Unknown agg: {agg}")
        monthly[sub][str(year)][month - 1] = round(value, 2)

    # Convert defaultdicts to regular dicts
    return {sub: dict(years) for sub, years in monthly.items()}


def main():
    print("=" * 60)
    print("ONS EAR/ENA pipeline")
    print(f"Started: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)

    years = years_to_fetch()
    print(f"Years to fetch: {years}")

    ear_records: list[dict] = []
    ena_records: list[dict] = []
    fetch_errors: list[str] = []

    for year in years:
        try:
            ear_records.extend(fetch_ear_year(year))
        except Exception as e:
            msg = f"EAR {year} failed: {e}"
            print(f"  WARN: {msg}")
            fetch_errors.append(msg)
        try:
            ena_records.extend(fetch_ena_year(year))
        except Exception as e:
            msg = f"ENA {year} failed: {e}"
            print(f"  WARN: {msg}")
            fetch_errors.append(msg)

    print(f"\nTotal EAR records: {len(ear_records)}")
    print(f"Total ENA records: {len(ena_records)}")

    if not ear_records and not ena_records:
        print("ERROR: No data fetched. Aborting.")
        sys.exit(1)

    output = {
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": {
            "ear": "ONS Dados Abertos — EAR Diário por Subsistema",
            "ena": "ONS Dados Abertos — ENA Diário por Subsistema",
            "years": years,
            "fetch_errors": fetch_errors,
        },
        "ear_now": build_ear_now(ear_records) if ear_records else {},
        "ena_now": build_ena_now(ena_records) if ena_records else {},
        "ear_monthly_pct": build_monthly(ear_records, "pct", agg="last") if ear_records else {},
        "ena_monthly_mwmed": build_monthly(ena_records, "bruta_mwmed", agg="mean") if ena_records else {},
        "ena_monthly_pct_mlt_bruta": build_monthly(ena_records, "pct_mlt_bruta", agg="mean") if ena_records else {},
    }

    out_path = Path(__file__).parent.parent / "data" / "ear_ena.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False, default=str))
    size_kb = out_path.stat().st_size / 1024
    print(f"\nWrote {out_path} ({size_kb:.1f} KB)")
    print("Done.")


if __name__ == "__main__":
    main()
