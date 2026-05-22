"""
Smoke tests for Gridpilot against a real Google Sheets test spreadsheet.

These tests require:
  1. A Google Sheet initialized with the test-estate schema (BUDGET, ONE_SHOT, MODULAR, KANBAN tabs)
  2. A test spreadsheet ID configured via:
       - env var: GRIDPILOT_TEST_SPREADSHEET_ID
       - or file:  tests/fixtures/test-estate/config.json  {"spreadsheet_id": "..."}

Run with:
    pytest tests/test_smoke.py --integration

Setup (one-time):
    python scripts/init_sheet.py --project test-estate
    # Then store the resulting spreadsheet ID as described above
"""
import json
import os
import shutil
import pytest

import push
import pull
import validate as validate_mod
from sheets_client import get_service, read_range, clear_scenario_rows
from project_config import load_row_map

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "test-estate")
FIXTURE_FILES = (
    "project.json", "inputs.json", "row_map.json", "input_map.json",
    "kanban.json", "scenario_one_shot.json", "scenario_modular.json",
)


def _load_json(path):
    with open(path) as f:
        return json.load(f)


def _setup_tmp_project(tmp_path):
    """Copy all fixture files to a writable temp dir. Returns the path."""
    tmp_project = tmp_path / "estate"
    tmp_project.mkdir()
    for fname in FIXTURE_FILES:
        shutil.copy(os.path.join(FIXTURES_DIR, fname), tmp_project / fname)
    return tmp_project


@pytest.fixture(scope="module")
def service():
    return get_service()


@pytest.fixture(scope="module")
def estate_row_map():
    return load_row_map(FIXTURES_DIR)


