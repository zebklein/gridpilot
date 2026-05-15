from push import fmt_currency


class TestFmtCurrency:
    def test_integer_passthrough(self):
        assert fmt_currency(55000) == 55000

    def test_float_truncates(self):
        assert fmt_currency(55000.9) == 55000

    def test_none_returns_empty_string(self):
        assert fmt_currency(None) == ""

    def test_zero(self):
        assert fmt_currency(0) == 0

    def test_large_value(self):
        assert fmt_currency(1_200_000) == 1200000
