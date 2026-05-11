"""Common utilities for ONS / CCEE / ANEEL data pipelines."""
import csv
import io
import time
from datetime import datetime
from typing import Iterator

import requests

USER_AGENT = (
    "Mozilla/5.0 (compatible; dashsin-pipeline/1.0; "
    "+https://github.com/rtbarbosa3/dashsin)"
)
DEFAULT_TIMEOUT = 60


def fetch_text(url: str, retries: int = 3, backoff: float = 2.0) -> str:
    """Download a URL and return text. Tries UTF-8-BOM, UTF-8, Latin-1 in order."""
    last_err = None
    for attempt in range(retries):
        try:
            r = requests.get(
                url,
                timeout=DEFAULT_TIMEOUT,
                headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
            )
            r.raise_for_status()
            for enc in ("utf-8-sig", "utf-8", "latin-1"):
                try:
                    return r.content.decode(enc)
                except UnicodeDecodeError:
                    continue
            raise RuntimeError(f"Could not decode {url} with any known encoding")
        except (requests.RequestException, RuntimeError) as e:
            last_err = e
            if attempt < retries - 1:
                wait = backoff ** attempt
                print(f"  retry {attempt + 1}/{retries} after {wait:.1f}s: {e}")
                time.sleep(wait)
    raise RuntimeError(f"Failed to fetch {url}: {last_err}")


def parse_csv(text: str, delimiter: str | None = None) -> list[dict]:
    """Parse CSV text into list of dicts. Auto-detects delimiter if not given."""
    if delimiter is None:
        sample = text[:4096]
        # ONS uses semicolon by official documentation
        delimiter = ";" if sample.count(";") > sample.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    return list(reader)


def find_col(row_keys: list[str], *keywords: str) -> str | None:
    """Find first column name containing ALL given keywords (case-insensitive)."""
    kw_lower = [k.lower() for k in keywords]
    for col in row_keys:
        col_lower = col.lower()
        if all(k in col_lower for k in kw_lower):
            return col
    return None


def parse_date_flex(s: str):
    """Try common date formats, return date or None."""
    if not s:
        return None
    s = s.strip()
    # Strip time component if present
    if " " in s:
        s = s.split(" ", 1)[0]
    if "T" in s:
        s = s.split("T", 1)[0]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def to_float(s) -> float | None:
    """Parse a number, handling both '.' and ',' as decimal separator."""
    if s is None:
        return None
    s = str(s).strip()
    if not s:
        return None
    # ONS uses '.' as decimal per their docs, but CCEE sometimes uses ','
    # Detect: if exactly one ',' and no '.', treat as decimal sep
    if "," in s and "." not in s:
        s = s.replace(",", ".")
    elif "," in s and "." in s:
        # likely thousand separator + decimal: drop commas
        s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


SUBSYSTEM_NORMALIZE = {
    "SE": "SECO",
    "SE/CO": "SECO",
    "SE_CO": "SECO",
    "SECO": "SECO",
    "SUDESTE": "SECO",
    "SUDESTE/CENTRO-OESTE": "SECO",
    "SUDESTE / CENTRO-OESTE": "SECO",
    "S": "SUL",
    "SUL": "SUL",
    "NE": "NE",
    "NORDESTE": "NE",
    "N": "N",
    "NORTE": "N",
    "SIN": "SIN",
}


def normalize_sub(name: str) -> str:
    """Normalize subsystem name to canonical form: SECO, SUL, NE, N, SIN."""
    if not name:
        return ""
    key = name.strip().upper()
    return SUBSYSTEM_NORMALIZE.get(key, key)
