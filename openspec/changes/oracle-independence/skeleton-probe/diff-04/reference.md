# diff-04 — reference (moved body + original pre-extraction body)

## Moved body (as it appears in the extracted collaborator)

```python
def find_bronze_batches(self) -> list[str]:
    """Find successful Bronze batches for the ingest date.

    Handles both standard and nested path structures:
    - Standard: bronze/{source}/{object}/ingest_date=*/batch_ts=*/
    - Nested:   bronze/{source}/{object}/{nested_key}/ingest_date=*/batch_ts=*/

    Returns:
        List of batch directory prefixes with _SUCCESS markers.
    """
    src = self._source_type.lower()
    obj = self._object_name.lower()
    batch_prefixes = set()

    if has_nested_key(src, obj):
        # Enumerate nested keys (e.g., space_keys) first
        base_prefix = f"bronze/{src}/{obj}/"
        nested_keys = self.enumerate_nested_keys(base_prefix)

        for nested_key in nested_keys:
            nested_prefix = f"bronze/{src}/{obj}/{nested_key}/ingest_date={self._ingest_date}/"
            for blob in self._storage_client.list_blobs(self._bucket_name, prefix=nested_prefix):
                if blob.name.startswith("_SUCCESS"):
                    batch_dir = blob.name.rsplit("/", 1)[0] + "/"
                    batch_prefixes.add(batch_dir)
    else:
        # Standard flat path structure
        prefix = f"bronze/{src}/{obj}/ingest_date={self._ingest_date}/"
        for blob in self._storage_client.list_blobs(self._bucket_name, prefix=prefix):
            if blob.name.endswith("_SUCCESS"):
                batch_dir = blob.name.rsplit("/", 1)[0] + "/"
                batch_prefixes.add(batch_dir)

    return sorted(batch_prefixes)
```

## Original pre-extraction body (from the parent commit, `processor.py`)

```python
def _find_bronze_batches(self) -> list[str]:
    """Find successful Bronze batches for the ingest date.

    Handles both standard and nested path structures:
    - Standard: bronze/{source}/{object}/ingest_date=*/batch_ts=*/
    - Nested:   bronze/{source}/{object}/{nested_key}/ingest_date=*/batch_ts=*/

    Returns:
        List of batch directory prefixes with _SUCCESS markers.

    """
    src = self.source_type.lower()
    obj = self.object_name.lower()
    batch_prefixes = set()

    if has_nested_key(src, obj):
        # Enumerate nested keys (e.g., space_keys) first
        base_prefix = f"bronze/{src}/{obj}/"
        nested_keys = self._enumerate_nested_keys(base_prefix)

        for nested_key in nested_keys:
            nested_prefix = f"bronze/{src}/{obj}/{nested_key}/ingest_date={self.ingest_date}/"
            for blob in self.storage_client.list_blobs(self.bucket_name, prefix=nested_prefix):
                if blob.name.endswith("_SUCCESS"):
                    batch_dir = blob.name.rsplit("/", 1)[0] + "/"
                    batch_prefixes.add(batch_dir)
    else:
        # Standard flat path structure
        prefix = f"bronze/{src}/{obj}/ingest_date={self.ingest_date}/"
        for blob in self.storage_client.list_blobs(self.bucket_name, prefix=prefix):
            if blob.name.endswith("_SUCCESS"):
                batch_dir = blob.name.rsplit("/", 1)[0] + "/"
                batch_prefixes.add(batch_dir)

    return sorted(batch_prefixes)
```

Expected mechanical differences from extraction: `self.source_type` →
`self._source_type`; `self.object_name` → `self._object_name`;
`self.ingest_date` → `self._ingest_date`; `self.storage_client` →
`self._storage_client`; `self.bucket_name` → `self._bucket_name`;
`self._enumerate_nested_keys(...)` → `self.enumerate_nested_keys(...)`. Compare
the *predicate that selects a `_SUCCESS` marker* and the batch-dir derivation in
**both** branches.
