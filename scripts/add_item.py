"""
Add or remove a line item from the live sheet without re-initializing.

Inserts a row immediately after an existing item, writes the new item's
data, and updates row_map.json so future push/pull operations stay correct.

Usage:
    python scripts/add_item.py --project <name> --after <existing_id> --new-id <new_id> --scenario <scenario_id>
    python scripts/add_item.py --project <name> --remove <item_id> --scenario <scenario_id>

Workflow for adding:
    1. Add the new item to the relevant scenario JSON file
    2. Run this script with --after <the item it should follow>
    3. Done — no re-init needed

The scenario ID matches the "id" field in project.json["scenarios"].
"""
import os
import sys
import json
import argparse

sys.path.insert(0, os.path.dirname(__file__))
from sheets_client import get_service, get_sheet_id, batch_write
from project_config import (
    get_project_dir, load_project, load_config, load_row_map, save_row_map,
    get_scenario_row_map_key,
)
from formula_engine import is_formula_item


def insert_row_after(service, spreadsheet_id, sheet_id, after_row_1idx):
    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": [{
            "insertDimension": {
                "range": {"sheetId": sheet_id, "dimension": "ROWS",
                           "startIndex": after_row_1idx, "endIndex": after_row_1idx + 1},
                "inheritFromBefore": True,
            }
        }]},
    ).execute()
    return after_row_1idx + 1


def delete_row(service, spreadsheet_id, sheet_id, row_1idx):
    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": [{
            "deleteDimension": {
                "range": {"sheetId": sheet_id, "dimension": "ROWS",
                           "startIndex": row_1idx - 1, "endIndex": row_1idx}
            }
        }]},
    ).execute()


def shift_row_map(rm, map_key, from_row_1idx, delta):
    rm[map_key] = {
        item_id: (row + delta if row >= from_row_1idx else row)
        for item_id, row in rm[map_key].items()
    }


def find_scenario(project, scenario_id):
    for s in project["scenarios"]:
        if s["id"] == scenario_id:
            return s
    return None


def load_item_from_json(project_dir, scenario, item_id):
    """Load a specific item from the scenario JSON. Returns (item, phase_key) or (None, None)."""
    json_path = os.path.join(project_dir, scenario["json_file"])
    with open(json_path) as f:
        data = json.load(f)

    if not scenario.get("phases"):
        item = next((i for i in data["line_items"] if i["id"] == item_id), None)
        return item, None
    else:
        for phase in scenario["phases"]:
            item = next((i for i in data[phase]["line_items"] if i["id"] == item_id), None)
            if item:
                return item, phase
    return None, None


def write_item_to_sheet(service, spreadsheet_id, tab_name, row_1idx, item, is_multiphase, phase_key):
    if is_formula_item(item):
        print(f"  Skipping write for {item['id']} — formula-driven row.")
        return

    def v(val):
        return val if val is not None else ""

    if not is_multiphase:
        values = [[item.get("section", ""), item.get("label", ""),
                   v(item.get("low")), v(item.get("mid")), v(item.get("high")),
                   item.get("notes", "")]]
        batch_write(service, spreadsheet_id, [{
            "range": f"{tab_name}!A{row_1idx}:F{row_1idx}",
            "values": values,
        }])
    else:
        # Write to correct phase columns
        if phase_key and "phase1" in phase_key:
            values = [[item.get("section", ""), item.get("label", ""),
                       v(item.get("low")), v(item.get("mid")), v(item.get("high")),
                       "", "", "", item.get("notes", "")]]
        else:
            values = [[item.get("section", ""), item.get("label", ""),
                       "", "", "",
                       v(item.get("low")), v(item.get("mid")), v(item.get("high")),
                       item.get("notes", "")]]
        batch_write(service, spreadsheet_id, [{
            "range": f"{tab_name}!A{row_1idx}:I{row_1idx}",
            "values": values,
        }])


