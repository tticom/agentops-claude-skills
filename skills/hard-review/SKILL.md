---
name: hard-review
description: Perform an exact-head hard review that includes the complete basic code review plus adversarial inspection of test-data provenance, real-world acceptance evidence, oracle independence, and production-code fixture coupling. Use for conversion fidelity, parsers, geometry, timing, matching, generated artifacts, private fixtures, empirical claims, or whenever synthetic, mocked, generated, or data-free tests could create false confidence.
---

# Hard review

**Prerequisite skills:** `code-review`, `identity-safe-git`

First perform the complete basic review in the `code-review` skill, including its
exact-head checks, code-smell review, inline comments, mandatory PR summary, and
reviewer role firewall. This skill only adds gates; it never relaxes the basic
review. All AgentOps skills are installed together in one skills directory; if
`code-review` is not available, stop and report
`REQUIRED_SKILL_MISSING code-review`.

The publisher, the evidence gate, and the assertion-smell scanner used below live
in the scripts directory of the `code-review` skill. Resolve them from the sibling
`code-review` directory of the skills directory that holds this skill.

Read [the evidence and falsification protocol](references/evidence-falsification-protocol.md)
completely before evaluating tests or empirical claims.

## 0. Choose the evidence scope proportionally

Hard review is for changes whose behaviour depends on real-world data. Decide the
scope first and record it in the approval packet as `evidence_scope`:

- `domain`: material behaviour depends on real source data. Everything in this
  skill applies in full.
- `infrastructure`: ordinary tooling, CI, dispatch, or documentation where
  real-source data is genuinely inapplicable. Do not demand real-source
  acceptance tests for it. Require the stated `inapplicability_rationale`, an
  independent `infrastructure_oracle`, controlled fixtures or mocked services
  classified as such, reviewer-created probes, and a manual fixture-coupling
  review.
- `governance_control_plane`: the stricter legacy form for control-plane state
  transitions.

Never pick a narrower scope to avoid available real-source evidence. A change
that mixes both is `domain` for its data-dependent behaviour.

## 1. Inventory changed behavior and tests

Build a claim ledger before accepting any test result:

| Material behavior | Production path | Test node | Data source | Oracle | Acceptance status |
|---|---|---|---|---|---|
| exact claim | changed seam and consumer | exact node | provenance classification | independent expected result | verified / contradicted / cannot verify |

Classify every changed or cited test as one of:

- `REAL_SOURCE_END_TO_END`: an actual real-world source artifact enters the
  production boundary under review;
- `REAL_SOURCE_EXTRACT`: data extracted from a real-world artifact with a
  reproducible extraction receipt and retained provenance;
- `SYNTHETIC_OR_MOCKED`: generated input, invented values, fabricated JSON,
  mocks, stubs, or reconstructed inputs;
- `DATA_FREE`: source existence, importability, schema shape, constant, refusal
  code, or control-flow test without representative domain data.

For `domain` scope, synthetic and data-free tests carry zero acceptance weight
for real-world behaviour. A changed domain test that substitutes synthetic,
mocked, generated, or data-free input for available real-source evidence is a
blocking finding and must be replaced. Every changed domain behaviour still
requires a data-bearing test derived from a genuine source and reaching the
changed production seam. A green synthetic-only suite remains a blocking
false-success mode for domain behaviour.

For `infrastructure` scope, use the infrastructure classes from the protocol
(`CONTROLLED_FIXTURE`, `MOCKED_SERVICE`, `CONTROL_PLANE`) and prove the changed
contract with independent probes.

Classify provenance by construction, not filename or author label. A file, image,
JSON document, or oracle created by a fixture generator for the change is
`SYNTHETIC_OR_MOCKED`; committing the generated binary does not make it a real
source. Expected output written by the same generator or derived from the
implementation is circular, not independent. When the task forbids synthetic
evidence, introducing it is itself a specification violation even if separate
real-source evidence also exists.

Inventory skips, xfails, deselections, and test deletions in the head delta.
Compare their guarded behaviour with the base head. A new or broadened
suppression that hides an affected failure is blocking; a green aggregate
obtained through suppression is evidence of false success.

