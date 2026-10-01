# Evidence and falsification protocol

Use this protocol to decide whether evidence can support a review claim. Its purpose is to expose false-success tests: tests that pass while the claimed behavior is absent, bypassed, hardcoded, ambiguous, or order-dependent.

## Contents

1. Claim tracing
2. Discriminating assertions
3. End-to-end and dynamic-input claims
4. Real-data provenance and fixture independence
5. State distinctions
6. Boundary and scale tests
7. Collections and matching
8. Validation provenance
9. Approval questions
10. Reviewer incentives and evidence packet

## Evidence scope (choose first)

Depth must be proportional to what the change can break. Declare one
`evidence_scope` in the approval packet before judging any test:

- `domain` (default): the material behaviour depends on real-world source data
  (parsers, conversion, extraction, matching, timing, generated artifacts,
  empirical claims). Real-source acceptance evidence, an independent oracle and a
  fixture-coupling scan are mandatory. Synthetic or data-free tests carry zero
  acceptance weight.
- `infrastructure`: ordinary tooling, CI, dispatch, documentation or other
  changes where real-source data is genuinely inapplicable. Controlled fixtures
  and mocked services are acceptable, but the packet must state why real-source
  evidence does not apply (`inapplicability_rationale`), name the independent
  oracle (`infrastructure_oracle`), classify each cited test as
  `CONTROLLED_FIXTURE`, `MOCKED_SERVICE` or `CONTROL_PLANE`, and still carry
  reviewer-created probes, a manual fixture-coupling review and specific
  residual risks.
- `governance_control_plane`: the stricter legacy form for control-plane state
  transitions; it must declare no real artifacts and a `NOT_APPLICABLE` scanner
  result.

Never choose a narrower scope to avoid available real-source evidence. If any
material behaviour in the change is data-dependent, that behaviour needs
`domain` evidence even when the rest of the change is infrastructure.

## 1. Claim tracing

Trace every material claim through four links:

```text
source input → production transformation → observable output → exact assertion
```

A missing link makes the claim `cannot verify`.

These are not substitutes for the chain:

- a test or function name;
- aggregate candidate counts;
- successful file creation;
- a mock that replaces the changed production seam;
- a manually reconstructed value when the claim says dynamically extracted;
- a PR or agent summary.

When only part of the chain is dynamic, state exactly which part. Do not promote “event coordinates are extracted” into “all geometry is dynamically extracted.”

## 2. Discriminating assertions

Ask: what smallest broken implementation would still pass?

Common non-discriminating patterns:

- `assert result is None or result == candidate`;
- asserting only non-`None`, truthiness, length, or file existence for a semantic claim;
- checking that a candidate was extracted but never passing it to changed production code;
- asserting a boundary “inside” input that succeeds without using the boundary;
- asserting only one ordering of a collection algorithm;
- comparing output to an oracle computed by copied implementation logic.

For each positive test, seek a negative control that differs in only the behavior-controlling fact.

Do not ban every disjunction mechanically. Reject it when the alternatives represent materially different specified outcomes.

## 3. End-to-end and dynamic-input claims

Inventory every claimed input:

| Claimed input | Actual source expression | Later overwritten or hardcoded? | Reaches changed function? |
|---|---|---|---|

Inspect unused extracted variables. Extraction followed by hardcoded substitution is not dynamic validation.

For fixture or integration claims, require the changed production function to consume the extracted values and produce the asserted semantic output. Aggregate extraction counts establish fixture presence only.

## 4. Real-data provenance and fixture independence

Classify every cited test as real-source end-to-end, reproducibly extracted
real-source data, synthetic/mocked, or data-free. Synthetic and data-free tests
may localize a defect but cannot prove real-world behavior. A material domain
claim needs a genuine source artifact to reach the changed production boundary
and an independent semantic oracle to inspect its output.

Reference outputs are oracles, not production inputs. Fail the review if
expected timing, coordinates, hashes, labels, or other reference-derived facts
are injected into the path being evaluated.

Search production code for fixture names, paths, hashes, exact coordinates,
expected counts, and branches keyed to file identity. One fixture can expose a
defect but cannot justify a universal tolerance. Require evidence from multiple
real sources or a domain-derived rationale for generalized thresholds.

Hardcoded values remain synthetic even when a comment says they were measured
from a real fixture. An extracted-real-data claim requires a reproducible
extraction command and provenance tying each value to the pinned source.

## 5. State distinctions

When the domain distinguishes states such as:

- absent;
- invalid;
- ambiguous;
- conflicting;
- fallback;
- valid;

require distinct representations and exact assertions for each. Confirm ambiguous/conflicting input cannot fall through to a valid default.

Exercise both returned-diagnostic and raised-error modes when both are public behavior.

## 6. Boundary and scale tests

For a threshold `t`, use samples whose result changes because of `t`:

- just inside: `t - ε`;
- exact boundary when inclusivity matters;
- just outside: `t + ε`.

For overlap extension, keep the candidate entirely outside the target and vary only the gap. A candidate that already crosses the target does not test the extension.

For scaled geometry:

- use non-zero offsets;
- test at least two scales plus baseline;
- distinguish normalized thresholds from absolute physical thresholds;
- test both sides at each scale;
- verify all claimed dimensions, not merely one representative dimension.

## 7. Collections and matching

For grouping, matching, assignment, and deduplication, inspect:

