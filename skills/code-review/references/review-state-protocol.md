# Live PR review-state protocol

Use one state model for authors, reviewers, and dispatchers.

## Sources

Query all three channels:

1. PR metadata for live head and state;
2. formal pull-request reviews for verdicts;
3. issue comments for author handbacks and finding dispositions.

Never infer a formal verdict from an issue comment or local task state.

## Current-head verdict

Filter reviews to the reviewer identity and exact live head. Prefer the
hosting service's review commit ID; require a full pinned SHA in the body when
project policy also demands it. Ignore dismissed reviews.

Sort by server timestamp, then stable review ID. The latest current-head
review governs. Thus a later `CHANGES_REQUESTED` supersedes an earlier
`APPROVED` on the same head.

## State transitions

- Latest current-head `CHANGES_REQUESTED`: author addresses that review.
- Latest current-head `APPROVED`: wait for human merge.
- No current-head verdict plus exact-head author handback: reviewer reviews.
- New author head: prior-head verdict is historical; require a new exact-head
  handback before review.

Repeated dispatch with unchanged inputs is idempotent: return the same state
without creating a new task, publishing duplicate comments, or implying
progress.

## Publication gate

Publish only through `scripts/publish_review.py`. It binds the formal review,
optional inline comments, and mandatory marked PR summary to one exact head.

After publishing, re-query formal reviews and issue comments. Require reviewer,
head, state, timestamp, review ID, summary marker, and summary comment ID to
match. Do not report `AWAITING_AUTHOR_FIXES` or `READY_FOR_HUMAN_MERGE` until
this proof succeeds.

Review publication never authorizes a repository edit or merge. A proposed
process improvement remains comment text until a separate development task is
authorized.
