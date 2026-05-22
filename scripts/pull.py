"""
Pull current values from Google Sheets into local JSON files, then git-commit
the snapshot into the project's own git repo.

Row positions are derived fresh from the live sheet on every run — no stored
row_map.json or input_map.json is trusted as positional truth.

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
from project_config import get_project_dir, load_project, load_config, get_scenario_row_map_key
from sheet_discovery import build_input_map, build_row_map, cache_maps


def pull_inputs(service, spreadsheet_id, project, input_map, project_dir):
    tab = project["tabs"]["inputs"]
    inputs_path = os.path.join(project_dir, "inputs.json")
    with open(inputs_path) as f:
        data = json.load(f)

    # Cells may be bare ("B24") or tab-qualified ("CAPITAL!B4")
    key_cell_pairs = list(input_map.items())
    ranges = [cell if "!" in cell else f"{tab}!{cell}" for _, cell in key_cell_pairs]

    result = service.spreadsheets().values().batchGet(
        spreadsheetId=spreadsheet_id, ranges=ranges,
        valueRenderOption="UNFORMATTED_VALUE",
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

        parts = key.split(".")
        node = data
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = raw

    data.setdefault("_meta", {})["last_pulled"] = datetime.now().isoformat()
    with open(inputs_path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=True)
    print(f"  inputs.json updated ({len(key_cell_pairs)} cells)")


def parse_num(v):
    """Parse a sheet cell value into a number, or None for blank/dash/unparseable."""
    if v in (None, "", "—"):
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return int(v) if v == int(v) else v
    try:
        return int(float(str(v).replace(",", "").replace("$", "")))
    except (ValueError, TypeError):
        return None


def pull_scenario(service, spreadsheet_id, tab_name, row_map, json_path, phase_key=None, notes_col=None):
    with open(json_path) as f:
        data = json.load(f)

    items = data[phase_key]["line_items"] if phase_key else data["line_items"]
    items_by_id = {item["id"]: item for item in items}

    row_list = sorted(row_map.items())  # [(item_id, row_1idx), ...]
    ranges = [f"{tab_name}!C{row}:I{row}" for _, row in row_list]

    if not ranges:
        return

    result = service.spreadsheets().values().batchGet(
        spreadsheetId=spreadsheet_id, ranges=ranges,
        valueRenderOption="UNFORMATTED_VALUE",
    ).execute()
    value_ranges = result.get("valueRanges", [])

    for i, (item_id, _) in enumerate(row_list):
        item = items_by_id.get(item_id)
        if item is None:
            continue
        row_vals = value_ranges[i].get("values", [[]])[0] if value_ranges[i].get("values") else []

        if item.get("formula"):
            continue

        if item.get("low") is not None or item.get("mid") is not None:
            v_off = 3 if (notes_col and item.get("sheet_phase") == 2) else 0
            item["low"]  = parse_num(row_vals[v_off])     if len(row_vals) > v_off     else item["low"]
            item["mid"]  = parse_num(row_vals[v_off + 1]) if len(row_vals) > v_off + 1 else item["mid"]
            item["high"] = parse_num(row_vals[v_off + 2]) if len(row_vals) > v_off + 2 else item["high"]
            if notes_col:
                notes_idx = ord(notes_col.upper()) - ord('C')
            else:
                notes_idx = 6 if phase_key else 3
            if len(row_vals) > notes_idx:
                item["notes"] = row_vals[notes_idx]
            elif len(row_vals) > 3:
                item["notes"] = row_vals[3]

        if notes_col and notes_col != "F" and item.get("sheet_phase") != 2:
            if "p2_low" in item or "p2_mid" in item or "p2_high" in item:
                item["p2_low"]  = parse_num(row_vals[3]) if len(row_vals) > 3 else item.get("p2_low")
                item["p2_mid"]  = parse_num(row_vals[4]) if len(row_vals) > 4 else item.get("p2_mid")
                item["p2_high"] = parse_num(row_vals[5]) if len(row_vals) > 5 else item.get("p2_high")

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
        range=f"{tab}!A2:I1000",
    ).execute()
    rows = result.get("values", [])

    existing = {t["id"]: t for t in data.get("tasks", [])}
    write_back = []

    for i, row in enumerate(rows):
        if not any(row):
            continue
        task_id     = row[0].strip() if len(row) > 0 else ""
        title       = row[1] if len(row) > 1 else ""
        status      = row[2] if len(row) > 2 else "New"
        owner       = row[3] if len(row) > 3 else ""
        priority    = row[4] if len(row) > 4 else "Medium"
        blocked_by  = row[5] if len(row) > 5 else ""
        description = row[6] if len(row) > 6 else ""
        deliverable = row[7] if len(row) > 7 else ""
        resources   = row[8] if len(row) > 8 else ""

        task_data = {"title": title, "status": status, "owner": owner,
                     "priority": priority, "blocked_by": blocked_by,
                     "description": description, "deliverable": deliverable,
                     "resources": resources}

        if task_id and task_id in existing:
            existing[task_id].update(task_data)
        elif task_id:
            existing[task_id] = {"id": task_id, **task_data}
        else:
            new_id = f"task_{len(existing) + len(write_back) + 1:02d}"
            existing[new_id] = {"id": new_id, **task_data}
            write_back.append((i + 2, new_id))

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

    project_dir    = get_project_dir(args.project)
    project        = load_project(project_dir)
    config         = load_config(project_dir)
    spreadsheet_id = config["spreadsheet_id"]

    print("Authenticating...")
    service = get_service()

    print("Scanning sheet for current row positions...")
    input_map = build_input_map(service, spreadsheet_id, project)
    row_map   = build_row_map(service, spreadsheet_id, project, project_dir)
    cache_maps(project_dir, input_map, row_map)

    print("Pulling BUDGET tab...")
    pull_inputs(service, spreadsheet_id, project, input_map, project_dir)

    for scenario in project["scenarios"]:
        json_path = os.path.join(project_dir, scenario["json_file"])

        if not scenario.get("phases"):
            print(f"Pulling {scenario['tab']} tab...")
            rm_key = get_scenario_row_map_key(scenario)
            pull_scenario(service, spreadsheet_id, scenario["tab"],
                          row_map.get(rm_key, {}), json_path, phase_key=None,
                          notes_col=scenario.get("notes_col"))
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
