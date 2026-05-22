"""
Tests for push_scenario() and push_inputs() in scripts/push.py.

Approach: service=None skips validate_row_map; patch push.batch_write to capture
what would be sent to the API without making real calls.
"""
import json
import os
import pytest
from unittest.mock import patch, MagicMock, call

import push


SID = "fake_spreadsheet_id"
TAB = "ONE_SHOT"
INP_TAB = "BUDGET"


def _write_scenario(tmp_path, items):
    """Write a minimal scenario JSON to a temp file and return its path."""
    data = {"line_items": items, "_meta": {"last_pulled": None}}
    path = tmp_path / "scenario.json"
    path.write_text(json.dumps(data, indent=2))
    return str(path)


def _write_inputs(tmp_path, inputs):
    path = tmp_path / "inputs.json"
    path.write_text(json.dumps(inputs, indent=2))
    return str(tmp_path)


class TestPushScenarioDryRun:
    """Tests that inspect which ranges/values push_scenario would write."""

    def _call(self, tmp_path, items, row_map, **kwargs):
        """Run push_scenario with service=None (skips validate) and capture batch_write calls."""
        json_path = _write_scenario(tmp_path, items)
        captured_raw = []
        captured_formula = []

        def fake_batch_write(svc, sid, data, value_input_option="RAW"):
            if value_input_option == "USER_ENTERED":
                captured_formula.extend(data)
            else:
                captured_raw.extend(data)

        with patch("push.batch_write", side_effect=fake_batch_write):
            push.push_scenario(
                service=None,  # skips validate_row_map
                spreadsheet_id=SID,
                tab_name=TAB,
                row_map=row_map,
                json_path=json_path,
                phase_key=None,
                dry_run=False,
                **kwargs,
            )
        return captured_raw, captured_formula

    def test_value_item_generates_c_to_e_range(self, tmp_path):
        items = [{"section": "Site Work", "id": "site_clearing", "label": "Land Clearing",
                  "low": 30000, "mid": 55000, "high": 90000, "notes": ""}]
        raw, formula = self._call(tmp_path, items, {"site_clearing": 5})
        ranges = [u["range"] for u in raw]
        # Standard single-phase with notes_col=None (default F): packed into C:F
        assert any("C5" in r for r in ranges), f"Expected C5 in ranges: {ranges}"

    def test_formula_item_not_in_raw_writes(self, tmp_path):
        items = [{"section": "Soft Costs", "id": "soft_arch", "label": "Architect",
                  "formula": True, "low": None, "mid": None, "high": None, "notes": "From INPUTS"}]
        raw, formula = self._call(tmp_path, items, {"soft_arch": 18})
        raw_ranges = [u["range"] for u in raw]
        # C/D/E should NOT appear for a formula item in raw writes
        assert not any(r.startswith(f"{TAB}!C") for r in raw_ranges)
        assert not any(r.startswith(f"{TAB}!D") for r in raw_ranges)
        assert not any(r.startswith(f"{TAB}!E") for r in raw_ranges)

    def test_formula_item_notes_written(self, tmp_path):
        items = [{"section": "Soft Costs", "id": "soft_arch", "label": "Architect",
                  "formula": True, "low": None, "mid": None, "high": None, "notes": "Calc'd"}]
        # Default notes_col for single-phase is F
        raw, formula = self._call(tmp_path, items, {"soft_arch": 18})
        raw_ranges = [u["range"] for u in raw]
        assert f"{TAB}!F18" in raw_ranges

    def test_formula_expr_item_populates_formula_updates(self, tmp_path, sample_formula_expr_item):
        input_map = {
            "construction.sqft_phase1": "B66",
            "construction.sqft_phase2": "B67",
            "construction.rate_framing_low": "B72",
            "construction.rate_framing_mid": "C72",
            "construction.rate_framing_high": "D72",
        }
        items = [sample_formula_expr_item]
        raw, formula = self._call(
            tmp_path, items, {"structure_framing_phase_1": 46},
            notes_col="I",
            input_map=input_map,
            inp_tab="BUDGET",
        )
        # Formula updates should be non-empty
        assert len(formula) > 0
        # All formula update values should start with "="
        for u in formula:
            val = u["values"][0][0]
            assert val.startswith("="), f"Expected formula: {val}"

    def test_formula_expr_resolves_to_budget_refs(self, tmp_path, sample_formula_expr_item):
        input_map = {
            "construction.sqft_phase1": "B66",
            "construction.rate_framing_low": "B72",
            "construction.rate_framing_mid": "C72",
            "construction.rate_framing_high": "D72",
            "construction.sqft_phase2": "B67",
        }
        raw, formula = self._call(
            tmp_path, [sample_formula_expr_item], {"structure_framing_phase_1": 46},
            notes_col="I", input_map=input_map, inp_tab="BUDGET",
        )
        # At least one formula should reference BUDGET cells
        all_vals = [u["values"][0][0] for u in formula]
        assert any("BUDGET!B66" in v for v in all_vals)
        assert any("BUDGET!B72" in v for v in all_vals)

    def test_sheet_phase_2_item_writes_f_to_h(self, tmp_path):
        items = [{"section": "Foundation", "id": "foundation_p2", "label": "Foundation P2",
                  "low": 50000, "mid": 70000, "high": 90000, "notes": "",
                  "sheet_phase": 2}]
        raw, formula = self._call(
            tmp_path, items, {"foundation_p2": 43},
            notes_col="I",  # custom notes col means sheet_phase routing is active
        )
        raw_ranges = [u["range"] for u in raw]
        assert any("F43" in r for r in raw_ranges), f"Expected F43 in: {raw_ranges}"
        assert not any("C43" in r for r in raw_ranges)

    def test_p2_values_written_when_present(self, tmp_path):
        items = [{"section": "Site Work", "id": "site_ex", "label": "Excavation",
                  "low": 8000, "mid": 12000, "high": 22000, "notes": "",
                  "p2_low": 8000, "p2_mid": 12000, "p2_high": 22000}]
        raw, formula = self._call(
            tmp_path, items, {"site_ex": 32},
            notes_col="I",
        )
        raw_ranges = [u["range"] for u in raw]
        assert any("F32" in r for r in raw_ranges), f"Expected F32 (P2) in: {raw_ranges}"

    def test_p2_values_not_written_when_formula_expr_present(self, tmp_path, sample_formula_expr_item):
        input_map = {
            "construction.sqft_phase1": "B66", "construction.sqft_phase2": "B67",
            "construction.rate_framing_low": "B72", "construction.rate_framing_mid": "C72",
            "construction.rate_framing_high": "D72",
        }
        raw, formula = self._call(
            tmp_path, [sample_formula_expr_item], {"structure_framing_phase_1": 46},
            notes_col="I", input_map=input_map, inp_tab="BUDGET",
        )
        # When formula_expr is present, raw p2 values should NOT be written separately
        raw_ranges = [u["range"] for u in raw]
        assert not any("F46" in r for r in raw_ranges), (
            f"formula_expr item should not also write raw p2 to F46: {raw_ranges}"
        )


