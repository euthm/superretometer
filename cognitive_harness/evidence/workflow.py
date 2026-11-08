"""Proposal-backed portable target and append-only evaluation archive.

The filesystem target explicitly restores a scoped InMemory snapshot. InMemory
itself remains volatile. Private adapters are not inferred from user config.
"""
from __future__ import annotations

import copy
import os
import shutil
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from cognitive_harness import __version__
from cognitive_harness.analysis.implementation_gate_policy import ImplementationGatePolicy, canonical_remote
from cognitive_harness.analysis.warrant_analyzer import WarrantAnalyzer
from cognitive_harness.model.ko import (FalsifiableValidator, KnowledgeObject, KOType,
                                      Provenance, TruthCategory, RelationType)
from cognitive_harness.model.proposal import Proposal, ProposalState, ProposalType
from cognitive_harness.storage.inmemory import InMemoryStorage
from .capture import remote
from .contracts import (EvidenceError, acceptance, canonical, file_entry, listed_files,
                        load, now, plain, package_source_sha256, receipt_at, safe_file, sha, validate, verify, write)


def _submit(storage, kind, **kwargs):
    p = Proposal(type=kind, proposer="portable-test-evidence/v1",
                 rationale="Import verified runner-reported receipt; no independent certification", **kwargs)
    pid = storage.submit_proposal(p)
    result = storage.validate_and_execute(pid)
    if result is None or result.state != ProposalState.ACCEPTED:
        raise EvidenceError("Incomplete import: proposal rejected or unsupported")
    return result


def _graph(storage, mapping, proposals):
    nodes = []
    for role in ("claim", "evidence", "validator"):
        ko = storage.get_ko(mapping[role]["ch_id"])
        if ko is None:
            raise EvidenceError(f"Incomplete import: {role} readback failed")
        nodes.append({"id": ko.id, "type": ko.type.value, "title": ko.title,
                      "content": plain(ko.content), "scope": ko.scope,
                      "truth_category": ko.truth_category.value,
                      "provenance": plain(ko.provenance),
                      "validators": plain(ko.validators),
                      "relations": [{"to": to, "type": typ.value} for to, typ in storage.get_outgoing_relations(ko.id)]})
    return {"schema_version": "portable-test-graph/v1", "mapping": mapping,
            "proposals": proposals, "nodes": nodes}


def _restore(graph):
    """Restore historical objects using public storage CRUD, not external mutation.

    Only this reference target's bounded, prior proposal results are supported.
    Never infer arbitrary KO classes or call executable fields from JSON.
    """
    if not isinstance(graph, dict):
        raise EvidenceError("Invalid portable graph object")
    if graph.get("schema_version") != "portable-test-graph/v1" or not isinstance(graph.get("nodes"), list) or len(graph["nodes"]) != 3:
        raise EvidenceError("Unsupported portable graph snapshot")
    storage = InMemoryStorage()
    if not isinstance(graph.get("mapping"), dict) or set(graph["mapping"]) != {"claim", "evidence", "validator"}:
        raise EvidenceError("Invalid graph mapping roles")
    if not isinstance(graph.get("proposals"), list):
        raise EvidenceError("Invalid graph proposal history")
    try:
        expected = {v["ch_id"] for v in graph["mapping"].values()}
        if len(expected) != 3 or {n["id"] for n in graph["nodes"]} != expected:
            raise EvidenceError("Graph mapping is incomplete")
        for n in graph["nodes"]:
            if not isinstance(n, dict) or not isinstance(n.get("content"), dict):
                raise EvidenceError("Invalid portable graph node")
            provenance = dict(n["provenance"])
            provenance["timestamp"] = datetime.fromisoformat(provenance["timestamp"])
            storage.create_ko(KnowledgeObject(
                id=n["id"], type=KOType(n["type"]), title=n["title"],
                content=copy.deepcopy(n["content"]), scope=n["scope"],
                truth_category=TruthCategory(n["truth_category"]),
                provenance=Provenance(**provenance),
                validators=[FalsifiableValidator(**v) for v in n["validators"]]))
        for n in graph["nodes"]:
            for relation in n["relations"]:
                if not storage.create_relation(n["id"], relation["to"], RelationType(relation["type"])):
                    raise EvidenceError("Graph relation endpoint missing")
        if _graph(storage, graph["mapping"], graph["proposals"]) != graph:
            raise EvidenceError("Graph restore/readback mismatch")
    except (KeyError, TypeError, ValueError) as exc:
        raise EvidenceError(f"Invalid portable graph: {exc}") from exc
    return storage


