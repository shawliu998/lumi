"""Shared local session runner for reviewed Xingce adaptive packs.

The runner is pack-agnostic: form/scoring/candidate details come only from the
validated subtype pack.  Draft packs cannot instantiate it.  It intentionally
keeps a short public projection separate from private scorer fields.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import hashlib
import secrets
from pathlib import Path
from typing import Any, Mapping

from hermes_domains.xingce_adaptive_pack import XingceAdaptivePackError, load_xingce_adaptive_pack, public_record_projection
from hermes_domains.xingce_adaptive_policy import Observation, XingceAdaptivePolicyError, diagnose_entry, independent_transfer_proposal, resolve_probe
from hermes_runtime.learner_state import LearnerStateError, LearnerStateStore
from hermes_runtime.store import EventStore, TraceVersionConflict


SCHEMA = "lumi.xingce-adaptive-session.v1"


class XingceAdaptiveSessionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class XingceAdaptiveSessionConfig:
    namespace_id: str = "human:local-lumi"
    evidence_origin: str = "human_local_interactive"
    learner_id: str = "local-lumi"

    def __post_init__(self) -> None:
        prefix = {"human_local_interactive": "human:", "evaluation_fixture": "eval:"}.get(self.evidence_origin)
        if prefix is None or not self.namespace_id.startswith(prefix):
            raise ValueError("adaptive session namespace must match its evidence origin")


class XingceAdaptiveSessionService:
    def __init__(self, database: str | Path, *, reviewed_pack_root: str | Path, config: XingceAdaptiveSessionConfig | None = None) -> None:
        self.database = str(database)
        self.config = config or XingceAdaptiveSessionConfig()
        try:
            pack = load_xingce_adaptive_pack(reviewed_pack_root, require_reviewed=True)
        except XingceAdaptivePackError as exc:
            raise XingceAdaptiveSessionError("content_review_required") from exc
        self.pack = pack
        self.records = tuple(pack["records"])
        self.index = {str(row["record_id"]): row for row in self.records}
        self.cause_index = {str(row["cause_id"]): row for row in pack["candidate_misconceptions"]}

    def workspace(self) -> dict[str, Any]:
        return {"schema_version": SCHEMA, "available": True, "local_only": True,
                "pack": {key: self.pack[key] for key in ("pack_id", "pack_version", "subtype_id", "module_id", "form")},
                "entry_items": [public_record_projection(row) for row in self.records if row["role"] in {"entry_diagnostic", "routing_diagnostic"}]}

    def start(self, *, entry_record_id: str, selected_response: str, confidence: str, elapsed_seconds: float, command_id: str, rationale: str | None = None) -> dict[str, Any]:
        entry = self._record(entry_record_id, {"entry_diagnostic", "routing_diagnostic"})
        observation = Observation(selected_response, confidence, elapsed_seconds, rationale=rationale)
        decision = diagnose_entry(self.records, scorer=self.pack["scorer"], entry_record_id=entry_record_id, observation=observation)
        run_id = "xa_" + hashlib.sha256(
            (self.config.namespace_id + "\x1f" + self.pack["subtype_id"] + "\x1f" + command_id).encode()
        ).hexdigest()[:36]
        public = self._entry_public(run_id, 1, entry, observation, decision)
        store, learner = EventStore(self.database), LearnerStateStore(self.database)
        try:
            events = store.events(run_id)
            if events:
                return self._replay_command(events, command_id, selected_response, confidence, elapsed_seconds)
            stage = "awaiting_probe" if decision.next_step == "probe" else "awaiting_transfer"
            event = store.append_if_version(run_id, 0, "xingce_adaptive_entry", self._payload(stage, command_id, {"entry_record_id": entry_record_id, "selected_response": selected_response, "confidence": confidence, "elapsed_seconds": elapsed_seconds, "rationale": rationale, "public_result": public}))
            self._append_evidence(learner, event, entry, observation, "attempt", decision.correct)
            for candidate in decision.candidates:
                learner.append_hypothesis(self._hypothesis(event, candidate.cause_id, "unconfirmed", entry))
            return public
        finally:
            learner.close(); store.close()

    def answer_probe(self, *, session_id: str, expected_version: int, selected_response: str, confidence: str, elapsed_seconds: float, command_id: str) -> dict[str, Any]:
        store, learner = EventStore(self.database), LearnerStateStore(self.database)
        try:
            events = self._events(store, session_id)
            if len(events) >= 2 and events[1].kind == "xingce_adaptive_probe":
                payload = events[1].payload
                if payload.get("command_id") != command_id or payload.get("selected_response") != selected_response or payload.get("confidence") != confidence or payload.get("elapsed_seconds") != elapsed_seconds:
                    raise XingceAdaptiveSessionError("command id is already bound to a different probe")
                return payload["public_result"]
            self._state(events, expected_version, "awaiting_probe")
            entry_event = events[0]; entry_id = str(entry_event.payload["entry_record_id"])
            entry_decision = diagnose_entry(self.records, scorer=self.pack["scorer"], entry_record_id=entry_id, observation=Observation(str(entry_event.payload["selected_response"]), str(entry_event.payload["confidence"]), float(entry_event.payload["elapsed_seconds"])))
            observation = Observation(selected_response, confidence, elapsed_seconds)
            resolution = resolve_probe(self.records, scorer=self.pack["scorer"], entry=entry_decision, observation=observation)
            probe = self._record(resolution.probe_record_id, {"probe"}); transfer = self._record(resolution.transfer_record_id, {"independent_transfer"})
            public = {"schema_version": SCHEMA, "session_id": session_id, "state_version": expected_version + 1, "stage": "awaiting_transfer", "probe": {**public_record_projection(probe), "selected_response": selected_response, "correct": resolution.correct, "evidence_updates": [{**row, "label": self._cause_label(str(row["cause_id"]))} for row in resolution.evidence_updates]}, "teaching": public_record_projection(self._record(resolution.teaching_record_id, {"teaching_asset"})) if resolution.teaching_record_id else None, "transfer": public_record_projection(transfer), "next_step": "answer_transfer"}
            event = store.append_if_version(session_id, expected_version, "xingce_adaptive_probe", self._payload("awaiting_transfer", command_id, {"selected_response": selected_response, "confidence": confidence, "elapsed_seconds": elapsed_seconds, "public_result": public}))
            self._append_evidence(learner, event, probe, observation, "probe_response", resolution.correct)
            for update in resolution.evidence_updates:
                learner.append_hypothesis(self._hypothesis(event, update["cause_id"], update["outcome"].replace("support", "supported").replace("refute", "refuted"), probe))
            return public
        finally:
            learner.close(); store.close()

    def answer_transfer(self, *, session_id: str, expected_version: int, selected_response: str, confidence: str, elapsed_seconds: float, command_id: str) -> dict[str, Any]:
        store, learner = EventStore(self.database), LearnerStateStore(self.database)
        try:
            events = self._events(store, session_id)
            if events[-1].kind == "xingce_adaptive_receipt":
                transfer_event, receipt = events[-2], events[-1].payload
                if transfer_event.payload.get("command_id") != command_id or transfer_event.payload.get("selected_response") != selected_response or transfer_event.payload.get("confidence") != confidence or transfer_event.payload.get("elapsed_seconds") != elapsed_seconds:
                    raise XingceAdaptiveSessionError("command id is already bound to a different transfer")
                return receipt["public_result"]
            if events[-1].kind == "xingce_adaptive_transfer":
                event = events[-1]
                self._same_transfer_command(event, command_id, selected_response, confidence, elapsed_seconds)
                return self._complete_transfer(store, learner, events, event)

            self._state(events, expected_version, "awaiting_transfer")
            event = store.append_if_version(
                session_id,
                expected_version,
                "xingce_adaptive_transfer",
                self._payload(
                    "committing_transfer",
                    command_id,
                    {
                        "selected_response": selected_response,
                        "confidence": confidence,
                        "elapsed_seconds": elapsed_seconds,
                    },
                ),
            )
            return self._complete_transfer(store, learner, events + [event], event)
        except (XingceAdaptivePolicyError, LearnerStateError, TraceVersionConflict) as exc:
            raise XingceAdaptiveSessionError(str(exc)) from exc
        finally:
            learner.close(); store.close()

    def _complete_transfer(self, store: EventStore, learner: LearnerStateStore, events: list, event: Any) -> dict[str, Any]:
        """Finish a persisted transfer command, including after a sidecar crash.

        The transfer trace event is the durable command boundary.  All learner
        writes use deterministic identifiers, so re-entering this method is
        safe whether the interruption occurred before, during, or after the
        learner-state writes.  Only the missing trace receipt is appended.
        """
        entry_event = events[0]
        entry_id = str(entry_event.payload["entry_record_id"])
        entry_decision = diagnose_entry(
            self.records,
            scorer=self.pack["scorer"],
            entry_record_id=entry_id,
            observation=Observation(
                str(entry_event.payload["selected_response"]),
                str(entry_event.payload["confidence"]),
                float(entry_event.payload["elapsed_seconds"]),
            ),
        )
        probe_event = next((row for row in events if row.kind == "xingce_adaptive_probe"), None)
        probe_decision = None
        if probe_event is not None:
            probe_decision = resolve_probe(
                self.records,
                scorer=self.pack["scorer"],
                entry=entry_decision,
                observation=Observation(
                    str(probe_event.payload["selected_response"]),
                    str(probe_event.payload["confidence"]),
                    float(probe_event.payload["elapsed_seconds"]),
                ),
            )
        observation = Observation(
            str(event.payload["selected_response"]),
            str(event.payload["confidence"]),
            float(event.payload["elapsed_seconds"]),
        )
        proposal = independent_transfer_proposal(
            self.records,
            scorer=self.pack["scorer"],
            entry=entry_decision,
            probe=probe_decision,
            observation=observation,
        )
        transfer_record_id = (
            probe_decision.transfer_record_id
            if probe_decision is not None
            else entry_decision.transfer_record_id
        )
        if transfer_record_id is None:
            raise XingceAdaptiveSessionError("session has no independent transfer")
        transfer = self._record(transfer_record_id, {"independent_transfer"})
        transfer_correct = next(
            fact["value"] for fact in proposal["evidence"] if fact["kind"] == "correctness"
        )
        evidence_id = self._append_evidence(
            learner, event, transfer, observation, "verification", bool(transfer_correct)
        )
        unseen_from = [
            "sha256:" + self._record(entry_id, {"entry_diagnostic", "routing_diagnostic"})["record_sha256"]
        ]
        if probe_decision is not None:
            unseen_from.append(
                "sha256:" + self._record(probe_decision.probe_record_id, {"probe"})["record_sha256"]
            )
        receipts = []
        for skill_id in transfer["target_skill_ids"]:
            current = learner.current_snapshot(
                namespace_id=self.config.namespace_id,
                evidence_origin=self.config.evidence_origin,
                learner_id=self.config.learner_id,
                skill_id=skill_id,
            )
            receipts.append(
                learner.commit_verification(
                    namespace_id=self.config.namespace_id,
                    evidence_origin=self.config.evidence_origin,
                    learner_id=self.config.learner_id,
                    skill_id=skill_id,
                    verification_id="vr_" + hashlib.sha256(f"{event.run_id}:{skill_id}".encode()).hexdigest()[:24],
                    evidence_event_id=evidence_id,
                    expected_state_version=int(current["state_version"]) if current else 0,
                    outcome="passed" if transfer_correct else "failed",
                    unseen_from_content_signatures=unseen_from,
                )
            )
        review = self._review_task(event.run_id, transfer, bool(proposal["eligible"]))
        learner.append_policy_decision(
            {
                "schema_version": "lumi.policy-decision.v1",
                "decision_id": "pd_" + hashlib.sha256(event.run_id.encode()).hexdigest()[:24],
                "namespace_id": self.config.namespace_id,
                "evidence_origin": self.config.evidence_origin,
                "learner_id": self.config.learner_id,
                "episode_id": "episode_" + event.run_id,
                "decision_type": "schedule_review",
                "selected_action_id": review["task_id"],
                "evidence_refs": [evidence_id],
                "review_task": review,
            }
        )
        public = {
            "schema_version": SCHEMA,
            "session_id": event.run_id,
            "state_version": event.seq + 1,
            "stage": "completed",
            "learning_route": "diagnostic_probe" if probe_decision is not None else "direct_verification",
            "transfer": {
                **public_record_projection(transfer),
                "selected_response": observation.selected_response,
                "correct": bool(proposal["eligible"]),
            },
            "state_update": {
                "eligible": proposal["eligible"],
                "reason": proposal["reason"],
                "receipts": [
                    {"skill_id": row["skill_id"], "state_version": row["state_version"], "state_delta": row["state_delta"]}
                    for row in receipts
                ],
            },
            "review_task": review,
            "next_step": "delayed_review" if proposal["eligible"] else "independent_retry",
        }
        try:
            store.append_if_version(
                event.run_id,
                event.seq,
                "xingce_adaptive_receipt",
                self._payload("completed", str(event.payload["command_id"]), {"public_result": public}),
            )
        except TraceVersionConflict:
            after = self._events(store, event.run_id)
            if len(after) >= 4 and after[-1].kind == "xingce_adaptive_receipt":
                self._same_transfer_command(
                    after[-2],
                    str(event.payload["command_id"]),
                    observation.selected_response,
                    observation.confidence,
                    observation.elapsed_seconds,
                )
                return after[-1].payload["public_result"]
            raise
        return public

    @staticmethod
    def _same_transfer_command(event: Any, command_id: str, selected_response: str, confidence: str, elapsed_seconds: float) -> None:
        if (
            event.payload.get("command_id") != command_id
            or event.payload.get("selected_response") != selected_response
            or event.payload.get("confidence") != confidence
            or event.payload.get("elapsed_seconds") != elapsed_seconds
        ):
            raise XingceAdaptiveSessionError("command id is already bound to a different transfer")

    def replay(self, session_id: str) -> dict[str, Any]:
        store = EventStore(self.database)
        try:
            events = self._events(store, session_id)
            if not store.verify(session_id): raise XingceAdaptiveSessionError("session trace verification failed")
            return {"schema_version":SCHEMA,"session_id":session_id,"trace_verified":True,"timeline":[{"seq":e.seq,"kind":e.kind,"stage_after":e.payload.get("stage_after"),"result":e.payload.get("public_result")} for e in events]}
        finally: store.close()

    def _entry_public(self, run_id: str, version: int, entry: Mapping[str, Any], o: Observation, d: Any) -> dict[str, Any]:
        stage = "awaiting_probe" if d.next_step == "probe" else "awaiting_transfer"
        result = {"schema_version":SCHEMA,"session_id":run_id,"state_version":version,"stage":stage,"entry":{**public_record_projection(entry),"selected_response":o.selected_response,"correct":d.correct,"confidence":o.confidence,"elapsed_seconds":o.elapsed_seconds},"candidate_causes":[{"cause_id":c.cause_id,"label":self._cause_label(c.cause_id),"status":"unconfirmed","rank":c.rank} for c in d.candidates],"next_step":"answer_probe" if d.next_step=="probe" else "answer_transfer"}
        if d.probe_record_id:
            result["probe"] = public_record_projection(self._record(d.probe_record_id,{"probe"}))
        if d.transfer_record_id:
            result["teaching"] = None
            result["transfer"] = public_record_projection(self._record(d.transfer_record_id,{"independent_transfer"}))
        return result

    def _payload(self, stage: str, command_id: str, fields: Mapping[str,Any]) -> dict[str,Any]: return {"schema_version":SCHEMA,"namespace_id":self.config.namespace_id,"evidence_origin":self.config.evidence_origin,"learner_id":self.config.learner_id,"stage_after":stage,"command_id":command_id,**fields}
    def _record(self, record_id: str, roles: set[str]) -> Mapping[str,Any]:
        r=self.index.get(record_id)
        if r is None or r.get("role") not in roles: raise XingceAdaptiveSessionError("pack record is unavailable")
        return r
    def _cause_label(self, cause_id: str) -> str:
        row = self.cause_index.get(cause_id)
        if row is None or not isinstance(row.get("label"), str) or not row["label"].strip():
            raise XingceAdaptiveSessionError("pack candidate cause is unavailable")
        return row["label"]
    def _events(self, store: EventStore, sid: str):
        events=store.events(sid)
        if not events or any(e.payload.get("namespace_id")!=self.config.namespace_id or e.payload.get("evidence_origin")!=self.config.evidence_origin for e in events): raise XingceAdaptiveSessionError("session unavailable")
        return events
    def _state(self, events: list, version:int, stage:str)->None:
        if not isinstance(version,int) or version!=events[-1].seq or events[-1].payload.get("stage_after")!=stage: raise XingceAdaptiveSessionError("stale or out-of-order session command")
    def _append_evidence(self, learner: LearnerStateStore,event: Any,record:Mapping[str,Any],o:Observation,kind:str,correct:bool)->str:
        eid="evt_"+event.run_id+"_"+kind
        role = "transfer" if record["role"] == "independent_transfer" else record["role"]
        learner.append_evidence({"schema_version":"lumi.evidence-event.v1","event_id":eid,"namespace_id":self.config.namespace_id,"evidence_origin":self.config.evidence_origin,"run_id":event.run_id,"trace_ref":{"run_id":event.run_id,"seq":event.seq,"event_hash":event.event_hash},"kind":kind,"content_ref":{"pack_id":self.pack["pack_id"],"pack_version":self.pack["pack_version"],"item_id":record["record_id"],"content_signature":"sha256:"+record["record_sha256"],"role":role},"observed":{"selected_response":o.selected_response,"correct":correct,"confidence":o.confidence,"response_time_seconds":o.elapsed_seconds,"hint_count":o.hint_count,"independently_answered":o.hint_count==0},"producer":{"kind":"deterministic_scorer","version":"xingce-type-policy-1.0.0"}}); return eid
    def _hypothesis(self,event:Any,cause:str,status:str,record:Mapping[str,Any])->dict[str,Any]: return {"schema_version":"lumi.diagnosis-hypothesis.v1","hypothesis_id":"dxh_"+event.run_id+"_"+cause+"_"+str(event.seq),"namespace_id":self.config.namespace_id,"evidence_origin":self.config.evidence_origin,"episode_id":"episode_"+event.run_id,"skill_id":record["target_skill_ids"][0],"learner_id":self.config.learner_id,"pack_id":self.pack["pack_id"],"pack_version":self.pack["pack_version"],"cause_id":cause,"status":status,"evidence_refs":["evt_"+event.run_id+("_attempt" if event.kind.endswith("entry") else "_probe_response")],"model":{"name":"lumi.xingce-type-policy","version":"1.0.0"}}
    def _review_task(self,sid:str,transfer:Mapping[str,Any],passed:bool)->dict[str,Any]:
        review=next(r for r in self.records if r["role"]=="delayed_review" and transfer["record_id"] in r["eligible_after_transfer_ids"]); days=review["scheduled_after_days"] if passed else 1
        return {"task_id":"xrt_"+hashlib.sha256(sid.encode()).hexdigest()[:24],"kind":"delayed_retention" if passed else "independent_retry","due_on":(date.today()+timedelta(days=days)).isoformat(),"source_session_id":sid,"item_selector":{"pack_id":self.pack["pack_id"],"record_id":review["record_id"]},"success_criterion":"无提示、独立、可确定评分的作答","skip_consequence":"学习状态保持证据有限；不会自动提高掌握状态。"}
    def _replay_command(self,events:list,command_id:str,response:str,confidence:str,elapsed:float)->dict[str,Any]:
        first=events[0]
        if first.payload.get("command_id")!=command_id or first.payload.get("selected_response")!=response or first.payload.get("confidence")!=confidence or first.payload.get("elapsed_seconds")!=elapsed: raise XingceAdaptiveSessionError("command id is already bound to a different answer")
        return first.payload["public_result"]
