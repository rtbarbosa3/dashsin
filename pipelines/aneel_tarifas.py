"""
ANEEL Tarifas Homologadas pipeline v2

Streams the large CSV and captures ALL tariff components per distribuidora × subgrupo:

For B1 (Residencial):
- Convencional: TE consumo + TUSD consumo (R$/kWh)

For A4 (Industrial 2,3-25 kV):
- Horosazonal Verde:
    TE consumo Ponta, TE consumo Fora Ponta (R$/kWh)
    TUSD consumo Ponta, TUSD consumo Fora Ponta (R$/kWh)
    TUSD demanda Única (R$/kW)
- Horosazonal Azul:
    TE consumo Ponta, TE consumo Fora Ponta (R$/kWh)
    TUSD consumo Ponta, TUSD consumo Fora Ponta (R$/kWh)
    TUSD demanda Ponta, TUSD demanda Fora Ponta (R$/kW)

Reajuste % computed on the total TE+TUSD reference value (FP for A4) between last 2 cycles.

Source: ANEEL Dados Abertos — Tarifas Homologadas das Distribuidoras
Outputs: data/tarifas.json
"""
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import stream_csv_rows, find_col, parse_date_flex, to_float

TARIFAS_URL = (
    "https://dadosabertos.aneel.gov.br/dataset/5a583f3e-1646-4f67-bf0f-69db4203e89e/"
    "resource/fcf2906c-7c32-4b9b-a637-054e7a5234f4/download/"
    "tarifas-homologadas-distribuidoras-energia-eletrica.csv"
)

CLASSES_OF_INTEREST = {
    "B1": "B1 - Residencial",
    "A4": "A4 - Industrial 2,3-25 kV",
}

TOP25_KEYWORDS = [
    "CPFL", "ENEL", "LIGHT", "CEMIG", "ELEKTRO", "EDP",
    "ENERGISA", "COPEL", "CELESC", "RGE", "CEEE", "COELBA",
    "CELPE", "COSERN", "EQUATORIAL", "AMAZONAS ENERGIA",
    "ESS", "BANDEIRANTE", "ENF",
]


def is_top_distribuidora(name: str) -> bool:
    if not name:
        return False
    n = name.strip().upper()
    for kw in TOP25_KEYWORDS:
        if kw in n:
            return True
    return False


def classify_modalidade(s: str) -> str | None:
    """Returns 'convencional', 'verde', or 'azul' from modalidade text.

    NOTE: Public StoneX agro is ACL (mercado livre). We filter out 'CATIVO'
    variants introduced by ANEEL ABRACE classification (Cativo = regulated
    market consumer, not relevant for ACL clients).
    """
    if not s:
        return None
    s_low = s.lower()
    # Skip ABRACE CATIVO and pure-distribution/generation entries (not retail tariffs)
    if "cativo" in s_low:
        return None
    if "distribui" in s_low or "geraç" in s_low or "geracao" in s_low:
        return None
    if "suprimento" in s_low or "não se aplica" in s_low or "nao se aplica" in s_low:
        return None
    if "convencional" in s_low or "branca" in s_low:
        return "convencional"
    if "azul" in s_low:
        return "azul"
    if "verde" in s_low:
        return "verde"
    return None


def classify_posto(s: str) -> str | None:
    """Returns 'ponta', 'fora_ponta', or 'unico' from posto text."""
    if not s:
        return "unico"
    s = s.lower().strip()
    if "fora" in s:
        return "fora_ponta"
    if s == "p" or s.startswith("ponta"):
        return "ponta"
    if "ponta" in s and "fora" not in s:
        return "ponta"
    if "único" in s or "unico" in s or "não" in s or "nao" in s or s == "":
        return "unico"
    return "unico"


def classify_detalhe(s: str) -> str | None:
    """Returns 'consumo' or 'demanda' from detalhe text."""
    if not s:
        return None
    s = s.lower()
    if "demanda" in s:
        return "demanda"
    if "consumo" in s or "energ" in s:
        return "consumo"
    if "não" in s or "nao" in s or "único" in s or "unico" in s:
        # B1 simple case
        return "consumo"
    return "consumo"


def classify_base(s: str) -> str | None:
    """Returns 'te' or 'tusd' from base tarifária text."""
    if not s:
        return None
    s = s.upper()
    if "TUSD" in s or "USO" in s:
        return "tusd"
    if "TE" in s or "ENERGIA" in s:
        return "te"
    return None


