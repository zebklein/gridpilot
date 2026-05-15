# AI Workflow Guide

Gridpilot is designed for AI-assisted editing. This guide covers how to work with an AI assistant (like Claude) to make changes to your budget.

---

## The golden rule

**Pull before editing. Push after editing.**

The sheet is the source of truth for anyone viewing the budget. The local JSON files are what the AI edits. Always sync them first.

```bash
python scripts/pull.py --project <name>    # get current sheet state
# AI makes changes to JSON files
python scripts/push.py --project <name> --message "what changed and why"
```

---

## How AI assistants should start each session

1. Read `CLAUDE.md` in the gridpilot repo root
2. Run `pull.py` to get the current sheet state
3. Read the relevant JSON files before proposing changes
4. Make changes to JSON files only — never to scripts or configs
5. Run `push.py` with a descriptive commit message

---

## What to tell the AI

**Update an estimate:**
> "Update the foundation mid estimate to $95,000 and push."

> "The GC quoted $280k for framing. Update the framing mid estimate in the full build scenario."

**Add a line item:**
> "Add a new line item called 'Retaining Walls' to Site Work in the full build scenario, after 'Drainage'. Estimates: $15k low, $28k mid, $50k high."

**Remove a line item:**
> "Remove the gym line item from both scenarios."

**Update inputs:**
> "Update the land purchase price to $185,000 and push."

**Add a kanban task:**
> "Add a task: 'Interview 3 septic designers', priority High, blocked by task_02."

**Sync status from the sheet:**
> "Pull the latest kanban status from the sheet."

---

## What the AI should NOT do

- Edit Python scripts (`scripts/*.py`) — unless fixing a bug or adding a feature
- Run `init_sheet.py` without explicit instruction — it rebuilds the entire sheet
- Guess at project decisions that have financial or legal implications — ask first
- Commit changes to the gridpilot app repo — only commit to the project's own repo inside `projects/<name>/`

---

## Files the AI will edit

| File | When |
|---|---|
| `projects/<name>/inputs.json` | Shared variables change: land price, sq footage, rates, etc. |
| `projects/<name>/scenario_*.json` | Line item estimates or notes change |
| `projects/<name>/kanban.json` | Adding or updating project tasks |
| `project-context.md` (if present) | Project decisions are made, open questions answered |

---

## Kanban workflow

**To add a task:** Add it to `kanban.json` under `"tasks"`, then push.

**To update status:** Edit the sheet directly (use the dropdown), then pull to sync back.

Each task requires: `id` (e.g. `"task_01"`), `title`, `status`, `owner`, `priority`, `blocked_by`, `notes`.

Valid statuses: `New`, `Active`, `Complete`, `Stopped`
Valid priorities: `Critical`, `High`, `Medium`, `Low`

---

## Example prompts that work well

```
Pull the current state, then update the sitework mid estimate to $120,000 and push with message "updated sitework after contractor walkthrough".
```

```
I've decided to go with a conditioned crawlspace. Remove the 'slab' foundation item from the full build scenario and update the crawlspace estimate to: low $55k, mid $80k, high $120k. Then push.
```

```
Add a new task to the kanban: 'Get 3 architect quotes', priority High, blocked by task_01. Notes: 'Prioritize SE Michigan experience with custom residential.'
```

---

## One-time scripts

Sometimes a task requires a small migration script. The convention:

- Write it to `scripts/` with a descriptive name
- Run it, verify the result, then **delete it immediately**
- Never commit one-time scripts to the gridpilot repo

If you modify any of the permanent scripts, commit those changes with a descriptive message. Do not let script changes sit uncommitted.
