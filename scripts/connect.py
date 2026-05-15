"""
Connect Gridpilot to an existing spreadsheet without rebuilding it.

Reads the spreadsheet to discover where each input field and line item lives,
then writes input_map.json and row_map.json so that pull/push can work normally.

This is the entry point for users with a sheet that was already created by
init_sheet.py (either on this machine or a different one).

Usage:
    python scripts/connect.py --project estate --spreadsheet-id 1xF0dAI...
    python scripts/connect.py --project estate --spreadsheet-id 1xF0dAI... --use-existing-row-map
"""
import os
import sys
import json
import argparse

sys.path.insert(0, os.path.dirname(__file__))
from sheets_client import get_service
from project_config import get_project_dir, load_project, get_scenario_row_map_key, GRIDPILOT_ROOT


def discover_input_map(service, spreadsheet_id, project):
    """
    Scans the BUDGET tab column A for field labels defined in project.json.
    Returns input_map: {dotted_key: "B{row}"}
    Also reports any fields that couldn't be matched.
    """
    inp_tab = project["tabs"]["inputs"]
    result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=f"{inp_tab}!A1:A200",
    ).execute()
    col_a = [row[0].strip() if row else "" for row in result.get("values", [])]

    input_map = {"_last_ai_edit": "B3"}  # always fixed
    unmatched = []

    for section in project["inputs_sections"]:
        for field in section["fields"]:
            label = field["label"].strip()
            matched = False
            for i, cell_val in enumerate(col_a):
                if cell_val.lower() == label.lower():
                    row_1idx = i + 1  # 1-indexed
                    input_map[field["key"]] = f"B{row_1idx}"
                    matched = True
                    break
            if not matched:
                unmatched.append(f"  {field['key']} (label: '{label}')")

    if unmatched:
        print(f"  WARNING: Could not find {len(unmatched)} field(s) in {inp_tab} tab:")
        for u in unmatched:
            print(u)
        print("  These fields will be missing from input_map.json.")
        print("  Check that project.json field labels match column A in the sheet.")

    return input_map


def discover_row_map(service, spreadsheet_id, project):
    """
    Scans each scenario tab column B for line item labels.
    Returns row_map: {scenario_key: {row_1idx_str: item_id}}
    """
    row_map = {}
    unmatched_total = []

    for scenario in project["scenarios"]:
        tab_name = scenario["tab"]

        # Read the whole tab column B
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=f"{tab_name}!B1:B500",
        ).execute()
        col_b = [row[0].strip() if row else "" for row in result.get("values", [])]

        # Gather all items across all phases
        if not scenario.get("phases"):
            all_items = {"single": []}
            for item in _load_items(scenario, None):
                all_items["single"].append(item)
        else:
            all_items = {}
            for phase in scenario["phases"]:
                all_items[phase] = _load_items(scenario, phase)

        if not scenario.get("phases"):
            items = all_items["single"]
            rm_key = get_scenario_row_map_key(scenario)
            rm, unmatched = _match_items_to_rows(items, col_b, tab_name)
            row_map[rm_key] = rm
            unmatched_total.extend(unmatched)
        else:
            # For multi-phase, all phases share rows — match once against all phase1 items
            phase0 = scenario["phases"][0]
            phase1 = scenario["phases"][1] if len(scenario["phases"]) > 1 else None

            p1_items = all_items.get(phase0, [])
            rm_p1, unmatched_p1 = _match_items_to_rows(p1_items, col_b, tab_name)
            row_map[get_scenario_row_map_key(scenario, phase0)] = rm_p1

            if phase1:
                p2_items = all_items.get(phase1, [])
                # Phase 2 items share rows with phase 1 (same row, different columns)
                # Match p2 items by their corresponding p1 item label
                rm_p2 = {}
                for item in p2_items:
                    p1_id = item["id"].replace("_p2", "")
                    if p1_id in {v: k for k, v in rm_p1.items()}:
                        # Find p1 row
                        for row_str, iid in rm_p1.items():
                            if iid == p1_id:
                                rm_p2[row_str] = item["id"]
                                break
                row_map[get_scenario_row_map_key(scenario, phase1)] = rm_p2

            unmatched_total.extend(unmatched_p1)

    if unmatched_total:
        print(f"\n  WARNING: {len(unmatched_total)} item(s) could not be matched in the sheet:")
        for u in unmatched_total[:10]:
            print(f"    {u}")
        if len(unmatched_total) > 10:
            print(f"    ... and {len(unmatched_total) - 10} more")

    return row_map


