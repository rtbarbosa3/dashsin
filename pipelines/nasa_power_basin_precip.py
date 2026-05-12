"""
NASA POWER precipitation by basin pipeline

For each of 8 main basins, queries NASA POWER (MERRA-2 reanalysis) for daily
precipitation in mm and aggregates to monthly totals. Also computes MLT
(long-term mean) climatology using 2014-2023 (10-year period).

NASA POWER documentation:
  https://power.larc.nasa.gov/docs/services/api/temporal/daily/

Variable: PRECTOTCORR (Precipitation Corrected, mm/day)
Source: MERRA-2 reanalysis + station bias correction
Resolution: 0.5° × 0.625° grid (~50 km)

Outputs: data/precip_bacia.json
"""
import json
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone, date
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).parent))
from common import fetch_text

# Basin centroids - representative point per basin for NASA POWER query
# Selected near hydrographic center of mass for each basin
BASIN_CENTROIDS = {
    'paranaiba':     {'lat': -18.5, 'lon': -49.0, 'name': 'Paranaíba',     'sub': 'SECO'},
    'grande':        {'lat': -20.5, 'lon': -47.0, 'name': 'Grande',        'sub': 'SECO'},
    'parana':        {'lat': -23.5, 'lon': -52.5, 'name': 'Paraná',        'sub': 'SECO'},
    'iguacu':        {'lat': -25.5, 'lon': -51.5, 'name': 'Iguaçu',        'sub': 'SUL'},
    'uruguai':       {'lat': -27.5, 'lon': -53.5, 'name': 'Uruguai',       'sub': 'SUL'},
    'sao_francisco': {'lat': -14.0, 'lon': -44.0, 'name': 'São Francisco', 'sub': 'NE'},
    'parnaiba':      {'lat':  -7.5, 'lon': -44.5, 'name': 'Parnaíba',      'sub': 'NE'},
    'tocantins':     {'lat': -10.0, 'lon': -48.5, 'name': 'Tocantins',     'sub': 'N'},
}

BASIN_ORDER = ['paranaiba', 'grande', 'parana', 'iguacu', 'uruguai', 'sao_francisco', 'parnaiba', 'tocantins']

POWER_URL = (
    "https://power.larc.nasa.gov/api/temporal/daily/point"
    "?parameters=PRECTOTCORR"
    "&community=AG"
    "&longitude={lon}"
    "&latitude={lat}"
    "&start={start}"
    "&end={end}"
    "&format=JSON"
)

# MLT climatology window (10 years) and display window (current + 2 prior years)
MLT_START_YEAR = 2014
MLT_END_YEAR = 2023
DISPLAY_YEARS_BACK = 2  # 2 prior years + current year


def fetch_basin_daily(lat: float, lon: float, start_date: date, end_date: date) -> dict[str, float]:
    """Returns {YYYYMMDD: mm_precip} dict. -999 values (no-data) are filtered out."""
    url = POWER_URL.format(
        lat=lat, lon=lon,
        start=start_date.strftime("%Y%m%d"),
        end=end_date.strftime("%Y%m%d"),
    )
    print(f"    GET {url[:120]}...")
    text = fetch_text(url, retries=3, backoff=3.0)
    j = json.loads(text)
    raw = j.get("properties", {}).get("parameter", {}).get("PRECTOTCORR", {})
    # NASA POWER uses -999 to indicate missing data
    return {k: v for k, v in raw.items() if v is not None and v > -900}


def daily_to_monthly_sum(daily: dict[str, float]) -> dict[tuple[int, int], float]:
    """{YYYYMMDD: mm} -> {(year, month): sum_mm}."""
    out = defaultdict(float)
    counts = defaultdict(int)
    for ymd, mm in daily.items():
        try:
            year = int(ymd[:4])
            month = int(ymd[4:6])
        except (ValueError, IndexError):
            continue
        out[(year, month)] += mm
        counts[(year, month)] += 1
    # Drop months with significantly missing data (< 25 days reported)
    result = {}
    for ym, total in out.items():
        if counts[ym] >= 25:
            result[ym] = round(total, 1)
    return result


def compute_mlt(monthly_sums: dict[tuple[int, int], float], start_year: int, end_year: int) -> list[float | None]:
    """Compute long-term mean per month (Jan-Dec) over [start_year, end_year] inclusive."""
    per_month = defaultdict(list)
    for (year, month), total in monthly_sums.items():
        if start_year <= year <= end_year:
            per_month[month].append(total)
    out: list[float | None] = [None] * 12
    for m in range(1, 13):
        if per_month[m]:
            out[m - 1] = round(mean(per_month[m]), 1)
    return out


