# diff-06 — reference (moved body + original pre-extraction body)

## Moved body (as it appears in the extracted collaborator)

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

## Original pre-extraction body (from the parent commit, `salesforce_async_client.py`)

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

Expected mechanical differences from extraction: none — this is a module-level
helper relocated as-is (it has no `self`). Compare the comprehension predicate:
the empty-string sentinel, the `None`-vs-`value` branches, and the iteration
target.
