# Contributing to Gridpilot

Thanks for your interest in contributing.

## Reporting bugs

Open a GitHub issue with:
- What you ran (the command and flags)
- What you expected to happen
- What actually happened (paste the full error)
- Your Python version and OS

## Suggesting features

Open an issue describing the use case before writing code. This keeps effort aligned with what the project actually needs.

## Submitting a pull request

1. Fork the repo and create a branch from `main`
2. Make your changes — keep them focused on one thing
3. Test manually: run `pull.py` and `push.py` against a real sheet and verify the output
4. Open a PR with a clear description of what changed and why

## What's in scope

- Bug fixes in any script
- New project templates (add to `templates/`)
- Improvements to docs
- New push/pull capabilities that don't break existing row maps

## What's out of scope (for now)

- A GUI or web interface
- Replacing Google Sheets with another backend
- Database storage for project data

## Code style

Plain Python. No frameworks. Match the style of the file you're editing — function names, spacing, and comment conventions are consistent throughout.

## License

By contributing, you agree your changes will be licensed under the [MIT License](LICENSE).
