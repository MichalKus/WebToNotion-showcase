---
trigger: model_decision
description: Read before opening or updating a pull request — required title format, description sections, and pre-merge checklist.
---

# Pull request standards

## Title

Conventional commit format, validated by CI: `type(scope): description`.

```
feat(scraping): implement video scraping service
fix(api): resolve timeout in notion client
docs(readme): update installation instructions
```

## Description

Required sections. Drop a heading only when it is genuinely empty — say "None" rather than
inventing content to fill it.

```markdown
## Summary
What this changes and why, in a few sentences.

## Changes
- `path/to/file.py` — what changed and why.

## Testing
How it was verified. Paste the command and its result:
`pytest tests/unit/test_notion_mapper.py -q` → 14 passed.
State plainly if something was not tested.

## Configuration
New or changed environment variables, and the matching `.env.example` update. "None" if none.

## Breaking changes & migration
What breaks and the steps to adapt. "None" if none.
```

Optional, when they add something: API endpoint changes, error-handling/resilience notes,
docs updated, follow-up work.

## Before requesting review

- [ ] `pyproject.toml` version bumped — **required** if the PR targets `master`.
- [ ] `black --check .` and `isort --check-only .` pass.
- [ ] `flake8 src/ tests/` and `mypy src/` pass (CI does not run these).
- [ ] `pytest` passes locally (CI does not run tests at all).
- [ ] `.env.example` updated if configuration changed.
- [ ] No secrets, tokens, or `.env` content in the diff.

## Writing style

Be specific: "fixed a bug" tells a reviewer nothing — name the failure and the cause.
Emojis are optional; information is not.
