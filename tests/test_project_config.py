import json
import os
import pytest
from project_config import (
    get_inputs_value,
    get_scenario_row_map_key,
    get_tab_name,
    load_row_map,
    save_row_map,
)


class TestGetInputsValue:
    INPUTS = {
        "land": {"purchase_price": 185000, "closing_costs_pct": 0.02},
        "construction": {"target_sqft": 4000, "cost_per_sqft_mid": None},
    }

    def test_simple_dotted_key(self):
        assert get_inputs_value(self.INPUTS, "land.purchase_price") == 185000

    def test_nested_key(self):
        assert get_inputs_value(self.INPUTS, "construction.target_sqft") == 4000

    def test_null_value_returns_none(self):
        assert get_inputs_value(self.INPUTS, "construction.cost_per_sqft_mid") is None

    def test_missing_section_returns_none(self):
        assert get_inputs_value(self.INPUTS, "financing.cash_available") is None

    def test_missing_field_returns_none(self):
        assert get_inputs_value(self.INPUTS, "land.nonexistent") is None


class TestGetScenarioRowMapKey:
    def test_single_phase_uses_scenario_id(self):
        scenario = {"id": "full_build", "phases": None}
        assert get_scenario_row_map_key(scenario) == "full_build"

    def test_multi_phase_appends_phase(self):
        scenario = {"id": "phased", "phases": ["phase1", "phase2"]}
        assert get_scenario_row_map_key(scenario, "phase1") == "phased_phase1"
        assert get_scenario_row_map_key(scenario, "phase2") == "phased_phase2"

    def test_no_phase_arg_uses_scenario_id(self):
        scenario = {"id": "phased", "phases": ["phase1", "phase2"]}
        assert get_scenario_row_map_key(scenario) == "phased"


class TestGetTabName:
    PROJECT = {
        "tabs": {"inputs": "BUDGET", "kanban": "KANBAN"},
        "scenarios": [
            {"id": "full_build", "tab": "ONE_SHOT"},
            {"id": "phased", "tab": "MODULAR"},
        ],
    }

    def test_inputs_tab(self):
        assert get_tab_name(self.PROJECT, "inputs") == "BUDGET"

    def test_kanban_tab(self):
        assert get_tab_name(self.PROJECT, "kanban") == "KANBAN"

    def test_scenario_by_id(self):
        assert get_tab_name(self.PROJECT, "full_build") == "ONE_SHOT"
        assert get_tab_name(self.PROJECT, "phased") == "MODULAR"

    def test_unknown_raises_key_error(self):
        with pytest.raises(KeyError):
            get_tab_name(self.PROJECT, "nonexistent")


class TestLoadRowMap:
    RAW = {
        "full_build": {"5": "site_clearing", "6": "site_well", "9": "soft_architect"},
        "phased_phase1": {"5": "p1_item", "10": "p1_other"},
    }

    def test_inverts_to_item_id_keyed(self, tmp_path):
        p = tmp_path / "row_map.json"
        p.write_text(json.dumps(self.RAW))
        result = load_row_map(str(tmp_path))
        assert result["full_build"]["site_clearing"] == 5
        assert result["full_build"]["site_well"] == 6
        assert result["full_build"]["soft_architect"] == 9

    def test_row_values_are_ints(self, tmp_path):
        p = tmp_path / "row_map.json"
        p.write_text(json.dumps(self.RAW))
        result = load_row_map(str(tmp_path))
        for rm_key, mapping in result.items():
            for row in mapping.values():
                assert isinstance(row, int), f"Expected int row in {rm_key}, got {type(row)}"

    def test_all_scenario_keys_present(self, tmp_path):
        p = tmp_path / "row_map.json"
        p.write_text(json.dumps(self.RAW))
        result = load_row_map(str(tmp_path))
        assert set(result.keys()) == {"full_build", "phased_phase1"}


class TestSaveRowMapRoundtrip:
    """
    Verifies the save→load roundtrip is lossless.

    Bug context: save_row_map was previously writing the in-memory inverted format
    {item_id: row_int} directly to disk. load_row_map would then try to invert it
    again, producing {row_int: int(item_id)} which fails on non-numeric item IDs.
    """

    RAW = {
        "full_build": {"5": "site_clearing", "6": "site_well"},
        "phased_phase1": {"5": "p1_item"},
    }

    def test_roundtrip_preserves_data(self, tmp_path):
        p = tmp_path / "row_map.json"
        p.write_text(json.dumps(self.RAW))

        # Load (inverts to {item_id: row_int}), then save back, then load again
        inverted = load_row_map(str(tmp_path))
        save_row_map(str(tmp_path), inverted)
        reloaded = load_row_map(str(tmp_path))

        assert reloaded == inverted

    def test_saved_file_is_in_storage_format(self, tmp_path):
        p = tmp_path / "row_map.json"
        p.write_text(json.dumps(self.RAW))

        inverted = load_row_map(str(tmp_path))
        save_row_map(str(tmp_path), inverted)

        on_disk = json.loads(p.read_text())
        # Storage format: keys are row strings, values are item_id strings
        for rm_key, mapping in on_disk.items():
            for row_str, item_id in mapping.items():
                assert isinstance(row_str, str), "Row key must be a string on disk"
                assert row_str.isdigit(), f"Row key must be numeric, got '{row_str}'"
                assert isinstance(item_id, str), "Item ID must be a string on disk"
