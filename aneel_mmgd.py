"""
ANEEL MMGD (Micro/Mini Geração Distribuída) pipeline

Streams the very large CSV of distributed generation installations in Brazil
(~millions of records, ~1-2 GB file) and aggregates to three views:

1. By UF (state) — top 27 states with installed capacity + connection count
2. By fonte (energy source) — solar fotovoltaica, eólica, biomassa, hídrica, etc.
3. By month — installed capacity growth over last 24 months

Each record has a connection date, a UF, a source type, an installed power (kW),
and a class (B1, B2, B3, A1, A4, etc.).

Source: ANEEL Dados Abertos — Relação de Empreendimentos de Mini e Micro Geração Distribuída

Outputs: data/mmgd.json
"""
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import stream_csv_rows, find_col, parse_date_flex, to_float

MMGD_URL = (
    "https://dadosabertos.aneel.gov.br/dataset/5e0fafd2-21b9-4d5b-b622-40438d40aba2/"
    "resource/b1bd71e7-d0ad-4214-9053-cbd58e9564a7/download/"
    "empreendimento-geracao-distribuida.csv"
)

# Map ANEEL source codes/names to canonical IDs
FONTE_MAP = {
    "UFV": "solar", "UFB": "solar",
    "FOTOVOLTAICA": "solar", "SOLAR": "solar", "SOLAR FOTOVOLTAICA": "solar",
    "EOL": "eolica", "EOLICA": "eolica", "EÓLICA": "eolica", "EOLICOELETRICA": "eolica",
    "BIO": "biomassa", "BIOMASSA": "biomassa", "TERMELETRICA A BIOMASSA": "biomassa",
    "TBM": "biomassa",
    "CGH": "hidrica", "PCH": "hidrica", "UHE": "hidrica",
    "HIDRICA": "hidrica", "HIDROELETRICA": "hidrica", "HIDRELETRICA": "hidrica",
}

# 27 Brazilian states + DF in canonical order
UF_ORDER = [
    # SE/CO
    "MG", "SP", "RJ", "ES", "GO", "MT", "MS", "DF",
    # S
    "PR", "SC", "RS",
    # NE
    "BA", "PE", "CE", "MA", "RN", "PB", "AL", "SE", "PI",
    # N
    "PA", "AM", "AC", "RO", "RR", "AP", "TO",
]


def normalize_fonte(raw: str) -> str:
    if not raw:
        return "outras"
    s = raw.strip().upper()
    if s in FONTE_MAP:
        return FONTE_MAP[s]
    # Substring search
    for k, v in FONTE_MAP.items():
        if k in s:
            return v
    return "outras"


