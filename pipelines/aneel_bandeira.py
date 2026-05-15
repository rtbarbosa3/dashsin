"""
ANEEL Bandeira Tarifária pipeline v2

Adds tariff additional value (R$/100 kWh) to each flag activation.

The activation CSV doesn't always include the monetary value, so we use a
hard-coded historical table of ANEEL Resoluções Homologatórias.
We still try to detect a value column in the CSV first as fallback.

Source: ANEEL Dados Abertos — Bandeiras Tarifárias - Acionamento
Outputs: data/bandeira.json
"""
import json
import sys
from collections import OrderedDict
from datetime import datetime, timezone, date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import fetch_text, parse_csv, find_col, parse_date_flex, to_float

BANDEIRA_URL = (
    "https://dadosabertos.aneel.gov.br/dataset/bandeiras-tarifarias/resource/"
    "0591b8f6-fe54-437b-b72b-1aa2efd46e42/download/bandeira-tarifaria-acionamento.csv"
)

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

# Historical adicional values per band, in R$/100 kWh.
# Each entry: (start_date, value_dict). Applied from start_date onwards until next entry.
# Sources: ANEEL Resoluções Homologatórias annual reviews.
BANDEIRA_VALOR_HISTORICO = [
    # 2015-01-01: initial values (Resol. Homol. 1858/2015)
    (date(2015, 1, 1), {"verde": 0.0, "amarela": 1.50, "vermelha1": 3.00, "vermelha2": 3.00, "escassez": 0.0}),
    # 2016-02-01: subdivision of red into P1/P2 (Resol. 2016/2016)
    (date(2016, 2, 1), {"verde": 0.0, "amarela": 1.50, "vermelha1": 3.00, "vermelha2": 4.50, "escassez": 0.0}),
    # 2018-03-22 (Resol. 2376/2018): new methodology, lower amarela, higher P1/P2
    (date(2018, 3, 22), {"verde": 0.0, "amarela": 1.00, "vermelha1": 3.00, "vermelha2": 5.00, "escassez": 0.0}),
    # 2019-08-01 (Resol. 2547/2019)
    (date(2019, 8, 1), {"verde": 0.0, "amarela": 1.343, "vermelha1": 4.169, "vermelha2": 6.243, "escassez": 0.0}),
    # 2021-09-01 (Escassez Hídrica criada — Resol. 2934/2021)
    (date(2021, 9, 1), {"verde": 0.0, "amarela": 1.874, "vermelha1": 3.971, "vermelha2": 9.492, "escassez": 14.20}),
    # 2022-04-16 (fim da Escassez Hídrica, retorno a valores normais)
    (date(2022, 4, 16), {"verde": 0.0, "amarela": 2.989, "vermelha1": 6.500, "vermelha2": 9.795, "escassez": 0.0}),
    # 2023-07-04 (Resol. 3219/2023)
    (date(2023, 7, 4), {"verde": 0.0, "amarela": 2.989, "vermelha1": 6.500, "vermelha2": 9.795, "escassez": 0.0}),
    # 2024-07-08 (Resol. 3331/2024)
    (date(2024, 7, 8), {"verde": 0.0, "amarela": 1.885, "vermelha1": 4.463, "vermelha2": 7.877, "escassez": 0.0}),
    # 2025-07 estimated revision (placeholder values, updated when official numbers known)
    (date(2025, 7, 1), {"verde": 0.0, "amarela": 1.885, "vermelha1": 4.463, "vermelha2": 7.877, "escassez": 0.0}),
]


def normalize_bandeira(raw: str) -> tuple[str, str]:
    if not raw:
        return ("desconhecida", "—")
    key = raw.strip().upper()
    if key in BANDEIRA_MAP:
        return BANDEIRA_MAP[key]
    if "VERDE" in key:
        return ("verde", "Verde")
    if "AMARELA" in key:
        return ("amarela", "Amarela")
    if "VERMELHA" in key:
        if "2" in key:
            return ("vermelha2", "Vermelha P2")
        return ("vermelha1", "Vermelha P1")
    if "ESCASSEZ" in key:
        return ("escassez", "Escassez Hídrica")
    return (key.lower().replace(" ", "_"), raw.strip())


