"""
NOAA CPC ONI pipeline

Downloads the Oceanic Niño Index (ONI) — the 3-month running mean of SST
anomalies in the Niño 3.4 region. Used to classify El Niño / Neutral / La Niña.

Source: NOAA Climate Prediction Center
URL: https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt

Format (whitespace-separated):
    SEAS YR TOTAL ANOM
    DJF 1950 24.72 -1.53
    ...

SEAS is a 3-letter month code representing 3-month rolling avg. We map to the
center month: DJF → Jan, JFM → Feb, FMA → Mar, etc.

Outputs: data/oni.json
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import fetch_text

ONI_URL = "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt"

# Map 3-month season to center month (1-12)
SEASON_TO_MONTH = {
    'DJF': 1, 'JFM': 2, 'FMA': 3, 'MAM': 4, 'AMJ': 5, 'MJJ': 6,
    'JJA': 7, 'JAS': 8, 'ASO': 9, 'SON': 10, 'OND': 11, 'NDJ': 12,
}


def classify(anom: float) -> str:
    if anom >= 0.5:
        return "El Niño"
    elif anom <= -0.5:
        return "La Niña"
    return "Neutral"


def parse_oni(text: str) -> list[dict]:
    """Parse ONI ASCII file, return list of records sorted oldest first."""
    out = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        seas = parts[0].upper()
        if seas == "SEAS":  # header
            continue
        if seas not in SEASON_TO_MONTH:
            continue
        try:
            year = int(parts[1])
            anom = float(parts[3])
        except (ValueError, IndexError):
            continue
        month = SEASON_TO_MONTH[seas]
        # DJF refers to December of (year-1) + Jan + Feb of (year)
        # We label it as January of `year`
        out.append({
            "year": year,
            "month": month,
            "season": seas,
            "anom": round(anom, 2),
            "classification": classify(anom),
        })
    return sorted(out, key=lambda r: (r["year"], r["month"]))


def main():
    print("=" * 60)
    print("NOAA CPC ONI pipeline")
    print(f"Started: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)

    print(f"Fetching: {ONI_URL}")
    text = fetch_text(ONI_URL)
    print(f"  Downloaded {len(text)} bytes")

    records = parse_oni(text)
    print(f"  Parsed {len(records)} monthly records")
    print(f"  Range: {records[0]['year']}-{records[0]['month']:02d} → {records[-1]['year']}-{records[-1]['month']:02d}")

    # For the chart, expose the most recent 30 months
    recent = records[-30:]

    # Identify current phase from last record
    last = records[-1]
    current_phase = last["classification"]

    # Count months in current phase (streak)
    streak = 1
    for r in reversed(records[:-1]):
        if r["classification"] == current_phase:
            streak += 1
        else:
            break

    output = {
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": {
            "name": "NOAA Climate Prediction Center — Oceanic Niño Index",
            "url": ONI_URL,
            "records_count": len(records),
            "note": "ONI = 3-month running mean SST anomaly in Niño 3.4 region. ±0.5 °C is the El Niño / La Niña threshold.",
        },
        "current": {
            "year": last["year"],
            "month": last["month"],
            "season": last["season"],
            "anom": last["anom"],
            "phase": current_phase,
            "streak_months": streak,
        },
        "recent_30m": recent,
        "all_records_since_1950": records,  # full history for any future use
    }

    out_path = Path(__file__).parent.parent / "data" / "oni.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    size_kb = out_path.stat().st_size / 1024
    print(f"\nWrote {out_path} ({size_kb:.1f} KB)")

    print("\n--- Summary ---")
    print(f"Current ONI:   {last['anom']:+.2f} ({last['season']} {last['year']}) — {current_phase}")
    print(f"Streak:        {streak} months")
    trend_str = ' → '.join(f"{r['anom']:+.1f}" for r in recent[-6:])
    print(f"Recent trend:  {trend_str}")
    print("Done.")


if __name__ == "__main__":
    main()
