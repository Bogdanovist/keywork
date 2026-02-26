# Incorporating Human Feedback

Rules for the plan agent when `{GOAL_DIR}/feedback.md` contains unprocessed entries.

## Process

1. Read the `Last incorporated` marker in feedback.md's header comment. Process only entries with IDs higher than the last incorporated ID.

2. For each unprocessed entry, determine action from its `Type` field:

   a. **Bug** (type: bug) — implementation doesn't match spec:
      - Create a NEW remediation task: `- [ ] T{next_ID}: Feedback fix: {description} [skill: {same skill as original}]`
      - Acceptance criteria should address observed vs expected behaviour from the feedback
      - Add a dependency on the original task ID
      - Do NOT modify the original `[x]` task

   b. **Spec gap** (type: spec-gap) — spec is incomplete or wrong:
      - Create TWO tasks:
        1. `- [ ] T{next_ID}: Update spec: {description} [skill: {same skill}]` — acceptance: spec file updated
        2. `- [ ] T{next_ID+1}: Implement spec change: {description} [skill: {same skill}]` — depends on the spec update task

   c. **New requirement** (type: new-requirement) — not in PRD or specs:
      - Create tasks as appropriate, following normal sizing and ordering rules
      - Note in task description: "From feedback F{NNN}"

   d. **Observation** (type: observation) — unclear root cause:
      - Read related code and specs to classify as bug, spec gap, or new requirement, then follow the appropriate path above
      - If genuinely ambiguous, create an investigation task: `- [ ] T{next_ID}: Investigate: {description} [skill: {relevant skill}]`

   e. **Blocker resolved** (type: blocker-resolved) — a previously reported external blocker is now cleared:
      - Find all `[BLOCKED: ...]` tasks in IMPLEMENTATION.md whose blocker reason matches the feedback description
      - Change their status from `[BLOCKED: reason]` to `[ ]`
      - Do NOT create new tasks — this type only unblocks existing ones

3. **Amend the PRD for requirement-changing feedback**: For each **spec-gap** or **new-requirement** entry (including observations reclassified as either):

   a. If `{GOAL_DIR}/prd.md` lacks a `## Requirements Evolution` section, append one:
      ```
      ## Requirements Evolution

      <!-- Amendments appended by the plan agent when feedback changes requirements. Do not edit above this section header. -->
      ```

   b. Append an amendment entry:
      ```
      ### F{NNN}: {brief title} ({date})
      - **Type**: spec-gap | new-requirement
      - **Change**: {one-sentence description of what changed}
      - **Rationale**: {from the feedback's Observed/Expected fields}
      ```

   c. Do NOT amend the PRD for **bug**-type or **blocker-resolved**-type feedback — bugs are implementation issues and blocker resolutions are operational, not requirement changes.
   d. Do NOT modify existing prd.md content. Only append to Requirements Evolution.

4. Update the `Last incorporated` marker in feedback.md: `<!-- Last incorporated: F{NNN} -->`

5. Mark each processed entry by adding `[incorporated -> T{ID}]` after its title.

6. If no new entries exist since the last marker, skip feedback processing.

## Pruning Resolved Entries

After incorporating new feedback (or if there are no new entries), collapse old entries whose remediation is complete. This prevents feedback.md from growing without bound.

### Resolution criteria

An entry is resolved and safe to collapse when ALL of:
1. Its F-number is at or below the `Last incorporated` marker
2. Its title contains an incorporation tag (`[incorporated -> T{ID}]` or `[incorporated — T{ID} unblocked]`)
3. Every task referenced in the tag is marked `[x]` in IMPLEMENTATION.md

Special cases:
- **Blocker-resolved** entries: resolved when the unblocked task is `[x]`
- **Missing incorporation tag** (F-number below marker but no tag in title): search IMPLEMENTATION.md for tasks whose description references `F{NNN}`. If all such tasks are `[x]`, the entry is resolved. If no tasks reference it, leave it uncollapsed.
- **Never collapse**: entries above the `Last incorporated` marker, or entries with any linked task still `[ ]` or `[BLOCKED]`

### Collapsed format

Replace the full entry (### header + Type + Related tasks + Observed + Expected + Notes) with a single line:

```
- [x] F{NNN}: {original title without [incorporated ...] suffix} [{type} -> T{IDs}]
```

For blocker-resolved entries: `[blocker-resolved -> T{ID} unblocked]`

### Placement

Move all collapsed entries to a `## Resolved` section at the bottom of feedback.md. Create this section if it does not exist. Keep entries in F-number order. Preserve the file header, `Last incorporated` marker, and any uncollapsed entries above this section.
