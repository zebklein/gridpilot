"""
Discover the structure of any existing Google Spreadsheet and generate all
Gridpilot project files from it.

Use this when connecting to a sheet NOT created by init_sheet.py — any
spreadsheet with a budget/inputs tab, one or more scenario tabs, and optionally
a kanban tab. The script classifies each tab, reads its structure, and writes:
project.json, inputs.json, scenario JSON files, kanban.json, row_map.json,
input_map.json, and config.json.

Review the printed summary and the generated project.json before running
pull.py — discovery is heuristic and may need corrections for unusual layouts.

Tab classification heuristics:
  kanban   — row 1 contains "status" and "priority"
  scenario — row 1 contains "low", "mid", and "high" (column headers)
  inputs   — everything else (key-value layout in cols A-B)

Section header detection in inputs tab:
  ALL CAPS label with no value in col B → section header
  Mixed-case label with a value in col B → field

Usage:
    python scripts/discover.py --project <name> --spreadsheet-id <id>
"""
import os
import sys
import json
import re
import argparse
import subprocess
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))
from sheets_client import get_service
from project_config import GRIDPILOT_ROOT


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def slugify(s):
    s = re.sub(r"[^a-z0-9]+", "_", s.lower().strip())
    return s.strip("_")[:50]


def parse_num(v):
    if v in (None, "", "—"):
        return None
    try:
        return int(float(str(v).replace(",", "").replace("$", "").replace("%", "").replace("£", "")))
    except ValueError:
        return None


def guess_type(value):
    if not value:
        return "text"
    s = str(value).strip()
    if s.startswith(("$", "£")):
        return "currency"
    cleaned = s.replace(",", "").replace("$", "").replace("%", "").replace("£", "")
    try:
        f = float(cleaned)
        if s.endswith("%"):
            return "percent"
        if 0 < f < 1:
            return "percent"
        if f > 100:
            return "currency"
        return "number"
    except ValueError:
        return "text"


def parse_value(raw, field_type):
    if not raw:
        return None
    s = str(raw).strip()
    if field_type == "text":
        return s
    cleaned = s.replace(",", "").replace("$", "").replace("%", "").replace("£", "")
    try:
        f = float(cleaned)
        if field_type == "percent" and f > 1:
            f = f / 100
        return int(f) if f == int(f) else f
    except ValueError:
        return s


def make_unique(id_str, seen):
    if id_str not in seen:
        seen.add(id_str)
        return id_str
    i = 2
    while f"{id_str}_{i}" in seen:
        i += 1
    result = f"{id_str}_{i}"
    seen.add(result)
    return result


def tab_range(tab_name, rng):
    """Return a safely-quoted range string for tabs that may contain spaces."""
    return f"'{tab_name}'!{rng}"


# ---------------------------------------------------------------------------
# Tab classification
# ---------------------------------------------------------------------------

def classify_tab(service, spreadsheet_id, tab_name):
    """Returns 'inputs', 'scenario', 'kanban', or 'unknown'."""
    result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=tab_range(tab_name, "A1:J2"),
    ).execute()
    rows = result.get("values", [])
    if not rows:
        return "unknown"

    row1 = [c.strip().lower() for c in rows[0]]
    row1_str = " ".join(row1)

    if "status" in row1 and "priority" in row1:
        return "kanban"

    if "low" in row1_str and "mid" in row1_str and "high" in row1_str:
        return "scenario"

    return "inputs"


# ---------------------------------------------------------------------------
# Inputs tab discovery
# ---------------------------------------------------------------------------

def discover_inputs_tab(service, spreadsheet_id, tab_name):
    """
    Scans an inputs/budget tab and returns:
      sections    — list of inputs_sections dicts for project.json
      input_map   — {field_key: "B{row}"}
      inputs_data — nested dict matching inputs.json structure
      warnings    — list of strings describing anything skipped
    """
    result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=tab_range(tab_name, "A1:B300"),
    ).execute()
    rows = result.get("values", [])

    sections = []
    input_map = {}
    inputs_data = {}
    current_section = None
    warnings = []
    seen_keys = set()

    for i, row in enumerate(rows):
        row_num = i + 1
        col_a = row[0].strip() if row else ""
        col_b = row[1].strip() if len(row) > 1 else ""

        if not col_a:
            continue

        # Section header: ALL CAPS, no value in col B
        is_header = (col_a == col_a.upper()
                     and any(c.isalpha() for c in col_a)
                     and not col_b)
        if is_header:
            section_id = slugify(col_a)
            if not section_id:
                continue
            current_section = {"id": section_id, "label": col_a, "fields": []}
            sections.append(current_section)
            inputs_data[section_id] = {}

        elif col_b and current_section:
            field_slug = slugify(col_a)
            if not field_slug:
                continue
            field_key = make_unique(f"{current_section['id']}.{field_slug}", seen_keys)
            field_type = guess_type(col_b)

            current_section["fields"].append({
                "key": field_key,
                "label": col_a,
                "type": field_type,
            })
            input_map[field_key] = f"B{row_num}"
            inputs_data[current_section["id"]][field_slug] = parse_value(col_b, field_type)

        elif col_b and not current_section:
            warnings.append(f"  Row {row_num}: field '{col_a}' appears before any section header — skipped")

    return sections, input_map, inputs_data, warnings


