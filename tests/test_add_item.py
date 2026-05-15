import pytest
from add_item import shift_row_map, find_scenario


class TestShiftRowMap:
    """
    shift_row_map works on the inverted in-memory format: {item_id: row_int}.
    It shifts all rows >= from_row_1idx by delta.
    """

    def _make_rm(self):
        return {
            "full_build": {"site_clearing": 5, "site_well": 6, "soft_architect": 9},
        }

    def test_shifts_rows_at_threshold(self):
        rm = self._make_rm()
        shift_row_map(rm, "full_build", from_row_1idx=6, delta=+1)
        assert rm["full_build"]["site_well"] == 7      # was 6, at threshold
        assert rm["full_build"]["soft_architect"] == 10  # was 9, above threshold

    def test_does_not_shift_rows_below_threshold(self):
        rm = self._make_rm()
        shift_row_map(rm, "full_build", from_row_1idx=6, delta=+1)
        assert rm["full_build"]["site_clearing"] == 5   # was 5, below threshold

    def test_negative_delta_on_delete(self):
        rm = self._make_rm()
        shift_row_map(rm, "full_build", from_row_1idx=7, delta=-1)
        assert rm["full_build"]["site_clearing"] == 5   # below threshold, unchanged
        assert rm["full_build"]["site_well"] == 6       # below threshold (6 < 7), unchanged
        assert rm["full_build"]["soft_architect"] == 8  # was 9, shifted down

    def test_empty_map_is_safe(self):
        rm = {"full_build": {}}
        shift_row_map(rm, "full_build", from_row_1idx=5, delta=+1)
        assert rm["full_build"] == {}

    def test_only_named_key_is_shifted(self):
        rm = {
            "full_build": {"item_a": 5},
            "phased_phase1": {"item_b": 5},
        }
        shift_row_map(rm, "full_build", from_row_1idx=5, delta=+1)
        assert rm["full_build"]["item_a"] == 6       # shifted
        assert rm["phased_phase1"]["item_b"] == 5    # untouched

    def test_insert_then_verify_ordering(self):
        # Simulates inserting a new row after site_clearing (row 5):
        # rows 6+ shift up, then new item assigned to row 6
        rm = self._make_rm()
        after_row = rm["full_build"]["site_clearing"]  # 5
        new_row = after_row + 1                         # 6
        shift_row_map(rm, "full_build", from_row_1idx=new_row, delta=+1)
        rm["full_build"]["new_item"] = new_row

        assert rm["full_build"]["site_clearing"] == 5
        assert rm["full_build"]["new_item"] == 6
        assert rm["full_build"]["site_well"] == 7       # was 6, pushed to 7
        assert rm["full_build"]["soft_architect"] == 10  # was 9, pushed to 10


class TestFindScenario:
    SCENARIOS = [
        {"id": "full_build", "tab": "ONE_SHOT"},
        {"id": "phased", "tab": "MODULAR"},
    ]
    PROJECT = {"scenarios": SCENARIOS}

    def test_finds_by_id(self):
        result = find_scenario(self.PROJECT, "full_build")
        assert result["tab"] == "ONE_SHOT"

    def test_finds_second_scenario(self):
        result = find_scenario(self.PROJECT, "phased")
        assert result["tab"] == "MODULAR"

    def test_returns_none_when_missing(self):
        result = find_scenario(self.PROJECT, "nonexistent")
        assert result is None

    def test_empty_scenarios_list(self):
        assert find_scenario({"scenarios": []}, "full_build") is None
