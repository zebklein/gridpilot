"""
Pull current values from Google Sheets into local JSON files, then git-commit
the snapshot into the project's own git repo.

Always run pull before asking an AI assistant to make edits.

Usage:
    python scripts/pull.py --project <name>
"""
import os
import sys
import json
import argparse
import subprocess
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))
from sheets_client import get_service
from project_config import (
    get_project_dir, load_project, load_config, load_input_map, load_row_map,
    get_scenario_row_map_key, get_inputs_value,
)


def pull_inputs(service, spreadsheet_id, project, input_map, project_dir):
    tab = project["tabs"]["inputs"]
    inputs_path = os.path.join(project_dir, "inputs.json")
    with open(inputs_path) as f:
        data = json.load(f)

    # Build (key, cell) pairs from input_map
    key_cell_pairs = [(k, v) for k, v in input_map.items() if k != "_last_ai_edit"]
    ranges = [f"{tab}!{cell}" for _, cell in key_cell_pairs]

    result = service.spreadsheets().values().batchGet(
        spreadsheetId=spreadsheet_id, ranges=ranges
    ).execute()
    value_ranges = result.get("valueRanges", [])

    for i, (key, _) in enumerate(key_cell_pairs):
        raw = None
        if i < len(value_ranges):
            vals = value_ranges[i].get("values", [])
            raw = vals[0][0] if vals and vals[0] else None

        if raw is not None:
            try:
                raw = float(str(raw).replace(",", "").replace("$", "").replace("%", ""))
                if raw == int(raw):
                    raw = int(raw)
            except (ValueError, AttributeError):
                pass

        # Set the value in the nested JSON structure
        parts = key.split(".")
        node = data
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = raw

    data.setdefault("_meta", {})["last_pulled"] = datetime.now().isoformat()
    with open(inputs_path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=True)
    print(f"  inputs.json updated ({len(key_cell_pairs)} cells)")


def pull_scenario(service, spreadsheet_id, tab_name, row_map, json_path, phase_key=None):
    with open(json_path) as f:
        data = json.load(f)

    items = data[phase_key]["line_items"] if phase_key else data["line_items"]
    items_by_id = {item["id"]: item for item in items}

    # Determine notes column letter based on number of value columns
    # Single-phase: C=Low, D=Mid, E=High, F=Notes  → read C:F
    # Multi-phase:  C-E=P1, F-H=P2, I=Notes         → read C:I
    # We detect by checking if any item has phase2 columns (items with _p2 suffix)
    # Simplest: always read C:I and handle what we get
    row_list = sorted(row_map.items())  # [(item_id, row_1idx), ...]
    ranges = [f"{tab_name}!C{row}:I{row}" for _, row in row_list]

    if not ranges:
        return

    result = service.spreadsheets().values().batchGet(
        spreadsheetId=spreadsheet_id, ranges=ranges
    ).execute()
    value_ranges = result.get("valueRanges", [])

    def parse_num(v):
        if v in (None, "", "—"):
            return None
        try:
            return int(float(str(v).replace(",", "").replace("$", "")))
        except ValueError:
            return None

    for i, (item_id, _) in enumerate(row_list):
        item = items_by_id.get(item_id)
        if item is None:
            continue
        row_vals = value_ranges[i].get("values", [[]])[0] if value_ranges[i].get("values") else []

        # Only update non-formula items (items that had values, not None)
        if item.get("low") is not None or item.get("mid") is not None:
            item["low"]  = parse_num(row_vals[0]) if len(row_vals) > 0 else item["low"]
            item["mid"]  = parse_num(row_vals[1]) if len(row_vals) > 1 else item["mid"]
            item["high"] = parse_num(row_vals[2]) if len(row_vals) > 2 else item["high"]
            # Notes: col F (index 3) for single-phase, col I (index 6) for multi-phase
            notes_idx = 6 if phase_key else 3
            if len(row_vals) > notes_idx:
                item["notes"] = row_vals[notes_idx]
            elif len(row_vals) > 3:
                item["notes"] = row_vals[3]

    data.setdefault("_meta", {})["last_pulled"] = datetime.now().isoformat()
    with open(json_path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=True)


