# ClaudeVision: rules every session follows

**Two GitHub repositories, kept in sync, always.** Cloud sessions push to `jbgray1874/ClaudeVision`
(`main-2026`). The laptop's `C:\ClaudeVision` pulls from `jbgraysdi2026/ClaudeVision` and runs the
portal branch `claude/app-portal-main-2026`, which merges `main-2026`. A session cannot push to
`jbgraysdi2026`, so after pushing engine work it gives JG the sync commands and the commit to check,
exactly as written in `SDI_Intelligence_HANDOFF_STATE_2.md` §0 ("TWO GITHUB REPOSITORIES"), and never
asks for a rerun until the laptop's check prints "fixes in".
