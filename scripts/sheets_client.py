from googleapiclient.discovery import build
from auth import get_credentials


def get_service():
    creds = get_credentials()
    return build("sheets", "v4", credentials=creds)


def read_range(service, spreadsheet_id, range_notation):
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=range_notation)
        .execute()
    )
    return result.get("values", [])


def write_range(service, spreadsheet_id, range_notation, values):
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=range_notation,
        valueInputOption="USER_ENTERED",
        body={"values": values},
    ).execute()


def batch_write(service, spreadsheet_id, data):
    """data: list of {"range": "A1 notation", "values": [[...]]}"""
    service.spreadsheets().values().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"valueInputOption": "USER_ENTERED", "data": data},
    ).execute()


def batch_format(service, spreadsheet_id, requests):
    """requests: list of Sheets API format request dicts"""
    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": requests},
    ).execute()


def get_sheet_id(service, spreadsheet_id, sheet_name):
    meta = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    for sheet in meta["sheets"]:
        if sheet["properties"]["title"] == sheet_name:
            return sheet["properties"]["sheetId"]
    raise ValueError(f"Sheet '{sheet_name}' not found in spreadsheet")


def create_spreadsheet(service, title):
    """Creates a spreadsheet with INPUTS as the first sheet.
    Returns (spreadsheet_id, inputs_sheet_id)."""
    body = {
        "properties": {"title": title},
        "sheets": [{"properties": {"title": "BUDGET"}}],
    }
    result = service.spreadsheets().create(body=body).execute()
    spreadsheet_id = result["spreadsheetId"]
    first_sheet_id = result["sheets"][0]["properties"]["sheetId"]
    return spreadsheet_id, first_sheet_id
