"""
CCEE PLD (Preço de Liquidação das Diferenças) daily pipeline.

Fetches daily PLD by submercado from CCEE Dados Abertos.
Aggregates to daily, monthly, and yearly statistics.

CCEE publishes one CSV per year. We use the package_show CKAN API to
discover current resource URLs, falling back to known UUIDs.

CSV schema:
  MES_REFERENCIA;SUBMERCADO;DIA;PLD_MEDIA_DIA
  202603;NORDESTE;10/03/2026;224.12
  202603;NORTE;10/03/2026;224.12
  202603;SUDESTE;10/03/2026;342.15
  202603;SUL;10/03/2026;511.32

- Separator: `;`
- Submarkets: NORDESTE, NORTE, SUDESTE, SUL  (we map to NE/N/SECO/SUL)
- Date: DD/MM/YYYY
- Value: R$/MWh (Brazilian decimal: `224.12`)

Outputs: data/pld.json
"""
import csv
import io
import json
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import mean, pstdev

sys.path.insert(0, str(Path(__file__).parent))
from common import fetch_text

# Known resource UUIDs for each year. The CKAN API also exposes these
# via package_show, but hardcoding makes the pipeline more resilient.
# Resource UUIDs are STABLE — they don't change per re-upload.
PLD_RESOURCES: dict[int, str] = {
    2021: "9e152b60-f75c-4219-bcee-6033d287e0ab",
    2022: "6ccbf348-66ca-4bb1-a329-f607761fdf11",
    2023: "f28d0cb3-1afa-4b55-bf90-71c68b28272a",
    2024: "ed66d3dd-1987-4460-9164-20e169ad36fc",
    2025: "8b81daa1-8155-4fe1-9ee3-e01beb42fcc8",
    2026: "3ca83769-de89-4dc5-84a7-0128167b594d",
}

# CKAN resource_show endpoint returns metadata including the download URL
CKAN_RESOURCE_SHOW = "https://dadosabertos.ccee.org.br/api/3/action/resource_show?id={uuid}"

# Submarket name mapping (PT → internal abbreviation)
SUB_MAP = {
    "SUDESTE": "SECO",
    "SUDESTE/CENTRO-OESTE": "SECO",  # if CCEE renames
    "SECO": "SECO",
    "SUL": "SUL",
    "NORDESTE": "NE",
    "NE": "NE",
    "NORTE": "N",
    "N": "N",
}

CANONICAL_SUBS = ("SECO", "SUL", "NE", "N")

# History window: persist 2021+ to match CCEE Dados Abertos coverage
HISTORY_START_YEAR = 2021


def fetch_resource_url(uuid: str) -> str:
    """Query CKAN resource_show for the actual download URL."""
    api_url = CKAN_RESOURCE_SHOW.format(uuid=uuid)
    text = fetch_text(api_url, retries=3, backoff=2.0)
    data = json.loads(text)
    if not data.get("success"):
        raise RuntimeError(f"CKAN API returned success=false for {uuid}: {data.get('error')}")
    return data["result"]["url"]


def fetch_pld_year(year: int) -> list[dict]:
    """Returns list of {sub, date, pld} records for the year.

    Skips rows with unparseable dates, unknown submarkets, or non-numeric prices.
    """
    uuid = PLD_RESOURCES.get(year)
    if not uuid:
        print(f"  no resource UUID for {year}, skipping")
        return []

    try:
        url = fetch_resource_url(uuid)
    except Exception as e:
        print(f"  failed to discover URL for {year}: {e}")
        return []

    print(f"  fetching {url[:120]}...")
    text = fetch_text(url, retries=3, backoff=3.0)
    # CSV may come as latin-1 or utf-8 (BOM); fetch_text handles encoding
    reader = csv.reader(io.StringIO(text), delimiter=";")
    header = next(reader, None)
    if not header:
        print(f"  empty CSV for {year}")
        return []

    # Resolve column indices
    h_norm = [h.strip().upper().replace("Á", "A").replace("É", "E") for h in header]
    try:
        sub_idx = next(i for i, h in enumerate(h_norm) if h in ("SUBMERCADO", "SUBMERCADOS"))
        dia_idx = next(i for i, h in enumerate(h_norm) if h in ("DIA", "DATA", "DATE"))
        val_idx = next(i for i, h in enumerate(h_norm) if "PLD" in h and "MEDIA" in h)
    except StopIteration:
        print(f"  CSV header doesn't match expected schema for {year}: {header}")
        return []

    records: list[dict] = []
    skipped = 0
    for row in reader:
        if len(row) <= max(sub_idx, dia_idx, val_idx):
            skipped += 1
            continue
        sub_raw = (row[sub_idx] or "").strip().upper()
        sub = SUB_MAP.get(sub_raw)
        if sub not in CANONICAL_SUBS:
            skipped += 1
            continue

        # Date: DD/MM/YYYY (most common) or YYYY-MM-DD (legacy)
        dia_raw = (row[dia_idx] or "").strip()
        d = None
        for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
            try:
                d = datetime.strptime(dia_raw, fmt).date()
                break
            except ValueError:
                continue
        if d is None:
            skipped += 1
            continue

        # Value: Brazilian decimal might use either `.` or `,`
        val_raw = (row[val_idx] or "").strip().replace(",", ".")
        try:
            pld = float(val_raw)
            if pld < 0:
                skipped += 1
                continue
        except ValueError:
            skipped += 1
            continue

        records.append({"sub": sub, "date": d, "pld": round(pld, 2)})

    print(f"  parsed {len(records):,} rows (skipped {skipped:,})")
    return records