# ---------------------------------------------------------------------------
# Scenario tab discovery
# ---------------------------------------------------------------------------

def _find_col(headers_lower, keywords):
    """Return list of 0-based column indices where any keyword appears."""
    return [i for i, h in enumerate(headers_lower) if any(k in h for k in keywords)]


def discover_scenario_tab(service, spreadsheet_id, tab_name):
    """
    Scans a scenario tab. Returns:
      scenario_data  — {"line_items": [...]} for single-phase,
                       {"phase1": {"line_items": [...]}, ...} for multi-phase
      row_map        — {item_id: row_int} for single-phase,
                       {phase: {item_id: row_int}} for multi-phase
      is_multiphase  — bool
      phases         — list of phase names (or None)
      warnings       — list of strings
    """
    header_result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=tab_range(tab_name, "A1:J1"),
    ).execute()
    header_row = [c.strip() for c in (header_result.get("values", [[]])[0]
                                       if header_result.get("values") else [])]
    hl = [h.lower() for h in header_row]

    low_cols  = _find_col(hl, ["low"])
    mid_cols  = _find_col(hl, ["mid"])
    high_cols = _find_col(hl, ["high"])
    note_cols = _find_col(hl, ["note"])

    is_multiphase = len(low_cols) > 1

    # Derive phase names from header text (e.g. "Phase 1 Low" → "phase1")
    phases = None
    if is_multiphase:
        phases = []
        for col in low_cols:
            raw = hl[col].replace("low", "").strip().strip("-_ ")
            phases.append(slugify(raw) if raw else f"phase{len(phases) + 1}")

    # Fallback column positions if headers weren't found
    if not low_cols:  low_cols  = [2]
    if not mid_cols:  mid_cols  = [3]
    if not high_cols: high_cols = [4]
    if not note_cols: note_cols = [8] if is_multiphase else [5]

    data_result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=tab_range(tab_name, "A2:J500"),
    ).execute()
    data_rows = data_result.get("values", [])

    warnings = []

    if not is_multiphase:
        line_items = []
        row_map = {}
        seen_ids = set()
        current_section = ""

        for i, row in enumerate(data_rows):
            row_num = i + 2
            col_a = row[0].strip() if row else ""
            col_b = row[1].strip() if len(row) > 1 else ""
            if not col_b:
                continue
            if col_a:
                current_section = col_a

            item_id = make_unique(
                f"{slugify(current_section)}_{slugify(col_b)}" if current_section else slugify(col_b),
                seen_ids,
            )

            def _v(cols):
                for c in cols:
                    if c < len(row) and row[c]:
                        return row[c]
                return None

            line_items.append({
                "section": current_section,
                "id": item_id,
                "label": col_b,
                "low":   parse_num(_v(low_cols)),
                "mid":   parse_num(_v(mid_cols)),
                "high":  parse_num(_v(high_cols)),
                "notes": _v(note_cols) or "",
            })
            row_map[item_id] = row_num

        return {"line_items": line_items}, row_map, False, None, warnings

    else:
        phases_data = {p: [] for p in phases}
        phases_row_map = {p: {} for p in phases}

        for phase_idx, phase in enumerate(phases):
            lc = low_cols[phase_idx]  if phase_idx < len(low_cols)  else low_cols[-1]
            mc = mid_cols[phase_idx]  if phase_idx < len(mid_cols)  else mid_cols[-1]
            hc = high_cols[phase_idx] if phase_idx < len(high_cols) else high_cols[-1]
            nc = note_cols[0]

            current_section = ""
            seen_ids = set()

            for i, row in enumerate(data_rows):
                row_num = i + 2
                col_a = row[0].strip() if row else ""
                col_b = row[1].strip() if len(row) > 1 else ""
                if not col_b:
                    continue
                if col_a:
                    current_section = col_a

                base = f"{slugify(current_section)}_{slugify(col_b)}" if current_section else slugify(col_b)
                item_id = make_unique(f"{base}_p{phase_idx + 1}", seen_ids)

                phases_data[phase].append({
                    "section": current_section,
                    "id": item_id,
                    "label": col_b,
                    "low":   parse_num(row[lc] if lc < len(row) else None),
                    "mid":   parse_num(row[mc] if mc < len(row) else None),
                    "high":  parse_num(row[hc] if hc < len(row) else None),
                    "notes": (row[nc] if nc < len(row) else "") or "",
                })
                phases_row_map[phase][item_id] = row_num

        scenario_data = {p: {"line_items": items} for p, items in phases_data.items()}
        return scenario_data, phases_row_map, True, phases, warnings


