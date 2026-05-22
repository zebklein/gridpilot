"""
Derive input_map and row_map from the live sheet at the start of every
pull and push. Row numbers are ephemeral; labels are the stable key.

build_input_map  — scans each input tab's column A, matches project.json labels
build_row_map    — scans each scenario tab's column B, matches JSON item labels

Both functions return the same in-memory format used by pull/push:
  input_map : {dotted_key: cell_ref}          e.g. "B12" or "CAPITAL!B4"
  row_map   : {rm_key: {item_id: row_int}}

Call _cache_maps() after discovery to write row_map.json / input_map.json to
disk as a debug artifact. Those files are never read by pull or push.
"""
import os
import json


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_input_map(service, spreadsheet_id, project):
    """
    Scan each input tab's column A to locate field labels.

    Returns {dotted_key: cell_ref} where cell_ref is "B{row}" for the
    primary inputs tab, or "TAB!B{row}" for fields living in other tabs.
    """
    inp_tab = project["tabs"]["inputs"]

    # Group (key, label) pairs by the tab they live in.
    # Sections may carry an explicit "tab" override (e.g. CAPITAL).
    by_tab = {}
    for section in project.get("inputs_sections", []):
        tab = section.get("tab", inp_tab)
        if tab not in by_tab:
            by_tab[tab] = []
        for field in section.get("fields", []):
            by_tab[tab].append((field["key"], field["label"]))

    input_map = {}
    unmatched = []

    for tab, fields in by_tab.items():
        if not fields:
            continue
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=f"{tab}!A1:A300",
        ).execute()
        col_a = [r[0].strip() if r else "" for r in result.get("values", [])]

        label_to_row = {}
        for i, label in enumerate(col_a):
            if label and label.lower() not in label_to_row:
                label_to_row[label.lower()] = i + 1

        for key, label in fields:
            row = label_to_row.get(label.strip().lower())
            if row is not None:
                input_map[key] = f"B{row}" if tab == inp_tab else f"{tab}!B{row}"
            else:
                unmatched.append(f"{key} ('{label}' in {tab})")

    if unmatched:
        print(f"  WARNING: {len(unmatched)} input field(s) not found in sheet:")
        for u in unmatched[:5]:
            print(f"    {u}")
        if len(unmatched) > 5:
            print(f"    ... and {len(unmatched) - 5} more")

    return input_map


def build_row_map(service, spreadsheet_id, project, project_dir):
    """
    Scan column B of each scenario tab to locate line item labels.

    Returns {rm_key: {item_id: row_int}} — same in-memory format as
    load_row_map() from project_config.
    """
    from project_config import get_scenario_row_map_key

    row_map = {}
    all_unmatched = []

    for scenario in project["scenarios"]:
        tab_name = scenario["tab"]

        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=f"{tab_name}!B1:B500",
        ).execute()
        col_b = [r[0].strip() if r else "" for r in result.get("values", [])]

        # First occurrence wins for any duplicate label.
        label_to_row = {}
        for i, label in enumerate(col_b):
            if label and label.lower() not in label_to_row:
                label_to_row[label.lower()] = i + 1

        if not scenario.get("phases"):
            items = _load_items(project_dir, scenario)
            rm, unmatched = _match_by_label(items, label_to_row, tab_name)
            row_map[get_scenario_row_map_key(scenario)] = rm
            all_unmatched.extend(unmatched)
        else:
            for phase in scenario["phases"]:
                items = _load_items(project_dir, scenario, phase)
                rm, unmatched = _match_by_label(items, label_to_row, tab_name)
                row_map[get_scenario_row_map_key(scenario, phase)] = rm
                all_unmatched.extend(unmatched)

    if all_unmatched:
        print(f"  WARNING: {len(all_unmatched)} item(s) not found in sheet:")
        for u in all_unmatched[:5]:
            print(f"    {u}")
        if len(all_unmatched) > 5:
            print(f"    ... and {len(all_unmatched) - 5} more")

    return row_map


def cache_maps(project_dir, input_map, row_map):
    """
    Write discovered maps to disk as a debug artifact.

    These files (row_map.json, input_map.json) are NOT read by pull or push.
    They exist solely for inspection and for tools that still need them
    (validate.py, discover.py initial output).
    """
    from project_config import save_row_map

    input_map_path = os.path.join(project_dir, "input_map.json")
    with open(input_map_path, "w") as f:
        json.dump(input_map, f, indent=2)

    save_row_map(project_dir, row_map)


def scan_label_to_row(service, spreadsheet_id, tab_name):
    """
    Scan column B of a single scenario tab and return {label_lower: row_int}.
    Used by add_item.py to locate rows without loading a stored row_map.
    """
    result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=f"{tab_name}!B1:B500",
    ).execute()
    col_b = [r[0].strip() if r else "" for r in result.get("values", [])]
    label_to_row = {}
    for i, label in enumerate(col_b):
        if label and label.lower() not in label_to_row:
            label_to_row[label.lower()] = i + 1
    return label_to_row


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _load_items(project_dir, scenario, phase=None):
    json_path = os.path.join(project_dir, scenario["json_file"])
    with open(json_path) as f:
        data = json.load(f)
    if phase:
        return data.get(phase, {}).get("line_items", [])
    return data.get("line_items", [])


def _match_by_label(items, label_to_row, tab_name):
    """Match items to rows by label. Returns ({item_id: row_int}, [unmatched])."""
    rm = {}
    unmatched = []
    for item in items:
        label = item.get("label", "").strip()
        row = label_to_row.get(label.lower())
        if row is not None:
            rm[item["id"]] = row
        elif label:
            unmatched.append(f"{tab_name}: {item['id']} ('{label}')")
    return rm, unmatched