class Target:
    """Explicit filesystem-backed scoped snapshot target, not a live Memory adapter."""
    def __init__(self, target_id: str, root, repositories=None):
        if not isinstance(target_id, str) or not target_id.strip():
            raise EvidenceError("An explicit nonempty target ID is required")
        self.id = target_id
        self.root = Path(root).resolve()
        self.repositories = {canonical_remote(k): Path(v).resolve() for k, v in (repositories or {}).items()}

    @classmethod
    def from_config(cls, path):
        path = Path(path).resolve()
        value = load(path)
        if set(value) != {"kind", "id", "root", "repositories"} or value["kind"] != "portable-inmemory/v1":
            raise EvidenceError("Unsupported target: configure portable-inmemory/v1 explicitly")
        return cls(value["id"], path.parent / value["root"],
                   {k: path.parent / v for k, v in value["repositories"].items()})

    @contextmanager
    def transaction(self):
        try:
            import fcntl
        except ImportError as exc:
            raise EvidenceError("This target requires POSIX process locking; unsupported on this OS") from exc
        self.root.mkdir(parents=True, exist_ok=True)
        with (self.root / ".lock").open("a+b") as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise EvidenceError("Target busy: concurrent import/evaluation is not accepted") from exc
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)

    def state(self):
        path = self.root / "imports.json"
        if not path.exists():
            return {"schema_version": "portable-test-target/v1", "target": self.id, "imports": {}}
        envelope = load(path)
        payload = envelope.get("payload")
        if envelope.get("sha256") != sha(canonical(payload)) or not isinstance(payload, dict):
            raise EvidenceError("Target state integrity mismatch")
        if payload.get("schema_version") != "portable-test-target/v1" or payload.get("target") != self.id:
            raise EvidenceError("Target identity/schema conflict")
        return payload

    def save(self, state):
        write(self.root / "imports.json", {"payload": state, "sha256": sha(canonical(state))}, replace=True)


def _record_proposal(p):
    return {"id": p.id, "type": p.type.value, "state": p.state.value,
            "created_ko_id": p.created_ko_id, "target_ko_id": p.target_ko_id,
            "from_ko_id": p.from_ko_id, "to_ko_id": p.to_ko_id}