def do_add(service, spreadsheet_id, after_id, new_id, scenario, project_dir, rm):
    is_mp = bool(scenario.get("phases"))
    primary_phase = scenario["phases"][0] if is_mp else None
    rm_key = get_scenario_row_map_key(scenario, primary_phase)
    tab_name = scenario["tab"]

    if after_id not in rm.get(rm_key, {}):
        print(f"ERROR: '{after_id}' not found in row_map for scenario '{scenario['id']}'.")
        print(f"  Known IDs: {sorted(rm.get(rm_key, {}).keys())}")
        sys.exit(1)

    after_row = rm[rm_key][after_id]
    print(f"  Inserting row after '{after_id}' (row {after_row})...")

    sheet_id = get_sheet_id(service, spreadsheet_id, tab_name)
    new_row = insert_row_after(service, spreadsheet_id, sheet_id, after_row)
    print(f"  Row inserted at position {new_row}.")

    for key in rm:
        shift_row_map(rm, key, new_row, +1)
    rm[rm_key][new_id] = new_row

    item, phase_key = load_item_from_json(project_dir, scenario, new_id)
    if item is None:
        print(f"  WARNING: '{new_id}' not found in JSON. Row inserted but left blank.")
        print(f"  Add it to the JSON file then run: python scripts/push.py --project ...")
    else:
        write_item_to_sheet(service, spreadsheet_id, tab_name, new_row, item, is_mp, phase_key)
        print(f"  '{new_id}' written to row {new_row}.")

    save_row_map(project_dir, rm)
    print(f"  row_map.json updated.")


def do_remove(service, spreadsheet_id, item_id, scenario, project_dir, rm):
    is_mp = bool(scenario.get("phases"))
    primary_phase = scenario["phases"][0] if is_mp else None
    rm_key = get_scenario_row_map_key(scenario, primary_phase)
    tab_name = scenario["tab"]

    if item_id not in rm.get(rm_key, {}):
        print(f"ERROR: '{item_id}' not found in row_map for scenario '{scenario['id']}'.")
        sys.exit(1)

    row = rm[rm_key][item_id]
    print(f"  Deleting row {row} ('{item_id}')...")

    sheet_id = get_sheet_id(service, spreadsheet_id, tab_name)
    delete_row(service, spreadsheet_id, sheet_id, row)

    del rm[rm_key][item_id]
    for key in rm:
        shift_row_map(rm, key, row + 1, -1)

    save_row_map(project_dir, rm)
    print(f"  Row deleted. row_map.json updated.")


def main():
    parser = argparse.ArgumentParser(description="Add or remove a line item from the live sheet")
    parser.add_argument("--project", required=True, help="Project name")
    parser.add_argument("--scenario", required=True, help="Scenario ID (from project.json)")
    parser.add_argument("--after", help="Item ID to insert the new item after")
    parser.add_argument("--new-id", help="ID of the new item (must exist in JSON)")
    parser.add_argument("--remove", help="Item ID to remove from the sheet")
    args = parser.parse_args()

    if not args.after and not args.remove:
        parser.print_help()
        sys.exit(1)

    project_dir = get_project_dir(args.project)
    project     = load_project(project_dir)
    config      = load_config(project_dir)
    rm          = load_row_map(project_dir)

    scenario = find_scenario(project, args.scenario)
    if scenario is None:
        print(f"ERROR: Scenario '{args.scenario}' not found in project.json.")
        print(f"  Available: {[s['id'] for s in project['scenarios']]}")
        sys.exit(1)

    print("Authenticating...")
    service = get_service()

    if args.remove:
        do_remove(service, config["spreadsheet_id"], args.remove, scenario, project_dir, rm)
    else:
        if not args.new_id:
            print("ERROR: --new-id required when using --after")
            sys.exit(1)
        do_add(service, config["spreadsheet_id"], args.after, args.new_id,
               scenario, project_dir, rm)


if __name__ == "__main__":
    main()
