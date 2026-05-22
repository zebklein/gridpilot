"""
Push local JSON files to Google Sheets, then git-commit the change into
the project's own git repo.

Row positions are derived fresh from the live sheet on every run — no stored
row_map.json or input_map.json is trusted as positional truth.

For --dry-run, falls back to cached row_map.json / input_map.json on disk
(no live sheet connection needed).

Usage:
    python scripts/push.py --project <name>
    python scripts/push.py --project <name> --dry-run
    python scripts/push.py --project <name> --message "updated land cost to $220k"
"""
import os
import sys
import json
import argparse
import subprocess
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))
from sheets_client import get_service, batch_write
from project_config import (
    get_project_dir, load_project, load_config, load_input_map, load_row_map,
    get_scenario_row_map_key,
)
from sheet_discovery import build_input_map, build_row_map, cache_maps
from formula_engine import is_formula_item, get_formula_expr_updates


def fmt_currency(v):
    if v is None:
        return ""
    return int(v)


def push_inputs(service, spreadsheet_id, project, input_map, project_dir, dry_run):
    tab = project["tabs"]["inputs"]
    inputs_path = os.path.join(project_dir, "inputs.json")
    with open(inputs_path) as f:
        data = json.load(f)

    updates = []
    for key, cell in input_map.items():
        parts = key.split(".")
        node = data
        try:
            for part in parts:
                node = node[part]
        except (KeyError, TypeError):
            continue
        value = node if node is not None else ""
        range_ref = cell if "!" in cell else f"{tab}!{cell}"
        updates.append({"range": range_ref, "values": [[value]]})

    if dry_run:
        print(f"  [dry-run] Would write {len(updates)} cells to {tab} tab")
        return

    batch_write(service, spreadsheet_id, updates)
    print(f"  Pushed {len(updates)} cells to {tab} tab")


def push_scenario(service, spreadsheet_id, tab_name, row_map, json_path, phase_key, dry_run,
                   is_multiphase=False, notes_col=None, input_map=None, inp_tab="BUDGET"):
    with open(json_path) as f:
        data = json.load(f)

    items = data[phase_key]["line_items"] if phase_key else data["line_items"]
    items_by_id = {item["id"]: item for item in items}

    if notes_col is None:
        notes_col = "I" if is_multiphase else "F"
    notes_col_letter = notes_col

    updates = []
    formula_updates = []
    skipped = []

    for item_id, row_1idx in sorted(row_map.items(), key=lambda x: x[1]):
        item = items_by_id.get(item_id)
        if item is None:
            continue

        if is_formula_item(item):
            note = item.get("notes", "")
            if note and isinstance(note, str) and not note.startswith("="):
                updates.append({
                    "range": f"{tab_name}!{notes_col_letter}{row_1idx}",
                    "values": [[note]],
                })
            if input_map and item.get("formula_expr"):
                formula_updates.extend(
                    get_formula_expr_updates(item, row_1idx, tab_name, input_map, inp_tab)
                )
            if notes_col and notes_col != "F" and not item.get("formula_expr"):
                p2 = [fmt_currency(item.get("p2_low")),
                      fmt_currency(item.get("p2_mid")),
                      fmt_currency(item.get("p2_high"))]
                if any(v != "" for v in p2):
                    updates.append({
                        "range": f"{tab_name}!F{row_1idx}:H{row_1idx}",
                        "values": [p2],
                    })
            skipped.append(item_id)
            continue

        if is_multiphase:
            if phase_key and phase_key.endswith("_phase1") or (phase_key and "phase1" in phase_key):
                row_values = [
                    fmt_currency(item.get("low")),
                    fmt_currency(item.get("mid")),
                    fmt_currency(item.get("high")),
                ]
                updates.append({
                    "range": f"{tab_name}!C{row_1idx}:E{row_1idx}",
                    "values": [row_values],
                })
            else:
                row_values = [
                    fmt_currency(item.get("low")),
                    fmt_currency(item.get("mid")),
                    fmt_currency(item.get("high")),
                ]
                updates.append({
                    "range": f"{tab_name}!F{row_1idx}:H{row_1idx}",
                    "values": [row_values],
                })
            note = item.get("notes", "")
            if note:
                updates.append({
                    "range": f"{tab_name}!I{row_1idx}",
                    "values": [[note]],
                })
        else:
            note = item.get("notes", "")
            if isinstance(note, str) and note.startswith("="):
                note = ""
            row_values = [
                fmt_currency(item.get("low")),
                fmt_currency(item.get("mid")),
                fmt_currency(item.get("high")),
            ]
            if notes_col == "F":
                updates.append({
                    "range": f"{tab_name}!C{row_1idx}:F{row_1idx}",
                    "values": [row_values + [note]],
                })
            else:
                if item.get("sheet_phase") == 2:
                    updates.append({
                        "range": f"{tab_name}!F{row_1idx}:H{row_1idx}",
                        "values": [row_values],
                    })
                else:
                    updates.append({
                        "range": f"{tab_name}!C{row_1idx}:E{row_1idx}",
                        "values": [row_values],
                    })
                    p2 = [fmt_currency(item.get("p2_low")),
                          fmt_currency(item.get("p2_mid")),
                          fmt_currency(item.get("p2_high"))]
                    if any(v != "" for v in p2):
                        updates.append({
                            "range": f"{tab_name}!F{row_1idx}:H{row_1idx}",
                            "values": [p2],
                        })
                if note:
                    updates.append({
                        "range": f"{tab_name}!{notes_col}{row_1idx}",
                        "values": [[note]],
                    })

    if dry_run:
        print(f"  [dry-run] Would write {len(updates)} value cells + "
              f"{len(formula_updates)} formula cells to {tab_name} "
              f"(skipped {len(skipped)} formula rows)")
        return

    if updates:
        batch_write(service, spreadsheet_id, updates)
    if formula_updates:
        batch_write(service, spreadsheet_id, formula_updates, value_input_option="USER_ENTERED")
    print(f"  Pushed {len(updates)} value cells + {len(formula_updates)} formula cells to {tab_name} "
          f"(skipped {len(skipped)} formula rows)")


