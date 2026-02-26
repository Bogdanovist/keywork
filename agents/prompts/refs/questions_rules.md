# Incorporating Agent Questions

Rules for the plan agent when `{GOAL_DIR}/questions.md` contains answered entries.

## Process

1. Read the `Last incorporated` marker in questions.md. Process only entries with IDs higher than the last incorporated ID that are in the `## Answered` section.

2. For each answered question:

   a. **Find the blocked task**: Locate the task referenced in the question's `Blocked task` field.

   b. **Determine action from Requires field**:

      - **spec-update**:
        - Write the answer into the relevant spec file(s) in `{GOAL_DIR}/specs/`
        - Add a dated note: `<!-- Updated {date}: {brief change} (from Q{NNN}) -->`
        - Change blocked task from `[BLOCKED: needs info — Q{NNN}]` to `[ ]`
        - Update task's acceptance criteria if the answer changes requirements

      - **new-tasks**:
        - Create new task(s) based on the answer
        - Change blocked task to depend on the new task(s)
        - Change blocked task from `[BLOCKED: needs info — Q{NNN}]` to `[ ]`

      - **task-modification**:
        - Update the blocked task's acceptance criteria to reflect the answer
        - If the answer changes the scope significantly, consider splitting into multiple tasks
        - Change status from `[BLOCKED: needs info — Q{NNN}]` to `[ ]`

      - **investigation-task** (human deferred or doesn't know):
        - Create investigation task: `- [ ] T{next_ID}: Investigate: {question title} [skill: {relevant skill}]`
        - Acceptance: answer the question with evidence
        - Blocked task stays `[BLOCKED: needs info — Q{NNN}]` until investigation completes

      - **none**:
        - Answer is clarification only, no changes needed
        - Change blocked task from `[BLOCKED: needs info — Q{NNN}]` to `[ ]`

3. **Update PRD for requirement-changing answers**: If `Requires: new-tasks` or the answer materially changes requirements:

   a. If `{GOAL_DIR}/prd.md` lacks a `## Requirements Evolution` section, append one:
      ```
      ## Requirements Evolution

      <!-- Amendments appended by the plan agent when feedback changes requirements. Do not edit above this section header. -->
      ```

   b. Append an entry:
      ```
      ### Q{NNN}: {question title} ({date})
      - **Type**: agent-question
      - **Change**: {what changed based on the answer}
      - **Rationale**: {from the answer}
      ```

4. **Update the Last incorporated marker** in questions.md: `<!-- Last incorporated: Q{NNN} -->`

5. **Mark incorporated in questions.md**: Each processed entry should already have `[answered -> T{ID} unblocked]` in its title (added by questions agent). Leave this as-is — it signals the entry has been processed.

6. If no new answered entries exist since the last marker, skip questions processing.

## Pruning Resolved Entries

After incorporating answered questions, collapse old entries whose unblocking is complete.

### Resolution criteria

An entry is resolved when ALL of:
1. Its Q-number is at or below the `Last incorporated` marker
2. Its title contains `[answered -> T{ID} unblocked]`
3. The referenced task is marked `[x]` in IMPLEMENTATION.md

### Collapsed format

Replace the full entry with:
```
- [x] Q{NNN}: {original title without [answered ...] suffix} [answered -> T{ID}]
```

### Placement

Move collapsed entries to the bottom of the `## Answered` section. Keep in Q-number order.
