# AI Operating Context — Gridpilot

This file is for AI assistants operating in this repository. Read it at the start of every session before making any changes.

---

## What This Tool Is

Gridpilot is a Google Sheets manager for AI-assisted project tracking. Local JSON files are the AI-editable data layer. Google Sheets is the live presentation layer. Git records every change.

---

## How the System Works

```
Google Sheets (live view) <-> pull.py / push.py <-> Local JSON (what you edit)
                                                           |
                                                    Git in projects/<name>/
```

- **You edit JSON files.** Never edit the sheet directly.
- **Pull before editing.** Always sync the latest sheet state first.
- **Push after editing.** Your changes go live via push.py.
- **Git commits go to the project's git repo** (`projects/<name>/`), NOT to the gridpilot app repo.

---

## First Thing Every Session

```bash
python scripts/pull.py --project <name>
```

Then read the relevant JSON files before proposing or making changes.

---

## Known Projects

Project-specific metadata (spreadsheet ID, private remote URL) lives in each project's
own `AGENTS.md` inside `projects/<name>/`. Read that file at the start of every session
for a project — it has the full context.

Each project directory is its own git repo. `pull.py` and `push.py` commit
automatically, but do **not** push to the remote. Push manually when you want
to sync the private repo:

```bash
git -C projects/<name> push
```

---

## Connecting to an Existing Sheet

When the user provides a spreadsheet ID, check the project directory to decide
which script to run. Do not ask the user — read the files and decide:

```
projects/<name>/project.json exists?
├── YES → schema is known. Use connect.py to map field/row positions.
│         python scripts/connect.py --project <name> --spreadsheet-id <id>
│
└── NO  → schema is unknown. Use discover.py to read the sheet and generate
          all project files from scratch.
          python scripts/discover.py --project <name> --spreadsheet-id <id>
          Then review the output summary and project.json with the user before
          running pull.py — field types and section groupings may need correction.
```

`connect.py` is also correct when `project.json` exists but `config.json` is
missing or has a null `spreadsheet_id` (e.g. re-connecting after moving machines).

### Overriding tab classification in discover.py

`discover.py` classifies tabs by scanning row 1 headers for "low / mid / high"
(scenario) or "status / priority" (kanban). If a tab's headers are not in row 1,
the heuristic misclassifies it. Override with `--scenario`:

```bash
python scripts/discover.py --project <name> --spreadsheet-id <id> \
  --scenario TAB_NAME --scenario ANOTHER_TAB
```

---

## Files You Will Edit

| File | When to edit |
|---|---|
| `projects/<name>/inputs.json` | Shared variables change |
| `projects/<name>/scenario_*.json` | Line item estimates or notes change |
| `projects/<name>/kanban.json` | Adding or updating project tasks |

**Never edit:**
- `projects/<name>/config.json` — holds the spreadsheet ID
- `projects/<name>/row_map.json` — managed by init/connect/add_item scripts
- `projects/<name>/input_map.json` — managed by init/connect scripts
- `projects/<name>/project.json` — schema config; changes require re-init
- Any file in `scripts/` unless fixing a bug or adding a feature

---

## Making Changes

### Value change (update an estimate, input, or note)

```bash
python scripts/pull.py --project <name>
# edit the relevant JSON file
python scripts/push.py --project <name> --message "what changed and why"
```

### Structural change (add or remove a line item)

```bash
# 1. Edit the JSON to add/remove the item
# 2. For adding:
python scripts/add_item.py --project <name> --scenario <scenario_id> --after <existing_id> --new-id <new_id>
# 3. For removing:
python scripts/add_item.py --project <name> --scenario <scenario_id> --remove <item_id>
```

### Preview without writing

```bash
python scripts/push.py --project <name> --dry-run
```

---

## Kanban Workflow

To **add a task**: add it to `kanban.json` under `"tasks"`, then push.
To **update status or any field**: edit the sheet directly, then pull to sync back.

Each task: `id` (e.g. `"task_01"`), `title`, `status`, `owner`, `priority`, `blocked_by`, `description`, `deliverable`, `resources`.
Valid statuses: `New`, `Active`, `Complete`, `Stopped`.
Valid priorities: `Critical`, `High`, `Medium`, `Low`.

---

## One-Time Scripts

Sometimes a task requires a small migration script. Rules:
- Write it to `scripts/` with a descriptive name
- Run it, verify the result, then **delete it immediately**
- Never commit one-time scripts — they clutter the repo
- Permanent scripts: `auth.py`, `sheets_client.py`, `project_config.py`, `formula_engine.py`, `init_sheet.py`, `connect.py`, `pull.py`, `push.py`, `add_item.py`

If you modify any permanent script, commit it immediately with a descriptive message. Do not let script changes sit uncommitted.

---

## JSON File Structure

### inputs.json

```json
{
  "_meta": { "last_pulled": "...", "last_pushed": null },
  "_last_ai_edit": "May 14, 2026 at 10:00 AM",
  "project": { "name": "My Project", ... },
  "land": { "purchase_price": 185000, ... }
}
```

### scenario JSON (single-phase)

```json
{
  "_meta": { ... },
  "line_items": [
    {
      "section": "Site Work",
      "id": "site_clearing",
      "label": "Land Clearing & Grading",
      "low": 30000, "mid": 55000, "high": 90000,
      "notes": ""
    }
  ]
}
```

Items with `"formula": true` and null low/mid/high are formula-driven in the sheet — do not assign values. Their notes are still pushed.

### kanban.json

```json
{
  "_meta": { "valid_statuses": [...], "valid_priorities": [...] },
  "tasks": [
    {
      "id": "task_01",
      "title": "...",
      "status": "New",
      "owner": "",
      "priority": "High",
      "blocked_by": "",
      "description": "...",
      "deliverable": "...",
      "resources": ""
    }
  ]
}
```

---

## Asking Clarifying Questions

If a change is ambiguous or requires a decision, ask before making it. Project decisions have financial and legal implications. Do not guess.

---

## Re-initialization (rare)

Only if the sheet is deleted or corrupted:
1. Delete the sheet from Google Drive
2. Set `projects/<name>/config.json` → `"spreadsheet_id": null`
3. Run `python scripts/init_sheet.py --project <name>`
