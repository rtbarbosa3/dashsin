"""
ANEEL MMGD pipeline v2

Streams the giant CSV and aggregates to multiple views:

1. by_uf — all 27 states with kW + count
2. by_fonte — solar, eolica, biomassa, hidrica, outras
3. by_modalidade — 'Geração na própria UC' vs other modalities (autoconsumo remoto, compartilhada, condomínio)
4. by_year — annual installation history since 2015 (cumulative & added per year)
5. monthly_last_24m — recent 24 months for trend

Also produces uf×modalidade and fonte×modalidade cross-tabs so the front can
filter by modalidade dynamically.

Source: ANEEL Dados Abertos — Empreendimentos MMGD
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

FONTE_MAP = {
    "UFV": "solar", "UFB": "solar",
    "FOTOVOLTAICA": "solar", "SOLAR": "solar", "SOLAR FOTOVOLTAICA": "solar",
    "EOL": "eolica", "EOLICA": "eolica", "EÓLICA": "eolica", "EOLICOELETRICA": "eolica",
    "BIO": "biomassa", "BIOMASSA": "biomassa", "TERMELETRICA A BIOMASSA": "biomassa",
    "TBM": "biomassa", "UTE": "biomassa",  # UTE in MMGD context = thermal, usually biomass
    "CGH": "hidrica", "PCH": "hidrica", "UHE": "hidrica",
    "HIDRICA": "hidrica", "HIDROELETRICA": "hidrica", "HIDRELETRICA": "hidrica",
}

# Canonical modalidades mapping
MODALIDADE_MAP = {
    "GERACAO NA PROPRIA UC": "propria_uc",
    "GERAÇÃO NA PROPRIA UC": "propria_uc",
    "GERAÇÃO NA PRÓPRIA UC": "propria_uc",
    "AUTOCONSUMO REMOTO": "autoconsumo_remoto",
    "AUTO CONSUMO REMOTO": "autoconsumo_remoto",
    "GERAÇÃO COMPARTILHADA": "compartilhada",
    "GERACAO COMPARTILHADA": "compartilhada",
    "COMPARTILHADA": "compartilhada",
    "CONDOMINIO": "condominio",
    "CONDOMÍNIO": "condominio",
    "EMPREENDIMENTO COM MÚLTIPLAS UC": "multipla_uc",
    "EMPREENDIMENTO COM MULTIPLAS UC": "multipla_uc",
}

UF_ORDER = [
    "MG", "SP", "RJ", "ES", "GO", "MT", "MS", "DF",
    "PR", "SC", "RS",
    "BA", "PE", "CE", "MA", "RN", "PB", "AL", "SE", "PI",
    "PA", "AM", "AC", "RO", "RR", "AP", "TO",
]

CURRENT_YEAR = datetime.now(timezone.utc).year


def normalize_fonte(raw: str) -> str:
    if not raw:
        return "outras"
    s = raw.strip().upper()
    if s in FONTE_MAP:
        return FONTE_MAP[s]
    for k, v in FONTE_MAP.items():
        if k in s:
            return v
    return "outras"


def normalize_modalidade(raw: str) -> str:
    if not raw:
        return "outras"
    s = raw.strip().upper()
    if s in MODALIDADE_MAP:
        return MODALIDADE_MAP[s]
    # Substring search
    if "PROPRIA" in s or "PRÓPRIA" in s:
        return "propria_uc"
    if "REMOTO" in s:
        return "autoconsumo_remoto"
    if "COMPARTILHADA" in s:
        return "compartilhada"
    if "CONDOMINIO" in s or "CONDOMÍNIO" in s:
        return "condominio"
    if "MULTIPLAS" in s or "MÚLTIPLAS" in s:
        return "multipla_uc"
    return "outras"


def main():
    print("=" * 60)
    print("ANEEL MMGD pipeline v2 (yearly + modalidade)")
    print(f"Started: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)
    print(f"URL: {MMGD_URL}")
    print("Streaming line-by-line — agregando 5 views diferentes\n")

    by_uf = defaultdict(lambda: {"count": 0, "kw": 0.0})
    by_fonte = defaultdict(lambda: {"count": 0, "kw": 0.0})
    by_modalidade = defaultdict(lambda: {"count": 0, "kw": 0.0})
    by_month = defaultdict(lambda: {"count": 0, "kw": 0.0})
    by_year = defaultdict(lambda: {"count": 0, "kw": 0.0})
    # Cross tabs for client-side filtering
    by_uf_modalidade = defaultdict(lambda: {"count": 0, "kw": 0.0})  # (uf, modalidade)
    by_fonte_modalidade = defaultdict(lambda: {"count": 0, "kw": 0.0})  # (fonte, modalidade)
    by_year_modalidade = defaultdict(lambda: {"count": 0, "kw": 0.0})  # (year, modalidade)

    rows_read = 0
    rows_kept = 0
    sample_keys = None
    cols = {}
    seen_modalidades_raw: set[str] = set()
    seen_fontes_raw: set[str] = set()

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
                             or find_col(sample_keys, "siggeracao")
                             or find_col(sample_keys, "fonte")
                             or find_col(sample_keys, "tipo", "geracao"))
            cols["kw"] = (find_col(sample_keys, "mdapotencia", "instalada")
                          or find_col(sample_keys, "potencia", "instalada")
                          or find_col(sample_keys, "kw"))
            cols["date"] = (find_col(sample_keys, "dthatualcadastral")
                            or find_col(sample_keys, "dthatualizacadastral")
                            or find_col(sample_keys, "data", "conexao")
                            or find_col(sample_keys, "dtconexao")
                            or find_col(sample_keys, "data"))
            cols["modalidade"] = (find_col(sample_keys, "dscmodalidade")
                                  or find_col(sample_keys, "sigmodalidade")
                                  or find_col(sample_keys, "modalidade"))
            print(f"\nResolved columns: {cols}\n")

        if rows_read % 200000 == 0:
            print(f"  ...processed {rows_read:,} rows, kept {rows_kept:,}")

        uf = (row.get(cols["uf"], "") or "").strip().upper()
        if not uf or uf not in UF_ORDER:
            continue

        fonte_raw = (row.get(cols["fonte"], "") or "").strip()
        if rows_kept < 20:
            seen_fontes_raw.add(fonte_raw[:30])
        fonte = normalize_fonte(fonte_raw)

        kw = to_float(row.get(cols["kw"], ""))
        if kw is None or kw <= 0 or kw > 5000:
            continue

        d = parse_date_flex(row.get(cols["date"], "") if cols.get("date") else "")
        ym = f"{d.year:04d}-{d.month:02d}" if d else None
        yr = d.year if d else None

        mod_raw = (row.get(cols["modalidade"], "") or "").strip() if cols.get("modalidade") else ""
        if rows_kept < 30:
            seen_modalidades_raw.add(mod_raw[:40])
        modalidade = normalize_modalidade(mod_raw)

        by_uf[uf]["count"] += 1
        by_uf[uf]["kw"] += kw
        by_fonte[fonte]["count"] += 1
        by_fonte[fonte]["kw"] += kw
        by_modalidade[modalidade]["count"] += 1
        by_modalidade[modalidade]["kw"] += kw
        by_uf_modalidade[(uf, modalidade)]["count"] += 1
        by_uf_modalidade[(uf, modalidade)]["kw"] += kw
        by_fonte_modalidade[(fonte, modalidade)]["count"] += 1
        by_fonte_modalidade[(fonte, modalidade)]["kw"] += kw

        if ym:
            by_month[ym]["count"] += 1
            by_month[ym]["kw"] += kw
        if yr and yr >= 2014:
            by_year[yr]["count"] += 1
            by_year[yr]["kw"] += kw
            by_year_modalidade[(yr, modalidade)]["count"] += 1
            by_year_modalidade[(yr, modalidade)]["kw"] += kw

        rows_kept += 1

    print(f"\nRows read: {rows_read:,}")
    print(f"Rows kept: {rows_kept:,}")
    print(f"Seen fontes raw: {seen_fontes_raw}")
    print(f"Seen modalidades raw: {seen_modalidades_raw}")
    if rows_kept == 0:
        print("ERROR: No valid records.")
        sys.exit(1)

    total_kw = sum(d["kw"] for d in by_uf.values())
    total_count = sum(d["count"] for d in by_uf.values())

    # by_uf list
    uf_ranking = sorted(by_uf.items(), key=lambda x: x[1]["kw"], reverse=True)
    uf_list = [
        {"uf": uf, "kw": round(d["kw"]), "mw": round(d["kw"]/1000.0, 1), "count": d["count"]}
        for uf, d in uf_ranking
    ]

    # by_fonte list
    fonte_list = [
        {"fonte": f, "kw": round(d["kw"]), "mw": round(d["kw"]/1000.0, 1),
         "gw": round(d["kw"]/1_000_000.0, 3), "count": d["count"],
         "pct_kw": round(d["kw"]/total_kw*100, 2) if total_kw else 0}
        for f, d in sorted(by_fonte.items(), key=lambda x: x[1]["kw"], reverse=True)
    ]

    # by_modalidade list
    modalidade_list = [
        {"modalidade": m, "kw": round(d["kw"]), "mw": round(d["kw"]/1000.0, 1),
         "gw": round(d["kw"]/1_000_000.0, 3), "count": d["count"],
         "pct_kw": round(d["kw"]/total_kw*100, 2) if total_kw else 0}
        for m, d in sorted(by_modalidade.items(), key=lambda x: x[1]["kw"], reverse=True)
    ]

    # by_year: annual since 2015 (with cumulative)
    years_data = []
    cum_kw = 0.0
    cum_count = 0
    for yr in range(2015, CURRENT_YEAR + 1):
        d = by_year.get(yr, {"count": 0, "kw": 0.0})
        cum_kw += d["kw"]
        cum_count += d["count"]
        years_data.append({
            "year": yr,
            "added_kw": round(d["kw"]),
            "added_mw": round(d["kw"]/1000.0, 1),
            "added_gw": round(d["kw"]/1_000_000.0, 3),
            "added_count": d["count"],
            "cumulative_mw": round(cum_kw/1000.0, 1),
            "cumulative_gw": round(cum_kw/1_000_000.0, 3),
            "cumulative_count": cum_count,
        })

    # monthly_last_24m
    today = datetime.now(timezone.utc).date()
    months_target = []
    y, m = today.year, today.month
    for _ in range(24):
        m -= 1
        if m == 0:
            m = 12; y -= 1
        months_target.insert(0, f"{y:04d}-{m:02d}")
    recent_24 = [
        {"month": ym, "kw": round(by_month.get(ym, {}).get("kw", 0)),
         "mw": round(by_month.get(ym, {}).get("kw", 0)/1000.0, 1),
         "count": by_month.get(ym, {}).get("count", 0)}
        for ym in months_target
    ]

    # Cross-tabs as nested dicts for client-side filtering
    uf_x_mod = defaultdict(dict)
    for (uf, mod), d in by_uf_modalidade.items():
        uf_x_mod[uf][mod] = {"kw": round(d["kw"]), "count": d["count"]}
    fonte_x_mod = defaultdict(dict)
    for (fonte, mod), d in by_fonte_modalidade.items():
        fonte_x_mod[fonte][mod] = {"kw": round(d["kw"]), "count": d["count"]}
    year_x_mod = defaultdict(dict)
    for (yr, mod), d in by_year_modalidade.items():
        year_x_mod[yr][mod] = {"kw": round(d["kw"]), "count": d["count"]}

    output = {
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": {
            "name": "ANEEL Dados Abertos — Empreendimentos MMGD",
            "url": MMGD_URL,
            "rows_read": rows_read,
            "rows_kept": rows_kept,
            "note": "Empreendimentos de MMGD conectados (Lei 14.300/2022). Modalidades: propria_uc, autoconsumo_remoto, compartilhada, condominio.",
        },
        "totals": {
            "kw": round(total_kw), "mw": round(total_kw/1000.0, 1),
            "gw": round(total_kw/1_000_000.0, 3), "count": total_count,
        },
        "by_uf": uf_list,
        "by_fonte": fonte_list,
        "by_modalidade": modalidade_list,
        "by_year": years_data,
        "monthly_last_24m": recent_24,
        "cross_tabs": {
            "uf_by_modalidade": dict(uf_x_mod),
            "fonte_by_modalidade": dict(fonte_x_mod),
            "year_by_modalidade": {str(yr): mods for yr, mods in year_x_mod.items()},
        },
    }

    out_path = Path(__file__).parent.parent / "data" / "mmgd.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    size_kb = out_path.stat().st_size / 1024
    print(f"\nWrote {out_path} ({size_kb:.1f} KB)")

    print("\n--- Summary ---")
    print(f"Total: {total_kw/1_000_000:.2f} GW from {total_count:,} installations")
    print("\nBy modalidade:")
    for x in modalidade_list:
        print(f"  {x['modalidade']:22s}: {x['gw']:>6.3f} GW  ({x['pct_kw']:>5.2f}%, {x['count']:,} unidades)")
    print("\nBy year (cumulative):")
    for y in years_data:
        print(f"  {y['year']}: +{y['added_gw']:>6.3f} GW ({y['added_count']:>7,} new)  cumulative: {y['cumulative_gw']:>6.3f} GW")
    print("\nTop 5 UF:")
    for x in uf_list[:5]:
        print(f"  {x['uf']:3s}: {x['mw']:>10,.1f} MW  ({x['count']:,} installations)")
    print("Done.")


if __name__ == "__main__":
    main()
