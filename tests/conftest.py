"""
Shared fixtures for all gridpilot tests.

Integration tests require a real Google Sheet and are skipped by default.
Run them with: pytest --integration
"""
import json
import os
import sys
import pytest

# Make scripts/ importable without installing the package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))


def pytest_addoption(parser):
    parser.addoption(
        "--integration",
        action="store_true",
        default=False,
        help="Run integration tests that hit the real Google Sheets API",
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "integration: mark test as requiring a live Google Sheets connection"
    )


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--integration"):
        skip = pytest.mark.skip(reason="Pass --integration to run live API tests")
        for item in items:
            if "integration" in item.keywords:
                item.add_marker(skip)


# ---------------------------------------------------------------------------
# Sample data mirrors the minimal shape every script expects
# ---------------------------------------------------------------------------

SAMPLE_PROJECT = {
    "spreadsheet_title": "Test Project",
    "tabs": {"inputs": "BUDGET", "kanban": "KANBAN"},
    "scenarios": [
        {
            "id": "full_build",
            "label": "Full Build",
            "tab": "ONE_SHOT",
            "json_file": "scenario_full_build.json",
            "phases": None,
        },
        {
            "id": "phased",
            "label": "Phased",
            "tab": "MODULAR",
            "json_file": "scenario_phased.json",
            "phases": ["phase1", "phase2"],
        },
    ],
    "kanban_meta": {
        "valid_statuses": ["New", "Active", "Complete", "Stopped"],
        "valid_priorities": ["Critical", "High", "Medium", "Low"],
    },
    "inputs_sections": [
        {
            "id": "land",
            "label": "LAND",
            "fields": [
                {"key": "land.purchase_price", "label": "Land Purchase Price", "type": "currency"},
                {"key": "land.closing_costs_pct", "label": "Closing Costs", "type": "percent"},
            ],
        }
    ],
}

SAMPLE_INPUTS = {
    "_meta": {"last_pulled": "2026-01-01T00:00:00", "last_pushed": None},
    "land": {
        "purchase_price": 185000,
        "closing_costs_pct": 0.02,
    },
    "construction": {
        "target_sqft": 4000,
        "cost_per_sqft_mid": 450,
    },
}

SAMPLE_SCENARIO = {
    "_meta": {"last_pulled": "2026-01-01T00:00:00"},
    "line_items": [
        {
            "section": "Site Work",
            "id": "site_clearing",
            "label": "Land Clearing & Grading",
            "low": 30000,
            "mid": 55000,
            "high": 90000,
            "notes": "",
        },
        {
            "section": "Site Work",
            "id": "site_well",
            "label": "Well Drilling",
            "low": 15000,
            "mid": 22000,
            "high": 35000,
            "notes": "Estimate pending test well",
        },
        {
            "section": "Soft Costs",
            "id": "soft_architect",
            "label": "Architect Fee",
            "formula": True,
            "low": None,
            "mid": None,
            "high": None,
            "notes": "",
        },
    ],
}

SAMPLE_KANBAN = {
    "_meta": {
        "valid_statuses": ["New", "Active", "Complete", "Stopped"],
        "valid_priorities": ["Critical", "High", "Medium", "Low"],
        "last_pulled": "2026-01-01T00:00:00",
        "last_pushed": None,
    },
    "tasks": [
        {
            "id": "task_01",
            "title": "Do a thing",
            "status": "New",
            "owner": "Alice",
            "priority": "High",
            "blocked_by": "",
            "notes": "Some notes",
            "resources": "",
        }
    ],
}

# row_map.json on disk is in storage format: {rm_key: {row_str: item_id}}
SAMPLE_ROW_MAP_RAW = {
    "full_build": {
        "5": "site_clearing",
        "6": "site_well",
        "9": "soft_architect",
    },
    "phased_phase1": {
        "5": "site_clearing_p1",
        "6": "site_well_p1",
    },
    "phased_phase2": {
        "5": "site_clearing_p2",
        "6": "site_well_p2",
    },
}

SAMPLE_INPUT_MAP = {
    "land.purchase_price": "B10",
    "land.closing_costs_pct": "B11",
    "construction.target_sqft": "B17",
    "construction.cost_per_sqft_mid": "B19",
    "soft_costs.architect_pct": "B32",
    "soft_costs.permits_fees_flat": "B34",
    "soft_costs.survey_geotech_flat": "B35",
    "soft_costs.legal_misc_flat": "B36",
    "soft_costs.engineering_pct": "B33",
    "financing.construction_loan_ltv": "B22",
}


@pytest.fixture
def tmp_project_dir(tmp_path):
    """A fully populated temporary project directory for use in tests."""
    project_dir = tmp_path / "testproject"
    project_dir.mkdir()

    (project_dir / "project.json").write_text(json.dumps(SAMPLE_PROJECT, indent=2))
    (project_dir / "inputs.json").write_text(json.dumps(SAMPLE_INPUTS, indent=2))
    (project_dir / "scenario_full_build.json").write_text(json.dumps(SAMPLE_SCENARIO, indent=2))
    (project_dir / "row_map.json").write_text(json.dumps(SAMPLE_ROW_MAP_RAW, indent=2))
    (project_dir / "input_map.json").write_text(json.dumps(SAMPLE_INPUT_MAP, indent=2))
    (project_dir / "kanban.json").write_text(json.dumps(SAMPLE_KANBAN, indent=2))
    (project_dir / "config.json").write_text(
        json.dumps({"spreadsheet_id": "fake_id", "spreadsheet_url": "https://example.com"}, indent=2)
    )

    return str(project_dir)


@pytest.fixture
def sample_project():
    return SAMPLE_PROJECT


@pytest.fixture
def sample_inputs():
    return SAMPLE_INPUTS


@pytest.fixture
def sample_scenario():
    return SAMPLE_SCENARIO
