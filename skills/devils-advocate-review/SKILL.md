---
name: devils-advocate-review
description: Perform the complete basic and hard reviews while presuming every developer claim, handback, test conclusion, and earlier reviewer approval is wrong until independent attempts fail to disprove it. Use for high-risk changes, disputed or repeatedly revised PRs, prior false approvals, governance handoffs, conversion correctness, or when the user asks for a real, adversarial, devil's-advocate, or final review.
---

# Devil's-advocate review

**Prerequisite skills:** `code-review`, `hard-review`, `identity-safe-git`

First execute the complete basic review (`code-review`) and hard review
(`hard-review`). Preserve every gate, publication duty, and the comment-only
reviewer firewall. All AgentOps skills are installed together in one skills
directory; if a prerequisite is unavailable, stop and report
`REQUIRED_SKILL_MISSING <name>`. The publisher and evidence gate used below live
in the scripts directory of the `code-review` skill.

Begin with the provisional verdict `CHANGES_REQUESTED`. The implementation must
earn its way out one claim at a time.

Before reading the author's claimed status, inspect exact-head CI conclusions,
validate from a clean detached checkout, inventory test suppression and deletion,
and map source requirements to the diff. If an author says `passed`, `green`,
`fixed`, or `addressed` while a required command failed or was not completed, an
input is untracked, evidence is synthetic where prohibited, or an obligation is
absent, record the contradiction as blocking and distrust every remaining claim
until independently executed.

## 1. Treat advocacy as hostile evidence

Assume these are wrong until independently verified:

- the PR body and developer handback;
- test names and green check summaries;
- claims of "dynamic", "end-to-end", "real-world", "full corpus", "no leak",
  "resolved", "100%", or "no residual risk";
- every prior reviewer finding disposition and approval, including reviews by
  trusted agents;
- the current task's translation of upstream architecture or requirements.

Do not seek confirmation. Seek the smallest realistic counterexample.

## 2. Audit every prior reviewer

Read all formal reviews, inline threads, and PR comments at every relevant head.
Build a contradiction ledger:

| Actor | Review ID/head | Claim or finding | Independent attack | Observed result | Disposition |
|---|---|---|---|---|---|

Re-run the underlying production path rather than repeating another reviewer's
words or command summary. A previous approval contributes no evidentiary weight.
A prior blocker remains open until the exact current head survives its original
counterexample and the remediation introduces no adjacent defect.

For re-review, compute the head delta and attack the fix itself: closest values
that must remain distinct, nearest representation that must remain rejected,
zero/one/many cases, and interactions with every earlier remediation.

## 3. Create independent disconfirmation attempts

For each material claim:

1. state a plausible broken implementation;
2. create a reviewer-owned probe outside the repository;
3. run it against the exact pinned production head;
4. record exact input, command, observed output, exit code, and execution
   receipt;
5. decide `disproved`, `survived`, or `cannot verify`.

Author tests and CI are context, not adversarial probes. Copying an author test
into prose or changing its label does not make it reviewer-created.

Minimum independent probes:

- three for ordinary devil's-advocate review;
- four for timing, grouping, parser, privacy, fail-closed, conversion-fidelity,
  or end-to-end claims;
- one additional probe for each independently overturned prior approval, up to
  two additional probes.

At least two probes must execute the production path for high-risk changes.
Prefer one counterexample that breaks the claim over many confirming examples.

## 4. Challenge the contract and architecture

When a PR translates architecture, governance, or a task prompt, build:

| Source obligation | Destination rule | Acceptance oracle | Negative control | Owner |
|---|---|---|---|---|

Every source obligation must be preserved, explicitly deferred with authority, or
rejected with authority. Internal consistency is insufficient if the source
contract was mistranslated.

Challenge whether the abstraction solves the actual production failure rather
than making diagnostics cleaner, making a fixture pass, or converting an unsafe
result into a graceful refusal. Trace observable user value through the final
consumer.

## 5. Approval burden

Approve only when all of the following are true:

- every basic and hard-review gate passes for the declared evidence scope;
- every mandated validation command completed at the exact head with exit code
  zero and no unexplained failure, error, skip, or xfail;
- every developer claim has a complete production-and-oracle trace;
- every relevant prior reviewer claim has been independently challenged;
- no disconfirmation attempt proves a material claim wrong;
- all earlier counterexamples survive freshly at the current exact head;
- required real-world tests run rather than skip;
- production code is demonstrably fixture-independent;
- remaining uncertainty is specific and non-blocking.

One proved contradiction requires `CHANGES_REQUESTED`. One material claim that
cannot be independently tested requires `CANNOT_VERIFY`. Do not turn uncertainty
into approval.

Use the evidence gate before approval and store its packet outside the reviewed
repository:

```text
python <code-review-skill-dir>/scripts/review_evidence_gate.py <external-evidence-packet.json> --expected-head <full-reviewed-head> [--prior-packet <external-prior-packet.json>] --prior-overturns <count> --high-risk --devils-advocate
```

The command must print `APPROVAL_EVIDENCE_GATE=PASS`. Never weaken or fabricate
the packet to obtain a pass. Declare the packet's `evidence_scope`
proportionally, as described in `hard-review`: real-source evidence is mandatory
only for data-dependent behaviour, and ordinary infrastructure uses the
`infrastructure` scope with its stated rationale and independent oracle.

Publish with the `code-review` publisher using `--level devils-advocate` and,
for approval, the same external packet plus any prior packet and overturn count,
plus `--role-policy`. The publisher requires at least four independent probes
before a devil's-advocate approval and always publishes the mandatory PR summary.

The mandatory PR summary must use:

```text
<!-- reviewer-summary:devils-advocate:<full-head-sha> -->
Review level: DEVILS_ADVOCATE
```

Include the contradiction ledger, reviewer-created probes, the strongest disproved
or surviving false-success mode, the evidence-gate result, and residual risk.

The reviewer must publish all review findings, decisions, and comments directly
to the PR thread. Output left only in the chat is not a review. Do not implement
fixes or reviewer-process improvements; publish them only as comments for a
separately authorised development cycle.