def monthly_for_year(monthly_sums: dict[tuple[int, int], float], year: int) -> list[float | None]:
    """Returns 12-element array [Jan..Dec], None for missing months."""
    out: list[float | None] = [None] * 12
    for m in range(1, 13):
        if (year, m) in monthly_sums:
            out[m - 1] = monthly_sums[(year, m)]
    return out


def main():
    print("=" * 60)
    print("NASA POWER precipitation by basin pipeline")
    print(f"Started: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)

    today = datetime.now(timezone.utc).date()
    current_year = today.year

    # Cover MLT window + recent years for display
    start_date = date(MLT_START_YEAR, 1, 1)
    end_date = today

    print(f"Date range: {start_date} → {end_date}")
    print(f"MLT window: {MLT_START_YEAR}-{MLT_END_YEAR}")
    print(f"Display years: {current_year - DISPLAY_YEARS_BACK}, {current_year - 1}, {current_year}")
    print()

    basins_out: dict[str, dict] = {}
    fetch_errors: list[str] = []

    for basin_id in BASIN_ORDER:
        meta = BASIN_CENTROIDS[basin_id]
        print(f"[{basin_id}] {meta['name']} ({meta['sub']}) @ {meta['lat']}, {meta['lon']}")
        try:
            daily = fetch_basin_daily(meta['lat'], meta['lon'], start_date, end_date)
            print(f"    parsed {len(daily)} daily records")
            if len(daily) < 365:
                print(f"    WARN: only {len(daily)} daily records - basin may be incomplete")
                fetch_errors.append(f"{basin_id}: only {len(daily)} daily records")
            monthly_sums = daily_to_monthly_sum(daily)
            print(f"    {len(monthly_sums)} complete months")

            mlt = compute_mlt(monthly_sums, MLT_START_YEAR, MLT_END_YEAR)
            yr_data: dict[str, list] = {}
            for yr in range(current_year - DISPLAY_YEARS_BACK, current_year + 1):
                yr_data[str(yr)] = monthly_for_year(monthly_sums, yr)

            basins_out[basin_id] = {
                'lat': meta['lat'],
                'lon': meta['lon'],
                'name': meta['name'],
                'sub': meta['sub'],
                'mlt': mlt,
                'monthly': yr_data,
            }
            # Be kind to NASA POWER - small pause between basins
            time.sleep(1)
        except Exception as e:
            msg = f"{basin_id} failed: {e}"
            print(f"    ERROR: {msg}")
            fetch_errors.append(msg)

    if not basins_out:
        print("\nERROR: No basin data fetched.")
        sys.exit(1)

    output = {
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": {
            "name": "NASA POWER (MERRA-2 reanalysis, station bias-corrected)",
            "variable": "PRECTOTCORR",
            "url_template": POWER_URL.split('?')[0],
            "mlt_window": f"{MLT_START_YEAR}-{MLT_END_YEAR}",
            "fetch_errors": fetch_errors,
            "note": (
                "Precipitation in mm/month aggregated from daily PRECTOTCORR at a single "
                "representative centroid per basin. NASA POWER uses MERRA-2 reanalysis with "
                "satellite + station bias correction at ~0.5° resolution."
            ),
        },
        "basin_order": BASIN_ORDER,
        "basins": basins_out,
    }

    out_path = Path(__file__).parent.parent / "data" / "precip_bacia.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False, default=str))
    size_kb = out_path.stat().st_size / 1024
    print(f"\nWrote {out_path} ({size_kb:.1f} KB)")

    print("\n--- Summary (current year YTD totals) ---")
    for bid in BASIN_ORDER:
        if bid in basins_out:
            b = basins_out[bid]
            cur_yr = b['monthly'].get(str(current_year), [])
            ytd = sum(v for v in cur_yr if v is not None)
            mlt_ytd = sum(b['mlt'][:len([v for v in cur_yr if v is not None])])
            pct = ytd / mlt_ytd * 100 if mlt_ytd else 0
            print(f"  {bid:18s} ({b['sub']:5s}): {ytd:6.0f} mm YTD ({pct:.0f}% of MLT)")
        else:
            print(f"  {bid:18s}: MISSING")

    print("Done.")


if __name__ == "__main__":
    main()
