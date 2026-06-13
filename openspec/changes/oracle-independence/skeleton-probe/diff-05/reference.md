# diff-05 — reference (moved body + original pre-extraction body)

## Moved body (as it appears in the extracted collaborator)

```python
def write_manifest(self, bronze_batches: list[str]) -> None:
    """Write the compaction manifest after a successful compaction."""
    manifest = {
        "compacted_at": datetime.now(UTC).isoformat(),
        "source": self._source_type,
        "object": self._object_name,
        "ingest_date": self._ingest_date,
        "batches_processed": sorted(bronze_batches),
        "batch_count": len(bronze_batches),
    }

    blob = self._bucket.blob(self.manifest_path)
    blob.upload_from_string(
        json.dumps(manifest, indent=2),
        content_type="application/json",
    )
    logger.info(f"Written compaction manifest: {self.manifest_path}")
```

## Original pre-extraction body (from the parent commit, `processor.py`)

```python
def _write_manifest(self, bronze_batches: list[str]) -> None:
    """Write compaction manifest after successful compaction.

    Args:
        bronze_batches: List of Bronze batch directories that were compacted.

    """
    manifest = {
        "compacted_at": datetime.now(UTC).isoformat(),
        "source": self.source_type,
        "object": self.object_name,
        "ingest_date": self.ingest_date,
        "batches_processed": sorted(bronze_batches),
        "batch_count": len(bronze_batches),
    }

    manifest_path = self._get_manifest_path()
    blob = self.bucket.blob(manifest_path)
    blob.upload_from_string(
        json.dumps(manifest, indent=2),
        content_type="application/json",
    )
    logger.info(f"Written compaction manifest: {manifest_path}")
```

Expected mechanical differences from extraction: `self.source_type` →
`self._source_type`; `self.object_name` → `self._object_name`;
`self.ingest_date` → `self._ingest_date`; `self.bucket` → `self._bucket`; the
local `manifest_path = self._get_manifest_path()` becomes the
`self.manifest_path` property. Compare the *manifest dict keys/values* and the
`json.dumps(..., indent=2)` / `content_type` arguments.