- input-order permutations;
- duplicate and near-duplicate values;
- one candidate competing for multiple targets;
- multiple candidates competing for one target;
- global assignment versus greedy local selection;
- ties and near-ties;
- irrelevant distant candidates;
- filtered candidates leaking into later ambiguity checks.

Fail-closed behavior is acceptable only when it is explicit and cannot be mistaken for valid evidence.

## 8. Validation provenance

For a live review, bind evidence to the exact reviewed head.

Check:

- full, exact head object ID;
- exact equality between initial live head, reviewed local `HEAD`, and final live head;
- command and executable;
- test collection count;
- pass/skip/fail count;
- changed paths;
- whether the newly added tests are included in the full-suite count;
- whether the evidence comment was published after the head it pins.

Chat output is navigation, not durable evidence.

## 9. Approval questions

Before approval answer all of these with concrete locations:

1. What is the strongest plausible false-success implementation?
2. Which exact test would fail under it?
3. Does that test reach the changed production path?
4. Are its inputs derived from the claimed source?
5. Is its assertion exact and discriminating?
6. What relevant state, boundary, ordering, or conflict remains untested?
7. Does the durable evidence pin the live reviewed state?

Any unsupported material answer blocks approval.

## 10. Reviewer incentives and evidence packet

Approval is the costliest verdict because it transfers risk to the maintainer.
Do not reward approval volume. Reward independently falsified claims and
reproducible counterexamples.

An approval packet has this shape:

```json
{
  "schema_version": 2,
  "changed_test_paths": ["tests/test_example.py"],
  "remediation_deltas": [],
  "verdict": "APPROVE",
  "review_head": "0123456789abcdef0123456789abcdef01234567",
  "prior_review_head": null,
  "head_delta_claims": [{"id": "delta-1", "changed_path": "src/example.py", "changed_hunk": "parse width and provenance", "risk": "line width confused with geometry width"}],
  "claims": [
    {
      "claim": "public sample input reaches the parser and the output writer",
      "status": "verified",
      "production_path": "sample input -> parser -> normalized model -> output file",
      "evidence_path": "reviewer probe e2e-public-sample",
      "false_success_mutation": "bypass parsing and inject the expected values"
    }
  ],
  "probes": [
    {
      "name": "e2e-public-sample",
      "reviewer_created": true,
      "author_test_only": false,
      "production_path": true,
      "command": "exact runnable command",
      "input": "exact fixture or constructed counterexample",
      "false_success_mutation": "one plausible broken behavior",
      "observed_output": "concrete value that distinguishes outcomes",
      "invariant": "what must remain true",
      "result": "killed",
      "artifact_origin": "reviewer-created",
      "artifact_path": "reviewer://width-probe",
      "oracle_authority": "spec.md section 4",
      "executed_head": "0123456789abcdef0123456789abcdef01234567",
      "fresh_execution": true,
      "execution_receipt": "sha256:new-captured-probe-output",
      "targets_delta_claims": ["delta-1"]
    }
  ],
  "counterexample_registry": [{"id": "width-boundary", "origin_head": "0123456789abcdef0123456789abcdef01234567", "invariant": "4.0pt is accepted and 4.001pt is rejected", "current_probe": "e2e-public-sample"}],
  "test_evidence": [{"test_node": "tests/test_example.py::test_width", "input_control": "real sample record", "production_boundary": "extract -> classify", "assertion": "candidate rejected", "claim": "geometry width controls rejection", "inspected_head": "0123456789abcdef0123456789abcdef01234567", "data_class": "REAL_SOURCE_END_TO_END", "source_artifact": "samples/example.input", "provenance_receipt": "sha256:source-artifact", "oracle": "independent reference output semantic comparison", "oracle_independent": true}],
  "real_artifacts_exercised": ["samples/example.input@sha256:source-artifact"],
  "fixture_coupling": {"scanner_result": "PASS", "manual_review": true, "production_paths": ["src/example.py"], "fixture_identifiers_found": []},
  "residual_risks": ["specific untested behavior and why it remains"],
  "integrity_attestation": "I personally ran every listed probe against the pinned review head and recorded observed output without inference."
}
```

Rules:

- every material claim must appear and be `verified` for approval;
- probes must be reviewer-created and must not be author-test-only;
- commands and false-success mutations must be unique;
- at least one probe must cross the production boundary; high-risk reviews
  require two;
- `residual_risks` must be non-empty and specific; “none”, “zero”, and
  equivalents are forbidden;
- a rerun of the developer's tests is baseline validation, not a probe;
- a claimed execution without a reproducible receipt invalidates the review.
- a re-review must name the prior head and pass its packet to the gate; prior
  receipts, output hashes, test inventories, and approval prose are historical;
- every changed-head claim requires a fresh exact-head reviewer probe;
- every cited test requires inspected input, production call, and assertion;
- library field names do not prove semantics; units, provenance, and
  one-source-to-many expansion require a direct API or source probe.
- reviewer-created probes must execute reviewer-owned artifacts outside every
  changed test path; self-declared provenance is insufficient;
- every re-review carries forward and freshly executes the complete
  counterexample registry;
- every remediation delta records new assumptions, adjacent risks, and an
  authority citation; changing an oracle without authority is forbidden;
- a remediation review must challenge the closest distinct value, the nearest
  rejected representation, and relevant zero/one/many cardinalities rather
  than confirming only the literal reported example.

Projects should keep a reviewer scorecard. An independently overturned approval
adds one strike for the next five reviews. Evidence fabrication adds two.
Each strike raises the approval probe quota by one, capped at two. Five
subsequent reviews without an overturned approval clear one strike.
