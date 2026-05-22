"""
Validate that row_map entries match actual sheet labels before any structural operation.

Usage (CLI):
    python scripts/validate.py --project <name> --scenario <scenario_id>
    python scripts/validate.py --project <name>   # validates all scenarios

Usage (library):
    from validate import validate_row_map
    ok = validate_row_map(service, sid, tab_name, row_map, items_by_id, abort=True)
"""
import os
import sys
import json
import argparse

sys.path.insert(0, os.path.dirname(__file__))
from sheets_client import get_service, read_range
from project_config import get_project_dir, load_project, load_config, load_row_map, get_scenario_row_map_key


def validate_row_map(service, spreadsheet_id, tab_name, row_map, items_by_id, abort=True):
    """
    Read column B of tab_name from the live sheet and compare each row_map entry
    to the expected label from items_by_id.

    row_map:     {item_id: row_1idx}   (already inverted by load_row_map)
    items_by_id: {item_id: item_dict}  (from the scenario JSON line_items)
    abort:       if True, sys.exit(1) on mismatch; if False, return False instead

    Returns True if all checked entries match, False otherwise.
    Skips entries where the expected label is unknown (item not in items_by_id or has no label).
    """
    rows = read_range(service, spreadsheet_id, f"{tab_name}!A:B")

    mismatches = []
    skipped = []

    for item_id, row in sorted(row_map.items(), key=lambda x: x[1]):
        item = items_by_id.get(item_id)
        if item is None:
            skipped.append((row, item_id, "not in JSON"))
            continue

        expected_label = item.get("label", "")
        if not expected_label:
            skipped.append((row, item_id, "no label field"))
            continue

        idx = row - 1  # 0-indexed
        actual_label = ""
        if idx < len(rows):
            row_data = rows[idx]
            if len(row_data) > 1:
                actual_label = row_data[1]
            elif row_data:
                actual_label = row_data[0]

        if actual_label.strip() != expected_label.strip():
            mismatches.append((row, actual_label, item_id, expected_label))

    if mismatches:
        print(f"\n  row_map MISMATCH detected in {tab_name} ({len(mismatches)} errors):")
        print(f"  {'Row':>4}  {'Sheet label':<40}  {'Expected (row_map)'}")
        print(f"  {'-'*4}  {'-'*40}  {'-'*30}")
        for row, actual, item_id, expected in mismatches:
            print(f"  {row:>4}  {actual:<40}  {expected}  [{item_id}]  ✗")
        if skipped:
            print(f"  (skipped {len(skipped)} entries with no expected label)")
        if abort:
            print(f"\n  Aborting — fix row_map.json before writing to {tab_name}.\n")
            sys.exit(1)
        return False

    checked = len(row_map) - len(skipped)
    print(f"  {tab_name}: row_map OK — {checked} entries verified ✓")
    return True


def validate_scenario(service, spreadsheet_id, scenario, row_map, project_dir):
    """Validate one scenario's row_map against the live sheet."""
    tab_name = scenario["tab"]
    json_path = os.path.join(project_dir, scenario["json_file"])

    with open(json_path) as f:
        data = json.load(f)

    if scenario.get("phases"):
        phase = scenario["phases"][0]
        items = data[phase]["line_items"]
    else:
        items = data["line_items"]

    items_by_id = {item["id"]: item for item in items}
    rm_key = get_scenario_row_map_key(scenario)
    scenario_row_map = row_map.get(rm_key, {})

    return validate_row_map(service, spreadsheet_id, tab_name, scenario_row_map, items_by_id, abort=False)


def main():
    parser = argparse.ArgumentParser(description="Validate row_map against live sheet labels")
    parser.add_argument("--project", required=True, help="Project name")
    parser.add_argument("--scenario", default=None, help="Scenario ID (default: all scenarios)")
    args = parser.parse_args()

    project_dir = get_project_dir(args.project)
    config = load_config(project_dir)
    project = load_project(project_dir)
    row_map = load_row_map(project_dir)

    print("Authenticating...")
    service = get_service()
    sid = config["spreadsheet_id"]

    scenarios = project["scenarios"]
    if args.scenario:
        scenarios = [s for s in scenarios if s["id"] == args.scenario]
        if not scenarios:
            print(f"ERROR: Scenario '{args.scenario}' not found.")
            print(f"  Available: {[s['id'] for s in project['scenarios']]}")
            sys.exit(1)

    all_ok = True
    for scenario in scenarios:
        ok = validate_scenario(service, sid, scenario, row_map, project_dir)
        if not ok:
            all_ok = False

    if not all_ok:
        print("\nValidation FAILED — row_map drift detected. Fix before running push or add_item.")
        sys.exit(1)
    else:
        print("\nAll row_map entries validated successfully.")


if __name__ == "__main__":
    main()
