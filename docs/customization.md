# Customization Guide

## Overview

Each project is configured by `projects/<name>/project.json`. This file defines:
- The spreadsheet title
- Tab names
- Input fields (what appears in the BUDGET tab)
- Scenarios (what scenario tabs are created)

You edit `project.json` before running `init_sheet.py`. After initialization, changing the schema requires re-initializing (delete the sheet, clear `config.json`, re-run init).

---

## Renaming the spreadsheet and tabs

```json
{
  "spreadsheet_title": "My Custom Project — Budget",
  "tabs": {
    "inputs": "BUDGET",
    "kanban": "KANBAN"
  }
}
```

Change any of these values to rename the corresponding Google Sheet tab.

---

## Adding or removing input fields

Input fields appear in the BUDGET tab. Each field maps to a JSON key path and a cell in the sheet.

```json
"inputs_sections": [
  {
    "id": "project",
    "label": "PROJECT",
    "fields": [
      {"key": "project.name",    "label": "Project Name",    "type": "text"},
      {"key": "project.address", "label": "Address",         "type": "text"}
    ]
  },
  {
    "id": "budget",
    "label": "BUDGET",
    "fields": [
      {"key": "budget.total",    "label": "Total Budget",    "type": "currency"},
      {"key": "budget.contingency_pct", "label": "Contingency", "type": "percent", "hint": "% of total"}
    ]
  }
]
```

**Field types:**
- `text` — plain text input
- `currency` — formatted as `$#,##0`
- `percent` — formatted as `0.0%`
- `number` — plain number

**Adding a field:** Add it to `project.json`, add the corresponding key to `inputs.json`, then re-init the sheet.

**The `hint` field** (optional) fills column C with a helper note (e.g. "% of total", "sq ft").

---

## Adding a scenario

Scenarios define the budget breakdown tabs. Each scenario gets its own tab.

**Single-phase scenario** (Low/Mid/High columns):
```json
{
  "id": "base_case",
  "label": "Base Case",
  "tab": "BASE_CASE",
  "json_file": "scenario_base_case.json",
  "phases": null
}
```

**Multi-phase scenario** (Phase 1 and Phase 2 columns):
```json
{
  "id": "phased",
  "label": "Phased Build",
  "tab": "PHASED",
  "json_file": "scenario_phased.json",
  "phases": ["phase1", "phase2"]
}
```

After adding a scenario to `project.json`, create the corresponding JSON file (copy a template as a starting point).

---

## Scenario JSON structure

**Single-phase** (`scenario_base_case.json`):
```json
{
  "_meta": { "description": "...", "last_pulled": null, "last_pushed": null },
  "line_items": [
    {
      "section": "Site Work",
      "id": "site_clearing",
      "label": "Land Clearing & Grading",
      "low": 30000,
      "mid": 55000,
      "high": 90000,
      "notes": "Assumes long private drive"
    }
  ]
}
```

**Multi-phase** (`scenario_phased.json`):
```json
{
  "_meta": {
    "description": "...",
    "remobilization_premium_pct": 0.10,
    "phase_gap_notes": "months between phases",
    "last_pulled": null, "last_pushed": null
  },
  "phase1": { "notes": "...", "line_items": [...] },
  "phase2": { "notes": "...", "line_items": [...] }
}
```

**Formula-driven items** (calculated in the sheet, not pushed):
```json
{
  "section": "Soft Costs",
  "id": "soft_architect",
  "label": "Architect",
  "formula": true,
  "low": null, "mid": null, "high": null,
  "notes": "Calculated from BUDGET: architect_pct x construction mid estimate"
}
```

---

## Adding or removing line items (without re-init)

To add a line item to the live sheet without rebuilding:

1. Add the new item to the relevant scenario JSON file
2. Run:
```bash
python scripts/add_item.py --project <name> --scenario <scenario_id> --after <existing_id> --new-id <new_id>
```

To remove:
```bash
python scripts/add_item.py --project <name> --scenario <scenario_id> --remove <item_id>
```

Item IDs are the `"id"` field in the JSON files. Current positions are in `projects/<name>/row_map.json`.

---

## Re-initialization

If you change the schema (add/remove inputs sections, add a scenario, rename tabs), you must re-initialize:

1. Delete the sheet from Google Drive
2. Open `projects/<name>/config.json` and set `"spreadsheet_id": null`
3. Run `python scripts/init_sheet.py --project <name>`

**Warning:** Re-init rebuilds the entire sheet from your local JSON files. Any values you had entered directly in the sheet (that haven't been pulled) will be lost.

---

## Known limitations (v1)

- Financing cost formulas (construction loan interest, origination fees) are hardcoded. Custom financing structures require editing `scripts/formula_engine.py`.
- The contingency section always includes four rows (sitework, construction, owner change, design). Different contingency types require re-init after editing `project.json`.
- Kanban always has 8 columns (ID, Title, Status, Owner, Priority, Blocked By, Notes, Resources). Column count is not configurable.
- Scenario column layout is fixed: single-phase uses A-F, multi-phase uses A-I.
