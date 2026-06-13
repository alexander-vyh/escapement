# diff-02 — extracted seam

Verbatim extraction of `_try_acquire_lock` into `cake/compactor/compaction_lock.py` (`CompactionLock.acquire`); byte-identical relocation; tests green.

```python
def acquire(self, lock_timeout_minutes: int = 30) -> tuple[bool, str | None]:
    """Try to acquire the partition lock.

    Uses an expiry so a stale lock can be taken over after
    ``lock_timeout_minutes``.

    Returns:
        ``(acquired, lock_holder)``. When ``acquired`` is ``False``,
        ``lock_holder`` describes the current holder.
    """
    lock_blob = self._bucket.blob(self._lock_path)
    lock_id = f"{self._run_id}@{os.environ.get('CLOUD_RUN_EXECUTION', 'local')}"
    lock_data = {
        "holder": lock_id,
        "acquired_at": datetime.now(UTC).isoformat(),
        "expires_at": (datetime.now(UTC) + timedelta(minutes=lock_timeout_minutes)).isoformat(),
    }

    try:
        # Check if lock exists and is expired
        if lock_blob.exists():
            existing = json.loads(lock_blob.download_as_string().decode())
            expires_at = datetime.fromisoformat(existing["expires_at"])
            if datetime.now(UTC) < expires_at:
                # Lock is still valid
                return False, f"locked by {existing['holder']} until {existing['expires_at']}"
            # Lock expired, try to take it
            logger.info(f"Lock expired, attempting to acquire: {existing['holder']}")

        lock_blob.upload_from_string(
            json.dumps(lock_data),
            content_type="application/json",
        )
        logger.info(f"Acquired lock for {self._label}")
        return True, None

    except google.api_core.exceptions.PreconditionFailed:
        # Another process acquired the lock
        try:
            existing = json.loads(lock_blob.download_as_string().decode())
            return False, f"locked by {existing['holder']}"
        except Exception:
            return False, "lock contention"
    except Exception as e:
        logger.warning(f"Lock acquisition error: {e}")
        return False, str(e)
```
