"""
Tests for scripts/validate.py — row_map drift detection.

All tests mock validate.read_range so no real Google Sheets API is needed.
"""
import sys
import pytest
from unittest.mock import patch

import validate


def _make_sheet_rows(*labels):
    """Build a fake read_range result: list of ["Section", "Label"] rows."""
    return [["", label] for label in labels]


def _make_items_by_id(**kwargs):
    """Build items_by_id dict: {item_id: {"label": label, ...}}"""
    return {k: {"id": k, "label": v} for k, v in kwargs.items()}


class TestValidateRowMap:
    SID = "fake_spreadsheet_id"
    TAB = "ONE_SHOT"

    def test_all_labels_match_returns_true(self, mock_service, capsys):
        """Perfect match across all rows → True and success message."""
        sheet_rows = _make_sheet_rows("Framing", "Roofing", "HVAC")
        with patch("validate.read_range", return_value=sheet_rows):
            row_map = {"item_framing": 1, "item_roofing": 2, "item_hvac": 3}
            items_by_id = _make_items_by_id(
                item_framing="Framing",
                item_roofing="Roofing",
                item_hvac="HVAC",
            )
            result = validate.validate_row_map(
                mock_service, self.SID, self.TAB, row_map, items_by_id, abort=False
            )
        assert result is True
        captured = capsys.readouterr()
        assert "OK" in captured.out

    def test_label_mismatch_detected(self, mock_service):
        """One wrong label → returns False when abort=False."""
        sheet_rows = _make_sheet_rows("Framing", "SUBTOTAL — Foundation")
        with patch("validate.read_range", return_value=sheet_rows):
            row_map = {"item_framing": 1, "item_roofing": 2}
            items_by_id = _make_items_by_id(
                item_framing="Framing",
                item_roofing="Roofing",  # sheet has wrong label at row 2
            )
            result = validate.validate_row_map(
                mock_service, self.SID, self.TAB, row_map, items_by_id, abort=False
            )
        assert result is False

    def test_abort_true_exits_on_mismatch(self, mock_service):
        """abort=True + mismatch → sys.exit(1)."""
        sheet_rows = _make_sheet_rows("Wrong Label")
        with patch("validate.read_range", return_value=sheet_rows):
            row_map = {"item_framing": 1}
            items_by_id = _make_items_by_id(item_framing="Framing")
            with pytest.raises(SystemExit) as exc_info:
                validate.validate_row_map(
                    mock_service, self.SID, self.TAB, row_map, items_by_id, abort=True
                )
        assert exc_info.value.code == 1

    def test_item_not_in_json_is_skipped(self, mock_service):
        """row_map entry with no matching item in items_by_id → skipped, not a mismatch."""
        sheet_rows = _make_sheet_rows("Framing")
        with patch("validate.read_range", return_value=sheet_rows):
            row_map = {"item_framing": 1, "orphan_id": 1}
            items_by_id = _make_items_by_id(item_framing="Framing")
            # orphan_id is in row_map but not items_by_id — should not cause failure
            result = validate.validate_row_map(
                mock_service, self.SID, self.TAB, row_map, items_by_id, abort=False
            )
        assert result is True

    def test_item_with_no_label_is_skipped(self, mock_service):
        """Item in items_by_id with no 'label' field → skipped."""
        sheet_rows = _make_sheet_rows("Framing")
        with patch("validate.read_range", return_value=sheet_rows):
            row_map = {"item_no_label": 1}
            items_by_id = {"item_no_label": {"id": "item_no_label"}}  # no "label" key
            result = validate.validate_row_map(
                mock_service, self.SID, self.TAB, row_map, items_by_id, abort=False
            )
        assert result is True

    def test_row_beyond_sheet_length_is_mismatch(self, mock_service):
        """Row number beyond the sheet data → treated as empty label → mismatch."""
        sheet_rows = _make_sheet_rows("Framing")  # only 1 row
        with patch("validate.read_range", return_value=sheet_rows):
            row_map = {"item_roofing": 99}  # row 99 doesn't exist
            items_by_id = _make_items_by_id(item_roofing="Roofing")
            result = validate.validate_row_map(
                mock_service, self.SID, self.TAB, row_map, items_by_id, abort=False
            )
        assert result is False

    def test_whitespace_trimmed_before_compare(self, mock_service):
        """Leading/trailing spaces in sheet label are trimmed before comparison."""
        sheet_rows = [["", "  Framing  "]]  # extra spaces
        with patch("validate.read_range", return_value=sheet_rows):
            row_map = {"item_framing": 1}
            items_by_id = _make_items_by_id(item_framing="Framing")
            result = validate.validate_row_map(
                mock_service, self.SID, self.TAB, row_map, items_by_id, abort=False
            )
        assert result is True

    def test_multiple_mismatches_all_reported(self, mock_service, capsys):
        """Three wrong rows → all three appear in the printed output."""
        sheet_rows = _make_sheet_rows("Wrong1", "Wrong2", "Wrong3")
        with patch("validate.read_range", return_value=sheet_rows):
            row_map = {"item_a": 1, "item_b": 2, "item_c": 3}
            items_by_id = _make_items_by_id(item_a="Correct1", item_b="Correct2", item_c="Correct3")
            result = validate.validate_row_map(
                mock_service, self.SID, self.TAB, row_map, items_by_id, abort=False
            )
        assert result is False
        captured = capsys.readouterr()
        # All three mismatches should appear in the diagnostic output
        assert "item_a" in captured.out
        assert "item_b" in captured.out
        assert "item_c" in captured.out

    def test_empty_row_map_returns_true(self, mock_service):
        """Empty row_map → trivially valid."""
        with patch("validate.read_range", return_value=[]):
            result = validate.validate_row_map(
                mock_service, self.SID, self.TAB, {}, {}, abort=False
            )
        assert result is True
