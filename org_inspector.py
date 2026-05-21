"""
org_inspector.py
----------------
Queries Salesforce APIs to retrieve org and sandbox expiration information.

Key design decisions (architecture):
  - The Organization object's TrialExpirationDate field is ONLY populated
    for trial orgs and Developer Edition orgs. Licensed production orgs
    return NULL for this field — this is expected behaviour, not an error.
  - Sandbox expiration dates come from the Tooling API's SandboxProcess object.
  - Both data sources are combined into a unified report structure.
"""

import logging
from datetime import datetime, timezone
from dateutil import parser as dateutil_parser
from simple_salesforce import Salesforce

logger = logging.getLogger(__name__)


def _days_remaining(expiration_date_str: str) -> int | None:
    """
    Given an ISO 8601 date string (e.g. '2025-08-15T00:00:00.000+0000'),
    returns the number of days from today until that date.
    Negative means already expired.
    Returns None if input is None or unparseable.
    """
    if not expiration_date_str:
        return None
    try:
        expiry_dt = dateutil_parser.parse(expiration_date_str)
        # Make sure we compare timezone-aware datetimes
        if expiry_dt.tzinfo is None:
            expiry_dt = expiry_dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        delta = expiry_dt - now
        return delta.days
    except Exception as e:
        logger.warning(f"Could not parse date '{expiration_date_str}': {e}")
        return None


def _classify_status(days: int | None, expiring_soon_threshold: int = 30) -> str:
    """
    Returns a human-readable status string based on days remaining.
    """
    if days is None:
        return "Active (No Expiry Set)"
    if days < 0:
        return "Expired"
    if days <= expiring_soon_threshold:
        return f"Expiring Soon ({days} days)"
    return "Active"


def query_org_info(sf: Salesforce, alias: str, expiring_soon_days: int = 30) -> dict:
    """
    Queries the Organization object for the org's basic info and
    trial expiration date (if this is a trial/dev org).

    Returns a dict with all fields needed for the report.
    """
    logger.info(f"[{alias}] Querying Organization object...")

    # Fields we want from the Organization object:
    # - Id               : 18-char Org ID
    # - Name             : Org name (e.g. "Acme Corp")
    # - OrganizationType : "Enterprise Edition", "Developer Edition", etc.
    # - InstanceName     : Server instance (e.g. "NA253", "CS42")
    # - IsSandbox        : True/False
    # - TrialExpirationDate: Populated ONLY for trial/developer orgs
    #
    # NOTE: OrganizationType is the API field; it maps to what UI shows as
    # "Salesforce.com Edition" on Company Information page.

    soql = (
        "SELECT Id, Name, OrganizationType, InstanceName, "
        "IsSandbox, TrialExpirationDate "
        "FROM Organization "
        "LIMIT 1"
    )

    try:
        result = sf.query(soql)
    except Exception as e:
        raise RuntimeError(
            f"[{alias}] Failed to query Organization object.\n"
            f"  Error: {str(e)}\n"
            f"  Make sure your user has 'View Setup and Configuration' permission."
        )

    if not result.get("records"):
        raise RuntimeError(
            f"[{alias}] Organization query returned no records. "
            f"This should never happen — check API permissions."
        )

    record = result["records"][0]
    logger.debug(f"[{alias}] Raw Organization record: {record}")

    org_id = record.get("Id", "N/A")
    org_name = record.get("Name", "N/A")
    org_type = record.get("OrganizationType", "N/A")
    instance_name = record.get("InstanceName", "N/A")
    is_sandbox = record.get("IsSandbox", False)
    trial_expiry = record.get("TrialExpirationDate")  # None for production orgs

    days = _days_remaining(trial_expiry)
    status = _classify_status(days, expiring_soon_days)

    org_data = {
        "alias": alias,
        "org_id": org_id,
        "org_name": org_name,
        "org_edition": org_type,
        "instance": instance_name,
        "is_sandbox": is_sandbox,
        "expiration_date": trial_expiry if trial_expiry else "N/A (Licensed Org)",
        "days_remaining": days if days is not None else "N/A",
        "status": status,
        "record_type": "Production Org",
    }

    if trial_expiry:
        logger.info(
            f"[{alias}] Org '{org_name}' expires on {trial_expiry} "
            f"({days} days remaining) — Status: {status}"
        )
    else:
        logger.info(
            f"[{alias}] Org '{org_name}' is a licensed org with no trial expiry date."
        )

    return org_data


def query_sandbox_expiry(
    sf: Salesforce,
    alias: str,
    expiring_soon_days: int = 30,
) -> list[dict]:
    """
    Queries the Tooling API's SandboxProcess object to find all sandboxes
    associated with this production org, including their expiration dates.

    IMPORTANT: This must be called on the PRODUCTION org, not a sandbox.
    Sandboxes cannot query their own SandboxProcess records.

    Returns a list of dicts, one per sandbox.
    """
    logger.info(f"[{alias}] Querying Tooling API for SandboxProcess records...")

    soql = (
        "SELECT Id, SandboxName, Status, ExpirationDate, LicenseType "
        "FROM SandboxProcess "
        "ORDER BY ExpirationDate ASC NULLS LAST"
    )

    sandbox_records = []

    try:
        # Tooling API query — different endpoint from regular SOQL
        result = sf.toolingexecute(
            f"query?q={requests_quote(soql)}"
        )
    except Exception as e:
        logger.warning(
            f"[{alias}] Could not query Tooling API SandboxProcess: {str(e)}\n"
            f"  This is expected if the connected org is itself a sandbox,\n"
            f"  or if the user lacks 'Manage Sandboxes' permission.\n"
            f"  Skipping sandbox expiry check for this org."
        )
        return []

    records = result.get("records", [])
    logger.info(f"[{alias}] Found {len(records)} sandbox record(s).")

    for rec in records:
        sandbox_name = rec.get("SandboxName", "N/A")
        status_raw = rec.get("Status", "N/A")
        expiry = rec.get("ExpirationDate")
        license_type = rec.get("LicenseType", "N/A")

        days = _days_remaining(expiry)
        status = _classify_status(days, expiring_soon_days)

        sandbox_records.append({
            "alias": alias,
            "org_id": rec.get("Id", "N/A"),
            "org_name": f"{alias} — Sandbox: {sandbox_name}",
            "org_edition": license_type,
            "instance": "Sandbox",
            "is_sandbox": True,
            "expiration_date": expiry if expiry else "N/A",
            "days_remaining": days if days is not None else "N/A",
            "status": status,
            "record_type": "Sandbox",
        })

        logger.info(
            f"[{alias}] Sandbox '{sandbox_name}': "
            f"Status={status_raw}, Expires={expiry or 'N/A'}, "
            f"Days={days if days is not None else 'N/A'}"
        )

    return sandbox_records


def requests_quote(s: str) -> str:
    """URL-encodes a SOQL string for use in Tooling API query parameter."""
    import urllib.parse
    return urllib.parse.quote(s)
