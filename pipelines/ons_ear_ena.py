"""
ONS EAR/ENA pipeline v2

Improvements over v1:
- Adds SIN aggregate (sum of SECO + SUL + NE + N) computed in MWmes/MWmed
- Extracts real MLT (long-term mean) values from CSV when columns exist
- Better logging: prints record counts, date ranges, per-sub samples

Outputs: data/ear_ena.json
"""
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
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

CANONICAL_SUBS = ("SECO", "SUL", "NE", "N")


def years_to_fetch() -> list[int]:
    now_year = datetime.now(timezone.utc).year
    return [now_year - 2, now_year - 1, now_year]


def fetch_ear_year(year: int) -> list[dict]:
    url = EAR_URL_TEMPLATE.format(year=year)
    print(f"  EAR {year}: {url}")
    text = fetch_text(url)
    rows = parse_csv(text)
    if not rows:
        return []
    keys = list(rows[0].keys())

    col_date = find_col(keys, "ear", "data") or find_col(keys, "data") or find_col(keys, "dia")
    col_sub = find_col(keys, "nom", "subsistema") or find_col(keys, "id", "subsistema") or find_col(keys, "subsistema")
    col_pct = find_col(keys, "verif", "percentual") or find_col(keys, "ear", "percentual") or find_col(keys, "percentual")
    col_mw = find_col(keys, "verif", "mwmes") or find_col(keys, "ear", "verif", "mwmes") or find_col(keys, "mwmes")
    col_max = find_col(keys, "max", "subsistema") or find_col(keys, "max")

    print(f"    cols: date={col_date!r}, sub={col_sub!r}, pct={col_pct!r}, mwmes={col_mw!r}, max={col_max!r}")
    if not all([col_date, col_sub, col_pct]):
        raise RuntimeError(f"Could not resolve EAR columns in {year}. Available: {keys}")

    out = []
    for r in rows:
        d = parse_date_flex(r.get(col_date, ""))
        sub = normalize_sub(r.get(col_sub, ""))
        pct = to_float(r.get(col_pct))
        mw = to_float(r.get(col_mw)) if col_mw else None
        mx = to_float(r.get(col_max)) if col_max else None
        if d and sub and pct is not None:
            out.append({"date": d, "sub": sub, "pct": pct, "mwmes": mw, "max": mx})
    print(f"    parsed: {len(out)} records, subsystems: {sorted(set(r['sub'] for r in out))}")
    return out


def fetch_ena_year(year: int) -> list[dict]:
    url = ENA_URL_TEMPLATE.format(year=year)
    print(f"  ENA {year}: {url}")
    text = fetch_text(url)
    rows = parse_csv(text)
    if not rows:
        return []
    keys = list(rows[0].keys())

    col_date = find_col(keys, "ena", "data") or find_col(keys, "data") or find_col(keys, "dia")
    col_sub = find_col(keys, "nom", "subsistema") or find_col(keys, "id", "subsistema") or find_col(keys, "subsistema")
    col_bruta_mw = find_col(keys, "bruta", "mwmed") or find_col(keys, "ena", "bruta")
    col_armaz_mw = find_col(keys, "armaz", "mwmed") or find_col(keys, "ena", "armaz")
    col_bruta_pct = find_col(keys, "bruta", "percentual") or find_col(keys, "bruta", "mlt")
    col_armaz_pct = find_col(keys, "armaz", "percentual") or find_col(keys, "armaz", "mlt")
    # MLT reference columns (used to derive real MLT per month per sub)
    col_bruta_mlt = find_col(keys, "bruta", "mlt", "mwmed") or find_col(keys, "bruta", "mlt_mwmed")
    col_armaz_mlt = find_col(keys, "armaz", "mlt", "mwmed") or find_col(keys, "armaz", "mlt_mwmed")

    print(f"    cols: date={col_date!r}, sub={col_sub!r}, bruta_mw={col_bruta_mw!r}, armaz_mw={col_armaz_mw!r}")
    print(f"          bruta_pct={col_bruta_pct!r}, bruta_mlt={col_bruta_mlt!r}")
    if not all([col_date, col_sub, col_bruta_mw]):
        raise RuntimeError(f"Could not resolve ENA columns in {year}. Available: {keys}")

    out = []
    for r in rows:
        d = parse_date_flex(r.get(col_date, ""))
        sub = normalize_sub(r.get(col_sub, ""))
        bm = to_float(r.get(col_bruta_mw))
        am = to_float(r.get(col_armaz_mw)) if col_armaz_mw else None
        bp = to_float(r.get(col_bruta_pct)) if col_bruta_pct else None
        ap = to_float(r.get(col_armaz_pct)) if col_armaz_pct else None
        bm_mlt = to_float(r.get(col_bruta_mlt)) if col_bruta_mlt else None
        am_mlt = to_float(r.get(col_armaz_mlt)) if col_armaz_mlt else None
        if d and sub and bm is not None:
            out.append({
                "date": d, "sub": sub,
                "bruta_mwmed": bm, "armaz_mwmed": am,
                "pct_mlt_bruta": bp, "pct_mlt_armaz": ap,
                "mlt_bruta_mwmed": bm_mlt, "mlt_armaz_mwmed": am_mlt,
            })
    print(f"    parsed: {len(out)} records, subsystems: {sorted(set(r['sub'] for r in out))}")
    return out