def build_daily_by_year(records: list[dict]) -> dict[str, dict[str, list[float | None]]]:
    """Returns {sub: {year_str: [366 daily values]}}.
    Slot index = day_of_year - 1 (0..365). Slot 365 is None in non-leap years.
    """
    daily: dict = defaultdict(lambda: defaultdict(lambda: [None] * 366))
    for r in records:
        doy = r["date"].timetuple().tm_yday - 1
        if 0 <= doy < 366:
            daily[r["sub"]][str(r["date"].year)][doy] = r["pld"]
    return {sub: dict(years) for sub, years in daily.items()}


def build_monthly_avg(records: list[dict]) -> dict[str, dict[str, list[float | None]]]:
    """Returns {sub: {year_str: [12 monthly average values]}}."""
    bucket: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for r in records:
        bucket[r["sub"]][str(r["date"].year)][r["date"].month - 1].append(r["pld"])

    monthly: dict = {}
    for sub, years in bucket.items():
        monthly[sub] = {}
        for yr, months in years.items():
            arr: list[float | None] = [None] * 12
            for m_idx, vals in months.items():
                if vals:
                    arr[m_idx] = round(mean(vals), 2)
            monthly[sub][yr] = arr
    return monthly


def build_year_stats(records: list[dict]) -> dict[str, dict[str, dict]]:
    """Returns {sub: {year_str: {avg, min, max, std, ytd_days}}}."""
    bucket: dict = defaultdict(lambda: defaultdict(list))
    for r in records:
        bucket[r["sub"]][str(r["date"].year)].append(r["pld"])

    stats: dict = {}
    for sub, years in bucket.items():
        stats[sub] = {}
        for yr, vals in years.items():
            if not vals:
                continue
            stats[sub][yr] = {
                "avg": round(mean(vals), 2),
                "min": round(min(vals), 2),
                "max": round(max(vals), 2),
                "std": round(pstdev(vals) if len(vals) > 1 else 0.0, 2),
                "days": len(vals),
            }
    return stats


def build_now(records: list[dict]) -> dict[str, dict]:
    """Returns latest PLD per submarket: {sub: {pld, date}}."""
    latest: dict[str, tuple[date, float]] = {}
    for r in records:
        cur = latest.get(r["sub"])
        if cur is None or r["date"] > cur[0]:
            latest[r["sub"]] = (r["date"], r["pld"])

    return {
        sub: {"pld": pld, "date": d.isoformat()}
        for sub, (d, pld) in latest.items()
    }


def main():
    print("=" * 60)
    print("CCEE PLD daily pipeline")
    print(f"Started: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)

    today = datetime.now(timezone.utc).date()
    current_year = today.year

    all_records: list[dict] = []
    fetch_errors: list[str] = []

    for year in sorted(PLD_RESOURCES.keys()):
        if year > current_year:
            continue
        if year < HISTORY_START_YEAR:
            continue
        print(f"\n[{year}]")
        try:
            recs = fetch_pld_year(year)
            all_records.extend(recs)
        except Exception as e:
            msg = f"{year} failed: {e}"
            print(f"  ERROR: {msg}")
            fetch_errors.append(msg)

    print(f"\nTotal records: {len(all_records):,}")
    if not all_records:
        print("\nERROR: No PLD data fetched. Aborting.")
        sys.exit(1)

    # Build aggregations
    daily_by_year = build_daily_by_year(all_records)
    monthly_avg = build_monthly_avg(all_records)
    year_stats = build_year_stats(all_records)
    now_data = build_now(all_records)

    # Print summary
    print("\n--- Year stats (avg PLD by submarket) ---")
    print(f"{'YEAR':<6} " + " ".join(f"{s:>10}" for s in CANONICAL_SUBS))
    all_years = sorted({yr for sub_stats in year_stats.values() for yr in sub_stats.keys()})
    for yr in all_years:
        cells = []
        for sub in CANONICAL_SUBS:
            ys = year_stats.get(sub, {}).get(yr)
            cells.append(f"{ys['avg']:>10.2f}" if ys else f"{'—':>10}")
        print(f"{yr:<6} " + " ".join(cells))

    print("\n--- Latest PLD ---")
    for sub in CANONICAL_SUBS:
        n = now_data.get(sub)
        if n:
            print(f"  {sub:<5}: R$ {n['pld']:>7.2f}/MWh on {n['date']}")
        else:
            print(f"  {sub:<5}: no data")

    output = {
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": {
            "name": "CCEE Dados Abertos — PLD_MEDIA_DIARIA",
            "url": "https://dadosabertos.ccee.org.br/dataset/pld_media_diaria",
            "rows_kept": len(all_records),
            "history_start": HISTORY_START_YEAR,
            "fetch_errors": fetch_errors,
            "note": (
                "Daily average PLD (Preço de Liquidação das Diferenças) per submercado "
                "in R$/MWh. CCEE calculates hourly PLD and publishes daily averages."
            ),
        },
        "submarkets": list(CANONICAL_SUBS),
        "now": now_data,
        "daily_by_year": daily_by_year,
        "monthly_avg": monthly_avg,
        "year_stats": year_stats,
    }

    out_path = Path(__file__).parent.parent / "data" / "pld.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False, default=str))
    size_kb = out_path.stat().st_size / 1024
    print(f"\nWrote {out_path} ({size_kb:.1f} KB)")
    print("Done.")


if __name__ == "__main__":
    main()