def _import_graph(run, receipt_hash, repo):
    storage, proposals = InMemoryStorage(), []
    def submit(kind, **kwargs):
        p = _submit(storage, kind, **kwargs)
        proposals.append(_record_proposal(p))
        return p
    ids = {}
    for role, typ, title, content in (
            ("claim", KOType.FINDING, run["claim"]["title"], {"receipt_sha256": receipt_hash, "bounded_scope": run["claim"]["scope"]}),
            ("evidence", KOType.EVIDENCE_ITEM, "Runner-reported execution", {"receipt_sha256": receipt_hash, "run_id": run["run_id"], "tests": run["tests"], "execution": run["execution"]}),
            ("validator", KOType.FINDING, "Runner result observation", {"receipt_sha256": receipt_hash, "acceptance": acceptance(run)})):
        p = submit(ProposalType.CREATE_KO, ko_type=typ, ko_title=title, ko_content=content, ko_scope=run["claim"]["scope"])
        ids[role] = {"ch_id": p.created_ko_id, "backend_id": p.created_ko_id}
    claim_id, evidence_id, validator_id = (ids[k]["ch_id"] for k in ("claim", "evidence", "validator"))
    before, after = run["code"]["before"], run["code"]["after"]
    stable = before == after
    clean = stable and before["clean"] and after["clean"] and not before["errors"] and not after["errors"]
    result_artifact = next((a for a in run["artifacts"] if a["role"] == "structured-result"), None)
    if result_artifact is None:
        result_artifact = next(a for a in run["artifacts"] if a["role"] == "stdout")
    diff = before["diff_sha256"] if stable else sha(canonical({"before": before, "after": after}))
    provenance = {"repo_remote_sanitized": run["code"]["remote"], "repo_remote_canonical": run["code"]["canonical_remote"],
                  "repo_path": str(repo) if repo is not None else "", "branch": before["branch"],
                  "commit": run["claim"]["requested_commit"] or before["commit"],
                  "worktree_clean": clean, "worktree_diff_sha256": diff,
                  "submodule_pins": before["submodules"], "tested_submodule_pins": before["submodules"],
                  "test_run_id": run["run_id"], "validator_ko_id": validator_id,
                  "test_command": __import__("shlex").join(run["execution"]["argv"]),
                  "test_exit_code": run["execution"]["exit_code"], "test_result_sha256": result_artifact["sha256"],
                  "tested_commit": before["commit"], "tested_worktree_diff_sha256": before["diff_sha256"],
                  "test_timestamp": run["ended_at"], "blob_digest": before["legacy_blob_digest"] or "",
                  "blob_paths": run["code"]["source_paths"]}
    success = acceptance(run)["status"] == "pass"
    validator = FalsifiableValidator(description="Operator-declared acceptance for this bounded run",
                                    what_would_falsify=run["claim"]["falsifier"], ko_id=validator_id,
                                    passes=success, observation="Runner-reported results; not independent certification")
    content = {**storage.get_ko(claim_id).content, "implementation_provenance": provenance,
               "declared_remotes": [run["claim"]["declared_remote"]]}
    submit(ProposalType.UPDATE_KO, target_ko_id=claim_id, updates={"content": content, "validators": [validator]})
    for role in ids:
        submit(ProposalType.UPDATE_KO, target_ko_id=ids[role]["ch_id"],
               updates={"provenance": Provenance(source=f"test-receipt:sha256:{receipt_hash}",
                                                author=run["producer"]["name"], independent=False)})
    if success:
        submit(ProposalType.CREATE_RELATION, from_ko_id=evidence_id, to_ko_id=claim_id, relation_type=RelationType.SUPPORTS)
        submit(ProposalType.CREATE_RELATION, from_ko_id=validator_id, to_ko_id=claim_id, relation_type=RelationType.VALIDATES)
        if (evidence_id, RelationType.SUPPORTS) not in storage.get_incoming_relations(claim_id):
            raise EvidenceError("Incomplete import: SUPPORTS readback failed")
        if (validator_id, RelationType.VALIDATES) not in storage.get_incoming_relations(claim_id):
            raise EvidenceError("Incomplete import: VALIDATES readback failed")
    if storage.get_ko(claim_id).content != content or storage.get_ko(claim_id).validators != [validator]:
        raise EvidenceError("Incomplete import: claim provenance/validator readback failed")
    graph = _graph(storage, ids, proposals)
    _restore(graph)
    return graph