class TestPushInputsDryRun:
    """Tests that inspect which BUDGET cells push_inputs would update."""

    def _call(self, tmp_path, inputs, input_map, project=None):
        project = project or {"tabs": {"inputs": "BUDGET"}}
        _write_inputs(tmp_path, inputs)
        captured = []

        def fake_batch_write(svc, sid, data, **kwargs):
            captured.extend(data)

        with patch("push.batch_write", side_effect=fake_batch_write):
            push.push_inputs(
                service=None,
                spreadsheet_id=SID,
                project=project,
                input_map=input_map,
                project_dir=str(tmp_path),
                dry_run=False,
            )
        return captured

    def test_builds_updates_from_inputs(self, tmp_path):
        inputs = {"construction": {"target_square_footage": 3200}}
        input_map = {"construction.target_square_footage": "B17"}
        updates = self._call(tmp_path, inputs, input_map)
        assert len(updates) == 1
        assert updates[0]["range"] == "BUDGET!B17"
        assert updates[0]["values"] == [[3200]]

    def test_tab_qualified_cell_preserved(self, tmp_path):
        inputs = {"borrower": {"gross_annual_income": 150000}}
        input_map = {"borrower.gross_annual_income": "CAPITAL!B4"}
        updates = self._call(tmp_path, inputs, input_map)
        assert updates[0]["range"] == "CAPITAL!B4"  # not "BUDGET!CAPITAL!B4"

    def test_unqualified_cell_gets_tab_prefix(self, tmp_path):
        inputs = {"construction": {"sqft_phase1": 1400}}
        input_map = {"construction.sqft_phase1": "B66"}
        updates = self._call(tmp_path, inputs, input_map)
        assert updates[0]["range"] == "BUDGET!B66"

    def test_none_value_written_as_empty_string(self, tmp_path):
        inputs = {"construction": {"rate_insulation_low": None}}
        input_map = {"construction.rate_insulation_low": "B85"}
        updates = self._call(tmp_path, inputs, input_map)
        assert updates[0]["values"] == [[""]]

    def test_missing_key_skipped(self, tmp_path):
        inputs = {"construction": {"target_square_footage": 3200}}
        input_map = {
            "construction.target_square_footage": "B17",
            "construction.nonexistent_key": "B99",  # not in inputs.json
        }
        updates = self._call(tmp_path, inputs, input_map)
        ranges = [u["range"] for u in updates]
        assert "BUDGET!B17" in ranges
        assert "BUDGET!B99" not in ranges


class TestFmtCurrencyExtended:
    def test_negative_number(self):
        assert push.fmt_currency(-50000) == -50000

    def test_zero(self):
        assert push.fmt_currency(0) == 0

    def test_float_truncates_to_int(self):
        assert push.fmt_currency(1234.99) == 1234

    def test_none_returns_empty_string(self):
        assert push.fmt_currency(None) == ""