If a private in-situ test skips in public CI, verify the skip guard is narrow
and explicit, then personally run it in the authorised private-fixture
environment. A skipped test is not approval evidence.

## 2. Verify provenance and oracle independence

For every real-data test, trace:

```text
real source → production transformation → produced output → independent oracle → exact assertion
```

Require all links and an independent semantic oracle. In systems that convert or
transform source artifacts:

- use the source artifact as input;
- use the reference output only as a post-conversion oracle;
- never feed expected output, reference-derived timing, coordinates, hashes, or
  labels into the conversion path;
- compare semantic behaviour rather than presence, as the domain requires;
- reject output-exists, candidate-count-only, snapshot-presence, and aggregate
  pass-count assertions as fidelity proof.

When a test uses extracted real-source values, reproduce the extraction from the
pinned artifact. Hardcoded values accompanied only by a comment saying "measured
from fixture" remain synthetic evidence.

## 3. Prove production code is fixture-independent

Inspect all changed production files and their relevant callers for:

- private repository names, fixture paths, basenames, document titles, hashes,
  page numbers, exact coordinates, expected counts, or reference-output values;
- constants or branches chosen to make one named fixture pass;
- behaviour selected by file identity rather than observable domain evidence;
- tests that monkeypatch away the changed production boundary;
- reference or private data copied into public source, snapshots, reports, or
  generated artifacts.

Run the fixture-coupling scanner when fixture roots are available. Project-specific
private-path markers and named-artifact patterns are supplied by the project, not
built in:

```text
python <skill-dir>/scripts/fixture_coupling_scan.py --production <changed-production-file> [...] --fixture-root <authorized-fixture-root> [...] [--marker <literal-substring> ...] [--pattern <regex> ...] [--markers-file <json>]
```

Treat its output as leads, not proof of safety. Manually inspect numeric and
semantic coupling that a lexical scanner cannot detect.

For every tolerance or heuristic, require a domain rationale plus examples on
both sides of the boundary from more than one real source when the claim is
general. One fixture may expose a bug but cannot establish a universal value.

## 4. Falsify the evidence

For each claim, name the smallest broken implementation that could still pass.
Verify the existing assertion would fail under that defect. Inspect:

- absence versus ambiguity versus rejection;
- positive and negative controls;
- just-inside and just-outside boundaries;
- ordering, duplicate, scale, cardinality, and neighboring-item competition;
- fallback behaviour and whether fallback masks loss of primary evidence;
- round-trip or semantic output, not only intermediate metadata.

For acceptance claims, explicitly challenge a constant-output implementation and
require a negative control differing only in the behaviour-controlling fact.
Also inspect the changed production function and its direct caller for undefined
names, early returns, unreachable initialization, and mocked seams; targeted
green tests do not discharge this code-sanity check.

Run the assertion-smell scanner from the `code-review` skill on changed tests:

```text
python <code-review-skill-dir>/scripts/assertion_smells.py <changed-test-path> [...]
```

A clean scan does not justify approval.

## 5. Gate and publish

Request changes when any material behaviour lacks evidence appropriate to its
scope, the oracle contaminates production input, code is fixture-coupled, a skip
prevents required acceptance from running, or an assertion cannot distinguish the
claimed behaviour from a plausible defect. Use `CANNOT_VERIFY` when required
private data or authority is unavailable.

For approval, the PR summary required by `code-review` must use:

```text
<!-- reviewer-summary:hard:<full-head-sha> -->
Review level: HARD
```

It must also include the provenance classification for every material test, the
real artifacts personally exercised (or the stated inapplicability under
`infrastructure`), the fixture-coupling result, the strongest false-success mode
tested, and specific residual risk.

For `APPROVE`, create the evidence packet outside the repository and publish
through the `code-review` publisher with `--level hard --packet <external-packet.json>`,
plus the usual `--role-policy`. The publisher applies the evidence gate for the
declared scope before writing any review metadata. For blocking verdicts, omit
`--packet` but still use the publisher or the GitHub CLI so the formal verdict,
inline findings, and mandatory PR summary comment are published directly to the
pull request.

The reviewer must post all comments and decisions directly to the PR thread. Do
not substitute chat-only output. Do not add tests, reports, rules, prompts,
skills, or evidence files to the reviewed branch.
