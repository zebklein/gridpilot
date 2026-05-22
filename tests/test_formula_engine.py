import pytest
from formula_engine import (
    is_formula_item, cell_ref, get_formula,
    resolve_formula_expr, get_formula_expr_updates,
)


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


class TestResolveFormulaExpr:
    INPUT_MAP = {
        "construction.sqft_phase1": "B66",
        "construction.sqft_phase2": "B67",
        "construction.rate_framing_low": "B72",
        "construction.rate_framing_mid": "C72",
        "construction.rate_framing_high": "D72",
        "borrower.gross_annual_income": "CAPITAL!B4",
    }
    TAB = "BUDGET"

    def _resolve(self, expr):
        return resolve_formula_expr(expr, self.INPUT_MAP, self.TAB)

    def test_single_placeholder_resolves(self):
        result = self._resolve("{construction.sqft_phase1}")
        assert result == "=BUDGET!B66"

    def test_multiple_placeholders_all_resolved(self):
        result = self._resolve(
            "{construction.sqft_phase1} * {construction.rate_framing_low}"
        )
        # Whitespace from the template is preserved; both refs must appear
        assert result is not None
        assert "BUDGET!B66" in result
        assert "BUDGET!B72" in result
        assert result.startswith("=")

    def test_missing_key_returns_none(self):
        result = self._resolve("{construction.unknown_key}")
        assert result is None

    def test_already_qualified_addr_not_double_tagged(self):
        # "CAPITAL!B4" already has a "!" — should NOT become "BUDGET!CAPITAL!B4"
        result = self._resolve("{borrower.gross_annual_income}")
        assert result == "=CAPITAL!B4"
        assert "BUDGET!CAPITAL" not in result

    def test_empty_expr_returns_equals_sign(self):
        result = self._resolve("")
        assert result == "="

    def test_result_starts_with_equals(self):
        result = self._resolve("{construction.sqft_phase1}")
        assert result is not None
        assert result.startswith("=")


class TestGetFormulaExprUpdates:
    INPUT_MAP = {
        "construction.sqft_phase1": "B66",
        "construction.sqft_phase2": "B67",
        "construction.rate_framing_low": "B72",
        "construction.rate_framing_mid": "C72",
        "construction.rate_framing_high": "D72",
    }
    TAB = "MODULAR"
    INP_TAB = "BUDGET"

    def _updates(self, item, row=46):
        return get_formula_expr_updates(item, row, self.TAB, self.INPUT_MAP, self.INP_TAB)

    def test_no_formula_expr_returns_empty(self):
        item = {"id": "some_item", "formula": True, "low": None, "mid": None, "high": None}
        assert self._updates(item) == []

    def test_p1_only_returns_three_updates(self):
        item = {
            "id": "structure_framing_phase_1",
            "formula": True,
            "formula_expr": {
                "low":  "{construction.sqft_phase1} * {construction.rate_framing_low}",
                "mid":  "{construction.sqft_phase1} * {construction.rate_framing_mid}",
                "high": "{construction.sqft_phase1} * {construction.rate_framing_high}",
            },
        }
        updates = self._updates(item, row=46)
        assert len(updates) == 3
        ranges = {u["range"] for u in updates}
        assert "MODULAR!C46" in ranges
        assert "MODULAR!D46" in ranges
        assert "MODULAR!E46" in ranges

    def test_p1_and_p2_returns_six_updates(self, sample_formula_expr_item):
        updates = self._updates(sample_formula_expr_item, row=46)
        assert len(updates) == 6
        ranges = {u["range"] for u in updates}
        for col in "CDEFGH":
            assert f"MODULAR!{col}46" in ranges

    def test_all_values_are_formula_strings(self, sample_formula_expr_item):
        updates = self._updates(sample_formula_expr_item, row=46)
        for u in updates:
            val = u["values"][0][0]
            assert val.startswith("="), f"Expected formula string, got: {val}"

    def test_missing_key_warns_and_skips(self, capsys):
        item = {
            "id": "bad_item",
            "formula": True,
            "formula_expr": {
                "low": "{construction.sqft_phase1} * {construction.rate_nonexistent}",
            },
        }
        updates = self._updates(item, row=10)
        assert len(updates) == 0
        captured = capsys.readouterr()
        assert "WARNING" in captured.out
