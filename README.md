# Gridpilot

A Google Sheets manager for AI-assisted project tracking. Define your data structure in JSON, let an AI assistant make changes, and push them live to any sheet — with git tracking every edit.

**What it does:**
- Keeps a Google Sheet as the live view of your project data
- Local JSON files are the AI-editable data layer — no Sheets API knowledge required
- `pull` / `push` scripts sync data in both directions
- Git records every pull and push as a timestamped commit
- A Kanban tab tracks project tasks with status, priority, and dependency fields

---

## Quickstart

```bash
git clone https://github.com/zebklein/gridpilot.git
cd gridpilot
pip install -r requirements.txt
```

**Set up Google credentials** (one-time — see [docs/setup.md](docs/setup.md)):
1. Go to [console.cloud.google.com](https://console.cloud.google.com) → create a project
2. Enable **Google Sheets API** and **Google Drive API**
3. Create OAuth 2.0 credentials (Desktop App) → download as `credentials.json` → place in `credentials/`
4. Go to **Google Auth Platform → Audience → Test Users** → add your email

**Create a project from a template:**
```bash
python scripts/init_sheet.py --project myproject --template new-construction
```

A new Google Sheet is created and the URL is printed. Open it to see your project.

**Daily workflow:**
```bash
python scripts/pull.py --project myproject        # sync sheet → local files
# edit projects/myproject/*.json (or ask an AI to)
python scripts/push.py --project myproject --message "what changed"
```

---

## Multiple Projects

Each project is a subdirectory inside `projects/` with its own git history. The `projects/` directory is gitignored from the gridpilot repo — your project data stays separate from the app code.

```bash
python scripts/init_sheet.py --project estate --template new-construction
python scripts/init_sheet.py --project garage --template home-renovation

python scripts/pull.py --project estate
python scripts/push.py --project garage --message "updated flooring estimate"
```

Or connect to an existing sheet instead of creating a new one:
```bash
python scripts/connect.py --project estate --spreadsheet-id 1xF0dAI...
```

---

## Command Reference

| Command | Description |
|---|---|
| `python scripts/init_sheet.py --project <name> --template <tpl>` | Create project from template + new Google Sheet |
| `python scripts/discover.py --project <name> --spreadsheet-id <id>` | Discover and import any existing sheet |
| `python scripts/connect.py --project <name> --spreadsheet-id <id>` | Reconnect a Gridpilot sheet on a new machine |
| `python scripts/pull.py --project <name>` | Sync sheet → local JSON + git commit |
| `python scripts/push.py --project <name>` | Sync local JSON → sheet + git commit |
| `python scripts/push.py --project <name> --dry-run` | Preview changes without writing |
| `python scripts/push.py --project <name> --message "..."` | Push with a custom commit message |
| `python scripts/add_item.py --project <name> --scenario <id> --after <id> --new-id <id>` | Insert a line item |
| `python scripts/add_item.py --project <name> --scenario <id> --remove <id>` | Remove a line item |

---

## Spreadsheet Structure

Gridpilot works with any sheet structure — either by creating one from a template or by connecting to a sheet you already have.

### Using a template

The built-in templates create a sheet with three tab types:

- **Inputs tab** — key-value pairs: shared variables your other tabs reference (rates, targets, flat costs, etc.). Each row is a labeled field. Tab name is configurable.
- **Scenario tabs** — row-per-item tables with Low / Mid / High columns. Supports single-phase and multi-phase layouts. Any number of scenario tabs.
- **Kanban tab** — task tracker with status, priority, owner, and dependency fields. Rows are tasks; status and priority use dropdown validation.

Tab names, field labels, sections, and line items are all defined in `project.json` — rename or restructure anything without touching the scripts.

### Connecting an existing sheet

If you already have a sheet, `discover.py` reads it and generates the project schema automatically:

```bash
python scripts/discover.py --project <name> --spreadsheet-id <id>
```

It classifies each tab by scanning row 1 headers, maps field positions, and writes all project files. Review the output and adjust `project.json` if needed, then use `pull` / `push` normally.

### What Gridpilot does not manage

Formula cells, chart objects, conditional formatting, and merged cells are owned by the sheet — Gridpilot will not overwrite them. It only reads and writes the data cells it has mapped.

---

## Documentation

- [docs/setup.md](docs/setup.md) — Full Google OAuth setup guide
- [docs/customization.md](docs/customization.md) — How to configure project.json, add fields, rename scenarios
- [docs/ai-workflow.md](docs/ai-workflow.md) — How to use an AI assistant with Gridpilot

This project was developed using Claude Sonnet 4.6 for code generation and documentation