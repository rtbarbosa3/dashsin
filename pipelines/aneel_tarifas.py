"""
ANEEL Tarifas Homologadas pipeline

Streams the large CSV of homologated tariffs for all distributors in Brazil
and extracts the latest readjustment data for B1 (Residencial) and A4 (Industrial 2.3-25 kV).

For each distribuidora and tariff class:
- The latest homologated TE + TUSD values (current effective tariff)
- The previous cycle's TE + TUSD (one year earlier)
- Computed % readjustment = (current - prev) / prev * 100

Source: ANEEL Dados Abertos — Tarifas de Aplicação das Distribuidoras

Outputs: data/tarifas.json
"""
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone, date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import stream_csv_rows, find_col, parse_date_flex, to_float

TARIFAS_URL = (
    "https://dadosabertos.aneel.gov.br/dataset/5a583f3e-1646-4f67-bf0f-69db4203e89e/"
    "resource/fcf2906c-7c32-4b9b-a637-054e7a5234f4/download/"
    "tarifas-homologadas-distribuidoras-energia-eletrica.csv"
)

# Classes of interest
CLASSES_OF_INTEREST = {
    "B1": {"label": "B1 - Residencial", "subgrupo": "B1"},
    "A4": {"label": "A4 - Industrial 2,3-25 kV", "subgrupo": "A4"},
}

# Top 25 distribuidoras by consumer market (approximate, hand-picked)
# These are the largest by MWh sold annually and most relevant for energy markets.
TOP25_DISTRIBUIDORAS = {
    # SECO subsystem
    "CPFL PAULISTA", "ENEL SP", "ENEL RJ", "ENEL CE", "LIGHT",
    "CEMIG D", "CEMIG", "ELEKTRO", "EDP SP", "EDP ES", "CPFL PIRATININGA",
    "ENERGISA MT", "ENERGISA MS", "ENERGISA MG", "ENERGISA SE", "ENERGISA TO",
    # SUL subsystem
    "COPEL DIS", "COPEL", "CELESC DIS", "CELESC", "RGE", "RGE SUL", "CEEE D", "CEEE EQUATORIAL",
    # NE subsystem
    "COELBA", "CELPE", "COSERN", "ENEL PE",
    # N subsystem
    "EQUATORIAL PA", "EQUATORIAL MA", "AMAZONAS ENERGIA",
    # Generic patterns: also match "EQUATORIAL", "ENERGISA", "ENEL" variants
}


def is_top_distribuidora(name: str) -> bool:
    """Match against top 25 list with fuzzy uppercase comparison."""
    if not name:
        return False
    n = name.strip().upper()
    if n in TOP25_DISTRIBUIDORAS:
        return True
    # Pattern matches for company groups
    keywords = ["CPFL", "ENEL", "LIGHT", "CEMIG", "ELEKTRO", "EDP",
                "ENERGISA", "COPEL", "CELESC", "RGE", "CEEE", "COELBA",
                "CELPE", "COSERN", "EQUATORIAL", "AMAZONAS ENERGIA"]
    for kw in keywords:
        if kw in n:
            return True
    return False


