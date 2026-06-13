# diff-02 — reference (moved body + original pre-extraction body)

## Moved body (as it appears in the extracted collaborator)

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

## Original pre-extraction body (from the parent commit, `processor.py`)

```python
def _try_acquire_lock(self, lock_timeout_minutes: int = 30) -> tuple[bool, str | None]:
    """Try to acquire distributed lock for this partition.

    Uses GCS generation-based conditional writes for atomic lock acquisition.
    Locks expire after lock_timeout_minutes to prevent deadlocks.

    Args:
        lock_timeout_minutes: Lock expiry time in minutes (default 30).

    Returns:
        Tuple of (acquired: bool, lock_holder: str | None).
        If acquired is False, lock_holder contains info about current holder.

    """
    lock_blob = self.bucket.blob(self._get_lock_path())
    lock_id = f"{self._generate_run_id()}@{os.environ.get('CLOUD_RUN_EXECUTION', 'local')}"
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

        # Try to create/overwrite lock atomically using if_generation_match
        # generation=0 means "only if blob doesn't exist" for create
        # For overwrite of expired lock, we just overwrite (no condition)
        lock_blob.upload_from_string(
            json.dumps(lock_data),
            content_type="application/json",
        )
        logger.info(f"Acquired lock for {self.source_type}/{self.object_name}/{self.ingest_date}")
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

Expected mechanical differences from extraction: `self.bucket` → `self._bucket`;
lock-path lookup `self._get_lock_path()` → cached `self._lock_path`;
`self._generate_run_id()` → injected `self._run_id`; log label
`self.source_type/.../...` → injected `self._label`; an intermediate
`if_generation_match` comment dropped. Compare the *control-flow and operators*
line by line.
