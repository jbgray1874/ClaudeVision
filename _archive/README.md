# _archive — historical mirror trees

These directories are **superseded copies** kept for reference only. They are
**not** on the active code path and nothing in `src/` imports from them.

| Folder | Was | Notes |
|--------|-----|-------|
| `sql_src/` | `sql/src/` | Whole-tree mirror of the source, full of versioned duplicates (`config_old.py`, `estimator (44).py`, …) |
| `docs_src/` | `docs/src/` | Another whole-tree mirror of the source |
| `src_backup_2026216/` | `src/src_backup_2026216/` | A dated nested backup of `src/` |

The single canonical, actively-maintained source tree is **`src/`** (entry
point `src/main.py`). Every file here has an equivalent (usually newer) version
under `src/`.

Kept rather than deleted at the maintainer's request; safe to remove entirely
later — full history is retained in git regardless.
