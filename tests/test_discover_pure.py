"""
Tests for the pure (no I/O) functions in scripts/discover.py.

No Google Sheets API calls and no disk I/O are needed for these tests.
"""
import pytest
from discover import slugify, parse_num, make_unique, guess_type, parse_value


class TestSlugify:
    def test_basic_two_word_label(self):
        assert slugify("Land Clearing") == "land_clearing"

    def test_ampersand_stripped(self):
        assert slugify("Site Work & Grading") == "site_work_grading"

    def test_em_dash_stripped(self):
        # "SUBTOTAL — Structure" should become "subtotal_structure"
        result = slugify("SUBTOTAL — Structure")
        assert result == "subtotal_structure"

    def test_parentheses_stripped(self):
        result = slugify("Framing (Minka-Style Complex Roof)")
        assert "minka" in result
        assert "(" not in result

    def test_already_snake_case_unchanged(self):
        result = slugify("framing_phase_1")
        assert result == "framing_phase_1"

    def test_multiple_spaces_collapsed(self):
        result = slugify("Land   Clearing")
        assert "__" not in result

    def test_leading_trailing_underscores_stripped(self):
        result = slugify(" SUBTOTAL ")
        assert not result.startswith("_")
        assert not result.endswith("_")


class TestMakeUnique:
    def test_no_collision_returns_unchanged(self):
        seen = set()
        result = make_unique("framing", seen)
        assert result == "framing"

    def test_single_collision_appends_2(self):
        seen = {"framing"}
        result = make_unique("framing", seen)
        assert result == "framing_2"

    def test_double_collision_appends_3(self):
        seen = {"framing", "framing_2"}
        result = make_unique("framing", seen)
        assert result == "framing_3"

    def test_adds_result_to_seen(self):
        seen = set()
        result = make_unique("item", seen)
        # make_unique registers the result in seen to prevent future collisions
        assert result in seen


class TestGuessType:
    def test_dollar_sign_is_currency(self):
        assert guess_type("$50,000") == "currency"

    def test_dollar_with_decimal(self):
        assert guess_type("$1,234.56") == "currency"

    def test_percentage_is_percent(self):
        assert guess_type("10%") == "percent"

    def test_large_number_classified_as_currency(self):
        # Values > 100 without $ are still inferred as currency (financial heuristic)
        assert guess_type("50000") == "currency"

    def test_small_integer_is_number(self):
        # Values in [1, 100] range are treated as plain numbers (e.g., sqft rates)
        assert guess_type("30") == "number"

    def test_plain_text_is_text(self):
        assert guess_type("Framing") == "text"

    def test_empty_string_is_text(self):
        assert guess_type("") == "text"

    def test_none_is_text(self):
        assert guess_type(None) == "text"


class TestParseNum:
    """Verify discover.parse_num handles the same formats as pull.parse_num."""

    def test_plain_integer_string(self):
        assert parse_num("50000") == 50000

    def test_currency_formatted(self):
        assert parse_num("$50,000") == 50000

    def test_comma_separated_number(self):
        assert parse_num("1,234,567") == 1234567

    def test_empty_string_returns_none(self):
        assert parse_num("") is None

    def test_none_returns_none(self):
        assert parse_num(None) is None

    def test_em_dash_returns_none(self):
        assert parse_num("—") is None

    def test_en_dash_returns_none(self):
        assert parse_num("–") is None

    def test_actual_integer_passthrough(self):
        assert parse_num(42) == 42

    def test_non_numeric_string_returns_none(self):
        assert parse_num("Framing") is None

    def test_percentage_strips_symbol_returns_raw_number(self):
        # discover.parse_num strips % but does NOT divide by 100 (unlike pull.parse_num)
        result = parse_num("10%")
        assert result == 10


class TestParseValue:
    def test_currency_type_returns_int(self):
        result = parse_value("$50,000", "currency")
        assert result == 50000
        assert isinstance(result, int)

    def test_percent_type_returns_float(self):
        result = parse_value("8%", "percent")
        assert result == pytest.approx(0.08, rel=1e-6)

    def test_number_type_returns_numeric(self):
        result = parse_value("3200", "number")
        assert result == 3200

    def test_text_type_returns_string(self):
        result = parse_value("Example County, MI", "text")
        assert result == "Example County, MI"

    def test_none_input_returns_none(self):
        result = parse_value(None, "currency")
        assert result is None
