#!/usr/bin/env python3
"""Fail closed when an approval lacks reviewer-created falsification evidence."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


class EvidenceError(ValueError):
    pass


FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
# domain: behaviour depends on real-world source data, so real-source evidence
#   is mandatory. infrastructure: ordinary tooling, CI, dispatch or documentation
#   changes where real-source data is genuinely inapplicable; controlled
#   fixtures and mocked services are acceptable with an independent oracle and a
#   stated rationale. governance_control_plane: the stricter legacy form.
EVIDENCE_SCOPES = {"domain", "infrastructure", "governance_control_plane"}
INFRASTRUCTURE_DATA_CLASSES = {"CONTROLLED_FIXTURE", "MOCKED_SERVICE", "CONTROL_PLANE"}


def text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvidenceError(f"{field} must be non-empty text")
    return value.strip()


def full_sha(value: Any, field: str) -> str:
    candidate = text(value, field)
    if not FULL_SHA.fullmatch(candidate):
        raise EvidenceError(f"{field} must be a full lowercase 40-character SHA")
    return candidate


def validate(packet: dict[str, Any], *, prior_overturns: int, high_risk: bool,
             expected_head: str, prior_packet: dict[str, Any] | None = None,
             devils_advocate: bool = False) -> tuple[int, int]:
    if packet.get("schema_version") != 2:
        raise EvidenceError("schema_version must be 2")
    if packet.get("verdict") != "APPROVE":
        raise EvidenceError("gate is only valid for verdict APPROVE")

    evidence_scope = packet.get("evidence_scope", "domain")
    if evidence_scope not in EVIDENCE_SCOPES:
        raise EvidenceError(
            "evidence_scope must be one of " + ", ".join(sorted(EVIDENCE_SCOPES))
        )
    if evidence_scope == "governance_control_plane":
        text(packet.get("inapplicability_rationale"), "inapplicability_rationale")
        text(packet.get("control_plane_oracle"), "control_plane_oracle")
    if evidence_scope == "infrastructure":
        text(packet.get("inapplicability_rationale"), "inapplicability_rationale")
        text(packet.get("infrastructure_oracle"), "infrastructure_oracle")

    review_head = full_sha(packet.get("review_head"), "review_head")
    if review_head != expected_head:
        raise EvidenceError("review_head does not equal --expected-head")
    prior_value = packet.get("prior_review_head")
    prior_head = None if prior_value is None else full_sha(prior_value, "prior_review_head")
    if prior_head is not None and prior_packet is None:
        raise EvidenceError("--prior-packet is required when prior_review_head is set")
    if prior_packet is not None:
        expected_prior = full_sha(prior_packet.get("review_head"), "prior packet review_head")
        if prior_head != expected_prior or prior_head == review_head:
            raise EvidenceError("prior packet does not identify a different prior reviewed head")

    changed_test_paths = packet.get("changed_test_paths")
    if not isinstance(changed_test_paths, list):
        raise EvidenceError("changed_test_paths must be a list")
    changed_tests = {
        text(value, "changed_test_paths[]").replace("\\", "/")
        for value in changed_test_paths
    }

    remediation_deltas = packet.get("remediation_deltas")
    if not isinstance(remediation_deltas, list):
        raise EvidenceError("remediation_deltas must be a list")
    if prior_packet is not None and not remediation_deltas:
        raise EvidenceError("a re-review requires a remediation delta threat model")
    for index, delta in enumerate(remediation_deltas):
        if not isinstance(delta, dict):
            raise EvidenceError(f"remediation_deltas[{index}] must be an object")
        for field in (
            "finding_id", "changed_symbols", "fix_assumption", "new_branches",
            "adjacent_risks", "authority_citation",
        ):
            text(delta.get(field), f"remediation_deltas[{index}].{field}")
        if not isinstance(delta.get("oracle_changed"), bool):
            raise EvidenceError(f"remediation_deltas[{index}].oracle_changed must be boolean")

    delta_claims = packet.get("head_delta_claims")
    if not isinstance(delta_claims, list) or not delta_claims:
        raise EvidenceError("head_delta_claims must be a non-empty list")
    delta_ids: set[str] = set()
    for index, delta in enumerate(delta_claims):
        if not isinstance(delta, dict):
            raise EvidenceError(f"head_delta_claims[{index}] must be an object")
        claim_id = text(delta.get("id"), f"head_delta_claims[{index}].id")
        if claim_id in delta_ids:
            raise EvidenceError(f"duplicate head-delta claim id: {claim_id}")
        delta_ids.add(claim_id)
        for field in ("changed_path", "changed_hunk", "risk"):
            text(delta.get(field), f"head_delta_claims[{index}].{field}")

    claims = packet.get("claims")
    if not isinstance(claims, list) or not claims:
        raise EvidenceError("claims must be a non-empty list")
    for index, claim in enumerate(claims):
        if not isinstance(claim, dict):
            raise EvidenceError(f"claims[{index}] must be an object")
        for field in ("claim", "production_path", "evidence_path", "false_success_mutation"):
            text(claim.get(field), f"claims[{index}].{field}")
        if claim.get("status") != "verified":
            raise EvidenceError(f"claims[{index}].status must be verified")

    probes = packet.get("probes")
    if not isinstance(probes, list):
        raise EvidenceError("probes must be a list")
    required = (4 if devils_advocate else 3 if high_risk else 2) + min(
        max(prior_overturns, 0), 2
    )
    if len(probes) < required:
        raise EvidenceError(f"need at least {required} reviewer-created probes; found {len(probes)}")

    commands: set[str] = set()
    probe_names: set[str] = set()
    mutations: set[str] = set()
    production_count = 0
    score = 0
    covered_delta_ids: set[str] = set()
    prior_receipts = {p.get("execution_receipt") for p in (prior_packet or {}).get("probes", []) if isinstance(p, dict)}
    for index, probe in enumerate(probes):
        if not isinstance(probe, dict):
            raise EvidenceError(f"probes[{index}] must be an object")
        if probe.get("reviewer_created") is not True:
            raise EvidenceError(f"probes[{index}] is not reviewer-created")
        if probe.get("artifact_origin") != "reviewer-created":
            raise EvidenceError(f"probes[{index}].artifact_origin must be reviewer-created")
        if probe.get("author_test_only") is not False:
            raise EvidenceError(f"probes[{index}] must not be author-test-only")
        if probe.get("result") not in {"killed", "exposed"}:
            raise EvidenceError(f"probes[{index}].result must be killed or exposed")
        for field in (
            "name", "command", "input", "false_success_mutation", "observed_output",
            "invariant", "execution_receipt", "artifact_path", "oracle_authority",
        ):
            text(probe.get(field), f"probes[{index}].{field}")
        probe_name = probe["name"].strip()
        if probe_name in probe_names:
            raise EvidenceError(f"duplicate probe name: {probe_name}")
        probe_names.add(probe_name)
        if full_sha(probe.get("executed_head"), f"probes[{index}].executed_head") != review_head:
            raise EvidenceError(f"probes[{index}] was not executed against review_head")
        if probe.get("fresh_execution") is not True or probe["execution_receipt"] in prior_receipts:
            raise EvidenceError(f"probes[{index}] lacks a fresh current-head execution receipt")
        targets = probe.get("targets_delta_claims")
        if not isinstance(targets, list) or not targets:
            raise EvidenceError(f"probes[{index}].targets_delta_claims must be non-empty")
        normalized_targets = {text(value, f"probes[{index}].targets_delta_claims") for value in targets}
        if normalized_targets - delta_ids:
            raise EvidenceError(f"probes[{index}] targets an unknown delta claim")
        covered_delta_ids.update(normalized_targets)
        command = probe["command"].strip()
        normalized_command = command.replace("\\", "/")
        artifact_path = probe["artifact_path"].strip().replace("\\", "/")
        if artifact_path in changed_tests or any(path in normalized_command for path in changed_tests):
            raise EvidenceError(
                f"probes[{index}] relies on an author-changed test and is not reviewer-owned evidence"
            )
        if not artifact_path.startswith("reviewer://") and artifact_path not in normalized_command:
            raise EvidenceError(f"probes[{index}].command does not execute artifact_path")
        mutation = probe["false_success_mutation"].strip()
        if command in commands:
            raise EvidenceError(f"duplicate probe command: {command}")
        if mutation in mutations:
            raise EvidenceError(f"duplicate false-success mutation: {mutation}")
        commands.add(command)
        mutations.add(mutation)
        if probe.get("production_path") is True:
            production_count += 1
        score += 2

    if delta_ids - covered_delta_ids:
        raise EvidenceError(f"head-delta claims lack fresh probes: {sorted(delta_ids - covered_delta_ids)}")

    registry = packet.get("counterexample_registry")
    if not isinstance(registry, list) or not registry:
        raise EvidenceError("counterexample_registry must be a non-empty list")
    registry_ids: set[str] = set()
    for index, entry in enumerate(registry):
        if not isinstance(entry, dict):
            raise EvidenceError(f"counterexample_registry[{index}] must be an object")
        entry_id = text(entry.get("id"), f"counterexample_registry[{index}].id")
        if entry_id in registry_ids:
            raise EvidenceError(f"duplicate counterexample registry id: {entry_id}")
        registry_ids.add(entry_id)
        full_sha(entry.get("origin_head"), f"counterexample_registry[{index}].origin_head")
        text(entry.get("invariant"), f"counterexample_registry[{index}].invariant")
        current_probe = text(entry.get("current_probe"), f"counterexample_registry[{index}].current_probe")
        if current_probe not in probe_names:
            raise EvidenceError(f"counterexample_registry[{index}] references an unknown current probe")
    prior_registry_ids = {
        entry.get("id") for entry in (prior_packet or {}).get("counterexample_registry", [])
        if isinstance(entry, dict)
    }
    if prior_registry_ids - registry_ids:
        raise EvidenceError(
            f"re-review dropped prior counterexamples: {sorted(prior_registry_ids - registry_ids)}"
        )

    test_evidence = packet.get("test_evidence")
    if not isinstance(test_evidence, list) or not test_evidence:
        raise EvidenceError("test_evidence must be a non-empty list")
    for index, item in enumerate(test_evidence):
        if not isinstance(item, dict):
            raise EvidenceError(f"test_evidence[{index}] must be an object")
        for field in ("test_node", "input_control", "production_boundary", "assertion", "claim"):
            text(item.get(field), f"test_evidence[{index}].{field}")
        if full_sha(item.get("inspected_head"), f"test_evidence[{index}].inspected_head") != review_head:
            raise EvidenceError(f"test_evidence[{index}] was not inspected at review_head")
        if (high_risk or devils_advocate) and evidence_scope == "governance_control_plane":
            if item.get("data_class") != "CONTROL_PLANE":
                raise EvidenceError(
                    f"test_evidence[{index}] must use CONTROL_PLANE evidence"
                )
            text(item.get("oracle"), f"test_evidence[{index}].oracle")
            if item.get("oracle_independent") is not True:
                raise EvidenceError(
                    f"test_evidence[{index}].oracle_independent must be true"
                )
        elif (high_risk or devils_advocate) and evidence_scope == "infrastructure":
            if item.get("data_class") not in INFRASTRUCTURE_DATA_CLASSES:
                raise EvidenceError(
                    f"test_evidence[{index}].data_class must be one of "
                    + ", ".join(sorted(INFRASTRUCTURE_DATA_CLASSES))
                )
            text(item.get("oracle"), f"test_evidence[{index}].oracle")
            if item.get("oracle_independent") is not True:
                raise EvidenceError(
                    f"test_evidence[{index}].oracle_independent must be true"
                )
        elif high_risk or devils_advocate:
            data_class = text(item.get("data_class"), f"test_evidence[{index}].data_class")
            if data_class not in {"REAL_SOURCE_END_TO_END", "REAL_SOURCE_EXTRACT"}:
                raise EvidenceError(
                    f"test_evidence[{index}] lacks real-source acceptance evidence"
                )
            for field in ("source_artifact", "provenance_receipt", "oracle"):
                text(item.get(field), f"test_evidence[{index}].{field}")
            if item.get("oracle_independent") is not True:
                raise EvidenceError(
                    f"test_evidence[{index}].oracle_independent must be true"
                )

    if (high_risk or devils_advocate) and evidence_scope == "governance_control_plane":
        if packet.get("real_artifacts_exercised") != []:
            raise EvidenceError(
                "governance_control_plane packets must declare no real artifacts"
            )
        coupling = packet.get("fixture_coupling")
        if not isinstance(coupling, dict):
            raise EvidenceError("fixture_coupling must be an object")
        if coupling.get("scanner_result") != "NOT_APPLICABLE":
            raise EvidenceError(
                "governance_control_plane fixture coupling must be NOT_APPLICABLE"
            )
        if coupling.get("manual_review") is not True:
            raise EvidenceError("fixture_coupling.manual_review must be true")
        production_paths = coupling.get("production_paths")
        if not isinstance(production_paths, list) or not production_paths:
            raise EvidenceError("fixture_coupling.production_paths must be non-empty")
        for index, path in enumerate(production_paths):
            text(path, f"fixture_coupling.production_paths[{index}]")
        if coupling.get("fixture_identifiers_found") != []:
            raise EvidenceError("fixture_coupling.fixture_identifiers_found must be empty")
    elif (high_risk or devils_advocate) and evidence_scope == "infrastructure":
        artifacts = packet.get("real_artifacts_exercised")
        if not isinstance(artifacts, list):
            raise EvidenceError("real_artifacts_exercised must be a list")
        for index, artifact in enumerate(artifacts):
            text(artifact, f"real_artifacts_exercised[{index}]")
        coupling = packet.get("fixture_coupling")
        if not isinstance(coupling, dict):
            raise EvidenceError("fixture_coupling must be an object")
        if coupling.get("scanner_result") not in {"PASS", "NOT_APPLICABLE"}:
            raise EvidenceError(
                "infrastructure fixture_coupling.scanner_result must be PASS or NOT_APPLICABLE"
            )
        if coupling.get("manual_review") is not True:
            raise EvidenceError("fixture_coupling.manual_review must be true")
        production_paths = coupling.get("production_paths")
        if not isinstance(production_paths, list) or not production_paths:
            raise EvidenceError("fixture_coupling.production_paths must be non-empty")
        for index, path in enumerate(production_paths):
            text(path, f"fixture_coupling.production_paths[{index}]")
        if coupling.get("fixture_identifiers_found") != []:
            raise EvidenceError("fixture_coupling.fixture_identifiers_found must be empty")
    elif high_risk or devils_advocate:
        artifacts = packet.get("real_artifacts_exercised")
        if not isinstance(artifacts, list) or not artifacts:
            raise EvidenceError("real_artifacts_exercised must be a non-empty list")
        for index, artifact in enumerate(artifacts):
            text(artifact, f"real_artifacts_exercised[{index}]")

        coupling = packet.get("fixture_coupling")
        if not isinstance(coupling, dict):
            raise EvidenceError("fixture_coupling must be an object")
        if coupling.get("scanner_result") != "PASS":
            raise EvidenceError("fixture_coupling.scanner_result must be PASS")
        if coupling.get("manual_review") is not True:
            raise EvidenceError("fixture_coupling.manual_review must be true")
        production_paths = coupling.get("production_paths")
        if not isinstance(production_paths, list) or not production_paths:
            raise EvidenceError("fixture_coupling.production_paths must be non-empty")
        for index, path in enumerate(production_paths):
            text(path, f"fixture_coupling.production_paths[{index}]")
        if coupling.get("fixture_identifiers_found") != []:
            raise EvidenceError("fixture_coupling.fixture_identifiers_found must be empty")

    required_production = 2 if high_risk else 1
    if production_count < required_production:
        raise EvidenceError(
            f"need {required_production} production-path probes; found {production_count}"
        )

    risks = packet.get("residual_risks")
    if not isinstance(risks, list) or not risks:
        raise EvidenceError("residual_risks must be a non-empty list")
    banned = {"none", "no risk", "no risks", "zero", "n/a"}
    for index, risk in enumerate(risks):
        normalized = text(risk, f"residual_risks[{index}]").lower().rstrip(".")
        if normalized in banned:
            raise EvidenceError("zero-risk claims are forbidden")

    expected = (
        "I personally ran every listed probe against the pinned review head "
        "and recorded observed output without inference."
    )
    if packet.get("integrity_attestation") != expected:
        raise EvidenceError("integrity_attestation is missing or not exact")
    return required, score


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("packet", type=Path)
    parser.add_argument("--prior-overturns", type=int, default=0)
    parser.add_argument("--high-risk", action="store_true")
    parser.add_argument("--devils-advocate", action="store_true")
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--prior-packet", type=Path)
    args = parser.parse_args()
    try:
        packet = json.loads(args.packet.read_text(encoding="utf-8"))
        if not isinstance(packet, dict):
            raise EvidenceError("packet root must be an object")
        expected_head = full_sha(args.expected_head, "--expected-head")
        prior_packet = None
        if args.prior_packet:
            prior_packet = json.loads(args.prior_packet.read_text(encoding="utf-8"))
            if not isinstance(prior_packet, dict):
                raise EvidenceError("prior packet root must be an object")
        required, score = validate(
            packet,
            prior_overturns=args.prior_overturns,
            high_risk=args.high_risk,
            expected_head=expected_head,
            prior_packet=prior_packet,
            devils_advocate=args.devils_advocate,
        )
    except (OSError, json.JSONDecodeError, EvidenceError) as error:
        raise SystemExit(f"APPROVAL_EVIDENCE_GATE=FAIL: {error}") from error
    print(f"APPROVAL_EVIDENCE_GATE=PASS required_probes={required} score={score}")


if __name__ == "__main__":
    main()
