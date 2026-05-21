"""
report_generator.py
-------------------
Generates the CSV report from the collected org data.
"""

import csv
import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)

# These are the exact columns that will appear in the CSV, in order.
REPORT_COLUMNS = [
    "Alias",
    "Organization ID",
    "Organization Name",
    "Organization Edition",
    "Instance",
    "Record Type",
    "Is Sandbox",
    "Expiration Date",
    "Days Remaining",
    "Status",
    "Report Generated At",
]


def generate_csv_report(all_records: list[dict], output_file: str) -> str:
    """
    Takes a list of org record dicts (as produced by org_inspector.py)
    and writes them to a CSV file.

    Returns the absolute path of the created CSV file.
    """
    if not all_records:
        logger.warning("No records to write. CSV will contain headers only.")

    # Ensure output directory exists
    output_dir = os.path.dirname(os.path.abspath(output_file))
    os.makedirs(output_dir, exist_ok=True)

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        with open(output_file, mode="w", newline="", encoding="utf-8") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=REPORT_COLUMNS)
            writer.writeheader()

            for record in all_records:
                row = {
                    "Alias": record.get("alias", "N/A"),
                    "Organization ID": record.get("org_id", "N/A"),
                    "Organization Name": record.get("org_name", "N/A"),
                    "Organization Edition": record.get("org_edition", "N/A"),
                    "Instance": record.get("instance", "N/A"),
                    "Record Type": record.get("record_type", "N/A"),
                    "Is Sandbox": "Yes" if record.get("is_sandbox") else "No",
                    "Expiration Date": record.get("expiration_date", "N/A"),
                    "Days Remaining": record.get("days_remaining", "N/A"),
                    "Status": record.get("status", "N/A"),
                    "Report Generated At": generated_at,
                }
                writer.writerow(row)

        abs_path = os.path.abspath(output_file)
        logger.info(f"CSV report written to: {abs_path}")
        logger.info(f"Total rows written: {len(all_records)}")
        return abs_path

    except PermissionError:
        raise RuntimeError(
            f"Cannot write to '{output_file}'. "
            f"Is the file open in Excel? Close it and try again."
        )
    except Exception as e:
        raise RuntimeError(f"Failed to write CSV report: {str(e)}")


def print_summary_to_console(all_records: list[dict]) -> None:
    """
    Prints a human-readable summary table to the terminal.
    """
    if not all_records:
        print("\n  [No records found]\n")
        return

    # Column widths for terminal display
    col_widths = {
        "Alias": 20,
        "Name": 30,
        "Expiration Date": 22,
        "Days": 8,
        "Status": 30,
    }

    header = (
        f"{'Alias':<{col_widths['Alias']}} "
        f"{'Org Name':<{col_widths['Name']}} "
        f"{'Expiration Date':<{col_widths['Expiration Date']}} "
        f"{'Days':<{col_widths['Days']}} "
        f"{'Status':<{col_widths['Status']}}"
    )
    separator = "-" * len(header)

    print("\n" + "=" * len(header))
    print("  SALESFORCE ORG EXPIRATION REPORT")
    print("=" * len(header))
    print(header)
    print(separator)

    for rec in all_records:
        status = rec.get("status", "N/A")
        # Add a visual indicator based on status
        if "Expired" in status:
            indicator = "🔴"
        elif "Expiring Soon" in status:
            indicator = "🟡"
        else:
            indicator = "🟢"

        days_val = rec.get("days_remaining", "N/A")
        days_str = str(days_val) if days_val != "N/A" else "N/A"

        line = (
            f"{rec.get('alias', 'N/A'):<{col_widths['Alias']}} "
            f"{rec.get('org_name', 'N/A')[:col_widths['Name']]:<{col_widths['Name']}} "
            f"{str(rec.get('expiration_date', 'N/A'))[:col_widths['Expiration Date']]:<{col_widths['Expiration Date']}} "
            f"{days_str:<{col_widths['Days']}} "
            f"{indicator} {status}"
        )
        print(line)

    print(separator)
    total = len(all_records)
    expired = sum(1 for r in all_records if "Expired" in r.get("status", ""))
    expiring = sum(1 for r in all_records if "Expiring Soon" in r.get("status", ""))
    print(
        f"\nSUMMARY: {total} total | "
        f"{expiring} expiring soon | "
        f"{expired} expired\n"
    )
