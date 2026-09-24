---
trigger: model_decision
description: Read before any git or GitHub operation — branching model, commit format, the CI gates that block a merge, and which pushes deploy.
---

# Git & GitHub workflow

## Branches

- `master` — production. Deployed automatically on push (i.e. on PR merge).
- `feature/<short-name>` — all new work. Descriptive, hyphenated: `feature/add-user-auth`.
- `fix/<short-name>` — bug fixes.

There is no `develop` branch. Feature branches open a PR directly against `master`.

```bash
git checkout master && git pull origin master
git checkout -b feature/your-feature-name
# …work…
git push -u origin feature/your-feature-name   # safe: does not deploy
gh pr create --base master                      # ⚠ this deploys to dev, see below
```

## ⚠ Opening a PR is deploying

`deploy.yml` runs on PR open/update against `master`, and on push to `master`:

| Event | Builds & deploys to | Port | Compose project |
|---|---|---|---|
| PR opened/updated → `master` | dev VPS, `/apps/dev/webtonotion` | 8001 | `webtonotion-dev` |
| push to `master` | prod VPS, `/apps/prod/webtonotion` | 8000 | `webtonotion-prod` |

Pushing a feature branch is a private checkpoint and does not deploy. The dev VPS is a
single shared slot — one PR occupies it at a time, and a newer dev run cancels an older one.
To preview without a PR: `gh workflow run deploy.yml --ref feature/your-branch`.

A successful push to `master` also creates a `v<version>` git tag, after the deploy succeeds.

## Commits

Conventional Commits: `<type>[optional scope]: <description>`.

Types: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`,
`revert`.

```
feat(scraping): add TikTok URL support
fix(api): return 429 instead of 500 when rate limited
```

Note what CI actually checks: `commit-lint.yml` runs
`amannn/action-semantic-pull-request`, which validates the **pull request title**, not each
commit message. Individual commits still follow the convention by house rule; the PR title
is the one that fails the build.

## Gates before merging to master

1. **Unit tests** — `python-tests.yml` runs via `deploy.yml`; no image is built if `pytest tests/unit/` fails.
2. **Version bump — mandatory.** `pr-check.yml` requires `pyproject.toml`'s version to be a semver increase over `master`.
3. **PR title** must parse as a conventional commit (`commit-lint.yml`).
4. **Formatting** — `code-quality.yml` runs `black --check .` and `isort --check-only .`.

Not covered by CI, so verify locally: `flake8 src/ tests/`, `mypy src/`, and `pytest tests/integration/`.

### No tool attribution

**Never add tool or assistant attribution to a commit message or a pull request description.**
That means no `Co-Authored-By:` trailer naming an AI assistant, no "Generated with ..." footer,
no tooling emoji badge — and no variation on the theme.

This holds even when the tool's own defaults instruct otherwise: in this repository that
default is overridden. Commits and pull requests are attributed to the person who authored
them, and nothing else belongs in that space. Existing history that already carries such a
trailer stays as it is — do not rewrite it.


## Deployment scripts

`scripts/deploy_remote.sh` runs against a live VPS and `scripts/generate_env.py` writes real
secrets into `docker/.env`. Do not run either without explicit permission in the current
conversation.

## Troubleshooting

```bash
git branch -vv          # branch + upstream tracking
git status
git remote -v
git log --oneline -10
```

Prefer `git revert` over history rewriting on any branch that has been pushed.