def _load_items(scenario, phase):
    """Load line items from the scenario JSON file for a given phase (or None for single-phase)."""
    # project_dir is not available here; use a relative lookup
    # The JSON file path is relative to the project dir — caller must have set up CWD
    # We need to pass project_dir in. For simplicity, we store it as a module-level var
    # set by main() before calling discover_row_map.
    json_path = _current_project_dir + "/" + scenario["json_file"]
    with open(json_path) as f:
        data = json.load(f)
    if phase:
        return data[phase]["line_items"]
    return data["line_items"]


_current_project_dir = None  # set by main() before discovery calls


def _match_items_to_rows(items, col_b, tab_name):
    """Match item labels to rows. Returns (row_map_dict, unmatched_list)."""
    rm = {}  # row_1idx_str -> item_id
    unmatched = []
    for item in items:
        label = item["label"].strip()
        matched = False
        for i, cell_val in enumerate(col_b):
            if cell_val.strip().lower() == label.lower():
                rm[str(i + 1)] = item["id"]
                matched = True
                break
        if not matched:
            unmatched.append(f"{tab_name}: {item['id']} (label: '{label}')")
    return rm, unmatched


def main():
    global _current_project_dir

    parser = argparse.ArgumentParser(description="Connect Gridpilot to an existing spreadsheet")
    parser.add_argument("--project", required=True, help="Project name (subdirectory of projects/)")
    parser.add_argument("--spreadsheet-id", required=True, help="Google Sheets spreadsheet ID")
    parser.add_argument("--use-existing-row-map", action="store_true",
                        help="Skip row map discovery; use row_map.json already in project dir")
    args = parser.parse_args()

    project_dir = get_project_dir(args.project)
    project = load_project(project_dir)
    _current_project_dir = project_dir

    # Write spreadsheet_id to config.json
    config_path = os.path.join(project_dir, "config.json")
    config = {}
    if os.path.exists(config_path):
        with open(config_path) as f:
            config = json.load(f)

    if config.get("spreadsheet_id") and config["spreadsheet_id"] != args.spreadsheet_id:
        print(f"WARNING: config.json already has a different spreadsheet_id.")
        print(f"  Existing: {config['spreadsheet_id']}")
        print(f"  New:      {args.spreadsheet_id}")
        print("  Overwriting...")

    print("Authenticating with Google...")
    service = get_service()

    spreadsheet_id = args.spreadsheet_id
    url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"

    # Discover input_map
    print(f"Scanning BUDGET tab for input field positions...")
    input_map = discover_input_map(service, spreadsheet_id, project)
    input_map_path = os.path.join(project_dir, "input_map.json")
    with open(input_map_path, "w") as f:
        json.dump(input_map, f, indent=2)
    print(f"  input_map.json written ({len(input_map)} fields mapped).")

    # Discover or use existing row_map
    if args.use_existing_row_map:
        row_map_path = os.path.join(project_dir, "row_map.json")
        if not os.path.exists(row_map_path):
            print("ERROR: --use-existing-row-map specified but row_map.json not found.")
            sys.exit(1)
        print("  Using existing row_map.json (skipping discovery).")
    else:
        print("Scanning scenario tabs for line item positions...")
        row_map = discover_row_map(service, spreadsheet_id, project)
        row_map_path = os.path.join(project_dir, "row_map.json")
        total_items = sum(len(v) for v in row_map.values())
        with open(row_map_path, "w") as f:
            json.dump(row_map, f, indent=2)
        print(f"  row_map.json written ({total_items} items mapped across "
              f"{len(row_map)} scenario keys).")

    # Save config.json
    config["spreadsheet_id"] = spreadsheet_id
    config["spreadsheet_url"] = url
    config["connected_at"] = __import__("datetime").datetime.now().isoformat()
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)

    print(f"\nConnected. Run pull to sync the sheet into local JSON:")
    print(f"  python scripts/pull.py --project {args.project}")
    print(f"Sheet URL: {url}")


if __name__ == "__main__":
    main()