def pull_kanban(service, spreadsheet_id, project, project_dir):
    tab = project["tabs"]["kanban"]
    kanban_path = os.path.join(project_dir, "kanban.json")
    with open(kanban_path) as f:
        data = json.load(f)

    result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=f"{tab}!A2:H1000",
    ).execute()
    rows = result.get("values", [])

    existing = {t["id"]: t for t in data.get("tasks", [])}
    write_back = []

    for i, row in enumerate(rows):
        if not any(row):
            continue
        task_id   = row[0].strip() if len(row) > 0 else ""
        title     = row[1] if len(row) > 1 else ""
        status    = row[2] if len(row) > 2 else "New"
        owner     = row[3] if len(row) > 3 else ""
        priority  = row[4] if len(row) > 4 else "Medium"
        blocked_by = row[5] if len(row) > 5 else ""
        notes     = row[6] if len(row) > 6 else ""
        resources = row[7] if len(row) > 7 else ""

        task_data = {"title": title, "status": status, "owner": owner,
                     "priority": priority, "blocked_by": blocked_by,
                     "notes": notes, "resources": resources}

        if task_id and task_id in existing:
            existing[task_id].update(task_data)
        elif task_id:
            existing[task_id] = {"id": task_id, **task_data}
        else:
            new_id = f"task_{len(existing) + len(write_back) + 1:02d}"
            existing[new_id] = {"id": new_id, **task_data}
            write_back.append((i + 2, new_id))

    # Write back any IDs we assigned for human-added rows
    if write_back:
        from sheets_client import batch_write as bw
        bw(service, spreadsheet_id, [
            {"range": f"{tab}!A{r}", "values": [[id_]]}
            for r, id_ in write_back
        ])

    data["tasks"] = list(existing.values())
    data.setdefault("_meta", {})["last_pulled"] = datetime.now().isoformat()
    with open(kanban_path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=True)
    print(f"  kanban.json updated ({len(data['tasks'])} tasks, {len(write_back)} new IDs assigned)")


def git_commit(project_dir, message):
    try:
        subprocess.run(["git", "-C", project_dir, "add", "."],
                       check=True, capture_output=True)
        staged = subprocess.run(
            ["git", "-C", project_dir, "diff", "--cached", "--quiet"],
            capture_output=True,
        )
        if staged.returncode == 0:
            print("  git: nothing to commit (sheet matches local files)")
            return
        subprocess.run(["git", "-C", project_dir, "commit", "-m", message],
                       check=True, capture_output=True)
        print(f"  git: committed — {message}")
    except subprocess.CalledProcessError as e:
        print(f"  git error: {e.stderr.decode().strip() if e.stderr else str(e)}")


def main():
    parser = argparse.ArgumentParser(description="Pull Google Sheets → local JSON")
    parser.add_argument("--project", required=True, help="Project name")
    args = parser.parse_args()

    project_dir = get_project_dir(args.project)
    project     = load_project(project_dir)
    config      = load_config(project_dir)
    input_map   = load_input_map(project_dir)
    row_map     = load_row_map(project_dir)

    spreadsheet_id = config["spreadsheet_id"]

    print("Authenticating...")
    service = get_service()

    print("Pulling BUDGET tab...")
    pull_inputs(service, spreadsheet_id, project, input_map, project_dir)

    for scenario in project["scenarios"]:
        json_path = os.path.join(project_dir, scenario["json_file"])

        if not scenario.get("phases"):
            print(f"Pulling {scenario['tab']} tab...")
            rm_key = get_scenario_row_map_key(scenario)
            pull_scenario(service, spreadsheet_id, scenario["tab"],
                          row_map.get(rm_key, {}), json_path, phase_key=None)
        else:
            for phase in scenario["phases"]:
                print(f"Pulling {scenario['tab']} tab ({phase})...")
                rm_key = get_scenario_row_map_key(scenario, phase)
                pull_scenario(service, spreadsheet_id, scenario["tab"],
                              row_map.get(rm_key, {}), json_path, phase_key=phase)

    print(f"Pulling {project['tabs']['kanban']} tab...")
    pull_kanban(service, spreadsheet_id, project, project_dir)

    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    git_commit(project_dir, f"snapshot: pulled from Sheets [{ts}]")
    print(f"\nPull complete. Local JSON files reflect current sheet state.")


if __name__ == "__main__":
    main()