def latest_per_sub(records: list[dict]) -> dict[str, dict]:
    """Return {sub: latest_record_for_that_sub}."""
    latest: dict[str, dict] = {}
    for r in records:
        s = r["sub"]
        if s not in latest or r["date"] > latest[s]["date"]:
            latest[s] = r
    return latest


def build_ear_now(records: list[dict]) -> dict:
    latest = latest_per_sub(records)
    out = {}
    sin_pct, sin_mwmes, sin_max, sin_date = [], 0, 0, None
    for sub, r in latest.items():
        if sub not in CANONICAL_SUBS:
            continue
        out[sub] = {
            "pct": round(r["pct"], 2),
            "mwmes": round(r["mwmes"]) if r["mwmes"] else None,
            "max": round(r["max"]) if r["max"] else None,
            "date": r["date"].isoformat(),
        }
        if r["mwmes"] and r["max"]:
            sin_mwmes += r["mwmes"]
            sin_max += r["max"]
            sin_date = r["date"] if sin_date is None or r["date"] > sin_date else sin_date
    # Compute SIN aggregate
    if sin_mwmes and sin_max:
        out["SIN"] = {
            "pct": round(sin_mwmes / sin_max * 100, 2),
            "mwmes": round(sin_mwmes),
            "max": round(sin_max),
            "date": sin_date.isoformat() if sin_date else None,
        }
    return out


def build_ena_now(records: list[dict]) -> dict:
    latest = latest_per_sub(records)
    out = {}
    for sub, r in latest.items():
        if sub not in CANONICAL_SUBS:
            continue
        out[sub] = {
            "mwmed": round(r["bruta_mwmed"]) if r["bruta_mwmed"] else None,
            "pct_mlt_bruta": round(r["pct_mlt_bruta"], 1) if r["pct_mlt_bruta"] is not None else None,
            "pct_mlt_armaz": round(r["pct_mlt_armaz"], 1) if r["pct_mlt_armaz"] is not None else None,
            "date": r["date"].isoformat(),
        }
    return out


def build_monthly(records: list[dict], value_key: str, agg: str = "last") -> dict:
    bucket: dict = defaultdict(lambda: defaultdict(list))
    for r in records:
        if r["sub"] not in CANONICAL_SUBS:
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

    return {sub: dict(years) for sub, years in monthly.items()}


