"""
ONS ENA Bruta por Bacia pipeline

Replaces the discontinued precipitation-by-basin dataset.
ENA bruta (MWmed) is the energy equivalent of precipitation runoff at each basin.

Outputs: data/ena_bacia.json with 8 main basins:
- Paranaíba, Grande, Paraná  (SE/CO)
- Iguaçu, Uruguai           (SUL)
- São Francisco, Parnaíba   (NE)
- Tocantins                 (N)
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
)

ENA_BACIA_URL = (
    "https://ons-aws-prod-opendata.s3.amazonaws.com/"
    "dataset/ena_bacia_di/ENA_DIARIO_BACIAS_{year}.csv"
)

# Map ONS basin names (various spellings) to canonical IDs + submarket
# ONS naming varies: sometimes uppercase, sometimes with accents
BASIN_MAP = {
    'PARANAIBA': ('paranaiba', 'Paranaíba', 'SECO'),
    'PARANAÍBA': ('paranaiba', 'Paranaíba', 'SECO'),
    'GRANDE': ('grande', 'Grande', 'SECO'),
    'PARANA': ('parana', 'Paraná', 'SECO'),
    'PARANÁ': ('parana', 'Paraná', 'SECO'),
    'IGUACU': ('iguacu', 'Iguaçu', 'SUL'),
    'IGUAÇU': ('iguacu', 'Iguaçu', 'SUL'),
    'URUGUAI': ('uruguai', 'Uruguai', 'SUL'),
    'SAO FRANCISCO': ('sao_francisco', 'São Francisco', 'NE'),
    'SÃO FRANCISCO': ('sao_francisco', 'São Francisco', 'NE'),
    'PARNAIBA': ('parnaiba', 'Parnaíba', 'NE'),
    'PARNAÍBA': ('parnaiba', 'Parnaíba', 'NE'),
    'TOCANTINS': ('tocantins', 'Tocantins', 'N'),
}

BASIN_ORDER = ['paranaiba', 'grande', 'parana', 'iguacu', 'uruguai', 'sao_francisco', 'parnaiba', 'tocantins']


def years_to_fetch() -> list[int]:
    now_year = datetime.now(timezone.utc).year
    return [now_year - 2, now_year - 1, now_year]


def normalize_basin(name: str) -> tuple[str, str, str] | None:
    """Return (basin_id, basin_name, sub) or None if not a basin we track."""
    if not name:
        return None
    key = name.strip().upper()
    # Try direct match
    if key in BASIN_MAP:
        return BASIN_MAP[key]
    # Try without accents / spaces normalization
    import unicodedata
    norm = unicodedata.normalize('NFD', key).encode('ascii', 'ignore').decode('ascii').strip()
    if norm in BASIN_MAP:
        return BASIN_MAP[norm]
    return None


def fetch_ena_bacia_year(year: int) -> list[dict]:
    url = ENA_BACIA_URL.format(year=year)
    print(f"  ENA bacia {year}: {url}")
    text = fetch_text(url)
    rows = parse_csv(text)
    if not rows:
        return []
    keys = list(rows[0].keys())

    col_date = find_col(keys, "ena", "data") or find_col(keys, "data") or find_col(keys, "dia")
    col_basin = (
        find_col(keys, "nom", "bacia")
        or find_col(keys, "bacia")
    )
    col_bruta_mw = find_col(keys, "bruta", "mwmed") or find_col(keys, "ena", "bruta")
    col_armaz_mw = find_col(keys, "armaz", "mwmed") or find_col(keys, "ena", "armaz")

    print(f"    cols: date={col_date!r}, basin={col_basin!r}, bruta_mw={col_bruta_mw!r}")
    if not all([col_date, col_basin, col_bruta_mw]):
        raise RuntimeError(f"Could not resolve ENA-bacia columns in {year}. Available: {keys}")

    out = []
    unmapped = set()
    for r in rows:
        d = parse_date_flex(r.get(col_date, ""))
        raw_basin = r.get(col_basin, "")
        bm = to_float(r.get(col_bruta_mw))
        if not d or bm is None:
            continue
        mapped = normalize_basin(raw_basin)
        if not mapped:
            if raw_basin.strip():
                unmapped.add(raw_basin.strip())
            continue
        basin_id, basin_name, sub = mapped
        out.append({"date": d, "basin": basin_id, "basin_name": basin_name, "sub": sub, "mwmed": bm})

    if unmapped:
        # Show what basins ONS published that we don't track (informational)
        print(f"    unmapped basins (skipped): {sorted(unmapped)[:10]}")
    print(f"    parsed: {len(out)} records, basins kept: {sorted(set(r['basin'] for r in out))}")
    return out


def build_basin_now(records: list[dict]) -> dict:
    """Latest day per basin."""
    latest: dict[str, dict] = {}
    for r in records:
        b = r["basin"]
        if b not in latest or r["date"] > latest[b]["date"]:
            latest[b] = r
    return {
        b: {"mwmed": round(r["mwmed"]), "date": r["date"].isoformat(), "sub": r["sub"], "name": r["basin_name"]}
        for b, r in latest.items()
    }


def build_basin_monthly_mwmed(records: list[dict]) -> dict:
    """Monthly mean MWmed per basin per year."""
    bucket = defaultdict(lambda: defaultdict(list))
    for r in records:
        key = (r["basin"], r["date"].year, r["date"].month)
        bucket[key]["records"].append(r["mwmed"])

    monthly = defaultdict(lambda: defaultdict(lambda: [None] * 12))
    for (basin, year, month), data in bucket.items():
        monthly[basin][str(year)][month - 1] = round(mean(data["records"]))

    return {b: dict(ys) for b, ys in monthly.items()}


def main():
    print("=" * 60)
    print("ONS ENA bruta por bacia pipeline")
    print(f"Started: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)

    years = years_to_fetch()
    print(f"Years to fetch: {years}\n")

    records: list[dict] = []
    fetch_errors: list[str] = []
    for year in years:
        try:
            records.extend(fetch_ena_bacia_year(year))
        except Exception as e:
            msg = f"Year {year} failed: {e}"
            print(f"  WARN: {msg}")
            fetch_errors.append(msg)

    if not records:
        print("\nERROR: No basin data fetched. Aborting.")
        sys.exit(1)

    dates = [r["date"] for r in records]
    print(f"\nTotal records: {len(records)}, dates {min(dates)} → {max(dates)}")

    output = {
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": {
            "name": "ONS Dados Abertos — ENA Diário por Bacia",
            "url_template": ENA_BACIA_URL,
            "years": years,
            "fetch_errors": fetch_errors,
            "records_count": len(records),
            "note": "ENA Bruta (MWmed) is the runoff energy equivalent — proxy for precipitation accumulation per basin.",
        },
        "basin_order": BASIN_ORDER,
        "basin_meta": {
            bid: {"name": bname, "sub": sub}
            for key, (bid, bname, sub) in BASIN_MAP.items()
            if not any(c in key for c in ['Á', 'É', 'Í', 'Ó', 'Ú', 'Ç'])  # dedupe
        },
        "now": build_basin_now(records),
        "monthly_mwmed": build_basin_monthly_mwmed(records),
    }

    out_path = Path(__file__).parent.parent / "data" / "ena_bacia.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False, default=str))
    size_kb = out_path.stat().st_size / 1024
    print(f"\nWrote {out_path} ({size_kb:.1f} KB)")

    print("\n--- Summary ---")
    for bid in BASIN_ORDER:
        if bid in output["now"]:
            n = output["now"][bid]
            print(f"  {bid:18s} ({n['sub']:5s}): {n['mwmed']:7d} MWmed on {n['date']}")
        else:
            print(f"  {bid:18s}: MISSING")

    print("Done.")


if __name__ == "__main__":
    main()