def main():
    print("=" * 60)
    print("ANEEL MMGD aggregation pipeline")
    print(f"Started: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)
    print(f"URL: {MMGD_URL}")
    print("Streaming line-by-line (file is several hundred MB to ~2 GB — be patient)\n")

    by_uf = defaultdict(lambda: {"count": 0, "kw": 0.0})
    by_fonte = defaultdict(lambda: {"count": 0, "kw": 0.0})
    by_month = defaultdict(lambda: {"count": 0, "kw": 0.0})  # key: "YYYY-MM"
    by_uf_fonte = defaultdict(lambda: {"count": 0, "kw": 0.0})  # key: (uf, fonte)

    rows_read = 0
    rows_kept = 0
    sample_keys = None
    cols = {}

    for row in stream_csv_rows(MMGD_URL):
        rows_read += 1
        if sample_keys is None:
            sample_keys = list(row.keys())
            print(f"Columns detected ({len(sample_keys)}):")
            for k in sample_keys:
                print(f"  - {k!r}")
            cols["uf"] = (find_col(sample_keys, "siguf")
                          or find_col(sample_keys, "uf")
                          or find_col(sample_keys, "estado"))
            cols["fonte"] = (find_col(sample_keys, "sigtipo", "geracao")
                             or find_col(sample_keys, "dsctipo", "geracao")
                             or find_col(sample_keys, "fonte")
                             or find_col(sample_keys, "tipo", "geracao"))
            cols["kw"] = (find_col(sample_keys, "mdapotencia", "instalada")
                          or find_col(sample_keys, "potencia", "instalada")
                          or find_col(sample_keys, "kw"))
            cols["date"] = (find_col(sample_keys, "dthatualcadastral")
                            or find_col(sample_keys, "dthatualizacadastral")
                            or find_col(sample_keys, "data", "conexao")
                            or find_col(sample_keys, "data"))
            cols["classe"] = (find_col(sample_keys, "dscclasse")
                              or find_col(sample_keys, "classe"))
            cols["subgrupo"] = find_col(sample_keys, "subgrupo")
            print(f"\nResolved columns: {cols}\n")

        if rows_read % 100000 == 0:
            print(f"  ...processed {rows_read:,} rows, kept {rows_kept:,}")

        uf = (row.get(cols["uf"], "") or "").strip().upper()
        if not uf or uf not in UF_ORDER:
            continue
        fonte_raw = (row.get(cols["fonte"], "") or "").strip()
        fonte = normalize_fonte(fonte_raw)
        kw = to_float(row.get(cols["kw"], ""))
        if kw is None or kw <= 0:
            continue
        # Skip extreme outliers (sanity guard): MMGD is by definition <= 5 MW = 5000 kW per installation
        if kw > 5000:
            continue

        d = parse_date_flex(row.get(cols["date"], "") if cols.get("date") else "")
        ym = f"{d.year:04d}-{d.month:02d}" if d else None

        by_uf[uf]["count"] += 1
        by_uf[uf]["kw"] += kw
        by_fonte[fonte]["count"] += 1
        by_fonte[fonte]["kw"] += kw
        by_uf_fonte[(uf, fonte)]["count"] += 1
        by_uf_fonte[(uf, fonte)]["kw"] += kw
        if ym:
            by_month[ym]["count"] += 1
            by_month[ym]["kw"] += kw
        rows_kept += 1

    print(f"\nRows read: {rows_read:,}")
    print(f"Rows kept: {rows_kept:,}")
    if rows_kept == 0:
        print("ERROR: No valid records.")
        sys.exit(1)

    # Aggregates summary
    total_kw = sum(d["kw"] for d in by_uf.values())
    total_count = sum(d["count"] for d in by_uf.values())
    total_gw = total_kw / 1_000_000.0

    # Top UF list (all 27, ordered by capacity)
    uf_ranking = sorted(by_uf.items(), key=lambda x: x[1]["kw"], reverse=True)
    uf_list = [
        {
            "uf": uf,
            "kw": round(d["kw"]),
            "mw": round(d["kw"] / 1000.0, 1),
            "count": d["count"],
        }
        for uf, d in uf_ranking
    ]

    # Fonte breakdown
    fonte_list = [
        {
            "fonte": fonte,
            "kw": round(d["kw"]),
            "mw": round(d["kw"] / 1000.0, 1),
            "gw": round(d["kw"] / 1_000_000.0, 3),
            "count": d["count"],
            "pct_kw": round(d["kw"] / total_kw * 100, 2) if total_kw else 0,
        }
        for fonte, d in sorted(by_fonte.items(), key=lambda x: x[1]["kw"], reverse=True)
    ]

    # Monthly series for last 24 months (only past months)
    today = datetime.now(timezone.utc).date()
    months_sorted = sorted(by_month.keys())
    # Filter to recent past 24 months
    recent_24 = []
    # Build a deterministic list of last 24 months
    current_y = today.year
    current_m = today.month
    months_target = []
    y, m = current_y, current_m
    for _ in range(24):
        m -= 1
        if m == 0:
            m = 12
            y -= 1
        months_target.insert(0, f"{y:04d}-{m:02d}")

    for ym in months_target:
        d = by_month.get(ym, {"count": 0, "kw": 0.0})
        recent_24.append({
            "month": ym,
            "kw": round(d["kw"]),
            "mw": round(d["kw"] / 1000.0, 1),
            "count": d["count"],
        })

    output = {
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": {
            "name": "ANEEL Dados Abertos — Empreendimentos de Mini e Micro Geração Distribuída",
            "url": MMGD_URL,
            "rows_read": rows_read,
            "rows_kept": rows_kept,
            "note": "Empreendimentos de MMGD conectados (Lei 14.300/2022).",
        },
        "totals": {
            "kw": round(total_kw),
            "mw": round(total_kw / 1000.0, 1),
            "gw": round(total_gw, 3),
            "count": total_count,
        },
        "by_uf": uf_list,
        "by_fonte": fonte_list,
        "monthly_last_24m": recent_24,
    }

    out_path = Path(__file__).parent.parent / "data" / "mmgd.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    size_kb = out_path.stat().st_size / 1024
    print(f"\nWrote {out_path} ({size_kb:.1f} KB)")

    print("\n--- Summary ---")
    print(f"Total: {total_gw:.2f} GW from {total_count:,} installations")
    print("\nTop 10 UF by capacity:")
    for x in uf_list[:10]:
        print(f"  {x['uf']:3s}: {x['mw']:>10,.1f} MW   ({x['count']:,} installations)")
    print("\nBy fonte:")
    for x in fonte_list:
        print(f"  {x['fonte']:10s}: {x['mw']:>10,.1f} MW  ({x['pct_kw']:>5.2f}%, {x['count']:,} units)")
    print("\nLast 6 months growth:")
    for x in recent_24[-6:]:
        print(f"  {x['month']}: +{x['mw']:>8,.1f} MW from {x['count']:,} new")

    print("Done.")


if __name__ == "__main__":
    main()