def build_ear_monthly_sin(records: list[dict]) -> dict:
    """Compute SIN as aggregate of (sum mwmes / sum max) per month."""
    bucket = defaultdict(lambda: {"recs": []})
    for r in records:
        if r["sub"] not in CANONICAL_SUBS:
            continue
        if r["mwmes"] is None or r["max"] is None:
            continue
        key = (r["date"].year, r["date"].month, r["date"])
        bucket[key]["recs"].append(r)

    # For each (year, month, date), sum across subs
    by_day = defaultdict(lambda: {"mwmes": 0.0, "max": 0.0})
    for (year, month, dt), data in bucket.items():
        if len(data["recs"]) >= len(CANONICAL_SUBS):  # only days with all 4 subs reported
            for r in data["recs"]:
                by_day[(year, month, dt)]["mwmes"] += r["mwmes"]
                by_day[(year, month, dt)]["max"] += r["max"]

    # Now take end-of-month value per (year, month)
    monthly = defaultdict(lambda: [None] * 12)
    by_ym = defaultdict(list)
    for (year, month, dt), v in by_day.items():
        by_ym[(year, month)].append((dt, v))
    for (year, month), lst in by_ym.items():
        lst.sort(key=lambda x: x[0])
        _, v = lst[-1]
        pct = v["mwmes"] / v["max"] * 100 if v["max"] > 0 else None
        if pct is not None:
            monthly[str(year)][month - 1] = round(pct, 2)
    return {"SIN": dict(monthly)}


def main():
    print("=" * 60)
    print("ONS EAR/ENA pipeline v2")
    print(f"Started: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)

    years = years_to_fetch()
    print(f"Years to fetch: {years}\n")

    ear_records: list[dict] = []
    ena_records: list[dict] = []
    fetch_errors: list[str] = []

    print("Fetching EAR...")
    for year in years:
        try:
            ear_records.extend(fetch_ear_year(year))
        except Exception as e:
            msg = f"EAR {year} failed: {e}"
            print(f"  WARN: {msg}")
            fetch_errors.append(msg)

    print("\nFetching ENA...")
    for year in years:
        try:
            ena_records.extend(fetch_ena_year(year))
        except Exception as e:
            msg = f"ENA {year} failed: {e}"
            print(f"  WARN: {msg}")
            fetch_errors.append(msg)

    if ear_records:
        dates = [r["date"] for r in ear_records]
        print(f"\nEAR records: {len(ear_records)}, dates {min(dates)} → {max(dates)}")
    if ena_records:
        dates = [r["date"] for r in ena_records]
        print(f"ENA records: {len(ena_records)}, dates {min(dates)} → {max(dates)}")

    if not ear_records and not ena_records:
        print("\nERROR: No data fetched. Aborting.")
        sys.exit(1)

    # Build outputs
    ear_now = build_ear_now(ear_records) if ear_records else {}
    ena_now = build_ena_now(ena_records) if ena_records else {}

    # EAR monthly (% by sub, end of month) + SIN aggregate
    ear_monthly = build_monthly(ear_records, "pct", agg="last") if ear_records else {}
    if ear_records:
        ear_monthly.update(build_ear_monthly_sin(ear_records))

    # ENA monthly (MWmed avg + % MLT avg)
    ena_monthly_mwmed = build_monthly(ena_records, "bruta_mwmed", agg="mean") if ena_records else {}
    ena_monthly_pct = build_monthly(ena_records, "pct_mlt_bruta", agg="mean") if ena_records else {}

    output = {
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": {
            "ear": "ONS Dados Abertos — EAR Diário por Subsistema",
            "ena": "ONS Dados Abertos — ENA Diário por Subsistema",
            "years": years,
            "fetch_errors": fetch_errors,
            "ear_records_count": len(ear_records),
            "ena_records_count": len(ena_records),
        },
        "ear_now": ear_now,
        "ena_now": ena_now,
        "ear_monthly_pct": ear_monthly,
        "ena_monthly_mwmed": ena_monthly_mwmed,
        "ena_monthly_pct_mlt_bruta": ena_monthly_pct,
    }

    out_path = Path(__file__).parent.parent / "data" / "ear_ena.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False, default=str))
    size_kb = out_path.stat().st_size / 1024
    print(f"\nWrote {out_path} ({size_kb:.1f} KB)")

    # Print summary
    print("\n--- Summary ---")
    print(f"EAR now subs: {list(ear_now.keys())}")
    print(f"ENA now subs: {list(ena_now.keys())}")
    if "SIN" in ear_now:
        print(f"SIN aggregate: {ear_now['SIN']['pct']}% ({ear_now['SIN']['mwmes']:,}/{ear_now['SIN']['max']:,} MWmes)")

    print("Done.")


if __name__ == "__main__":
    main()