def import_receipt(path, target: Target) -> dict:
    """Validate first; publish scoped graph and identity atomically under a lock."""
    checked = verify(path)
    source, run = receipt_at(Path(path))
    rid, digest = run["run_id"], checked["receipt_sha256"]
    with target.transaction():
        state = target.state()
        existing = state["imports"].get(rid)
        if existing is not None:
            if existing["receipt_sha256"] != digest:
                raise EvidenceError("Run ID conflict: different immutable receipt content")
            _restore(existing["graph"])
            if verify(target.root / "receipts" / digest)["receipt_sha256"] != digest:
                raise EvidenceError("Archived receipt identity mismatch")
            return {"status": "existing", "target": target.id, "run_id": rid,
                    "receipt_sha256": digest, "mapping": existing["graph"]["mapping"]}
        repo = target.repositories.get(run["code"]["canonical_remote"])
        if repo is not None and canonical_remote(remote(repo)) != run["code"]["canonical_remote"]:
            raise EvidenceError("Operator repository mapping remote mismatch")
        graph = _import_graph(run, digest, repo)
        destination = target.root / "receipts" / digest
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            with tempfile.TemporaryDirectory(prefix=".import-", dir=destination.parent) as temp:
                staging = Path(temp) / "receipt"
                staging.mkdir()
                # Import execution evidence only; historical evaluations are separate.
                for name in ["run.json"] + [a["path"] for a in run["artifacts"]]:
                    out = staging / name
                    out.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(safe_file(source, name), out)
                verify(staging)
                os.rename(staging, destination)
        else:
            if verify(destination)["receipt_sha256"] != digest:
                raise EvidenceError("Prior partial import receipt conflict")
        state["imports"][rid] = {"receipt_sha256": digest, "graph": graph}
        target.save(state)
    return {"status": "imported", "target": target.id, "run_id": rid,
            "receipt_sha256": digest, "mapping": graph["mapping"]}


def _policy_identity():
    return {"name": "ImplementationGatePolicy", "package_version": __version__,
            "source_sha256": package_source_sha256()}


def evaluate(target: Target, run_id: str, *, control="baseline") -> dict:
    """Append an evaluation. Negative controls mutate only an ephemeral claim copy."""
    if control not in ("baseline", "commit_mismatch", "missing_validator"):
        raise EvidenceError("Unsupported negative control")
    with target.transaction():
        state = target.state()
        if run_id not in state["imports"]:
            raise EvidenceError("No imported receipt for this target/run")
        entry = state["imports"][run_id]
        receipt_root = target.root / "receipts" / entry["receipt_sha256"]
        _, run = receipt_at(receipt_root)
        repo = target.repositories.get(run["code"]["canonical_remote"])
        checked = verify(receipt_root, repo=repo)
        if checked["receipt_sha256"] != entry["receipt_sha256"]:
            raise EvidenceError("Imported receipt identity mismatch")
        graph = copy.deepcopy(entry["graph"])
        storage = _restore(graph)
        claim_id = graph["mapping"]["claim"]["ch_id"]
        claim = storage.get_ko(claim_id)
        prov = claim.content["implementation_provenance"]
        prov["repo_path"] = str(repo) if repo is not None else ""
        if repo is not None:
            try:
                for name in run["code"]["source_paths"]:
                    safe_file(repo, name)
            except EvidenceError:
                # Do not let the legacy digest helper follow unsafe or missing paths.
                prov["repo_path"] = ""
        if repo is not None and canonical_remote(remote(repo)) != run["code"]["canonical_remote"]:
            checked["source_current"] = "mismatch"
            checked["reasons"].append("Mapped repository remote mismatch")
            prov["repo_path"] = ""
        if control == "commit_mismatch":
            prov["commit"] = "0" * len(prov["tested_commit"])
        elif control == "missing_validator":
            prov["validator_ko_id"] = ""
        gates = ImplementationGatePolicy(storage).evaluate_gates(claim_id)
        warrant = plain(WarrantAnalyzer(storage).compute_warrant(claim_id))
        snapshot = _graph(storage, graph["mapping"], graph["proposals"])
        eid = str(uuid.uuid4())
        result = {"schema_version": "test-evaluation/v1", "evaluation_id": eid,
                  "receipt_sha256": entry["receipt_sha256"], "run_id": run_id, "target": target.id,
                  "timestamp": now(), "policy": _policy_identity(), "control": control,
                  "verification": {k: checked[k] for k in ("integrity", "source_current", "reasons")},
                  "acceptance": checked["acceptance"], "gates": gates, "warrant": warrant,
                  "graph_sha256": sha(canonical(snapshot)),
                  "approved": (control == "baseline" and checked["acceptance"]["status"] == "pass"
                               and checked["source_current"] == "verified" and gates["design_bearing"])}
        validate(result, "test-evaluation-v1")
        parent = target.root / "evaluations"
        parent.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".evaluation-", dir=parent) as temp:
            stage = Path(temp) / eid
            stage.mkdir()
            for name, value in (("evaluation", result), ("gates", gates), ("warrant", warrant), ("graph", snapshot)):
                write(stage / f"{name}.json", value)
            os.rename(stage, parent / eid)
        return result


