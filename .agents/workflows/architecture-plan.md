---
description: Produce an architectural plan and task breakdown for a new feature in this repository.
---

# Workflow: architecture plan

Act as the architectural conscience of this project: favour DRY, KISS, YAGNI, separation of
concerns, and single responsibility. Prefer extending an existing service over adding a new
one.

**Input:** a feature description from the user.

## Steps

1. **Understand the ground.** Read `CLAUDE.md` and the relevant modules under
   `src/webtonotion/`. Check `docs/` for how the area works today, and `.workbench/plans/`
   for an existing plan covering it. Identify
   which layer the feature belongs to: `api/`, `services/extraction|analysis|storage/`,
   `models/`, or `config/`.
2. **Impact analysis.** List the modules that change, whether this extends an existing
   service or needs a new one, and any change to the request flow in `api/process.py`, to
   `VideoContent`, or to the Notion payload contract.
3. **Design.** Describe the approach, with a Mermaid diagram when the flow is non-obvious.
   Specify new/changed Pydantic models, endpoint signatures, and settings. Note the
   observability, rate-limiting, and secret-handling implications.
4. **Task breakdown.** Group as Backend / Tests / Docs / DevOps. One clear deliverable per
   task, with dependencies marked. Omit groups that do not apply — this project has no
   frontend and no database.
5. **Risks and open questions.** State what could go wrong and what you need decided.

## Output

Save the plan as `.workbench/plans/<YYYY-MM-DD>-<feature-name>.md` using this structure.
Plans are working artifacts and stay out of `docs/`, which documents shipped behaviour:

    ### Architectural Plan: <Feature>
    1. Summary & goal
    2. Impact & integration strategy
    3. Proposed design (high-level, components, models, endpoints, non-functional)
    4. Task breakdown (Backend / Tests / Docs / DevOps, as `[ ]` items)
    5. Risks & open questions

Then tell the user where it was saved. Do not start implementing until they approve it.
