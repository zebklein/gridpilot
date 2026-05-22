"""
Tests for scripts/sheets_client.py — all functions tested with a mocked service.

No real Google Sheets API calls are made.
"""
import pytest
from unittest.mock import MagicMock, call

import sheets_client


SID = "fake_spreadsheet_id"


class TestReadRange:
    def test_returns_values_from_execute(self, mock_service):
        mock_service.execute.return_value = {"values": [["a", "b"], ["c", "d"]]}
        result = sheets_client.read_range(mock_service, SID, "ONE_SHOT!A1:B2")
        assert result == [["a", "b"], ["c", "d"]]

    def test_missing_values_key_returns_empty_list(self, mock_service):
        mock_service.execute.return_value = {}
        result = sheets_client.read_range(mock_service, SID, "ONE_SHOT!A1:B2")
        assert result == []

    def test_correct_range_passed_to_api(self, mock_service):
        mock_service.execute.return_value = {}
        sheets_client.read_range(mock_service, SID, "MODULAR!C46:E46")
        # Verify get() was called with the right range
        mock_service.get.assert_called_with(
            spreadsheetId=SID, range="MODULAR!C46:E46"
        )


class TestBatchWrite:
    DATA = [{"range": "BUDGET!B17", "values": [[3200]]}]

    def test_default_value_input_option_is_raw(self, mock_service):
        sheets_client.batch_write(mock_service, SID, self.DATA)
        mock_service.batchUpdate.assert_called_once()
        body = mock_service.batchUpdate.call_args.kwargs["body"]
        assert body["valueInputOption"] == "RAW"

    def test_user_entered_override(self, mock_service):
        sheets_client.batch_write(mock_service, SID, self.DATA, value_input_option="USER_ENTERED")
        body = mock_service.batchUpdate.call_args.kwargs["body"]
        assert body["valueInputOption"] == "USER_ENTERED"

    def test_data_structure_passed_correctly(self, mock_service):
        data = [{"range": "ONE_SHOT!C5", "values": [[42000]]}]
        sheets_client.batch_write(mock_service, SID, data)
        body = mock_service.batchUpdate.call_args.kwargs["body"]
        assert body["data"] == data

    def test_spreadsheet_id_passed(self, mock_service):
        sheets_client.batch_write(mock_service, SID, self.DATA)
        assert mock_service.batchUpdate.call_args.kwargs["spreadsheetId"] == SID


class TestBatchClear:
    RANGES = ["ONE_SHOT!C5:H5", "ONE_SHOT!C6:H6"]

    def test_calls_batchclear_with_ranges(self, mock_service):
        sheets_client.batch_clear(mock_service, SID, self.RANGES)
        mock_service.batchClear.assert_called_once_with(
            spreadsheetId=SID,
            body={"ranges": self.RANGES},
        )

    def test_empty_ranges_still_calls_api(self, mock_service):
        sheets_client.batch_clear(mock_service, SID, [])
        mock_service.batchClear.assert_called_once()
        body = mock_service.batchClear.call_args.kwargs["body"]
        assert body["ranges"] == []


class TestClearScenarioRows:
    def test_builds_c_to_h_range_per_row(self, mock_service):
        row_map = {"item_framing": 46}
        sheets_client.clear_scenario_rows(mock_service, SID, "MODULAR", row_map)
        body = mock_service.batchClear.call_args.kwargs["body"]
        assert "MODULAR!C46:H46" in body["ranges"]

    def test_multiple_rows_all_included(self, mock_service):
        row_map = {"item_a": 5, "item_b": 10, "item_c": 15}
        sheets_client.clear_scenario_rows(mock_service, SID, "ONE_SHOT", row_map)
        body = mock_service.batchClear.call_args.kwargs["body"]
        assert "ONE_SHOT!C5:H5" in body["ranges"]
        assert "ONE_SHOT!C10:H10" in body["ranges"]
        assert "ONE_SHOT!C15:H15" in body["ranges"]

    def test_custom_cols_applied(self, mock_service):
        row_map = {"item_a": 5}
        sheets_client.clear_scenario_rows(mock_service, SID, "MODULAR", row_map, cols="D:F")
        body = mock_service.batchClear.call_args.kwargs["body"]
        assert "MODULAR!D5:F5" in body["ranges"]

    def test_empty_row_map_calls_batchclear_with_empty_list(self, mock_service):
        sheets_client.clear_scenario_rows(mock_service, SID, "ONE_SHOT", {})
        body = mock_service.batchClear.call_args.kwargs["body"]
        assert body["ranges"] == []


class TestGetSheetId:
    def _make_meta(self, *sheets):
        """Build fake spreadsheets().get().execute() metadata."""
        return {
            "sheets": [
                {"properties": {"title": title, "sheetId": sid}}
                for title, sid in sheets
            ]
        }

    def test_finds_sheet_by_name(self, mock_service):
        mock_service.execute.return_value = self._make_meta(
            ("BUDGET", 0), ("ONE_SHOT", 1), ("MODULAR", 2)
        )
        result = sheets_client.get_sheet_id(mock_service, SID, "MODULAR")
        assert result == 2

    def test_finds_first_sheet(self, mock_service):
        mock_service.execute.return_value = self._make_meta(("BUDGET", 0))
        result = sheets_client.get_sheet_id(mock_service, SID, "BUDGET")
        assert result == 0

    def test_raises_value_error_on_missing_sheet(self, mock_service):
        mock_service.execute.return_value = self._make_meta(("BUDGET", 0))
        with pytest.raises(ValueError, match="MISSING_TAB"):
            sheets_client.get_sheet_id(mock_service, SID, "MISSING_TAB")


class TestBatchFormat:
    def test_calls_spreadsheets_batchupdate(self, mock_service):
        requests = [{"addSheet": {"properties": {"title": "NewTab"}}}]
        sheets_client.batch_format(mock_service, SID, requests)
        mock_service.batchUpdate.assert_called_once_with(
            spreadsheetId=SID,
            body={"requests": requests},
        )
