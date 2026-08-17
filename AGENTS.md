# AGENTS.md

Entry point for coding agents working in this repository.

1. Read [CLAUDE.md](CLAUDE.md) first — commands, architecture, code patterns, boundaries.
2. Read the rule file for the area you are touching, in [.agents/rules/](.agents/rules/):
   - `00-project.md` — repo identity, stack, MCP defaults (start here).
   - `python-fastapi.md` — anything under `src/webtonotion/` or `tests/`.
   - `pydantic-ai.md` — anything under `src/webtonotion/services/analysis/`.
   - `git-workflow.md` — before any git or GitHub operation.
   - `pull-requests.md` — before opening a PR.

Antigravity loads `.agents/rules/` as workspace rules automatically. Claude Code loads
`CLAUDE.md` automatically and reads the rule files on demand.

Update the rule files when guidance changes; keep this file a pointer.