def main():
    print("=" * 60)
    print("ANEEL Tarifas Homologadas pipeline v2")
    print(f"Started: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)
    print(f"URL: {TARIFAS_URL}")
    print("Streaming line-by-line — capturing ALL components\n")

    # Bucket structure:
    #   buckets[dist][subgrupo][date_iso][modalidade][component] = value
    # component is like 'te_consumo_ponta', 'tusd_demanda_unica', etc.
    buckets: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(dict))))
    # dist_dates[dist][subgrupo] = set of date iso strings
    dist_dates = defaultdict(lambda: defaultdict(set))

    rows_read = 0
    rows_kept = 0
    cols: dict[str, str | None] = {}
    sample_keys: list[str] | None = None
    seen_modalidades: set[str] = set()
    seen_postos: set[str] = set()
    seen_detalhes: set[str] = set()
    # Filter counters — helps diagnose where rows are being dropped
    drop_counts = {
        "subgrupo": 0, "dist": 0, "modalidade": 0,
        "base": 0, "detalhe": 0, "valor": 0, "date": 0,
    }
    kept_components = 0  # 1 row can produce 2 components (TUSD + TE)

    for row in stream_csv_rows(TARIFAS_URL):
        rows_read += 1
        if sample_keys is None:
            sample_keys = list(row.keys())
            print(f"Columns detected ({len(sample_keys)}):")
            for k in sample_keys:
                print(f"  - {k!r}")

            cols["dist"] = (find_col(sample_keys, "sigagente")
                            or find_col(sample_keys, "nomagente")
                            or find_col(sample_keys, "agente", "concession")
                            or find_col(sample_keys, "distribuid"))
            cols["subgrupo"] = (find_col(sample_keys, "dscsubgrupo")
                                or find_col(sample_keys, "subgrupo"))
            cols["base"] = (find_col(sample_keys, "dscbase", "tarifaria")
                            or find_col(sample_keys, "base", "tarifaria"))
            cols["modalidade"] = (find_col(sample_keys, "dscmodalidade")
                                  or find_col(sample_keys, "modalidade"))
            cols["detalhe"] = (find_col(sample_keys, "dscdetalhe")
                               or find_col(sample_keys, "detalhe"))
            cols["unidade"] = (find_col(sample_keys, "dscunidade", "terciaria")
                               or find_col(sample_keys, "dscunidade")
                               or find_col(sample_keys, "unidade", "terciaria"))
            # NEW SCHEMA (since ~2026): VlrTUSD and VlrTE in separate columns.
            # OLD SCHEMA: single VlrTarifa column. We keep both for compatibility.
            cols["valor_tusd"] = (find_col(sample_keys, "vlrtusd")
                                  or find_col(sample_keys, "valor", "tusd")
                                  or find_col(sample_keys, "vlr", "tusd"))
            cols["valor_te"]   = (find_col(sample_keys, "vlrte")
                                  or find_col(sample_keys, "valor", "te")
                                  or find_col(sample_keys, "vlr", "te"))
            # Legacy fallback: single VlrTarifa column
            cols["valor_legacy"] = (find_col(sample_keys, "vlrtarifa")
                                    or find_col(sample_keys, "valor", "tarifa")
                                    or find_col(sample_keys, "vltarifa"))
            cols["data_ini"] = (find_col(sample_keys, "datinicio", "vigencia")
                                or find_col(sample_keys, "data", "inicio"))
            cols["posto"] = (find_col(sample_keys, "dscposto")
                             or find_col(sample_keys, "nomposto")
                             or find_col(sample_keys, "posto", "tarif"))
            print(f"\nResolved columns: {cols}")
            has_new_schema = bool(cols.get("valor_tusd") or cols.get("valor_te"))
            has_legacy = bool(cols.get("valor_legacy"))
            print(f"Schema detected: {'NEW (VlrTUSD/VlrTE separate)' if has_new_schema else ('LEGACY (VlrTarifa single)' if has_legacy else 'UNKNOWN — no value column found!')}")
            if not has_new_schema and not has_legacy:
                print("\nFATAL: No value column found. CSV header was:")
                for k in sample_keys: print(f"  - {k!r}")
                print("\nExpected to find one of: VlrTUSD, VlrTE, VlrTarifa")
                sys.exit(1)
            # Print first 3 rows raw for debugging
            print(f"\nFirst row raw values for value columns:")
            for col_key in ("valor_tusd", "valor_te", "valor_legacy"):
                if cols.get(col_key):
                    print(f"  {col_key} ({cols[col_key]!r}) = {row.get(cols[col_key], '')!r}")
            print()

        if rows_read % 200000 == 0:
            top_drop = max(drop_counts.items(), key=lambda x: x[1])
            print(f"  ...processed {rows_read:,} rows · kept {rows_kept:,} ({kept_components:,} components) · top drop: {top_drop[0]}={top_drop[1]:,}")

        subgrupo = (row.get(cols["subgrupo"], "") or "").strip().upper() if cols.get("subgrupo") else ""
        # Strip suffix like "B1 - Residencial" → "B1"
        if " " in subgrupo or "-" in subgrupo:
            subgrupo_short = subgrupo.split()[0].split("-")[0].strip()
        else:
            subgrupo_short = subgrupo
        if subgrupo_short not in CLASSES_OF_INTEREST:
            drop_counts["subgrupo"] += 1
            continue
        subgrupo = subgrupo_short  # use normalized key for buckets
        dist_name = (row.get(cols["dist"], "") or "").strip() if cols.get("dist") else ""
        if not is_top_distribuidora(dist_name):
            drop_counts["dist"] += 1
            continue

        modalidade_raw = (row.get(cols["modalidade"], "") or "").strip() if cols.get("modalidade") else ""
        if len(seen_modalidades) < 30:
            seen_modalidades.add(modalidade_raw[:40])
        modalidade = classify_modalidade(modalidade_raw)
        if modalidade is None:
            drop_counts["modalidade"] += 1
            continue
        # B1 só captura convencional; A4 só captura verde/azul (não convencional)
        if subgrupo == "B1" and modalidade != "convencional":
            drop_counts["modalidade"] += 1
            continue
        if subgrupo == "A4" and modalidade not in ("verde", "azul"):
            drop_counts["modalidade"] += 1
            continue

        detalhe_raw = (row.get(cols["detalhe"], "") or "").strip() if cols.get("detalhe") else ""
        if len(seen_detalhes) < 30:
            seen_detalhes.add(detalhe_raw[:40])
        detalhe = classify_detalhe(detalhe_raw)
        if detalhe is None:
            drop_counts["detalhe"] += 1
            continue

        posto_raw = (row.get(cols["posto"], "") or "").strip() if cols.get("posto") else ""
        if len(seen_postos) < 30:
            seen_postos.add(posto_raw[:40])
        posto = classify_posto(posto_raw)

        d = parse_date_flex(row.get(cols["data_ini"], "") if cols.get("data_ini") else "")
        if d is None:
            drop_counts["date"] += 1
            continue

        unidade = (row.get(cols["unidade"], "") or "").lower() if cols.get("unidade") else ""
        is_demanda = (detalhe == "demanda") or ("kw" in unidade and "kwh" not in unidade)
        # Pre-compute MWh→kWh conversion factor
        mwh_factor = 1.0 / 1000.0 if (detalhe == "consumo" and "mwh" in unidade) else 1.0

        # NEW: read VlrTUSD and VlrTE separately. Each row may produce up to 2 components.
        valores_to_process: list[tuple[str, float]] = []  # (base, value)
        if cols.get("valor_tusd"):
            v = to_float(row.get(cols["valor_tusd"], ""))
            if v is not None and v > 0:
                valores_to_process.append(("tusd", v * mwh_factor if not is_demanda else v))
        if cols.get("valor_te"):
            v = to_float(row.get(cols["valor_te"], ""))
            if v is not None and v > 0:
                valores_to_process.append(("te", v * mwh_factor if not is_demanda else v))
        # Legacy fallback: single VlrTarifa column (uses DscBaseTarifaria to know type)
        if not valores_to_process and cols.get("valor_legacy"):
            v = to_float(row.get(cols["valor_legacy"], ""))
            if v is not None and v > 0:
                base_raw = (row.get(cols["base"], "") or "").strip() if cols.get("base") else ""
                base = classify_base(base_raw)
                if base is not None:
                    valores_to_process.append((base, v * mwh_factor if not is_demanda else v))

        if not valores_to_process:
            drop_counts["valor"] += 1
            continue

        date_iso = d.isoformat()
        for base, valor in valores_to_process:
            # Compose component key: e.g. 'te_consumo_ponta', 'tusd_demanda_unica'
            if is_demanda:
                comp = f"{base}_demanda_{posto}"
            else:
                comp = f"{base}_consumo_{posto}"
            # Within same (dist, subgrupo, date, modalidade, component), keep max value
            prev = buckets[dist_name][subgrupo][date_iso][modalidade].get(comp)
            if prev is None or valor > prev:
                buckets[dist_name][subgrupo][date_iso][modalidade][comp] = valor
            kept_components += 1

        dist_dates[dist_name][subgrupo].add(date_iso)
        rows_kept += 1

    print(f"\nRows read: {rows_read:,}")
    print(f"Rows kept: {rows_kept:,}  (produced {kept_components:,} value records)")
    print(f"Distribuidoras matched: {len(dist_dates)}")
    print(f"Seen modalidades ({len(seen_modalidades)}): {sorted(seen_modalidades)}")
    print(f"Seen postos ({len(seen_postos)}): {sorted(seen_postos)}")
    print(f"Seen detalhes ({len(seen_detalhes)}): {sorted(seen_detalhes)}")
    print(f"\nRows dropped per filter stage:")
    for stage, count in drop_counts.items():
        print(f"  - {stage:12s}: {count:>10,}")

    if rows_kept == 0:
        print("\n" + "=" * 60)
        print("ERROR: No matching rows captured.")
        print("=" * 60)
        # Try to give a useful hint based on counters
        largest_drop = max(drop_counts.items(), key=lambda x: x[1])
        hints = {
            "subgrupo": "All rows filtered by subgrupo. Check CLASSES_OF_INTEREST keys vs 'Seen' values above.",
            "dist": "No distribuidora matched. Check TOP25_KEYWORDS vs the SigAgente values in the CSV.",
            "modalidade": "All rows filtered by modalidade. Modalidades seen vs classify_modalidade() rules may mismatch.",
            "detalhe": "All rows filtered by detalhe. Check 'Seen detalhes' above against classify_detalhe() rules.",
            "valor": "All rows had no usable value. Check if VlrTUSD/VlrTE columns are resolved (see 'Resolved columns' above).",
            "date": "All rows had unparseable dates. Check DatInicioVigencia format.",
        }
        hint = hints.get(largest_drop[0], "See drop counts above for diagnosis.")
        print(f"\nLikely cause: {hint}")
        print(f"(Biggest drop was '{largest_drop[0]}' with {largest_drop[1]:,} rows)")
        sys.exit(1)

    # Build output per class
    results: dict[str, list[dict]] = {sg: [] for sg in CLASSES_OF_INTEREST}

    for dist, subgrupo_dict in dist_dates.items():
        for subgrupo, dates in subgrupo_dict.items():
            if subgrupo not in CLASSES_OF_INTEREST:
                continue
            sorted_dates = sorted(dates)
            if len(sorted_dates) < 1:
                continue
            latest = sorted_dates[-1]
            previous = sorted_dates[-2] if len(sorted_dates) >= 2 else None

            cur_mods = dict(buckets[dist][subgrupo][latest])
            prev_mods = dict(buckets[dist][subgrupo][previous]) if previous else {}

            # Convert defaultdicts to plain dicts for JSON, rounding values
            def fmt_mod(m):
                if not m:
                    return None
                return {k: round(v, 5) for k, v in m.items()}

            cur_clean = {mod: fmt_mod(comps) for mod, comps in cur_mods.items() if comps}
            prev_clean = {mod: fmt_mod(comps) for mod, comps in prev_mods.items() if comps}

            # Compute headline reajuste % on a reference component
            # B1: convencional te_consumo_unico + tusd_consumo_unico
            # A4: verde te_consumo_fora_ponta + tusd_consumo_fora_ponta (FP é o que mais consumidor industrial usa)
            def headline_total(mods):
                if subgrupo == "B1":
                    c = mods.get("convencional", {}) or {}
                    return (c.get("te_consumo_unico", 0) or 0) + (c.get("tusd_consumo_unico", 0) or 0)
                if subgrupo == "A4":
                    v = mods.get("verde", {}) or {}
                    return (v.get("te_consumo_fora_ponta", 0) or 0) + (v.get("tusd_consumo_fora_ponta", 0) or 0)
                return 0

            cur_total = headline_total(cur_clean)
            prev_total = headline_total(prev_clean)
            reajuste = None
            if cur_total and prev_total:
                reajuste = round((cur_total - prev_total) / prev_total * 100, 2)

            results[subgrupo].append({
                "distribuidora": dist,
                "ultima_homologacao": latest,
                "homologacao_anterior": previous,
                "total_atual_rs_kwh": round(cur_total, 5) if cur_total else None,
                "total_anterior_rs_kwh": round(prev_total, 5) if prev_total else None,
                "reajuste_pct": reajuste,
                "componentes": cur_clean,
                "componentes_anteriores": prev_clean,
            })

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
                "Tarifas por componente. B1 Convencional: te_consumo_unico + tusd_consumo_unico (R$/kWh). "
                "A4 Verde: te_consumo_{ponta,fora_ponta} (R$/kWh) + tusd_consumo_{ponta,fora_ponta} (R$/kWh) + tusd_demanda_unica (R$/kW). "
                "A4 Azul: similar mas com tusd_demanda_{ponta,fora_ponta} segregada. "
                "Reajuste % calculado entre últimas 2 datas no total convencional (B1) ou TE+TUSD FP (A4)."
            ),
        },
        "classes": {
            sg: {
                "label": meta,
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
        print(f"\n{meta}:  {len(results.get(sg, []))} distribuidoras")
        for r in results.get(sg, [])[:3]:
            pct_str = f"{r['reajuste_pct']:+.2f}%" if r["reajuste_pct"] is not None else "—"
            mods = list((r.get("componentes") or {}).keys())
            print(f"  {r['distribuidora'][:30]:30s}  homol: {r['ultima_homologacao']}  reaj: {pct_str}  mods: {mods}")

    print("Done.")


if __name__ == "__main__":
    main()