def main():
    print("=" * 60)
    print("ANEEL Tarifas Homologadas pipeline")
    print(f"Started: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)
    print(f"URL: {TARIFAS_URL}")
    print("Streaming line-by-line (file is large — may take a few minutes)\n")

    # Bucket: (distribuidora, subgrupo, date) -> { te: float, tusd: float, modalidade, posto }
    # We'll keep the simplest: convencional, posto "Não Aplicável" / "Único", modalidade B1/A4 base
    # The CSV has multiple rows per (dist, subgrupo, cycle) for different details (TUSD, TE, posto P/FP, etc.)
    # We aggregate by summing TE + TUSD where applicable, preferring single-value rows.

    # Strategy: capture all (dist, subgrupo, year-month) values for "tarifa total"
    # by looking at the column DscDetalhe ("Não Aplicável" for B1 simple, "Único" for A4 simple)
    # and BaseTarifaria ("Tarifa de Energia - TE" or "Tarifa de Uso do Sistema - TUSD").

    # Bucket: (distribuidora, subgrupo, year_month) -> {'TE': v, 'TUSD': v}
    buckets: dict[tuple[str, str, str], dict[str, float]] = defaultdict(dict)
    dist_dates: dict[tuple[str, str], set[str]] = defaultdict(set)

    rows_read = 0
    rows_kept = 0
    sample_keys: list[str] | None = None
    sample_row: dict | None = None
    diagnose_cols = {}

    for row in stream_csv_rows(TARIFAS_URL):
        rows_read += 1
        if sample_keys is None:
            sample_keys = list(row.keys())
            sample_row = row
            print(f"Columns detected ({len(sample_keys)}):")
            for k in sample_keys:
                print(f"  - {k!r}")
            # Resolve columns once
            diagnose_cols["dist"] = (find_col(sample_keys, "sigagente")
                                     or find_col(sample_keys, "nomagente")
                                     or find_col(sample_keys, "agente", "concession")
                                     or find_col(sample_keys, "distribuid"))
            diagnose_cols["subgrupo"] = (find_col(sample_keys, "dscsubgrupo")
                                         or find_col(sample_keys, "subgrupo"))
            diagnose_cols["base"] = (find_col(sample_keys, "dscbase", "tarifaria")
                                     or find_col(sample_keys, "base", "tarifaria"))
            diagnose_cols["modalidade"] = (find_col(sample_keys, "modalidade")
                                           or find_col(sample_keys, "dscmodalidade"))
            diagnose_cols["detalhe"] = (find_col(sample_keys, "detalhe")
                                        or find_col(sample_keys, "dscdetalhe"))
            diagnose_cols["unidade"] = (find_col(sample_keys, "unidade", "terciaria")
                                        or find_col(sample_keys, "dscunidade"))
            diagnose_cols["valor"] = (find_col(sample_keys, "vlrtarifa")
                                      or find_col(sample_keys, "valor", "tarifa")
                                      or find_col(sample_keys, "vltarifa"))
            diagnose_cols["data_ini"] = (find_col(sample_keys, "datinicio", "vigencia")
                                         or find_col(sample_keys, "data", "inicio"))
            diagnose_cols["posto"] = (find_col(sample_keys, "dscposto")
                                      or find_col(sample_keys, "posto", "tarif"))
            print(f"\nResolved columns: {diagnose_cols}")
            print(f"Sample row: {sample_row}\n")

        # Read columns
        subgrupo = (row.get(diagnose_cols["subgrupo"], "") or "").strip().upper() if diagnose_cols.get("subgrupo") else ""
        if subgrupo not in CLASSES_OF_INTEREST:
            continue
        dist_name = (row.get(diagnose_cols["dist"], "") or "").strip() if diagnose_cols.get("dist") else ""
        if not is_top_distribuidora(dist_name):
            continue

        # For B1 simple residential: modalidade "Convencional", detalhe "Não Aplicável"
        # For A4 simple: modalidade "Convencional", posto "Não se aplica" or "Único"
        modalidade = (row.get(diagnose_cols["modalidade"], "") or "").strip().lower() if diagnose_cols.get("modalidade") else ""
        if "convencional" not in modalidade and subgrupo == "B1":
            continue  # only B1 conventional for simplicity

        # Skip posto Ponta/Fora Ponta (Horosazonal Verde/Azul) to keep convencional
        posto = (row.get(diagnose_cols["posto"], "") or "").strip().lower() if diagnose_cols.get("posto") else ""
        if posto in ("ponta", "fora ponta", "p", "fp"):
            continue

        base = (row.get(diagnose_cols["base"], "") or "").strip().upper() if diagnose_cols.get("base") else ""
        if "TE" not in base and "TUSD" not in base:
            continue
        base_id = "TE" if "TE" in base else "TUSD"

        valor = to_float(row.get(diagnose_cols["valor"], "")) if diagnose_cols.get("valor") else None
        if valor is None:
            continue

        d = parse_date_flex(row.get(diagnose_cols["data_ini"], "") if diagnose_cols.get("data_ini") else "")
        if d is None:
            continue

        # Detect unit. Often R$/MWh or R$/kWh — we want kWh consistent.
        # If we see "MWh" in unidade, divide by 1000 to get R$/kWh.
        unidade = (row.get(diagnose_cols["unidade"], "") or "").lower() if diagnose_cols.get("unidade") else ""
        if "mwh" in unidade:
            valor = valor / 1000.0

        # Bucket key: (distribuidora, subgrupo, YYYY-MM-DD start date)
        key = (dist_name, subgrupo, d.isoformat())
        # Keep the maximum value for each base (sometimes multiple rows for same TE/TUSD detail)
        prev = buckets[key].get(base_id)
        if prev is None or valor > prev:
            buckets[key][base_id] = valor
        dist_dates[(dist_name, subgrupo)].add(d.isoformat())
        rows_kept += 1

    print(f"\nRows read: {rows_read:,}")
    print(f"Rows kept: {rows_kept:,}")
    print(f"Distribuidora × subgrupo unique: {len(dist_dates)}")

    if not buckets:
        print("ERROR: No matching rows. Schema may differ from expectations.")
        sys.exit(1)

    # For each (dist, subgrupo), find the LATEST cycle and the PREVIOUS cycle (most recent before it)
    # Compute % readjustment in TE+TUSD total tariff
    results: dict[str, list[dict]] = {sg: [] for sg in CLASSES_OF_INTEREST}
    for (dist, subgrupo), dates in dist_dates.items():
        sorted_dates = sorted(dates)
        if len(sorted_dates) < 1:
            continue
        latest = sorted_dates[-1]
        previous = sorted_dates[-2] if len(sorted_dates) >= 2 else None
        cur = buckets.get((dist, subgrupo, latest), {})
        prev = buckets.get((dist, subgrupo, previous), {}) if previous else {}

        cur_te = cur.get("TE")
        cur_tusd = cur.get("TUSD")
        prev_te = prev.get("TE")
        prev_tusd = prev.get("TUSD")
        cur_total = (cur_te or 0) + (cur_tusd or 0)
        prev_total = (prev_te or 0) + (prev_tusd or 0)

        # Compute % only if both totals are populated
        readjust_pct = None
        if cur_total and prev_total:
            readjust_pct = round((cur_total - prev_total) / prev_total * 100, 2)

        results[subgrupo].append({
            "distribuidora": dist,
            "ultima_homologacao": latest,
            "homologacao_anterior": previous,
            "te_atual": round(cur_te, 5) if cur_te else None,
            "tusd_atual": round(cur_tusd, 5) if cur_tusd else None,
            "total_atual_rs_kwh": round(cur_total, 5) if cur_total else None,
            "te_anterior": round(prev_te, 5) if prev_te else None,
            "tusd_anterior": round(prev_tusd, 5) if prev_tusd else None,
            "total_anterior_rs_kwh": round(prev_total, 5) if prev_total else None,
            "reajuste_pct": readjust_pct,
        })

    # Sort each class by date descending (most recent first)
    for sg in results:
        results[sg].sort(key=lambda x: (x["ultima_homologacao"] or ""), reverse=True)

    output = {
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": {
            "name": "ANEEL Dados Abertos — Tarifas Homologadas das Distribuidoras",
            "url": TARIFAS_URL,
            "rows_read": rows_read,
            "rows_kept": rows_kept,
            "note": (
                "Tarifa total (TE + TUSD) em R$/kWh para classe convencional. "
                "Reajuste % calculado entre as duas últimas datas de homologação por distribuidora. "
                "Lista limitada às top ~25 distribuidoras por mercado."
            ),
        },
        "classes": {
            sg: {
                "label": meta["label"],
                "distribuidoras": results.get(sg, []),
            }
            for sg, meta in CLASSES_OF_INTEREST.items()
        },
    }

    out_path = Path(__file__).parent.parent / "data" / "tarifas.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False, default=str))
    size_kb = out_path.stat().st_size / 1024
    print(f"\nWrote {out_path} ({size_kb:.1f} KB)")

    print("\n--- Summary ---")
    for sg, meta in CLASSES_OF_INTEREST.items():
        print(f"\n{meta['label']}:")
        for r in results.get(sg, [])[:5]:
            pct_str = f"{r['reajuste_pct']:+.2f}%" if r["reajuste_pct"] is not None else "—"
            print(f"  {r['distribuidora'][:35]:35s}  homol: {r['ultima_homologacao']}  reajuste: {pct_str}")

    print("Done.")


if __name__ == "__main__":
    main()