@pytest.mark.integration
class TestSmokePushValidate:
    """Push test-estate data to the test sheet, then probe correctness."""

    def test_validate_passes_after_push(self, service, test_spreadsheet_id, estate_row_map):
        """Push test-estate scenarios to the test sheet — validate should report zero mismatches."""
        project_file = os.path.join(FIXTURES_DIR, "project.json")
        with open(project_file) as f:
            project = json.load(f)

        input_map_file = os.path.join(FIXTURES_DIR, "input_map.json")
        with open(input_map_file) as f:
            input_map = json.load(f)

        inp_tab = project["tabs"]["inputs"]
        for scenario in project["scenarios"]:
            json_path = os.path.join(FIXTURES_DIR, scenario["json_file"])
            rm_key = scenario["id"]
            row_map = estate_row_map.get(rm_key, {})

            with open(json_path) as f:
                data = json.load(f)
            items_by_id = {item["id"]: item for item in data["line_items"]}

            # Push first
            push.push_scenario(
                service=service,
                spreadsheet_id=test_spreadsheet_id,
                tab_name=scenario["tab"],
                row_map=row_map,
                json_path=json_path,
                phase_key=None,
                dry_run=False,
                notes_col=scenario.get("notes_col"),
                input_map=input_map,
                inp_tab=inp_tab,
            )

            # Then validate — should pass
            ok = validate_mod.validate_row_map(
                service, test_spreadsheet_id, scenario["tab"], row_map, items_by_id, abort=False
            )
            assert ok, f"row_map validation failed for scenario '{scenario['id']}'"

    def test_formula_expr_cells_are_live_formulas(self, service, test_spreadsheet_id, estate_row_map):
        """After push, formula_expr cells in ONE_SHOT should start with '='."""
        input_map_file = os.path.join(FIXTURES_DIR, "input_map.json")
        with open(input_map_file) as f:
            input_map = json.load(f)

        json_path = os.path.join(FIXTURES_DIR, "scenario_one_shot.json")
        row_map = estate_row_map.get("one_shot", {})

        push.push_scenario(
            service=service,
            spreadsheet_id=test_spreadsheet_id,
            tab_name="ONE_SHOT",
            row_map=row_map,
            json_path=json_path,
            phase_key=None,
            dry_run=False,
            input_map=input_map,
            inp_tab="BUDGET",
        )

        # Framing row in ONE_SHOT is row 46 — column C should be a live formula
        framing_row = row_map.get("structure_framing_minka_style_complex_roof")
        assert framing_row is not None, "structure_framing row not in row_map"

        from sheets_client import read_range as _read
        from googleapiclient.discovery import build  # noqa: F401  (just to confirm import)

        # Read with FORMULA render option to get the formula string
        result = (
            service.spreadsheets()
            .values()
            .get(
                spreadsheetId=test_spreadsheet_id,
                range=f"ONE_SHOT!C{framing_row}",
                valueRenderOption="FORMULA",
            )
            .execute()
        )
        cell_values = result.get("values", [[""]])
        cell = cell_values[0][0] if cell_values and cell_values[0] else ""
        assert cell.startswith("="), (
            f"Expected formula in ONE_SHOT!C{framing_row}, got: {cell!r}"
        )

    def test_push_pull_roundtrip_formula_items_stay_null(
        self, service, test_spreadsheet_id, estate_row_map, tmp_path
    ):
        """Push → pull → formula items in JSON should still have null values (formulas live in sheet)."""
        import shutil

        input_map_file = os.path.join(FIXTURES_DIR, "input_map.json")
        json_path_src = os.path.join(FIXTURES_DIR, "scenario_one_shot.json")

        # Copy fixture to tmp dir so pull.py can write back
        tmp_project = tmp_path / "estate"
        tmp_project.mkdir()
        for fname in ("project.json", "inputs.json", "row_map.json", "input_map.json",
                      "kanban.json", "scenario_one_shot.json", "scenario_modular.json"):
            shutil.copy(os.path.join(FIXTURES_DIR, fname), tmp_project / fname)
        (tmp_project / "config.json").write_text(
            json.dumps({"spreadsheet_id": test_spreadsheet_id})
        )

        with open(input_map_file) as f:
            input_map = json.load(f)

        # Push
        push.push_scenario(
            service=service,
            spreadsheet_id=test_spreadsheet_id,
            tab_name="ONE_SHOT",
            row_map=estate_row_map.get("one_shot", {}),
            json_path=str(tmp_project / "scenario_one_shot.json"),
            phase_key=None,
            dry_run=False,
            input_map=input_map,
            inp_tab="BUDGET",
        )

        # Pull back
        pull.pull_scenario(
            service=service,
            spreadsheet_id=test_spreadsheet_id,
            tab_name="ONE_SHOT",
            row_map=estate_row_map.get("one_shot", {}),
            json_path=str(tmp_project / "scenario_one_shot.json"),
        )

        with open(tmp_project / "scenario_one_shot.json") as f:
            pulled = json.load(f)

        items_by_id = {item["id"]: item for item in pulled["line_items"]}
        framing = items_by_id.get("structure_framing_minka_style_complex_roof")
        assert framing is not None, "framing item missing after pull"
        # Formula items should have null values — the formula lives in the sheet
        assert framing["low"] is None, (
            f"formula item should stay null after pull, got: {framing['low']}"
        )

    def test_clear_scenario_rows_preserves_sum_rows(
        self, service, test_spreadsheet_id, estate_row_map
    ):
        """clear_scenario_rows() must not wipe SUM formula rows (subtotals)."""
        row_map = estate_row_map.get("one_shot", {})

        # clear only tracked data rows
        clear_scenario_rows(service, test_spreadsheet_id, "ONE_SHOT", row_map)

        # The subtotal row for Due Diligence is row 16 — not in row_map — should survive
        subtotal_row = 16
        result = (
            service.spreadsheets()
            .values()
            .get(
                spreadsheetId=test_spreadsheet_id,
                range=f"ONE_SHOT!C{subtotal_row}",
                valueRenderOption="FORMULA",
            )
            .execute()
        )
        vals = result.get("values", [[""]])
        cell = vals[0][0] if vals and vals[0] else ""
        assert cell.startswith("=SUM"), (
            f"Subtotal SUM formula at row {subtotal_row} should survive clear_scenario_rows, got: {cell!r}"
        )

    def test_validate_detects_row_map_drift(
        self, service, test_spreadsheet_id, estate_row_map
    ):
        """Shifting a row_map entry by 5 rows should produce a mismatch report."""
        row_map = dict(estate_row_map.get("one_shot", {}))

        # Offset one entry by 5 (simulate discover.py missing 5 header rows)
        item_id = "site_work_land_clearing_grading"
        if item_id in row_map:
            row_map[item_id] = row_map[item_id] + 5  # now points to wrong row

        json_path = os.path.join(FIXTURES_DIR, "scenario_one_shot.json")
        with open(json_path) as f:
            data = json.load(f)
        items_by_id = {item["id"]: item for item in data["line_items"]}

        ok = validate_mod.validate_row_map(
            service, test_spreadsheet_id, "ONE_SHOT", row_map, items_by_id, abort=False
        )
        assert ok is False, "Expected validate to detect the 5-row offset"


