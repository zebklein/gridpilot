"""
Shared loaders for project.json, input_map.json, row_map.json, config.json.

All scripts resolve their project directory via get_project_dir(), which reads
the --project flag or the GRIDPILOT_PROJECT environment variable.
"""
import os
import sys
import json

GRIDPILOT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def get_project_dir(project_name):
    name = project_name or os.environ.get("GRIDPILOT_PROJECT")
    if not name:
        print("ERROR: No project specified.")
        print("  Use --project <name> or set GRIDPILOT_PROJECT env var.")
        print("  Project directories live in gridpilot/projects/<name>/")
        sys.exit(1)
    path = os.path.join(GRIDPILOT_ROOT, "projects", name)
    if not os.path.isdir(path):
        print(f"ERROR: Project directory not found: {path}")
        print(f"  Run: cp -r templates/new-construction projects/{name}")
        sys.exit(1)
    return path


def load_project(project_dir):
    path = os.path.join(project_dir, "project.json")
    if not os.path.exists(path):
        print(f"ERROR: project.json not found in {project_dir}")
        print("  Copy a template: cp -r templates/new-construction projects/<name>")
        sys.exit(1)
    with open(path) as f:
        return json.load(f)


def load_config(project_dir):
    path = os.path.join(project_dir, "config.json")
    if not os.path.exists(path):
        print("ERROR: config.json not found. Run init_sheet.py or connect.py first.")
        sys.exit(1)
    with open(path) as f:
        cfg = json.load(f)
    if not cfg.get("spreadsheet_id"):
        print("ERROR: spreadsheet_id not set. Run init_sheet.py or connect.py first.")
        sys.exit(1)
    return cfg


def load_input_map(project_dir):
    path = os.path.join(project_dir, "input_map.json")
    if not os.path.exists(path):
        print("ERROR: input_map.json not found. Run init_sheet.py or connect.py first.")
        sys.exit(1)
    with open(path) as f:
        return json.load(f)


def load_row_map(project_dir):
    path = os.path.join(project_dir, "row_map.json")
    if not os.path.exists(path):
        print("ERROR: row_map.json not found. Run init_sheet.py or connect.py first.")
        sys.exit(1)
    with open(path) as f:
        rm = json.load(f)
    # Return inverted maps: {row_1idx_str: item_id} → {item_id: row_1idx_int}
    inverted = {}
    for key, mapping in rm.items():
        inverted[key] = {v: int(k) for k, v in mapping.items()}
    return inverted


def save_row_map(project_dir, rm):
    path = os.path.join(project_dir, "row_map.json")
    with open(path, "w") as f:
        json.dump(rm, f, indent=2)


def get_tab_name(project, logical_name):
    """Resolve a logical tab name (inputs, kanban, or scenario id) to the sheet tab title."""
    if logical_name in project.get("tabs", {}):
        return project["tabs"][logical_name]
    for s in project.get("scenarios", []):
        if s["id"] == logical_name:
            return s["tab"]
    raise KeyError(f"Tab '{logical_name}' not found in project.json")


def get_scenario_row_map_key(scenario, phase=None):
    """Return the row_map key for a given scenario and optional phase."""
    if phase:
        return f"{scenario['id']}_{phase}"
    return scenario["id"]


def get_inputs_value(inputs_data, dotted_key):
    """Extract a value from inputs.json using a dotted key like 'land.purchase_price'."""
    parts = dotted_key.split(".")
    node = inputs_data
    try:
        for part in parts:
            node = node[part]
        return node
    except (KeyError, TypeError):
        return None
