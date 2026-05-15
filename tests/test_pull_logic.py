from pull import parse_num


class TestParseNum:
    def test_integer_string(self):
        assert parse_num("55000") == 55000

    def test_float_truncates_to_int(self):
        assert parse_num("55000.9") == 55000

    def test_currency_formatted(self):
        assert parse_num("$55,000") == 55000

    def test_comma_separated(self):
        assert parse_num("1,200,000") == 1200000

    def test_empty_string_returns_none(self):
        assert parse_num("") is None

    def test_none_returns_none(self):
        assert parse_num(None) is None

    def test_em_dash_returns_none(self):
        # Sheets sometimes puts an em dash for blank formula cells
        assert parse_num("—") is None

    def test_zero(self):
        assert parse_num("0") == 0

    def test_actual_integer(self):
        assert parse_num(30000) == 30000

    def test_non_numeric_string_returns_none(self):
        assert parse_num("n/a") is None

    def test_percentage_string(self):
        # % sign not stripped in parse_num (only $ and , are)
        # 0.075 parses fine; "7.5%" would fail — document the behavior
        assert parse_num("0.075") == 0
        assert parse_num("7.5%") is None