def lookup_valor(bandeira: str, ref_date: date) -> float | None:
    """Returns R$/100 kWh adicional for the given bandeira and reference date."""
    if bandeira == "verde":
        return 0.0
    # Walk from latest entry backwards, find first start_date <= ref_date
    for start_date, values in reversed(BANDEIRA_VALOR_HISTORICO):
        if start_date <= ref_date:
            return values.get(bandeira)
    return None


def main():
    print("=" * 60)
    print("ANEEL Bandeira Tarifária pipeline v2")
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

    col_date = (find_col(keys, "inicio", "vigencia")
                or find_col(keys, "data", "inicio")
                or find_col(keys, "periodo", "competencia")
                or find_col(keys, "competencia")
                or find_col(keys, "data"))
    col_band = (find_col(keys, "bandeira", "acionamento")
                or find_col(keys, "tipo", "bandeira")
                or find_col(keys, "bandeira"))
    # Try to detect a monetary value column (e.g. ValorAdicional)
    col_valor = (find_col(keys, "valor", "adicional")
                 or find_col(keys, "adicional", "bandeira")
                 or find_col(keys, "vlrbandeira")
                 or find_col(keys, "valor", "bandeira"))
    print(f"  date column:    {col_date!r}")
    print(f"  bandeira col:   {col_band!r}")
    print(f"  valor col:      {col_valor!r} (optional)")

    if not col_date or not col_band:
        print(f"ERROR: Could not resolve columns. Available: {keys}")
        sys.exit(1)

    records = []
    for r in rows:
        d = parse_date_flex(r.get(col_date, ""))
        if d is None:
            raw = (r.get(col_date) or "").strip()
            try:
                if "/" in raw:
                    parts = raw.split("/")
                    if len(parts) == 2:
                        month = int(parts[0]); year = int(parts[1])
                        d = date(year, month, 1)
                elif "-" in raw and len(raw) == 7:
                    year = int(raw[:4]); month = int(raw[5:7])
                    d = date(year, month, 1)
            except (ValueError, IndexError):
                pass
        if d is None:
            continue
        b_id, b_label = normalize_bandeira(r.get(col_band, ""))

        # Prefer value from CSV; fall back to historical table
        valor = None
        if col_valor:
            valor = to_float(r.get(col_valor, ""))
        if valor is None:
            valor = lookup_valor(b_id, d)

        records.append({
            "year": d.year, "month": d.month,
            "bandeira": b_id, "label": b_label,
            "valor_adicional_rs_100kwh": round(valor, 3) if valor is not None else None,
        })

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

    recent = records[-24:]
    current = records[-1]

    streak = 1
    for r in reversed(records[:-1]):
        if r["bandeira"] == current["bandeira"]:
            streak += 1
        else:
            break

    # Current valores table - current vigência of the band values
    today = datetime.now(timezone.utc).date()
    valores_atuais = {}
    for start_date, values in reversed(BANDEIRA_VALOR_HISTORICO):
        if start_date <= today:
            valores_atuais = {k: round(v, 3) for k, v in values.items()}
            valores_atuais["_vigencia_desde"] = start_date.isoformat()
            break

    output = {
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": {
            "name": "ANEEL Dados Abertos — Bandeira Tarifária - Acionamento",
            "url": BANDEIRA_URL,
            "records_total": len(records),
            "note": "Valor adicional em R$/100 kWh. Verde sempre 0. Outros valores homologados anualmente pela ANEEL.",
        },
        "valores_atuais": valores_atuais,
        "current": {
            "year": current["year"],
            "month": current["month"],
            "bandeira": current["bandeira"],
            "label": current["label"],
            "valor_adicional_rs_100kwh": current["valor_adicional_rs_100kwh"],
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
    print(f"Current: {current['label']} ({current['year']}-{current['month']:02d}, {streak} months) · +R$ {current['valor_adicional_rs_100kwh']:.3f}/100 kWh" if current['valor_adicional_rs_100kwh'] is not None else f"Current: {current['label']} ({current['year']}-{current['month']:02d}, {streak} months) · valor n/a")
    print(f"Valores atuais (vigência desde {valores_atuais.get('_vigencia_desde')}):")
    for k, v in valores_atuais.items():
        if not k.startswith("_"):
            print(f"  {k:12s}: R$ {v:.3f}/100 kWh")
    print("Done.")


if __name__ == "__main__":
    main()
