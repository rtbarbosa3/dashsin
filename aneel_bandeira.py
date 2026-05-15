"""
ANEEL Bandeira Tarifária pipeline

Downloads the monthly tariff flag activation history from ANEEL Dados Abertos.
The bandeira (verde/amarela/vermelha 1/vermelha 2) signals the wholesale energy
cost regime to captive market consumers.

Source: ANEEL Dados Abertos — Bandeiras Tarifárias - Acionamento

Outputs: data/bandeira.json with current month + last 24 months
"""
import json
import sys
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import fetch_text, parse_csv, find_col, parse_date_flex

# Resource UUID for "Bandeira Tarifária - Acionamento"
BANDEIRA_URL = (
    "https://dadosabertos.aneel.gov.br/dataset/bandeiras-tarifarias/resource/"
    "0591b8f6-fe54-437b-b72b-1aa2efd46e42/download/bandeira-tarifaria-acionamento.csv"
)

# Normalize bandeira names to canonical IDs and display labels
BANDEIRA_MAP = {
    "VERDE": ("verde", "Verde"),
    "AMARELA": ("amarela", "Amarela"),
    "VERMELHA - PATAMAR 1": ("vermelha1", "Vermelha P1"),
    "VERMELHA - PATAMAR 2": ("vermelha2", "Vermelha P2"),
    "VERMELHA PATAMAR 1": ("vermelha1", "Vermelha P1"),
    "VERMELHA PATAMAR 2": ("vermelha2", "Vermelha P2"),
    "VERMELHA P1": ("vermelha1", "Vermelha P1"),
    "VERMELHA P2": ("vermelha2", "Vermelha P2"),
    "ESCASSEZ HIDRICA": ("escassez", "Escassez Hídrica"),
    "ESCASSEZ HÍDRICA": ("escassez", "Escassez Hídrica"),
}


def normalize_bandeira(raw: str) -> tuple[str, str]:
    """Returns (canonical_id, display_label) or (raw_lower, raw) if not in map."""
    if not raw:
        return ("desconhecida", "—")
    key = raw.strip().upper()
    if key in BANDEIRA_MAP:
        return BANDEIRA_MAP[key]
    # Fuzzy: search for color keywords
    if "VERDE" in key:
        return ("verde", "Verde")
    if "AMARELA" in key:
        return ("amarela", "Amarela")
    if "VERMELHA" in key:
        if "2" in key:
            return ("vermelha2", "Vermelha P2")
        return ("vermelha1", "Vermelha P1")
    return (key.lower().replace(" ", "_"), raw.strip())


def main():
    print("=" * 60)
    print("ANEEL Bandeira Tarifária pipeline")
    print(f"Started: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)

    print(f"Fetching: {BANDEIRA_URL}")
    text = fetch_text(BANDEIRA_URL)
    rows = parse_csv(text)
    if not rows:
        print("ERROR: No data parsed.")
        sys.exit(1)

    keys = list(rows[0].keys())
    print(f"Columns detected: {keys}")

    # Common column names in ANEEL CSV:
    #   "Data_Inicio_Vigencia" or "DatInicioVigencia" or "Periodo_de_Competencia"
    #   "Bandeira_Acionamento" or "Bandeira" or "Tipo_Bandeira"
    col_date = (find_col(keys, "inicio", "vigencia")
                or find_col(keys, "data", "inicio")
                or find_col(keys, "periodo", "competencia")
                or find_col(keys, "competencia")
                or find_col(keys, "data"))
    col_band = (find_col(keys, "bandeira", "acionamento")
                or find_col(keys, "tipo", "bandeira")
                or find_col(keys, "bandeira"))
    print(f"  date column:    {col_date!r}")
    print(f"  bandeira col:   {col_band!r}")

    if not col_date or not col_band:
        print(f"ERROR: Could not resolve columns. Available: {keys}")
        sys.exit(1)

    # Parse each record into (year, month, bandeira_canonical, display)
    records = []
    for r in rows:
        d = parse_date_flex(r.get(col_date, ""))
        if d is None:
            # ANEEL sometimes uses "YYYY-MM" or "MM/YYYY" format directly
            raw = (r.get(col_date) or "").strip()
            try:
                if "/" in raw:
                    parts = raw.split("/")
                    if len(parts) == 2:
                        month = int(parts[0]); year = int(parts[1])
                        d = datetime(year, month, 1).date()
                elif "-" in raw and len(raw) == 7:  # YYYY-MM
                    year = int(raw[:4]); month = int(raw[5:7])
                    d = datetime(year, month, 1).date()
            except (ValueError, IndexError):
                pass
        if d is None:
            continue
        b_id, b_label = normalize_bandeira(r.get(col_band, ""))
        records.append({
            "year": d.year, "month": d.month,
            "bandeira": b_id, "label": b_label,
        })

    # Deduplicate by (year, month), keep the latest entry in row order
    seen = OrderedDict()
    for rec in sorted(records, key=lambda x: (x["year"], x["month"])):
        seen[(rec["year"], rec["month"])] = rec
    records = list(seen.values())

    print(f"Parsed {len(records)} months total")
    if records:
        print(f"  range: {records[0]['year']}-{records[0]['month']:02d} → {records[-1]['year']}-{records[-1]['month']:02d}")

    if not records:
        print("ERROR: No bandeira records.")
        sys.exit(1)

    # Last 24 months for display
    recent = records[-24:]
    current = records[-1]

    # Count streak: months in current bandeira
    streak = 1
    for r in reversed(records[:-1]):
        if r["bandeira"] == current["bandeira"]:
            streak += 1
        else:
            break

    output = {
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": {
            "name": "ANEEL Dados Abertos — Bandeira Tarifária - Acionamento",
            "url": BANDEIRA_URL,
            "records_total": len(records),
        },
        "current": {
            "year": current["year"],
            "month": current["month"],
            "bandeira": current["bandeira"],
            "label": current["label"],
            "streak_months": streak,
        },
        "recent_24m": recent,
        "all_records": records,
    }

    out_path = Path(__file__).parent.parent / "data" / "bandeira.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    size_kb = out_path.stat().st_size / 1024
    print(f"\nWrote {out_path} ({size_kb:.1f} KB)")

    print("\n--- Summary ---")
    print(f"Current bandeira: {current['label']} ({current['year']}-{current['month']:02d}, {streak} months)")
    print("Recent 12m:")
    for r in recent[-12:]:
        print(f"  {r['year']}-{r['month']:02d}: {r['label']}")
    print("Done.")


if __name__ == "__main__":
    main()
