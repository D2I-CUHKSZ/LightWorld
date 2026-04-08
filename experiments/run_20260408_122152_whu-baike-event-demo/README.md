# Public Experiment Snapshot

This directory is a sanitized snapshot of the full run `run_20260408_122152_whu-baike-event-demo`.

Included:
- Consolidated full-run artifacts from `backend/uploads/full_runs/...`
- Selected simulation outputs from `output/simulations/sim_91e21a6aade3`
- Selected report outputs from `output/reports/report_0b00682ac0c9`

Excluded:
- Local secret files such as `.env` and `backend/app/setting/settings_local.py`
- SQLite databases and other large local runtime state
- Local-only workspace paths and symlinks
- Upload/cache directories that are only meaningful on the original machine

Notes:
- Absolute local paths were rewritten or omitted for GitHub publication.
- This snapshot is intended for inspection and reproducibility review, not as a drop-in runtime workspace.
