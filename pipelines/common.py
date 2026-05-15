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


def stream_csv_rows(url: str, retries: int = 3, chunk_size: int = 8192) -> Iterator[dict]:
    """Stream a CSV from URL row-by-row without loading it all in memory.

    Use for very large files (MMGD ~2 GB, Tarifas ~hundreds of MB).
    Auto-detects delimiter from the first 4 KB of content and decodes line-by-line.
    """
    for attempt in range(retries):
        try:
            with requests.get(
                url,
                timeout=DEFAULT_TIMEOUT * 4,  # large file = more patience
                headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
                stream=True,
            ) as r:
                r.raise_for_status()
                content_len = r.headers.get("Content-Length")
                if content_len:
                    mb = int(content_len) / (1024 * 1024)
                    print(f"  streaming {mb:.1f} MB from {url[:80]}...")

                # Iterate raw bytes, decode, then yield csv-parsed rows.
                # Use iter_lines for line-by-line decoding (handles \r\n correctly).
                first_line = None
                delimiter = None
                header = None
                for raw_line in r.iter_lines(chunk_size=chunk_size, decode_unicode=False):
                    if not raw_line:
                        continue
                    # Decode flexibly per-line (utf-8 with fallback to latin-1)
                    for enc in ("utf-8-sig", "utf-8", "latin-1"):
                        try:
                            line = raw_line.decode(enc)
                            break
                        except UnicodeDecodeError:
                            continue
                    else:
                        continue  # skip undecodable line

                    if first_line is None:
                        first_line = line
                        # Detect delimiter from header
                        delimiter = ";" if first_line.count(";") > first_line.count(",") else ","
                        header = next(csv.reader([first_line], delimiter=delimiter))
                        continue

                    # Parse this line as a single-row CSV
                    try:
                        row = next(csv.reader([line], delimiter=delimiter))
                    except (StopIteration, csv.Error):
                        continue
                    if len(row) != len(header):
                        # Skip malformed lines
                        continue
                    yield dict(zip(header, row))
                return
        except requests.RequestException as e:
            if attempt < retries - 1:
                wait = 2.0 ** attempt
                print(f"  stream retry {attempt + 1}/{retries} after {wait:.1f}s: {e}")
                time.sleep(wait)
            else:
                raise RuntimeError(f"Failed to stream {url}: {e}")


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
    """Parse a number, handling both '.' and ',' as decimal separator.

    Brazilian locale: '1.234,56' → 1234.56 (dot is thousand sep, comma is decimal).
    US locale: '1,234.56' → 1234.56 (comma is thousand sep, dot is decimal).
    Detection: the rightmost separator is the decimal one.
    """
    if s is None:
        return None
    s = str(s).strip()
    if not s:
        return None
    has_dot = "." in s
    has_comma = "," in s
    if has_dot and has_comma:
        # Whichever appears last is the decimal separator
        last_dot = s.rfind(".")
        last_comma = s.rfind(",")
        if last_comma > last_dot:
            # BR style: dots are thousand separators, comma is decimal
            s = s.replace(".", "").replace(",", ".")
        else:
            # US style: commas are thousand separators, dot is decimal
            s = s.replace(",", "")
    elif has_comma:
        # Only comma: ambiguous, but BR convention dominates → decimal
        s = s.replace(",", ".")
    # Only dot or no separator: leave as is (already US-style decimal)
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
