# Gridpilot

A Google Sheets budget manager designed for AI-assisted project tracking. Define your budget in JSON, let an AI assistant make changes, and push them live to a Google Sheet — with git tracking every edit.

**What it does:**
- Maintains a Google Sheet as a live budget dashboard (auto-calculating subtotals, contingency, financing)
- Local JSON files are the AI-editable data layer — no Sheets API knowledge required
- `pull` / `push` scripts sync data in both directions
- Git records every pull and push as a timestamped commit
- A Kanban tab tracks project tasks with status, priority, and dependency fields

**Who it's for:** Homebuilders, contractors, renovation project managers, or anyone managing a multi-line budget who wants to keep an AI in the loop.

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

A new Google Sheet is created and the URL is printed. Open it to see your budget.

**Daily workflow:**
```bash
python scripts/pull.py --project myproject        # sync sheet → local files
# edit projects/myproject/*.json (or ask an AI to)
python scripts/push.py --project myproject --message "what changed"
```

---

## Multiple Projects

Each project is a subdirectory inside `projects/` with its own git history. The `projects/` directory is gitignored from the gridpilot repo — your budget data stays separate from the app code.

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

Each project creates a Google Sheet with:
- **BUDGET** — shared inputs (land price, sq footage, rates, etc.) + scenario comparison summary
- **Scenario tabs** — Low/Mid/High estimates per line item, with auto-calculated subtotals, contingency, and financing
- **KANBAN** — project task tracker with status/priority dropdowns and color coding

Yellow cells = editable inputs. Grey = formula cells (do not overwrite). Dark rows = totals.

---

## Documentation

- [docs/setup.md](docs/setup.md) — Full Google OAuth setup guide
- [docs/customization.md](docs/customization.md) — How to configure project.json, add fields, rename scenarios
- [docs/ai-workflow.md](docs/ai-workflow.md) — How to use an AI assistant with Gridpilot

This project was developed using Claude Sonnet 4.6 for code generation and documentation