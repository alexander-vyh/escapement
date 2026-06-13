# diff-01 — reference (moved body + original pre-extraction body)

## Moved body (as it appears in the extracted collaborator)

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

## Original pre-extraction body (from the parent commit, `processor.py`)

```python
def _sanitize_for_table_name(self, name: str) -> str:
    """Sanitize a name for use in BigQuery table IDs.

    BigQuery table IDs only allow letters, numbers, and underscores.
    This replaces slashes and other invalid characters with underscores.

    Args:
        name: The name to sanitize (e.g., 'spaces/ac').

    Returns:
        Sanitized name safe for use in table IDs (e.g., 'spaces_ac').

    """
    # Replace common path separators and invalid characters with underscore
    sanitized = name.replace("/", "_").replace("-", "_")
    # Remove any double underscores that might result
    while "__" in sanitized:
        sanitized = sanitized.replace("__", "_")
    # Strip leading/trailing underscores
    return sanitized.strip("_")
```

Expected mechanical differences from extraction: `self`-receiver dropped (now a
`@staticmethod`), docstring `Args:`/`Returns:` trimmed. Compare the *body logic*
line by line.