def push_kanban(service, spreadsheet_id, project, project_dir, dry_run):
    tab = project["tabs"]["kanban"]
    kanban_path = os.path.join(project_dir, "kanban.json")
    with open(kanban_path) as f:
        data = json.load(f)

    tasks = data.get("tasks", [])
    if not tasks:
        print("  No kanban tasks to push.")
        return

    if dry_run:
        print(f"  [dry-run] Would update/append {len(tasks)} kanban tasks")
        return

    result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=f"{tab}!A2:A1000",
    ).execute()
    existing_rows = {}
    for i, row in enumerate(result.get("values", [])):
        if row and row[0]:
            existing_rows[row[0]] = i + 2

    updates = []
    appends = []

    for task in tasks:
        tid = task.get("id", "")
        row_data = [
            tid,
            task.get("title", ""),
            task.get("status", "New"),
            task.get("owner", ""),
            task.get("priority", "Medium"),
            task.get("blocked_by", ""),
            task.get("description", ""),
            task.get("deliverable", ""),
            task.get("resources", ""),
        ]
        if tid in existing_rows:
            updates.append({
                "range": f"{tab}!A{existing_rows[tid]}:I{existing_rows[tid]}",
                "values": [row_data],
            })
        else:
            appends.append(row_data)

    if updates:
        batch_write(service, spreadsheet_id, updates, value_input_option="USER_ENTERED")
    if appends:
        service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=f"{tab}!A:I",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": appends},
        ).execute()

    data.setdefault("_meta", {})["last_pushed"] = datetime.now().isoformat()
    with open(kanban_path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=True)
    print(f"  Kanban: updated {len(updates)} rows, appended {len(appends)} new tasks")


def git_commit(project_dir, message):
    try:
        subprocess.run(["git", "-C", project_dir, "add", "."],
                       check=True, capture_output=True)
        staged = subprocess.run(
            ["git", "-C", project_dir, "diff", "--cached", "--quiet"],
            capture_output=True,
        )
        if staged.returncode == 0:
            print("  git: nothing to commit (budget files unchanged)")
            return
        subprocess.run(["git", "-C", project_dir, "commit", "-m", message],
                       check=True, capture_output=True)
        print(f"  git: committed — {message}")
    except subprocess.CalledProcessError as e:
        print(f"  git error: {e.stderr.decode().strip() if e.stderr else str(e)}")


def main():
    parser = argparse.ArgumentParser(description="Push local JSON → Google Sheets")
    parser.add_argument("--project", required=True, help="Project name")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview changes without writing to Sheets")
    parser.add_argument("--message", "-m", default=None,
                        help="Commit message describing what changed")
    args = parser.parse_args()

    project_dir = get_project_dir(args.project)
    project     = load_project(project_dir)

    if args.dry_run:
        print("DRY RUN — no changes will be written to Sheets\n")
        service        = None
        config         = {"spreadsheet_id": None}
        spreadsheet_id = None
        # Fall back to cached maps for dry-run preview
        input_map = load_input_map(project_dir)
        row_map   = load_row_map(project_dir)
    else:
        config         = load_config(project_dir)
        spreadsheet_id = config["spreadsheet_id"]
        print("Authenticating...")
        service = get_service()
        print("Scanning sheet for current row positions...")
        input_map = build_input_map(service, spreadsheet_id, project)
        row_map   = build_row_map(service, spreadsheet_id, project, project_dir)
        cache_maps(project_dir, input_map, row_map)

    print("Pushing BUDGET tab...")
    push_inputs(service, spreadsheet_id, project, input_map, project_dir, args.dry_run)

    for scenario in project["scenarios"]:
        json_path = os.path.join(project_dir, scenario["json_file"])
        is_mp = bool(scenario.get("phases"))

        inp_tab = project["tabs"]["inputs"]
        if not is_mp:
            print(f"Pushing {scenario['tab']} tab...")
            rm_key = get_scenario_row_map_key(scenario)
            push_scenario(service, spreadsheet_id, scenario["tab"],
                          row_map.get(rm_key, {}), json_path, phase_key=None,
                          dry_run=args.dry_run, is_multiphase=False,
                          notes_col=scenario.get("notes_col"),
                          input_map=input_map, inp_tab=inp_tab)
        else:
            for phase in scenario["phases"]:
                print(f"Pushing {scenario['tab']} tab ({phase})...")
                rm_key = get_scenario_row_map_key(scenario, phase)
                push_scenario(service, spreadsheet_id, scenario["tab"],
                              row_map.get(rm_key, {}), json_path, phase_key=phase,
                              dry_run=args.dry_run, is_multiphase=True,
                              input_map=input_map, inp_tab=inp_tab)

    print(f"Pushing {project['tabs']['kanban']} tab...")
    push_kanban(service, spreadsheet_id, project, project_dir, args.dry_run)

    if not args.dry_run:
        ts_msg = datetime.now().strftime("%Y-%m-%d %H:%M")
        msg = args.message or f"push: updated data [{ts_msg}]"
        git_commit(project_dir, msg)
        print(f"\nPush complete. Changes are live in Google Sheets:\n  {config.get('spreadsheet_url', '')}")
    else:
        print("\nDry run complete. Re-run without --dry-run to write to Sheets.")


if __name__ == "__main__":
    main()
