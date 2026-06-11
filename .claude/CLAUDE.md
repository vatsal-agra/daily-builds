# Daily Builds — Routine Instructions

## Git workflow
- **Push directly to `main`** — no feature branches.
- Each day's project goes in a new folder: `YYYY-MM-DD-projectname/`
- The project's own README lives inside that folder.
- **LEDGER.md** is a single shared file at repo root — append to it, never recreate it. Fetch the latest version from `origin/main` before editing.

## Daily build structure
1. Create a new dated folder for the day's project (e.g. `2026-06-12-coolproject/`)
2. All project code, tests, README, etc. go inside that folder
3. Append an entry to the repo-root `LEDGER.md` summarizing what was built
4. Commit and push directly to `main`