# ---------------------------------------------------------------------------
# Kanban tab discovery
# ---------------------------------------------------------------------------

def discover_kanban_tab(service, spreadsheet_id, tab_name):
    result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=tab_range(tab_name, "A2:H1000"),
    ).execute()
    rows = result.get("values", [])

    tasks = []
    for i, row in enumerate(rows):
        if not any(c.strip() for c in row if c):
            continue
        task_id = row[0].strip() if row and row[0].strip() else f"task_{i + 1:02d}"
        tasks.append({
            "id": task_id,
            "title":      row[1] if len(row) > 1 else "",
            "status":     row[2] if len(row) > 2 else "New",
            "owner":      row[3] if len(row) > 3 else "",
            "priority":   row[4] if len(row) > 4 else "Medium",
            "blocked_by": row[5] if len(row) > 5 else "",
            "notes":      row[6] if len(row) > 6 else "",
            "resources":  row[7] if len(row) > 7 else "",
        })
    return tasks


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Discover a spreadsheet's structure and generate Gridpilot project files"
    )
    parser.add_argument("--project", required=True, help="Project name (creates projects/<name>/)")
    parser.add_argument("--spreadsheet-id", required=True, help="Google Sheets spreadsheet ID")
    parser.add_argument("--scenario", action="append", default=[], metavar="TAB",
                        help="Force this tab to be classified as a scenario (repeatable)")
    args = parser.parse_args()
    forced_scenarios = set(args.scenario)

    project_dir = os.path.join(GRIDPILOT_ROOT, "projects", args.project)
    os.makedirs(project_dir, exist_ok=True)

    if not os.path.exists(os.path.join(project_dir, ".git")):
        subprocess.run(["git", "-C", project_dir, "init"], capture_output=True)

    print("Authenticating with Google...")
    service = get_service()
    spreadsheet_id = args.spreadsheet_id

    meta = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    spreadsheet_title = meta.get("properties", {}).get("title", "My Project")
    tab_names = [s["properties"]["title"] for s in meta["sheets"]]

    print(f"\nFound {len(tab_names)} tab(s): {', '.join(tab_names)}")
    print("Classifying tabs...")

    inputs_tabs, scenario_tabs, kanban_tabs, unknown_tabs = [], [], [], []
    for tab in tab_names:
        kind = "scenario" if tab in forced_scenarios else classify_tab(service, spreadsheet_id, tab)
        print(f"  {tab!r:30s} -> {kind}")
        {"inputs": inputs_tabs, "scenario": scenario_tabs,
         "kanban": kanban_tabs, "unknown": unknown_tabs}[kind].append(tab)

    if not inputs_tabs:
        print("\nWARNING: No inputs/budget tab detected. Creating empty inputs.json.")
    if not kanban_tabs:
        print("WARNING: No kanban tab detected. Creating empty kanban.json.")

    all_warnings = []

    # ── Inputs ──────────────────────────────────────────────────────────────
    inputs_tab = inputs_tabs[0] if inputs_tabs else None
    all_sections, input_map, flat_inputs = [], {}, {}

    if inputs_tab:
        print(f"\nDiscovering inputs from '{inputs_tab}'...")
        all_sections, input_map, flat_inputs, warnings = discover_inputs_tab(
            service, spreadsheet_id, inputs_tab
        )
        all_warnings.extend(warnings)
        total_fields = sum(len(s["fields"]) for s in all_sections)
        print(f"  {len(all_sections)} sections, {total_fields} fields")

    inputs_json = {"_meta": {"last_pulled": None, "last_pushed": None}, **flat_inputs}

    # ── Scenarios ────────────────────────────────────────────────────────────
    scenarios = []
    row_map = {}

    for tab in scenario_tabs:
        print(f"\nDiscovering scenario from '{tab}'...")
        scenario_data, tab_row_map, is_mp, phases, warnings = discover_scenario_tab(
            service, spreadsheet_id, tab
        )
        all_warnings.extend(warnings)

        scenario_id = slugify(tab)
        json_file = f"scenario_{scenario_id}.json"

        if is_mp:
            print(f"  Multi-phase: {phases}")
            for phase, rm in tab_row_map.items():
                row_map[f"{scenario_id}_{phase}"] = {str(r): iid for iid, r in rm.items()}
        else:
            n = len(scenario_data.get("line_items", []))
            print(f"  Single-phase: {n} line items")
            row_map[scenario_id] = {str(r): iid for iid, r in tab_row_map.items()}

        scenario_data["_meta"] = {"last_pulled": None, "last_pushed": None}
        with open(os.path.join(project_dir, json_file), "w") as f:
            json.dump(scenario_data, f, indent=2)

        scenarios.append({
            "id": scenario_id,
            "label": tab,
            "tab": tab,
            "json_file": json_file,
            "phases": phases,
        })

    # ── Kanban ───────────────────────────────────────────────────────────────
    kanban_tab = kanban_tabs[0] if kanban_tabs else "KANBAN"
    kanban_tasks = []
    if kanban_tabs:
        print(f"\nDiscovering kanban from '{kanban_tab}'...")
        kanban_tasks = discover_kanban_tab(service, spreadsheet_id, kanban_tab)
        print(f"  {len(kanban_tasks)} tasks")

    kanban_json = {
        "_meta": {
            "valid_statuses": ["New", "Active", "Complete", "Stopped"],
            "valid_priorities": ["Critical", "High", "Medium", "Low"],
            "last_pulled": None, "last_pushed": None,
        },
        "tasks": kanban_tasks,
    }

    # ── project.json ─────────────────────────────────────────────────────────
    project_json = {
        "spreadsheet_title": spreadsheet_title,
        "tabs": {
            "inputs": inputs_tab or "BUDGET",
            "kanban": kanban_tab,
        },
        "scenarios": scenarios,
        "kanban_meta": {
            "valid_statuses": ["New", "Active", "Complete", "Stopped"],
            "valid_priorities": ["Critical", "High", "Medium", "Low"],
        },
        "inputs_sections": all_sections,
    }

    config_json = {
        "spreadsheet_id": spreadsheet_id,
        "spreadsheet_url": f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}",
        "connected_at": datetime.now().isoformat(),
        "discovered": True,
    }

    for filename, data in [
        ("project.json",  project_json),
        ("inputs.json",   inputs_json),
        ("kanban.json",   kanban_json),
        ("row_map.json",  row_map),
        ("input_map.json", input_map),
        ("config.json",   config_json),
    ]:
        with open(os.path.join(project_dir, filename), "w") as f:
            json.dump(data, f, indent=2)

    # ── Summary ──────────────────────────────────────────────────────────────
    print(f"\n{'=' * 60}")
    print(f"Discovery complete: '{args.project}'")
    print(f"{'=' * 60}")
    print(f"Sheet:    {spreadsheet_title}")
    print(f"Inputs:   '{inputs_tab}' — "
          f"{sum(len(s['fields']) for s in all_sections)} fields in {len(all_sections)} sections")
    for s in scenarios:
        phase_str = f" ({', '.join(s['phases'])})" if s["phases"] else ""
        print(f"Scenario: '{s['tab']}'{phase_str} -> {s['json_file']}")
    print(f"Kanban:   '{kanban_tab}' — {len(kanban_tasks)} tasks")
    if unknown_tabs:
        print(f"Skipped:  {', '.join(unknown_tabs)}")
    if all_warnings:
        print(f"\nWarnings ({len(all_warnings)}):")
        for w in all_warnings:
            print(w)

    print(f"\nReview projects/{args.project}/project.json before proceeding.")
    print("Field types and section groupings may need adjustment.")
    print(f"\nNext step: python scripts/pull.py --project {args.project}")


if __name__ == "__main__":
    main()
