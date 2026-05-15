import pytest
from formula_engine import is_formula_item, cell_ref, get_formula


class TestIsFormulaItem:
    def test_formula_flag_true(self):
        item = {"id": "soft_architect", "formula": True, "low": None, "mid": None, "high": None}
        assert is_formula_item(item) is True

    def test_all_null_values_treated_as_formula(self):
        item = {"id": "some_item", "low": None, "mid": None, "high": None}
        assert is_formula_item(item) is True

    def test_has_values_not_formula(self):
        item = {"id": "site_clearing", "low": 30000, "mid": 55000, "high": 90000}
        assert is_formula_item(item) is False

    def test_partial_null_not_formula(self):
        # Mid is set — item has real data even if low/high are missing
        item = {"id": "site_clearing", "low": None, "mid": 55000, "high": None}
        assert is_formula_item(item) is False

    def test_formula_false_key_overrides_values(self):
        item = {"id": "site_clearing", "formula": False, "low": 30000, "mid": 55000, "high": 90000}
        assert is_formula_item(item) is False


class TestCellRef:
    def test_returns_qualified_reference(self):
        assert cell_ref("BUDGET", {"land.purchase_price": "B10"}, "land.purchase_price") == "BUDGET!B10"

    def test_missing_key_returns_none(self):
        assert cell_ref("BUDGET", {}, "land.purchase_price") is None

    def test_different_tab(self):
        assert cell_ref("INPUTS", {"soft_costs.architect_pct": "B32"}, "soft_costs.architect_pct") == "INPUTS!B32"


class TestGetFormula:
    INPUT_MAP = {
        "soft_costs.architect_pct": "B32",
        "soft_costs.engineering_pct": "B33",
        "soft_costs.permits_fees_flat": "B34",
        "soft_costs.survey_geotech_flat": "B35",
        "soft_costs.legal_misc_flat": "B36",
        "financing.construction_loan_ltv": "B22",
    }
    TAB = "BUDGET"
    MID = "(BUDGET!B17*BUDGET!B19)"

    def _formula(self, item_id):
        return get_formula(item_id, self.INPUT_MAP, self.TAB, self.MID)

    def test_unknown_item_returns_none(self):
        assert self._formula("site_clearing") is None

    def test_returns_three_tuple(self):
        result = self._formula("soft_architect")
        assert result is not None
        assert len(result) == 3

    def test_all_formulas_start_with_equals(self):
        for item_id in ("soft_architect", "soft_engineering", "soft_permits",
                        "soft_survey_geotech", "soft_legal", "soft_loan_fees"):
            result = self._formula(item_id)
            assert result is not None, f"Expected formula for {item_id}"
            for formula in result:
                assert formula.startswith("="), f"{item_id} formula missing '=': {formula}"

    def test_flat_cost_low_mid_high_equal(self):
        # Flat costs (permits, survey, legal) are the same across all three bands
        for item_id in ("soft_permits", "soft_survey_geotech", "soft_legal"):
            low, mid, high = self._formula(item_id)
            assert low == mid == high

    def test_percent_cost_low_less_than_mid(self):
        low, mid, high = self._formula("soft_architect")
        # Low formula has *0.6 multiplier, high has *1.4 — verify they differ
        assert low != mid
        assert mid != high
        assert "0.6" in low
        assert "1.4" in high

    def test_missing_input_map_key_returns_none(self):
        result = get_formula("soft_architect", {}, self.TAB, self.MID)
        assert result is None

    def test_loan_fees_p2_same_as_p1(self):
        p1 = self._formula("soft_loan_fees")
        p2 = self._formula("soft_loan_fees_p2")
        assert p1 == p2
