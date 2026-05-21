"""
main.py
-------
Entry point for the Salesforce Org Expiration Checker.

How it works:
  1. Loads configuration from config.json
  2. For each org in the config, authenticates and queries:
     a. The Organization object (for trial/dev org expiry)
     b. The Tooling API SandboxProcess object (for sandbox expiry)
  3. Combines all results into a single list
  4. Writes a CSV report
  5. Prints a summary table to the terminal
"""

import json
import logging
import os
import sys
from datetime import datetime

from sf_client import SalesforceClient
from org_inspector import query_org_info, query_sandbox_expiry
from report_generator import generate_csv_report, print_summary_to_console


# ---------------------------------------------------------------------------
# LOGGING SETUP
# ---------------------------------------------------------------------------

def setup_logging(log_level: str = "INFO") -> None:
    """
    Configures logging to write to both the terminal and a timestamped log file.
    Log files are stored in the 'logs/' directory.
    """
    os.makedirs("logs", exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_filename = os.path.join("logs", f"sf_expiry_check_{timestamp}.log")

    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    # Create formatter
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    date_fmt = "%Y-%m-%d %H:%M:%S"
    formatter = logging.Formatter(fmt=fmt, datefmt=date_fmt)

    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    # Terminal handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(numeric_level)
    root_logger.addHandler(console_handler)

    # File handler
    file_handler = logging.FileHandler(log_filename, encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)  # Always capture DEBUG in file
    root_logger.addHandler(file_handler)

    logging.info(f"Logging initialised. Log file: {log_filename}")


# ---------------------------------------------------------------------------
# CONFIG LOADING
# ---------------------------------------------------------------------------

def load_config(config_path: str = "config.json") -> dict:
    """
    Loads and validates config.json.
    """
    if not os.path.exists(config_path):
        print(
            f"\n[ERROR] Config file not found: '{config_path}'\n"
            f"  Please create config.json in the same folder as main.py.\n"
            f"  Use the provided config.json example as a template.\n"
        )
        sys.exit(1)

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        print(
            f"\n[ERROR] config.json is not valid JSON.\n"
            f"  Error: {str(e)}\n"
            f"  Common cause: missing comma, trailing comma, or unquoted value.\n"
        )
        sys.exit(1)

    if "orgs" not in config or not config["orgs"]:
        print(
            "\n[ERROR] config.json must contain an 'orgs' list with at least one org.\n"
        )
        sys.exit(1)

    return config


# ---------------------------------------------------------------------------
# MAIN FUNCTION
# ---------------------------------------------------------------------------

def main():
    # 1. Load configuration
    config = load_config("config.json")

    # 2. Set up logging
    settings = config.get("settings", {})
    log_level = settings.get("log_level", "INFO")
    setup_logging(log_level)

    logger = logging.getLogger(__name__)
    logger.info("=" * 60)
    logger.info("Salesforce Org Expiration Checker — Starting")
    logger.info("=" * 60)

    orgs = config["orgs"]
    expiring_soon_days = settings.get("expiring_soon_days", 30)
    output_file = settings.get("output_file", "org_expiration_report.csv")

    logger.info(f"Configuration loaded. Processing {len(orgs)} org(s).")
    logger.info(f"'Expiring Soon' threshold: {expiring_soon_days} days")
    logger.info(f"Output CSV: {output_file}")

    all_records = []
    errors = []

    # 3. Process each org
    for org_config in orgs:
        alias = org_config.get("alias", "UnknownOrg")
        logger.info(f"\n--- Processing org: {alias} ---")

        try:
            # Authenticate
            client = SalesforceClient(org_config)
            sf = client.connect()

            # Query Organization object (main org info + trial expiry)
            org_data = query_org_info(sf, alias, expiring_soon_days)
            all_records.append(org_data)

            # Query Sandbox expiry (only makes sense on production orgs)
            # If the org itself is a sandbox, SandboxProcess won't be queryable
            is_sandbox = org_config.get("is_sandbox", False)
            if not is_sandbox:
                sandbox_records = query_sandbox_expiry(sf, alias, expiring_soon_days)
                all_records.extend(sandbox_records)
            else:
                logger.info(
                    f"[{alias}] Skipping SandboxProcess query "
                    f"(this org is configured as a sandbox)."
                )

        except RuntimeError as e:
            error_msg = str(e)
            logger.error(f"[{alias}] FAILED: {error_msg}")
            errors.append({"alias": alias, "error": error_msg})

            # Add an error record to the CSV so the org still appears
            all_records.append({
                "alias": alias,
                "org_id": "ERROR",
                "org_name": f"FAILED: {alias}",
                "org_edition": "N/A",
                "instance": "N/A",
                "is_sandbox": org_config.get("is_sandbox", False),
                "expiration_date": "N/A",
                "days_remaining": "N/A",
                "status": f"ERROR: {error_msg[:80]}",
                "record_type": "Error",
            })

        except Exception as e:
            # Catch any unexpected exceptions so one bad org doesn't stop all
            error_msg = f"Unexpected error: {str(e)}"
            logger.exception(f"[{alias}] {error_msg}")
            errors.append({"alias": alias, "error": error_msg})

    # 4. Print summary to terminal
    print_summary_to_console(all_records)

    # 5. Write CSV report
    logger.info("Writing CSV report...")
    try:
        csv_path = generate_csv_report(all_records, output_file)
        print(f"\n✅ Report saved to: {csv_path}\n")
    except RuntimeError as e:
        logger.error(f"CSV generation failed: {e}")
        print(f"\n❌ CSV generation failed: {e}\n")

    # 6. Final summary
    logger.info("=" * 60)
    logger.info(f"Run complete. {len(all_records)} record(s) processed.")
    if errors:
        logger.warning(f"{len(errors)} org(s) had errors:")
        for err in errors:
            logger.warning(f"  - {err['alias']}: {err['error'][:100]}")
    logger.info("=" * 60)

    # Exit with error code if any org failed
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
