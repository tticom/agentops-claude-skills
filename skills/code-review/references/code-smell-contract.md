# Code-smell contract

Use this contract for developer self-review and independent code review. A
smell is not a disliked style. It is a named structural pattern with concrete
evidence and a credible cost to correctness, change safety, test reliability,
or comprehension.

## Decision rule

Classify each candidate as one of:

- `NOT_PRESENT`: the defining evidence is absent;
- `SUSPECTED`: a lead exists but production context or impact is not yet proved;
- `CONFIRMED`: the defining evidence and impact are both demonstrated;
- `EXEMPT`: a cited repository rule or task requirement intentionally requires
  the pattern, and the implementation contains the smallest necessary form.

Never report a smell from its name alone. A confirmed smell must record:

1. smell name and definition;
2. exact changed path and line or hunk;
3. the defining evidence;
4. an affected caller, test, requirement, or future change scenario;
5. the concrete reliability or maintenance impact;
6. the smallest credible correction, or the exact exemption source.

Under a no-code-smells policy, a diff-introduced or materially worsened
`CONFIRMED` smell blocks developer handback and reviewer approval. A
`SUSPECTED` smell triggers inspection, not rejection. Do not waive a confirmed
smell because tests pass, label it “subjective,” or demote it to residual risk.
Do not use this policy to demand unrelated cleanup of unchanged legacy code.

## Production and evidence smells

### Dead code

**Definition:** production code has no reachable production caller, producer,
consumer, registration, or externally used entrypoint.

**Confirm with:** repository reference search plus entrypoint/data-flow tracing.
Test-only references do not make code production-reachable.

**Impact:** creates false completion signals, unexercised behavior, and unused
maintenance surface. Delete it or connect and test its production path.

### Speculative generality

**Definition:** an abstraction, parameter, hook, model, or extension point
exists for no current requirement or demonstrated caller.

**Distinguish from dead code:** reachable code may still be speculative when
its generalized form has no present use. Inline or narrow it until a real need
exists.

### Test theatre

**Definition:** a test exercises a representation, mock, helper, or shallow
seam while being cited as proof of behavior beyond that seam.

**Confirm with:** map the claimed observable backward from the final consumer.
If the test never crosses a required handoff, it cannot prove that handoff.

**Impact:** green tests coexist with absent, bypassed, constant, or disconnected
production behavior. Add an assertion at the claimed production boundary and
a false-success mutation or equivalent negative control.

### Exception-as-fallback

**Definition:** code raises, logs, or describes a fallback without returning,
emitting, or invoking the required fallback behavior.

**Impact:** data is rejected or lost while messages and tests imply graceful
handling. Assert the fallback's actual typed or user-visible output.

### Circular evidence

**Definition:** the implementation, fixture generator, or shared algorithm
also supplies the expected result used to validate itself.

**Impact:** the same defect can occur on both sides and pass. Replace the oracle
with independently derived expected semantics and preserve provenance.

## Domain-model and heuristic smells

### Primitive obsession

**Definition:** unconstrained strings, numbers, tuples, or dictionaries stand
in for a domain concept whose invariants or units affect behavior.

**Evidence:** repeated validation, ambiguous units, sentinel values, or the
same primitives passed together across boundaries. Introduce the smallest type
that owns the invariant; do not create a wrapper with no behavior or clarity.

### Stringly typed classification / substring trap

**Definition:** domain identity or control flow depends on incidental string
contents rather than a defined token, label grammar, enum, or parser result.

**Boundary probe:** include embedded keywords, negation, punctuation, case,
prefix/suffix collisions, and unknown values. Use exact normalized labels or a
documented grammar where those are the contract.

### Magic number or threshold

**Definition:** a behavioral boundary is embedded without a named invariant,
unit, provenance, or explanation of inclusive/exclusive and sign behavior.

**Boundary probe:** test immediately below, at, and above the boundary, plus
both signs when the value can be signed. A named constant alone does not cure
an unjustified threshold.

### Data clump

**Definition:** the same fields travel together across multiple declarations or
calls and share invariants, identity, or units.

**Impact:** callers can mix incompatible values. Introduce one domain type when
it reduces invalid states; do not bundle unrelated convenience parameters.

### Refused bequest

**Definition:** a subtype cannot honor material parent behavior or invariants
and therefore ignores, disables, or contradicts them.

**Impact:** substitutability fails. Prefer composition or a narrower interface.

## Change-structure smells

### Duplicated code

**Definition:** materially identical knowledge or decision logic occurs in
multiple places that must change together.

**Confirm before extracting:** repeated syntax alone is insufficient when the
concepts vary independently. Centralize shared knowledge, not accidental shape.

### Repeated conditional dispatch

**Definition:** multiple sites switch on the same discriminator and must remain
synchronized as variants change.

**Impact:** adding a variant requires scattered edits. Centralize dispatch or
put behavior behind the owning type when that makes the variant set safer.

### Shotgun surgery

**Definition:** one domain decision requires coordinated edits across multiple
otherwise unrelated modules.

**Impact:** omission risk and merge friction. Move the decision behind one
stable boundary; do not confuse legitimate end-to-end wiring with shotgun
surgery.

### Divergent change

**Definition:** one module changes for multiple unrelated business or technical
reasons and therefore has more than one axis of volatility.

**Impact:** unrelated work collides. Separate responsibilities around stable
cohesive boundaries, not arbitrary file size.

### Feature envy

**Definition:** a function primarily interprets or manipulates another
module/type's internal data rather than the state or abstraction it owns.

**Evidence:** repeated field navigation and decisions based on another type's
invariants. Move behavior to the information owner or expose a focused query.

### Message chain

**Definition:** a caller navigates a multi-object internal structure and becomes
coupled to each intermediate relationship.

**Impact:** internal reshaping breaks distant callers. Hide the traversal behind
a meaningful query at the stable boundary.

### Middle man

**Definition:** a layer delegates nearly all behavior without enforcing an
invariant, translating a boundary, isolating volatility, or adding policy.

**Impact:** indirection obscures the real owner. Remove it unless it has a
demonstrable boundary role.

## Naming and test smells

### Mysterious name

**Definition:** a name cannot distinguish the value's domain meaning, unit,
state, or effect at its use sites.

**Evidence:** readers must inspect the implementation or comments to know what
the name means. Rename for the domain concept; if no honest concise name exists,
reconsider the abstraction.

### Over-broad exception oracle

**Definition:** a test accepts a superclass such as `Exception`, or matches only
generic message text, when the failure type is part of the behavior.

**Impact:** unrelated crashes satisfy the test. Assert the narrow exception and
the state/output boundary that must remain unchanged.

### Weak or non-discriminating assertion

**Definition:** an assertion proves existence, non-emptiness, type, or a copied
constant while the cited requirement is about exact semantics, placement,
ordering, refusal, or final output.

**Impact:** plausible broken implementations pass. Assert the exact observable
and show that the nearest incorrect result fails.

### Import and dependency clutter

**Definition:** unused, duplicated, late, wildcard, or boundary-crossing imports
obscure the dependencies actually exercised.

**Impact:** weakens static signal and makes tests appear broader than they are.
Remove unused imports, keep imports in the repository-standard location, and
depend on the narrowest owning module.

## Review output

Include a smell ledger when any candidate is found:

| smell | status | path/hunk | defining evidence | impact | correction/exemption |
|---|---|---|---|---|---|

An empty ledger is not evidence by itself. State which changed production and
test paths were inspected and which relevant boundary probes or static checks
were run.