def export_bundle(target: Target, evaluation_ids: list[str], output) -> dict:
    """Export selected historical snapshots; never run a new evaluation implicitly."""
    if not evaluation_ids or len(set(evaluation_ids)) != len(evaluation_ids):
        raise EvidenceError("Select unique evaluation IDs")
    output = Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise EvidenceError("Export destination must not already exist")
    with target.transaction():
        evaluations = []
        for eid in evaluation_ids:
            try:
                uuid.UUID(eid)
            except (ValueError, AttributeError) as exc:
                raise EvidenceError("Invalid evaluation identity") from exc
            value = load(safe_file(target.root, f"evaluations/{eid}/evaluation.json"))
            validate(value, "test-evaluation-v1")
            if value["evaluation_id"] != eid or value["target"] != target.id:
                raise EvidenceError("Evaluation target/identity mismatch")
            evaluations.append(value)
        if len({v["receipt_sha256"] for v in evaluations}) != 1:
            raise EvidenceError("One bundle binds exactly one execution receipt")
        digest = evaluations[0]["receipt_sha256"]
        source = target.root / "receipts" / digest
        checked = verify(source)
        if checked["receipt_sha256"] != digest:
            raise EvidenceError("Receipt archive identity mismatch")
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".export-", dir=output.parent) as temp:
            stage = Path(temp) / "bundle"
            shutil.copytree(source, stage, symlinks=True)
            for value in evaluations:
                eid = value["evaluation_id"]
                shutil.copytree(target.root / "evaluations" / eid, stage / "evaluations" / eid, symlinks=True)
            readme = ("# Runner-reported test evidence\n\n"
                      "This bundle is a historical record, not independent certification.\n"
                      "Inspect run.json for bounded scope, command, counts, exclusions, retention and artifact transformations.\n"
                      "Inspect evaluations/*/{evaluation,gates,warrant,graph}.json for the exact recorded inputs and verdicts.\n"
                      "Negative controls are labeled evaluation inputs; the execution receipt is unchanged.\n\n"
                      "Verify offline: superretometer evidence verify <bundle-directory>\n"
                      "To reproduce, supply your own trusted checkout, runner and explicit capture profile; imported commands never execute.\n"
                      "Current freshness requires an explicitly mapped matching checkout and a new evaluation.\n")
            (stage / "README.md").write_text(readme)
            index = {"schema_version": "evidence-bundle/v1", "receipt_sha256": digest,
                     "evaluation_ids": evaluation_ids, "files": {},
                     "trust": "runner-reported; checksums are not authenticity or independent certification"}
            for name in listed_files(stage):
                entry = file_entry(stage, name)
                index["files"][name] = {k: entry[k] for k in ("size", "sha256")}
            write(stage / "SHA256SUMS", index)
            verify(stage)
            os.rename(stage, output)
    return {"status": "exported", "bundle": str(output), "receipt_sha256": digest,
            "evaluation_ids": evaluation_ids, "manifest_sha256": sha((output / "SHA256SUMS").read_bytes())}
