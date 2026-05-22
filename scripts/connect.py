"""
Connect Gridpilot to an existing spreadsheet.

Writes config.json with the spreadsheet ID and URL so that pull.py and
push.py can authenticate. Row and input mappings are derived automatically
on every pull/push — no separate discovery step is needed.

Usage:
    python scripts/connect.py --project <name> --spreadsheet-id <id>
"""
import os
import sys
import json
import argparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))
from sheets_client import get_service
from project_config import get_project_dir, load_project


def main():
    parser = argparse.ArgumentParser(description="Connect Gridpilot to an existing spreadsheet")
    parser.add_argument("--project", required=True, help="Project name (subdirectory of projects/)")
    parser.add_argument("--spreadsheet-id", required=True, help="Google Sheets spreadsheet ID")
    args = parser.parse_args()

    project_dir = get_project_dir(args.project)
    load_project(project_dir)  # validates project.json exists

    spreadsheet_id = args.spreadsheet_id
    url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"

    print("Authenticating with Google...")
    get_service()  # validates credentials work

    config_path = os.path.join(project_dir, "config.json")
    config = {}
    if os.path.exists(config_path):
        with open(config_path) as f:
            config = json.load(f)

    if config.get("spreadsheet_id") and config["spreadsheet_id"] != spreadsheet_id:
        print(f"WARNING: replacing existing spreadsheet_id:")
        print(f"  Old: {config['spreadsheet_id']}")
        print(f"  New: {spreadsheet_id}")

    config["spreadsheet_id"] = spreadsheet_id
    config["spreadsheet_url"] = url
    config["connected_at"] = datetime.now().isoformat()
    config.setdefault("discovered", False)

    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)

    print(f"\nConnected. Row positions will be discovered automatically on first pull.")
    print(f"Next step: python scripts/pull.py --project {args.project}")
    print(f"Sheet URL: {url}")


if __name__ == "__main__":
    main()
