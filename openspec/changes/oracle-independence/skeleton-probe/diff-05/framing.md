# diff-05 — extracted seam

Verbatim extraction of `_write_manifest` into `cake/compactor/manifest_store.py` (`CompactionManifestStore.write_manifest`); byte-identical relocation; tests green.

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
