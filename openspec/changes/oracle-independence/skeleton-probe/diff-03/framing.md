# diff-03 — extracted seam

Verbatim extraction of `describe_report` into `cake/clients/_async/salesforce/reports.py` (`ReportsMixin`); byte-identical relocation; tests green.

```python
async def describe_report(self, report_id: str) -> ReportMetadata:
    """Get report metadata without executing it.

    Args:
        report_id: The Salesforce report ID

    Returns:
        ReportMetadata object with report structure

    """
    await self._ensure_valid_token()

    url = f"analytics/reports/{report_id}/describe"
    data = (await self.make_request_with_headers("GET", url)).data

    metadata = data.get("reportMetadata", {})

    return ReportMetadata(
        id=report_id,
        name=metadata.get("name", ""),
        description=metadata.get("description"),
        report_type=data.get("reportTypeMetadata", {}),
        report_format=metadata.get("reportFormat", "TABULAR"),
        columns=metadata.get("detailColumns", []),
        filters=metadata.get("reportFilters", []),
        created_date=metadata.get("createdDate", ""),
        last_modified_date=metadata.get("lastModifiedDate", ""),
    )
```
