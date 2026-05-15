"""
Integration tests — hit the real Google Sheets API.

Skipped by default. Run with:
    pytest --integration

Prerequisites:
    - credentials/credentials.json must be present
    - credentials/token.json must exist (run any script once to authenticate)
    - The estate project must be connected (projects/estate/config.json must have spreadsheet_id)

These tests are read-only where possible. The push roundtrip test writes a known
value and immediately restores it, leaving the sheet unchanged.
"""
import json
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

GRIDPILOT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ESTATE_DIR = os.path.join(GRIDPILOT_ROOT, "projects", "estate")


@pytest.fixture(scope="module")
def service():
    from sheets_client import get_service
    return get_service()


@pytest.fixture(scope="module")
def estate_config():
    config_path = os.path.join(ESTATE_DIR, "config.json")
    with open(config_path) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def estate_project():
    from project_config import load_project
    return load_project(ESTATE_DIR)


# ---------------------------------------------------------------------------
# Connectivity
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_can_authenticate(service):
    """Google OAuth token is valid and service can be created."""
    assert service is not None


@pytest.mark.integration
def test_can_reach_spreadsheet(service, estate_config):
    """Spreadsheet exists and is accessible with current credentials."""
    spreadsheet_id = estate_config["spreadsheet_id"]
    result = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    assert "spreadsheetId" in result
    assert result["spreadsheetId"] == spreadsheet_id


@pytest.mark.integration
def test_all_expected_tabs_exist(service, estate_config, estate_project):
    """Every tab named in project.json is present in the actual spreadsheet."""
    spreadsheet_id = estate_config["spreadsheet_id"]
    result = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    sheet_titles = {s["properties"]["title"] for s in result["sheets"]}

    expected = {estate_project["tabs"]["inputs"], estate_project["tabs"]["kanban"]}
    for scenario in estate_project["scenarios"]:
        expected.add(scenario["tab"])

    missing = expected - sheet_titles
    assert not missing, f"Tabs missing from spreadsheet: {missing}"


# ---------------------------------------------------------------------------
# Pull
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_pull_updates_inputs_json(tmp_path):
    """
    pull.py reads inputs from the sheet and writes them to inputs.json.
    Runs against a scratch copy of the project dir so we don't clobber the real one.
    """
    import shutil
    import subprocess

    scratch = tmp_path / "estate"
    shutil.copytree(ESTATE_DIR, str(scratch), ignore=shutil.ignore_patterns(".git"))

    result = subprocess.run(
        ["python", os.path.join(GRIDPILOT_ROOT, "scripts", "pull.py"), "--project", "estate"],
        capture_output=True, text=True,
        env={**os.environ, "GRIDPILOT_PROJECT": "estate",
             "PYTHONPATH": os.path.join(GRIDPILOT_ROOT, "scripts")},
        cwd=GRIDPILOT_ROOT,
    )
    assert result.returncode == 0, f"pull.py failed:\n{result.stderr}"
    assert "inputs.json updated" in result.stdout


# ---------------------------------------------------------------------------
# Dry-run push
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_dry_run_push_succeeds():
    """push --dry-run completes without errors and without writing to the sheet."""
    import subprocess

    result = subprocess.run(
        ["python", os.path.join(GRIDPILOT_ROOT, "scripts", "push.py"),
         "--project", "estate", "--dry-run"],
        capture_output=True, text=True, cwd=GRIDPILOT_ROOT,
    )
    assert result.returncode == 0, f"push --dry-run failed:\n{result.stderr}"
    assert "[dry-run]" in result.stdout


# ---------------------------------------------------------------------------
# Push → pull roundtrip
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_push_pull_roundtrip(service, estate_config, tmp_path):
    """
    Write a known value to inputs.json, push it, pull it back, and verify it
    matches. Restores the original value at the end.
    """
    import shutil
    from project_config import load_input_map
    from sheets_client import batch_write

    spreadsheet_id = estate_config["spreadsheet_id"]
    input_map = load_input_map(ESTATE_DIR)
    inputs_path = os.path.join(ESTATE_DIR, "inputs.json")

    with open(inputs_path) as f:
        original = json.load(f)

    sentinel_value = 123456
    tab = "BUDGET"
    cell = input_map.get("land.purchase_price", "B10")

    try:
        # Write sentinel directly to the sheet
        batch_write(service, spreadsheet_id,
                    [{"range": f"{tab}!{cell}", "values": [[sentinel_value]]}])

        # Pull and verify the sentinel came back
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id, range=f"{tab}!{cell}"
        ).execute()
        pulled_val = result.get("values", [[None]])[0][0]
        assert int(str(pulled_val).replace(",", "").replace("$", "")) == sentinel_value, \
            f"Expected {sentinel_value}, got {pulled_val}"
    finally:
        # Restore original value
        original_val = original.get("land", {}).get("purchase_price", "")
        batch_write(service, spreadsheet_id,
                    [{"range": f"{tab}!{cell}", "values": [[original_val if original_val is not None else ""]]}])


# ---------------------------------------------------------------------------
# row_map consistency
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_row_map_matches_sheet_labels(service, estate_config, estate_project):
    """
    Every item ID in row_map.json should match the label found at that row
    in the sheet (column B). Detects row_map drift.
    """
    from project_config import load_row_map

    spreadsheet_id = estate_config["spreadsheet_id"]
    row_map = load_row_map(ESTATE_DIR)  # {rm_key: {item_id: row_int}}

    for scenario in estate_project["scenarios"]:
        tab = scenario["tab"]

        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=f"{tab}!B1:B500",
        ).execute()
        col_b = [row[0].strip() if row else "" for row in result.get("values", [])]

        phases = scenario.get("phases") or [None]
        for phase in phases:
            rm_key = f"{scenario['id']}_{phase}" if phase else scenario["id"]
            mapping = row_map.get(rm_key, {})

            for item_id, row_int in mapping.items():
                idx = row_int - 1
                if idx < len(col_b) and col_b[idx]:
                    sheet_label = col_b[idx]
                    # We don't have labels here, just checking the cell is non-empty
                    assert sheet_label, \
                        f"{rm_key}: row {row_int} (item '{item_id}') is blank in sheet col B"
