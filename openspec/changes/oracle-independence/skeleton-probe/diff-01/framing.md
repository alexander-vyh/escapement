# diff-01 — extracted seam

Verbatim extraction of `_sanitize_for_table_name` into `cake/compactor/biglake_table.py` (`BigLakeTableManager`); byte-identical relocation; tests green.

```python
@staticmethod
def _sanitize_for_table_name(name: str) -> str:
    """Sanitize a name for use in BigQuery table IDs.

    BigQuery table IDs only allow letters, numbers, and underscores. This
    replaces slashes and other invalid characters with underscores.
    """
    # Replace common path separators and invalid characters with underscore
    sanitized = name.replace("/", "_").replace("-", "_")
    # Remove any double underscores that might result
    if "__" in sanitized:
        sanitized = sanitized.replace("__", "_")
    # Strip leading/trailing underscores
    return sanitized.strip("_")
```