@pytest.mark.integration
class TestSmokeRoundtrip:
    """
    End-to-end data accuracy tests: push known values → read back from sheet → verify exact match.

    Each test uses a fresh copy of the fixture files in tmp_path so pull.py can write
    back without touching the committed fixtures.
    """

    # ------------------------------------------------------------------
    # Value item roundtrip — ONE_SHOT
    # ------------------------------------------------------------------

    def test_value_items_roundtrip_accurately(self, service, test_spreadsheet_id, estate_row_map, tmp_path):
        """
        Push all non-formula ONE_SHOT items → pull back → every low/mid/high matches exactly.

        This is the core accuracy test: catches parse_num / fmt_currency mismatches,
        column-index drift, and API value rendering bugs.
        """
        tmp = _setup_tmp_project(tmp_path)
        json_path = str(tmp / "scenario_one_shot.json")
        input_map = _load_json(os.path.join(FIXTURES_DIR, "input_map.json"))
        row_map = estate_row_map.get("one_shot", {})

        push.push_scenario(
            service=service, spreadsheet_id=test_spreadsheet_id,
            tab_name="ONE_SHOT", row_map=row_map,
            json_path=json_path, phase_key=None, dry_run=False,
            input_map=input_map, inp_tab="BUDGET",
        )
        pull.pull_scenario(
            service=service, spreadsheet_id=test_spreadsheet_id,
            tab_name="ONE_SHOT", row_map=row_map, json_path=json_path,
        )

        original = _load_json(os.path.join(FIXTURES_DIR, "scenario_one_shot.json"))
        pulled = _load_json(json_path)
        orig_by_id = {i["id"]: i for i in original["line_items"]}
        pulled_by_id = {i["id"]: i for i in pulled["line_items"]}

        mismatches = []
        for item_id, orig in orig_by_id.items():
            if orig.get("formula") or all(orig.get(f) is None for f in ("low", "mid", "high")):
                continue  # formula items: values live in sheet, not JSON
            pulled_item = pulled_by_id.get(item_id)
            if pulled_item is None:
                mismatches.append(f"{item_id}: missing from pulled JSON")
                continue
            for field in ("low", "mid", "high"):
                ov, pv = orig.get(field), pulled_item.get(field)
                if ov != pv:
                    mismatches.append(f"{item_id}.{field}: pushed={ov!r}, pulled={pv!r}")

        assert not mismatches, (
            f"{len(mismatches)} value mismatch(es) after ONE_SHOT roundtrip:\n"
            + "\n".join(mismatches)
        )

    # ------------------------------------------------------------------
    # Phase 2 value roundtrip — MODULAR
    # ------------------------------------------------------------------

    def test_modular_p2_values_roundtrip(self, service, test_spreadsheet_id, estate_row_map, tmp_path):
        """
        Push MODULAR (P1 + P2 columns) → pull back → p2_low/mid/high preserved.

        Covers the F/G/H column write path that only exists in MODULAR's custom notes_col layout.
        """
        tmp = _setup_tmp_project(tmp_path)
        json_path = str(tmp / "scenario_modular.json")
        input_map = _load_json(os.path.join(FIXTURES_DIR, "input_map.json"))
        row_map = estate_row_map.get("modular", {})

        push.push_scenario(
            service=service, spreadsheet_id=test_spreadsheet_id,
            tab_name="MODULAR", row_map=row_map,
            json_path=json_path, phase_key=None, dry_run=False,
            notes_col="I", input_map=input_map, inp_tab="BUDGET",
        )
        pull.pull_scenario(
            service=service, spreadsheet_id=test_spreadsheet_id,
            tab_name="MODULAR", row_map=row_map,
            json_path=json_path, notes_col="I",
        )

        original = _load_json(os.path.join(FIXTURES_DIR, "scenario_modular.json"))
        pulled = _load_json(json_path)
        orig_by_id = {i["id"]: i for i in original["line_items"]}
        pulled_by_id = {i["id"]: i for i in pulled["line_items"]}

        mismatches = []
        for item_id, orig in orig_by_id.items():
            if orig.get("formula"):
                continue
            if not any(orig.get(f) is not None for f in ("p2_low", "p2_mid", "p2_high")):
                continue  # no P2 values to check
            pulled_item = pulled_by_id.get(item_id)
            if pulled_item is None:
                continue
            for field in ("p2_low", "p2_mid", "p2_high"):
                ov, pv = orig.get(field), pulled_item.get(field)
                if ov is not None and ov != pv:
                    mismatches.append(f"{item_id}.{field}: pushed={ov!r}, pulled={pv!r}")

        assert not mismatches, (
            f"{len(mismatches)} P2 mismatch(es) after MODULAR roundtrip:\n"
            + "\n".join(mismatches)
        )

    # ------------------------------------------------------------------
    # BUDGET inputs roundtrip
    # ------------------------------------------------------------------

    def test_inputs_budget_roundtrip(self, service, test_spreadsheet_id, tmp_path):
        """
        Push inputs.json to BUDGET tab → pull back → all numeric inputs preserved.

        Covers construction rates, sqft targets, financing params, soft cost percentages.
        If a value comes back as the wrong type or wrong number, this catches it.
        """
        tmp = _setup_tmp_project(tmp_path)
        project = _load_json(os.path.join(FIXTURES_DIR, "project.json"))
        input_map = _load_json(os.path.join(FIXTURES_DIR, "input_map.json"))

        push.push_inputs(
            service=service, spreadsheet_id=test_spreadsheet_id,
            project=project, input_map=input_map,
            project_dir=str(tmp), dry_run=False,
        )
        pull.pull_inputs(
            service=service, spreadsheet_id=test_spreadsheet_id,
            project=project, input_map=input_map,
            project_dir=str(tmp),
        )

        pulled = _load_json(str(tmp / "inputs.json"))

        checks = [
            # sqft targets
            ("construction", "target_square_footage", 3200),
            ("construction", "sqft_phase1", 1400),
            ("construction", "sqft_phase2", 1800),
            # construction rates ($/sqft integers)
            ("construction", "rate_framing_low",   31),
            ("construction", "rate_framing_mid",   63),
            ("construction", "rate_framing_high",  94),
            ("construction", "rate_roofing_low",   13),
            ("construction", "rate_hvac_mid",      22),
            ("construction", "rate_flooring_high", 39),
            # financing (floats / percentages)
            ("financing", "construction_loan_rate", 0.075),
            ("financing", "construction_loan_ltv",  0.8),
            ("financing", "permanent_loan_rate",    0.065),
            ("financing", "permanent_loan_term",    30),
            ("financing", "construction_duration",  18),
            # soft costs (flat amounts)
            ("soft_costs", "permits_fees_flat",        25000),
            ("soft_costs", "survey_geotech_flat",      15000),
            ("soft_costs", "legal_miscellaneous_flat", 10000),
            # contingency rates
            ("contingency", "construction_contingency", 0.1),
            ("contingency", "owner_change_reserve",     0.05),
        ]
        mismatches = []
        for section, key, expected in checks:
            actual = pulled.get(section, {}).get(key)
            if actual != expected:
                mismatches.append(f"{section}.{key}: expected={expected!r}, got={actual!r}")

        assert not mismatches, (
            f"{len(mismatches)} input mismatch(es) after BUDGET roundtrip:\n"
            + "\n".join(mismatches)
        )

    # ------------------------------------------------------------------
    # Notes string roundtrip
    # ------------------------------------------------------------------

    def test_notes_strings_survive_roundtrip(self, service, test_spreadsheet_id, estate_row_map, tmp_path):
        """
        Push ONE_SHOT with notes → pull back → notes text preserved verbatim.

        Guards against the notes column being misread (wrong column index) or truncated.
        """
        tmp = _setup_tmp_project(tmp_path)
        json_path = str(tmp / "scenario_one_shot.json")
        input_map = _load_json(os.path.join(FIXTURES_DIR, "input_map.json"))
        row_map = estate_row_map.get("one_shot", {})

        push.push_scenario(
            service=service, spreadsheet_id=test_spreadsheet_id,
            tab_name="ONE_SHOT", row_map=row_map,
            json_path=json_path, phase_key=None, dry_run=False,
            input_map=input_map, inp_tab="BUDGET",
        )
        pull.pull_scenario(
            service=service, spreadsheet_id=test_spreadsheet_id,
            tab_name="ONE_SHOT", row_map=row_map, json_path=json_path,
        )

        original = _load_json(os.path.join(FIXTURES_DIR, "scenario_one_shot.json"))
        pulled = _load_json(json_path)
        orig_by_id = {i["id"]: i for i in original["line_items"]}
        pulled_by_id = {i["id"]: i for i in pulled["line_items"]}

        items_with_notes = [
            item_id for item_id, item in orig_by_id.items()
            if item.get("notes") and not item.get("formula")
        ][:8]

        mismatches = []
        for item_id in items_with_notes:
            orig_note = orig_by_id[item_id].get("notes", "")
            pulled_note = pulled_by_id.get(item_id, {}).get("notes", "")
            if orig_note != pulled_note:
                mismatches.append(
                    f"{item_id}:\n  pushed={orig_note!r}\n  pulled={pulled_note!r}"
                )

        assert not mismatches, f"Notes mismatch after roundtrip:\n" + "\n".join(mismatches)

    # ------------------------------------------------------------------
    # Broad-stroke: full pipeline, both scenarios
    # ------------------------------------------------------------------

    def test_full_pipeline_both_scenarios(self, service, test_spreadsheet_id, estate_row_map, tmp_path):
        """
        Broad smoke test: push inputs + both scenarios → validate both → pull everything back
        → spot-check values from each major section.

        This is the single "is the whole system working?" test. Failure here means
        something at the integration layer broke; the individual roundtrip tests above
        narrow down which data path is at fault.
        """
        tmp = _setup_tmp_project(tmp_path)
        project = _load_json(os.path.join(FIXTURES_DIR, "project.json"))
        input_map = _load_json(os.path.join(FIXTURES_DIR, "input_map.json"))

        # ── 1. Push BUDGET inputs ──────────────────────────────────────
        push.push_inputs(
            service=service, spreadsheet_id=test_spreadsheet_id,
            project=project, input_map=input_map,
            project_dir=str(tmp), dry_run=False,
        )

        # ── 2. Push both scenarios + validate after each ───────────────
        for scenario in project["scenarios"]:
            json_path = str(tmp / scenario["json_file"])
            row_map = estate_row_map.get(scenario["id"], {})

            push.push_scenario(
                service=service, spreadsheet_id=test_spreadsheet_id,
                tab_name=scenario["tab"], row_map=row_map,
                json_path=json_path, phase_key=None, dry_run=False,
                notes_col=scenario.get("notes_col"),
                input_map=input_map, inp_tab=project["tabs"]["inputs"],
            )

            with open(json_path) as f:
                items_by_id = {i["id"]: i for i in json.load(f)["line_items"]}

            ok = validate_mod.validate_row_map(
                service, test_spreadsheet_id, scenario["tab"], row_map, items_by_id, abort=False
            )
            assert ok, f"row_map validation failed for scenario '{scenario['id']}'"

        # ── 3. Pull everything back ────────────────────────────────────
        pull.pull_inputs(
            service=service, spreadsheet_id=test_spreadsheet_id,
            project=project, input_map=input_map, project_dir=str(tmp),
        )
        for scenario in project["scenarios"]:
            pull.pull_scenario(
                service=service, spreadsheet_id=test_spreadsheet_id,
                tab_name=scenario["tab"],
                row_map=estate_row_map.get(scenario["id"], {}),
                json_path=str(tmp / scenario["json_file"]),
                notes_col=scenario.get("notes_col"),
            )

        # ── 4. Spot-check across sections ─────────────────────────────
        # BUDGET: key inputs survived
        inputs = _load_json(str(tmp / "inputs.json"))
        assert inputs["construction"]["target_square_footage"] == 3200
        assert inputs["construction"]["rate_framing_mid"] == 63
        assert inputs["financing"]["permanent_loan_term"] == 30

        # ONE_SHOT: value items from three different sections
        one_shot = _load_json(str(tmp / "scenario_one_shot.json"))
        os_items = {i["id"]: i for i in one_shot["line_items"]}

        clearing = os_items.get("site_work_land_clearing_grading")
        assert clearing and clearing["low"] == 30000 and clearing["high"] == 90000, \
            f"site work mismatch: {clearing}"

        kitchens = os_items.get("interior_kitchens_multiple_up_to_4_units")
        assert kitchens and kitchens["mid"] == 115000, f"kitchens mid: {kitchens}"

        gym = os_items.get("specialty_gym_shared_space_fit_out")
        assert gym and gym["low"] == 15000, f"gym low: {gym}"

        # ONE_SHOT: formula items still null
        framing = os_items.get("structure_framing_minka_style_complex_roof")
        assert framing and framing["low"] is None, \
            f"formula item should stay null, got: {framing['low']}"

        # MODULAR: P2 values from site work
        modular = _load_json(str(tmp / "scenario_modular.json"))
        mod_items = {i["id"]: i for i in modular["line_items"]}

        excavation = mod_items.get("site_work_excavation_phase_1_footprint")
        assert excavation and excavation["p2_low"] == 8000, \
            f"modular P2 excavation: {excavation}"

        permits = mod_items.get("soft_costs_permits_fees_phase_1")
        assert permits and permits["p2_mid"] == 15000, \
            f"modular P2 permits: {permits}"
