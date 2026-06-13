# diff-06 — extracted seam

Verbatim extraction of `_coerce_eventlog_row` into `cake/clients/_async/salesforce/eventlog.py`; byte-identical relocation; tests green.

```python
def _coerce_eventlog_row(row: dict[str, str]) -> dict[str, Any]:
    """Preserve EventLogFile CSV values as strings — no type guessing.

    EventLogFile has no schema, and heuristic coercion (int/float/bool)
    produces mixed types in JSONL that poison BigQuery autodetect schemas.
    Example: SESSION_LEVEL is sometimes "1" (coerced to int) and sometimes
    "STANDARD(db=1,api=STANDARD)" (kept as string) — BigQuery locks the
    column as INTEGER and rejects the string rows.

    Fix (cake-1o0): Keep all values as strings. Silver dbt models handle
    typing via SAFE_CAST.

    Args:
        row: CSV row with all string values

    Returns:
        Row with string values preserved; empty strings become None
    """
    return {field: (None if value == "" else value) for field, value in row.items()}
```
