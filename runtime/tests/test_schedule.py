from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from hermes_runtime.schedule import (
    ActivityRef,
    EvidenceRef,
    PlanningEvidence,
    ScheduleBudgetBelowAcceptedCommitment,
    ScheduleCommandConflict,
    ScheduleError,
    ScheduleStore,
    ScheduleValidationError,
    ScheduleVersionConflict,
    build_scheduler_decision,
)
from hermes_runtime.store import EventStore, _event_hash


def opaque_public_id(prefix: str, label: str) -> str:
    alphabet = "ABCDEFGHIJKLMNOP"
    digest = hashlib.sha256(label.encode("utf-8")).digest()[:20]
    encoded = "".join(
        f"{alphabet[byte >> 4]}{alphabet[byte & 15]}" for byte in digest
    )
    return f"{prefix}_{encoded}"


def test_command_id(label: str) -> str:
    if (
        label.startswith("c_")
        and len(label) == 42
        and all(character in "ABCDEFGHIJKLMNOP" for character in label[2:])
    ):
        return label
    return opaque_public_id("c", label)


class ScheduleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary.name) / "schedule.sqlite3"
        self.day = date(2026, 7, 11)
        content_store = EventStore(self.database)
        fixture_hash = content_store.put_content_snapshot(
            "domain_fixture",
            {
                "fixture_id": "xingce.data-analysis.growth-rate.synthetic-01",
                "domain": "xingce",
                "skills": [{"skill_id": "xingce.skill.review", "weight": 1.0}],
                "diagnosis": {
                    "candidate_causes": [
                        {
                            "cause_id": "authored-cause",
                            "label": "作者定义错因",
                        }
                    ]
                },
            },
        )
        content_store.close()
        self.activity = ActivityRef(
            fixture_id="xingce.data-analysis.growth-rate.synthetic-01",
            fixture_content_sha256=fixture_hash,
            availability="launchable",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def evidence(
        self,
        suffix: str,
        *,
        kind: str = "candidate_cause",
        occurred_on: date | None = None,
        effective: bool | None = None,
        failed: bool = True,
        activity: ActivityRef | None = None,
        event_time: str | None = None,
        timezone_offset_minutes: int = 0,
        evidence_origin: str = "human_local_interactive",
        later_verification_effective: bool | None = None,
        later_claim_status: str | None = None,
    ) -> PlanningEvidence:
        occurred = event_time or datetime.combine(
            occurred_on or (self.day - timedelta(days=1)),
            datetime.min.time(),
            tzinfo=timezone.utc,
        ).isoformat()
        local_day = occurred_on or (
            datetime.fromisoformat(occurred)
            + timedelta(minutes=timezone_offset_minutes)
        ).date()
        run_id = f"run-{suffix}"
        cause_id = "authored-cause"
        observe_payload = {
            "phase": "observe",
            "output": {"score": {"passed": not failed}},
            "state_after": {"status": "running"},
        }
        observe_hash = self._insert_trace_event(
            run_id, 1, occurred, "phase_completed", observe_payload, "GENESIS"
        )
        observe_pointer = "/output/score/passed"
        observe_ref = EvidenceRef(
            ref=(
                f"trace:{run_id}:event:1:{observe_hash}"
                f"#pointer={observe_pointer}"
            ),
            kind="trace_observation",
            source_type="trace_event",
            run_id=run_id,
            event_seq=1,
            event_hash=observe_hash,
            event_kind="phase_completed",
            json_pointer=observe_pointer,
            semantic="initial_answer_passed",
            phase="observe",
        )
        if kind == "candidate_cause":
            diagnose_payload = {
                "phase": "diagnose",
                "output": {
                    "diagnosis": {
                        "hypotheses": [
                            {
                                "cause_id": cause_id,
                                "status": "unconfirmed_hypothesis",
                            }
                        ]
                    }
                },
                "state_after": {"status": "running"},
            }
            diagnose_hash = self._insert_trace_event(
                run_id,
                2,
                occurred,
                "phase_completed",
                diagnose_payload,
                observe_hash,
            )
            diagnose_pointer = "/output/diagnosis/hypotheses/0/status"
            diagnose_ref = EvidenceRef(
                ref=(
                    f"trace:{run_id}:event:2:{diagnose_hash}"
                    f"#pointer={diagnose_pointer}"
                ),
                kind="candidate_cause",
                source_type="trace_event",
                run_id=run_id,
                event_seq=2,
                event_hash=diagnose_hash,
                event_kind="phase_completed",
                json_pointer=diagnose_pointer,
                semantic="candidate_hypothesis",
                subject_id=cause_id,
                phase="diagnose",
                claim_status="unconfirmed_hypothesis",
                confirmation_status="unconfirmed",
            )
            assessment_payload = {
                "assessments": [
                    {
                        "cause_id": cause_id,
                        "claim_status": "supported_hypothesis",
                    }
                ],
                "state_after": {"status": "interrupted"},
            }
            assessment_hash = self._insert_trace_event(
                run_id,
                3,
                occurred,
                "probe_assessed",
                assessment_payload,
                diagnose_hash,
            )
            assessment_pointer = "/assessments/0/claim_status"
            primary = EvidenceRef(
                ref=(
                    f"trace:{run_id}:event:3:{assessment_hash}"
                    f"#pointer={assessment_pointer}"
                ),
                kind="candidate_cause",
                source_type="trace_event",
                run_id=run_id,
                event_seq=3,
                event_hash=assessment_hash,
                event_kind="probe_assessed",
                json_pointer=assessment_pointer,
                semantic="candidate_claim_status",
                subject_id=cause_id,
                claim_status="supported_hypothesis",
                confirmation_status="unconfirmed",
            )
            previous_hash = assessment_hash
            terminal_seq = 4
            if later_claim_status is not None:
                later_payload = {
                    "assessments": [
                        {
                            "cause_id": cause_id,
                            "claim_status": later_claim_status,
                        }
                    ],
                    "state_after": {"status": "interrupted"},
                }
                previous_hash = self._insert_trace_event(
                    run_id,
                    terminal_seq,
                    occurred,
                    "probe_assessed",
                    later_payload,
                    previous_hash,
                )
                terminal_seq += 1
            candidate_supporting = (diagnose_ref, observe_ref)
        else:
            payload = {
                "phase": "update",
                "output": {
                    "commit_status": "committed",
                    "skill_id": "xingce.skill.review",
                    "evidence": {"verification_effective": effective},
                },
                "state_after": {"status": "running"},
            }
            pointer = "/output/evidence/verification_effective"
            event_hash = self._insert_trace_event(
                run_id, 2, occurred, "phase_completed", payload, observe_hash
            )
            primary = EvidenceRef(
                ref=f"trace:{run_id}:event:2:{event_hash}#pointer={pointer}",
                kind="trace_skill_evidence",
                source_type="trace_event",
                run_id=run_id,
                event_seq=2,
                event_hash=event_hash,
                event_kind="phase_completed",
                json_pointer=pointer,
                semantic="verification_effective",
                phase="update",
            )
            previous_hash = event_hash
            terminal_seq = 3
            if later_verification_effective is not None:
                later_payload = {
                    "phase": "update",
                    "output": {
                        "commit_status": "committed",
                        "skill_id": "xingce.skill.review",
                        "evidence": {
                            "verification_effective": later_verification_effective
                        },
                    },
                    "state_after": {"status": "running"},
                }
                previous_hash = self._insert_trace_event(
                    run_id,
                    terminal_seq,
                    occurred,
                    "phase_completed",
                    later_payload,
                    previous_hash,
                )
                terminal_seq += 1
            candidate_supporting = ()
        terminal_payload = {
            "phase": "reflect",
            "state_after": {
                "status": "completed",
                "domain": "xingce",
                "learner_id": "local-learner",
                "context": {
                    "scenario": "attempt",
                    "evidence_origin": evidence_origin,
                    "fixture_id": self.activity.fixture_id,
                    "fixture_content_sha256": self.activity.fixture_content_sha256,
                },
            },
        }
        terminal_hash = self._insert_trace_event(
            run_id,
            terminal_seq,
            occurred,
            "phase_completed",
            terminal_payload,
            previous_hash,
        )
        terminal = EvidenceRef(
            ref=(
                f"trace:{run_id}:event:{terminal_seq}:{terminal_hash}"
                "#pointer=/state_after/status"
            ),
            kind="trace_terminal",
            source_type="trace_event",
            run_id=run_id,
            event_seq=terminal_seq,
            event_hash=terminal_hash,
            event_kind="phase_completed",
            json_pointer="/state_after/status",
            semantic="terminal_completed",
            phase="reflect",
        )
        if kind == "candidate_cause":
            return PlanningEvidence(
                evidence_ref=primary,
                supporting_refs=(*candidate_supporting, terminal),
                occurred_at=occurred,
                occurred_on=local_day.isoformat(),
                timezone_offset_minutes=timezone_offset_minutes,
                domain="xingce",
                skill_id="xingce.skill.review",
                verification_effective=None,
                attempt_failed=failed,
                cause_id=cause_id,
                cause_label="作者定义错因",
                activity_ref=activity or self.activity,
            )
        return PlanningEvidence(
            evidence_ref=primary,
            supporting_refs=(observe_ref, terminal),
            occurred_at=occurred,
            occurred_on=local_day.isoformat(),
            timezone_offset_minutes=timezone_offset_minutes,
            domain="xingce",
            skill_id="xingce.skill.review",
            verification_effective=effective,
            attempt_failed=failed,
            activity_ref=activity or self.activity,
        )

    def _insert_trace_event(
        self,
        run_id: str,
        seq: int,
        occurred_at: str,
        kind: str,
        payload: dict,
        previous_hash: str,
    ) -> str:
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        event_hash = _event_hash(
            run_id, seq, occurred_at, kind, encoded, previous_hash
        )
        connection = sqlite3.connect(self.database)
        try:
            connection.execute(
                "INSERT INTO trace_events VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    seq,
                    occurred_at,
                    kind,
                    encoded,
                    previous_hash,
                    event_hash,
                ),
            )
            connection.commit()
        finally:
            connection.close()
        return event_hash

    def decision(
        self,
        evidence: list[PlanningEvidence],
        *,
        day: date | None = None,
        budget: int = 60,
    ):
        target = day or self.day
        return build_scheduler_decision(
            evidence,
            plan_date=target.isoformat(),
            exam_date=(target + timedelta(days=30)).isoformat(),
            daily_budget_minutes=budget,
        )

    def create(
        self,
        store: ScheduleStore,
        evidence: list[PlanningEvidence],
        *,
        day: date | None = None,
        budget: int = 60,
        command_id: str = "create-plan",
        raw_command_id: bool = False,
    ):
        target = day or self.day
        return store.create_today_plan(
            plan_date=target.isoformat(),
            exam_date=(target + timedelta(days=30)).isoformat(),
            daily_budget_minutes=budget,
            expected_version=0,
            command_id=(command_id if raw_command_id else test_command_id(command_id)),
            evidence=evidence,
        )

    def test_no_evidence_creates_honest_empty_replayable_plan(self) -> None:
        store = ScheduleStore(self.database)
        plan = self.create(store, [])
        self.assertEqual(plan["status"], "empty")
        self.assertEqual(plan["empty_reason"], "no_recorded_evidence")
        self.assertEqual(plan["tasks"], [])
        self.assertFalse(plan["mastery_write_capability"])
        self.assertTrue(plan["event_stream"]["trace_verified"])
        replay = store.replay("today_plan", plan["plan_id"])
        self.assertEqual(replay["frames"][-1]["state"]["empty_reason"], "no_recorded_evidence")
        store.close()

    def test_budget_never_selects_an_over_budget_task(self) -> None:
        store = ScheduleStore(self.database)
        plan = self.create(store, [self.evidence("budget")], budget=5)
        self.assertEqual(plan["tasks"], [])
        self.assertEqual(plan["empty_reason"], "no_task_within_guardrail")
        self.assertEqual(store.review_schedule()["count"], 1)
        self.assertLessEqual(
            sum(item["expected_duration_minutes"] for item in plan["tasks"]), 5
        )
        store.close()

    def test_task_copy_and_activity_disclose_same_fixture_retest_limit(self) -> None:
        decision = self.decision(
            [
                self.evidence("copy-cause"),
                self.evidence(
                    "copy-retention",
                    kind="trace_skill_evidence",
                    occurred_on=self.day - timedelta(days=5),
                    effective=True,
                    failed=False,
                ),
                self.evidence(
                    "copy-retry",
                    kind="trace_skill_evidence",
                    effective=False,
                    failed=True,
                ),
            ]
        )
        self.assertEqual(
            {task.task_kind for task in decision.candidate_tasks},
            {"cause_probe", "delayed_retention", "independent_retry"},
        )
        for task in decision.candidate_tasks:
            self.assertEqual(
                task.activity_ref.novelty_status,
                "same_fixture_retest_not_novel_item",
            )
            self.assertIn("同题组独立复测", task.success_criterion)
            self.assertIn("未见平行题", task.success_criterion)
            self.assertNotIn("无提示的新题", task.success_criterion)
            self.assertIn("公平轮候", task.skip_consequence)
            self.assertNotIn("下一学习日", task.skip_consequence)

    def test_command_results_are_exactly_idempotent_and_conflicts_fail_closed(self) -> None:
        store = ScheduleStore(self.database)
        plan = self.create(store, [self.evidence("idem")], command_id="create-idem")
        replayed_create = self.create(
            store, [], command_id="create-idem"
        )
        self.assertEqual(replayed_create, plan)
        task_id = plan["tasks"][0]["task_id"]
        accepted = store.transition_task(
            plan_id=plan["plan_id"],
            task_id=task_id,
            action="accept",
            action_date=self.day.isoformat(),
            expected_version=1,
            expected_task_version=1,
            command_id=test_command_id("task-idem"),
        )
        replayed = store.transition_task(
            plan_id=plan["plan_id"],
            task_id=task_id,
            action="accept",
            action_date=(self.day + timedelta(days=1)).isoformat(),
            expected_version=1,
            expected_task_version=1,
            command_id=test_command_id("task-idem"),
        )
        self.assertEqual(replayed, accepted)
        with self.assertRaises(ScheduleCommandConflict):
            store.transition_task(
                plan_id=plan["plan_id"],
                task_id=task_id,
                action="skip",
                action_date=self.day.isoformat(),
                expected_version=1,
                expected_task_version=1,
                command_id=test_command_id("task-idem"),
            )
        self.assertEqual(len(store.events("today_plan", plan["plan_id"])), 2)
        store.close()

    def test_two_connections_with_same_version_accept_exactly_one_write(self) -> None:
        seed = ScheduleStore(self.database)
        plan = self.create(seed, [self.evidence("cas")], command_id="create-cas")
        task_id = plan["tasks"][0]["task_id"]
        seed.close()
        barrier = threading.Barrier(3)

        def accept(command_id: str):
            store = ScheduleStore(self.database)
            barrier.wait(timeout=3)
            try:
                result = store.transition_task(
                    plan_id=plan["plan_id"],
                    task_id=task_id,
                    action="accept",
                    action_date=self.day.isoformat(),
                    expected_version=1,
                    expected_task_version=1,
                    command_id=test_command_id(command_id),
                )
                return result
            except ScheduleVersionConflict as error:
                return error
            finally:
                store.close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(accept, "cas-one"),
                executor.submit(accept, "cas-two"),
            ]
            barrier.wait(timeout=3)
            results = [future.result(timeout=5) for future in futures]
        self.assertEqual(sum(isinstance(item, dict) for item in results), 1)
        self.assertEqual(
            sum(isinstance(item, ScheduleVersionConflict) for item in results), 1
        )
        audit = ScheduleStore(self.database)
        self.assertEqual(len(audit.events("today_plan", plan["plan_id"])), 2)
        self.assertTrue(audit.verify("today_plan", plan["plan_id"]))
        audit.close()

    def test_skipped_and_postponed_tasks_necessarily_resurface_when_due(self) -> None:
        store = ScheduleStore(self.database)
        evidence = [self.evidence("skip"), self.evidence("postpone")]
        plan = self.create(store, evidence, command_id="create-resurface")
        first, second = [item["task_id"] for item in plan["tasks"]]
        skipped = store.transition_task(
            plan_id=plan["plan_id"],
            task_id=first,
            action="skip",
            action_date=self.day.isoformat(),
            expected_version=1,
            expected_task_version=1,
            command_id=test_command_id("skip-task"),
        )
        postponed = store.transition_task(
            plan_id=plan["plan_id"],
            task_id=second,
            action="postpone",
            action_date=self.day.isoformat(),
            postpone_until=(self.day + timedelta(days=1)).isoformat(),
            expected_version=skipped["version"],
            expected_task_version=1,
            command_id=test_command_id("postpone-task"),
        )
        tomorrow = self.day + timedelta(days=1)
        postponed_replay = store.transition_task(
            plan_id=plan["plan_id"],
            task_id=second,
            action="postpone",
            action_date=tomorrow.isoformat(),
            postpone_until=tomorrow.isoformat(),
            expected_version=skipped["version"],
            expected_task_version=1,
            command_id=test_command_id("postpone-task"),
        )
        self.assertEqual(postponed_replay, postponed)
        resurfaced = self.create(
            store,
            evidence,
            day=tomorrow,
            command_id="create-next-day",
        )
        self.assertEqual({item["task_id"] for item in resurfaced["tasks"]}, {first, second})
        self.assertTrue(all(item["state"] == "scheduled" for item in resurfaced["tasks"]))
        for task_id in (first, second):
            self.assertEqual(
                store.events("review_task", task_id)[-1].kind, "task_resurfaced"
            )
        old_replay = store.replay("today_plan", plan["plan_id"])
        self.assertTrue(old_replay["projection_verified"])
        self.assertTrue(
            store.load_plan(plan["plan_id"])["event_stream"]["projection_verified"]
        )
        self.assertEqual(
            [item["state"] for item in old_replay["frames"][-1]["state"]["tasks"]],
            ["skipped", "postponed"],
        )
        store.close()

    def test_user_marked_completion_does_not_touch_trace_or_kt_evidence(self) -> None:
        trace_store = EventStore(self.database)
        trace_store.append("real-run", "phase_completed", {"phase": "update", "output": {"skill_id": "s"}})
        before = trace_store.events("real-run")
        trace_store.close()

        store = ScheduleStore(self.database)
        plan = self.create(store, [self.evidence("complete")], command_id="create-complete")
        task_id = plan["tasks"][0]["task_id"]
        accepted = store.transition_task(
            plan_id=plan["plan_id"],
            task_id=task_id,
            action="accept",
            action_date=self.day.isoformat(),
            expected_version=1,
            expected_task_version=1,
            command_id=test_command_id("accept-complete"),
        )
        completed = store.transition_task(
            plan_id=plan["plan_id"],
            task_id=task_id,
            action="complete",
            action_date=self.day.isoformat(),
            expected_version=accepted["version"],
            expected_task_version=2,
            command_id=test_command_id("mark-complete"),
        )
        self.assertEqual(
            completed["tasks"][0]["completion_semantics"],
            "user_marked_not_learning_evidence",
        )
        self.assertFalse(completed["mastery_write_capability"])
        store.close()

        reopened = EventStore(self.database)
        self.assertEqual(reopened.events("real-run"), before)
        self.assertTrue(reopened.verify("real-run"))
        reopened.close()

    def test_successful_transfer_creates_fixed_unvalidated_delayed_review(self) -> None:
        store = ScheduleStore(self.database)
        evidence = [
            self.evidence(
                "retention",
                kind="trace_skill_evidence",
                occurred_on=self.day,
                effective=True,
                failed=False,
            )
        ]
        today = self.create(store, evidence, command_id="create-retention")
        self.assertEqual(today["empty_reason"], "no_task_due_today")
        schedule = store.review_schedule()
        self.assertEqual(schedule["items"][0]["task_kind"], "delayed_retention")
        self.assertEqual(
            schedule["items"][0]["due_on"], (self.day + timedelta(days=3)).isoformat()
        )
        due = self.create(
            store,
            evidence,
            day=self.day + timedelta(days=3),
            command_id="create-retention-due",
        )
        self.assertEqual(len(due["tasks"]), 1)
        self.assertEqual(due["tasks"][0]["definition_status"], "authored_engineering_estimate_unvalidated")
        store.close()

    def test_overdue_retry_exposes_policy_window_and_actual_catch_up_date(self) -> None:
        store = ScheduleStore(self.database)
        evidence_day = self.day - timedelta(days=5)
        plan = self.create(
            store,
            [
                self.evidence(
                    "overdue-retry",
                    kind="trace_skill_evidence",
                    occurred_on=evidence_day,
                    effective=False,
                    failed=True,
                )
            ],
            command_id="create-overdue-retry",
        )
        task = plan["tasks"][0]
        self.assertEqual(task["task_kind"], "independent_retry")
        self.assertEqual(task["policy_offset_days"], 1)
        self.assertEqual(
            task["base_due_on"], (evidence_day + timedelta(days=1)).isoformat()
        )
        self.assertEqual(task["initial_due_on"], self.day.isoformat())
        self.assertEqual(task["due_on"], self.day.isoformat())
        self.assertEqual(task["scheduling_adjustment"], "overdue_catch_up")
        self.assertEqual(
            task["schedule_window"],
            {
                "policy_offset_days": 1,
                "base_due_on": (evidence_day + timedelta(days=1)).isoformat(),
                "initial_due_on": self.day.isoformat(),
                "scheduling_adjustment": "overdue_catch_up",
                "calibration": "fixed_engineering_policy_unvalidated",
                "exam_adjustment": "withhold_if_due_after_exam",
            },
        )
        self.assertNotIn("applied_offset_days", task["schedule_window"])
        self.assertIn("窗口已错过", task["reason"])
        store.close()

    def test_overdue_retention_exposes_missed_plus_three_without_false_claim(self) -> None:
        store = ScheduleStore(self.database)
        evidence_day = self.day - timedelta(days=8)
        plan = self.create(
            store,
            [
                self.evidence(
                    "overdue-retention",
                    kind="trace_skill_evidence",
                    occurred_on=evidence_day,
                    effective=True,
                    failed=False,
                )
            ],
            command_id="create-overdue-retention",
        )
        task = plan["tasks"][0]
        self.assertEqual(task["task_kind"], "delayed_retention")
        self.assertEqual(task["policy_offset_days"], 3)
        self.assertEqual(
            task["base_due_on"], (evidence_day + timedelta(days=3)).isoformat()
        )
        self.assertEqual(task["initial_due_on"], self.day.isoformat())
        self.assertEqual(task["scheduling_adjustment"], "overdue_catch_up")
        self.assertIn("不代表仍按 +3 天执行", task["reason"])
        self.assertNotIn("applied_offset_days", task["schedule_window"])
        store.close()

    def test_completed_overdue_task_is_not_recounted_on_the_next_day(self) -> None:
        store = ScheduleStore(self.database)
        evidence = [
            self.evidence(
                "completed-overdue",
                kind="trace_skill_evidence",
                occurred_on=self.day - timedelta(days=5),
                effective=False,
                failed=True,
            )
        ]
        plan = self.create(
            store,
            evidence,
            command_id="create-completed-overdue",
        )
        task = plan["tasks"][0]
        self.assertEqual(
            plan["basis"]["workload_guardrail"]["overdue_catch_up_count"], 1
        )
        accepted = store.transition_task(
            plan_id=plan["plan_id"],
            task_id=task["task_id"],
            action="accept",
            action_date=self.day.isoformat(),
            expected_version=plan["version"],
            expected_task_version=task["version"],
            command_id=test_command_id("accept-completed-overdue"),
        )
        store.transition_task(
            plan_id=plan["plan_id"],
            task_id=task["task_id"],
            action="complete",
            action_date=self.day.isoformat(),
            expected_version=accepted["version"],
            expected_task_version=accepted["tasks"][0]["version"],
            command_id=test_command_id("complete-overdue"),
        )
        tomorrow = self.create(
            store,
            evidence,
            day=self.day + timedelta(days=1),
            command_id="create-after-completed-overdue",
        )
        self.assertEqual(tomorrow["tasks"], [])
        self.assertEqual(tomorrow["empty_reason"], "no_pending_review_tasks")
        self.assertEqual(
            tomorrow["basis"]["workload_guardrail"]["overdue_catch_up_count"],
            0,
        )
        store.close()

    def test_missed_existing_on_policy_task_does_not_turn_into_catch_up(self) -> None:
        store = ScheduleStore(self.database)
        evidence = [
            self.evidence(
                "missed-on-policy",
                kind="trace_skill_evidence",
                occurred_on=self.day,
                effective=False,
                failed=True,
            )
        ]
        seed = self.create(
            store,
            evidence,
            command_id="create-missed-on-policy-seed",
        )
        self.assertEqual(seed["empty_reason"], "no_task_due_today")
        late = self.create(
            store,
            evidence,
            day=self.day + timedelta(days=2),
            command_id="create-missed-on-policy-late",
        )
        self.assertEqual(len(late["tasks"]), 1)
        self.assertEqual(
            late["tasks"][0]["scheduling_adjustment"], "on_policy_window"
        )
        self.assertEqual(
            late["basis"]["workload_guardrail"]["overdue_catch_up_count"], 0
        )
        store.close()

    def test_evidence_older_than_fourteen_days_is_persisted_not_starved(self) -> None:
        store = ScheduleStore(self.database)
        evidence_day = self.day - timedelta(days=30)
        plan = self.create(
            store,
            [
                self.evidence(
                    "old-evidence",
                    kind="trace_skill_evidence",
                    occurred_on=evidence_day,
                    effective=False,
                    failed=True,
                )
            ],
            command_id="create-old-evidence",
        )
        self.assertEqual(plan["basis"]["evidence_status"], "recorded")
        self.assertEqual(
            plan["basis"]["workload_guardrail"]["recent_evidence_count"], 0
        )
        self.assertEqual(
            plan["basis"]["workload_guardrail"]["eligible_evidence_count"], 1
        )
        self.assertEqual(len(plan["tasks"]), 1)
        self.assertEqual(store.review_schedule()["count"], 1)
        self.assertEqual(
            plan["tasks"][0]["scheduling_adjustment"], "overdue_catch_up"
        )
        store.close()

    def test_recovery_load_persists_all_candidates_and_surfaces_each_one(self) -> None:
        store = ScheduleStore(self.database)
        evidence = [
            self.evidence(
                f"recovery-{index}",
                kind="trace_skill_evidence",
                effective=False,
                failed=True,
            )
            for index in range(3)
        ]
        first = self.create(
            store,
            evidence,
            command_id="create-recovery-one",
        )
        self.assertEqual(
            first["basis"]["workload_guardrail"]["max_non_accepted_tasks"], 1
        )
        self.assertEqual(len(first["tasks"]), 1)
        self.assertEqual(store.review_schedule()["count"], 3)

        surfaced: list[str] = []
        plan = first
        for index in range(3):
            self.assertEqual(len(plan["tasks"]), 1)
            task = plan["tasks"][0]
            surfaced.append(task["task_id"])
            accepted = store.transition_task(
                plan_id=plan["plan_id"],
                task_id=task["task_id"],
                action="accept",
                action_date=(self.day + timedelta(days=index)).isoformat(),
                expected_version=plan["version"],
                expected_task_version=task["version"],
                command_id=test_command_id(f"accept-recovery-{index}"),
            )
            store.transition_task(
                plan_id=plan["plan_id"],
                task_id=task["task_id"],
                action="complete",
                action_date=(self.day + timedelta(days=index)).isoformat(),
                expected_version=accepted["version"],
                expected_task_version=accepted["tasks"][0]["version"],
                command_id=test_command_id(f"complete-recovery-{index}"),
            )
            if index < 2:
                plan = self.create(
                    store,
                    evidence,
                    day=self.day + timedelta(days=index + 1),
                    command_id=f"create-recovery-{index + 2}",
                )

        self.assertEqual(len(set(surfaced)), 3)
        self.assertTrue(
            all(item["state"] == "completed" for item in store.review_schedule()["items"])
        )
        store.close()

    def test_repeated_skip_rotates_due_recovery_tasks_without_starvation(self) -> None:
        store = ScheduleStore(self.database)
        evidence = [
            self.evidence(
                f"skip-rotation-{index}",
                kind="trace_skill_evidence",
                effective=False,
                failed=True,
            )
            for index in range(3)
        ]
        plan = self.create(
            store,
            evidence,
            command_id="create-skip-rotation-0",
        )
        surfaced: list[str] = []
        for index in range(5):
            self.assertEqual(len(plan["tasks"]), 1)
            task = plan["tasks"][0]
            surfaced.append(task["task_id"])
            store.transition_task(
                plan_id=plan["plan_id"],
                task_id=task["task_id"],
                action="skip",
                action_date=(self.day + timedelta(days=index)).isoformat(),
                expected_version=plan["version"],
                expected_task_version=task["version"],
                command_id=test_command_id(f"skip-rotation-{index}"),
            )
            if index < 4:
                plan = self.create(
                    store,
                    evidence,
                    day=self.day + timedelta(days=index + 1),
                    command_id=f"create-skip-rotation-{index + 1}",
                )

        self.assertEqual(len(set(surfaced[:3])), 3)
        self.assertTrue(
            all(left != right for left, right in zip(surfaced, surfaced[1:]))
        )
        self.assertEqual(store.review_schedule()["count"], 3)
        store.close()

    def test_accepted_commitment_remains_actionable_in_the_next_day_plan(self) -> None:
        store = ScheduleStore(self.database)
        evidence = [
            self.evidence(
                f"accepted-carry-{index}",
                kind="trace_skill_evidence",
                effective=False,
                failed=True,
            )
            for index in range(3)
        ]
        first = self.create(
            store,
            evidence,
            command_id="create-accepted-carry",
        )
        task = first["tasks"][0]
        accepted = store.transition_task(
            plan_id=first["plan_id"],
            task_id=task["task_id"],
            action="accept",
            action_date=self.day.isoformat(),
            expected_version=first["version"],
            expected_task_version=task["version"],
            command_id=test_command_id("accept-carry"),
        )
        tomorrow = self.create(
            store,
            evidence,
            day=self.day + timedelta(days=1),
            command_id="create-accepted-carry-next",
        )
        self.assertEqual(tomorrow["tasks"][0]["task_id"], task["task_id"])
        self.assertEqual(tomorrow["tasks"][0]["state"], "accepted")
        completed = store.transition_task(
            plan_id=tomorrow["plan_id"],
            task_id=task["task_id"],
            action="complete",
            action_date=(self.day + timedelta(days=1)).isoformat(),
            expected_version=tomorrow["version"],
            expected_task_version=accepted["tasks"][0]["version"],
            command_id=test_command_id("complete-carried-task"),
        )
        self.assertEqual(
            next(
                item["state"]
                for item in completed["tasks"]
                if item["task_id"] == task["task_id"]
            ),
            "completed",
        )
        self.assertEqual(completed["status"], "active")
        store.close()

    def test_low_budget_cannot_persist_a_plan_that_hides_an_accepted_task(self) -> None:
        store = ScheduleStore(self.database)
        evidence = [
            self.evidence(
                "accepted-budget",
                kind="trace_skill_evidence",
                effective=False,
                failed=True,
            )
        ]
        plan = self.create(
            store,
            evidence,
            command_id="create-accepted-budget",
        )
        task = plan["tasks"][0]
        accepted = store.transition_task(
            plan_id=plan["plan_id"],
            task_id=task["task_id"],
            action="accept",
            action_date=self.day.isoformat(),
            expected_version=plan["version"],
            expected_task_version=task["version"],
            command_id=test_command_id("accept-budget-task"),
        )
        tomorrow = self.day + timedelta(days=1)
        with self.assertRaises(ScheduleBudgetBelowAcceptedCommitment):
            self.create(
                store,
                evidence,
                day=tomorrow,
                budget=5,
                command_id="create-too-small-budget",
            )
        self.assertIsNone(
            store._connection.execute(
                "SELECT 1 FROM today_plans WHERE plan_date = ?",
                (tomorrow.isoformat(),),
            ).fetchone()
        )
        unchanged = store.review_schedule()["items"][0]
        self.assertEqual(unchanged["state"], "accepted")
        self.assertEqual(unchanged["version"], accepted["tasks"][0]["version"])

        retried = self.create(
            store,
            evidence,
            day=tomorrow,
            budget=60,
            command_id="create-large-enough-budget",
        )
        self.assertEqual(retried["tasks"][0]["task_id"], task["task_id"])
        self.assertEqual(retried["tasks"][0]["state"], "accepted")
        store.close()

    def test_all_accepted_commitments_survive_recovery_mode_task_cap(self) -> None:
        store = ScheduleStore(self.database)
        evidence = [
            self.evidence(
                f"accepted-cap-success-{index}",
                kind="trace_skill_evidence",
                occurred_on=self.day - timedelta(days=5),
                effective=True,
                failed=False,
            )
            for index in range(3)
        ]
        plan = self.create(
            store,
            evidence,
            command_id="create-accepted-cap",
        )
        accepted_ids = [task["task_id"] for task in plan["tasks"]]
        self.assertEqual(len(accepted_ids), 3)
        current = plan
        for index, task_id in enumerate(accepted_ids):
            current_task = next(
                task for task in current["tasks"] if task["task_id"] == task_id
            )
            current = store.transition_task(
                plan_id=current["plan_id"],
                task_id=task_id,
                action="accept",
                action_date=self.day.isoformat(),
                expected_version=current["version"],
                expected_task_version=current_task["version"],
                command_id=test_command_id(f"accept-cap-{index}"),
            )

        evidence.extend(
            self.evidence(
                f"accepted-cap-failure-{index}",
                kind="trace_skill_evidence",
                occurred_on=self.day,
                effective=False,
                failed=True,
            )
            for index in range(3)
        )
        tomorrow = self.create(
            store,
            evidence,
            day=self.day + timedelta(days=1),
            budget=60,
            command_id="create-accepted-cap-recovery",
        )
        self.assertEqual(
            tomorrow["basis"]["workload_guardrail"]["max_non_accepted_tasks"], 1
        )
        self.assertEqual(
            {
                task["task_id"]
                for task in tomorrow["tasks"]
                if task["state"] == "accepted"
            },
            set(accepted_ids),
        )
        self.assertLessEqual(
            sum(task["state"] != "accepted" for task in tomorrow["tasks"]), 1
        )
        store.close()

    def test_aging_prevents_old_skipped_task_starvation_under_daily_arrivals(self) -> None:
        store = ScheduleStore(self.database)
        evidence = [
            self.evidence(
                f"aging-seed-{index}",
                kind="trace_skill_evidence",
                effective=False,
                failed=True,
            )
            for index in range(3)
        ]
        plan = self.create(
            store,
            evidence,
            command_id="create-aging-0",
        )
        first_task_id = plan["tasks"][0]["task_id"]
        surfaced = [first_task_id]
        for index in range(8):
            task = plan["tasks"][0]
            store.transition_task(
                plan_id=plan["plan_id"],
                task_id=task["task_id"],
                action="skip",
                action_date=(self.day + timedelta(days=index)).isoformat(),
                expected_version=plan["version"],
                expected_task_version=task["version"],
                command_id=test_command_id(f"skip-aging-{index}"),
            )
            evidence.append(
                self.evidence(
                    f"aging-arrival-{index}",
                    kind="trace_skill_evidence",
                    occurred_on=self.day + timedelta(days=index),
                    effective=False,
                    failed=True,
                )
            )
            plan = self.create(
                store,
                evidence,
                day=self.day + timedelta(days=index + 1),
                command_id=f"create-aging-{index + 1}",
            )
            surfaced.append(plan["tasks"][0]["task_id"])

        self.assertIn(first_task_id, surfaced[1:6])
        self.assertGreater(store.review_schedule()["count"], 3)
        store.close()

    def test_fresh_schedule_store_initialization_is_concurrency_safe(self) -> None:
        for index in range(12):
            database = Path(self.temporary.name) / f"fresh-{index}.sqlite3"
            barrier = threading.Barrier(3)

            def open_and_close() -> None:
                barrier.wait(timeout=3)
                instance = ScheduleStore(database)
                instance.close()

            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [executor.submit(open_and_close) for _ in range(2)]
                barrier.wait(timeout=3)
                for future in futures:
                    future.result(timeout=10)

    def test_partial_schedule_migration_restart_repairs_all_nullable_fields(self) -> None:
        store = ScheduleStore(self.database)
        plan = self.create(
            store,
            [
                self.evidence(
                    "partial-migration",
                    kind="trace_skill_evidence",
                    effective=False,
                    failed=True,
                )
            ],
            command_id="create-partial-migration",
        )
        task_id = plan["tasks"][0]["task_id"]
        store.close()

        connection = sqlite3.connect(self.database)
        try:
            connection.executescript(
                """
                PRAGMA foreign_keys = OFF;
                BEGIN IMMEDIATE;
                CREATE TABLE review_schedule_tasks_partial (
                    task_id TEXT PRIMARY KEY,
                    source_key TEXT NOT NULL UNIQUE,
                    task_kind TEXT NOT NULL,
                    domain TEXT NOT NULL,
                    skill_id TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    expected_duration_minutes INTEGER NOT NULL,
                    success_criterion TEXT NOT NULL,
                    skip_consequence TEXT NOT NULL,
                    evidence_refs_json TEXT NOT NULL,
                    activity_ref_json TEXT NOT NULL,
                    cause_id TEXT,
                    cause_label TEXT,
                    cause_confirmation_status TEXT,
                    definition_status TEXT NOT NULL,
                    policy_offset_days INTEGER,
                    base_due_on TEXT,
                    initial_due_on TEXT,
                    scheduling_adjustment TEXT,
                    completion_semantics TEXT,
                    state TEXT NOT NULL,
                    due_on TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                INSERT INTO review_schedule_tasks_partial
                SELECT task_id, source_key, task_kind, domain, skill_id, reason,
                       expected_duration_minutes, success_criterion, skip_consequence,
                       evidence_refs_json, activity_ref_json, cause_id, cause_label,
                       cause_confirmation_status, definition_status,
                       NULL, NULL, NULL, NULL,
                       completion_semantics, state, due_on, version, created_at, updated_at
                FROM review_schedule_tasks;

                CREATE TABLE today_plan_tasks_partial (
                    plan_id TEXT NOT NULL REFERENCES today_plans(plan_id),
                    task_id TEXT NOT NULL REFERENCES review_schedule_tasks(task_id),
                    ordinal INTEGER NOT NULL,
                    state TEXT NOT NULL,
                    task_snapshot_json TEXT,
                    PRIMARY KEY(plan_id, task_id),
                    UNIQUE(plan_id, ordinal)
                );
                INSERT INTO today_plan_tasks_partial
                SELECT plan_id, task_id, ordinal, state, NULL
                FROM today_plan_tasks;

                DROP TABLE today_plan_tasks;
                DROP TABLE review_schedule_tasks;
                ALTER TABLE review_schedule_tasks_partial RENAME TO review_schedule_tasks;
                ALTER TABLE today_plan_tasks_partial RENAME TO today_plan_tasks;
                COMMIT;
                PRAGMA foreign_keys = ON;
                """
            )
        finally:
            connection.close()

        recovered = ScheduleStore(self.database)
        task = next(
            item
            for item in recovered.review_schedule()["items"]
            if item["task_id"] == task_id
        )
        self.assertEqual(task["policy_offset_days"], 1)
        self.assertEqual(task["base_due_on"], task["due_on"])
        self.assertEqual(task["initial_due_on"], task["due_on"])
        self.assertEqual(task["scheduling_adjustment"], "on_policy_window")
        restored_plan = recovered.load_plan(plan["plan_id"])
        self.assertEqual(restored_plan["tasks"][0]["task_id"], task_id)
        self.assertEqual(restored_plan["tasks"][0]["policy_offset_days"], 1)
        with self.assertRaises(sqlite3.IntegrityError):
            recovered._connection.execute(
                "UPDATE review_schedule_tasks SET policy_offset_days = 3 WHERE task_id = ?",
                (task_id,),
            )
        recovered.close()

        healthy_reopen = ScheduleStore(self.database)
        self.assertEqual(healthy_reopen._connection.total_changes, 0)
        healthy_reopen.close()

    def test_pre_novelty_contract_migrates_with_audit_events_and_supersedes_receipts(self) -> None:
        store = ScheduleStore(self.database)
        create_command_id = test_command_id("create-legacy-contract")
        plan = self.create(
            store,
            [self.evidence("legacy-contract")],
            command_id=create_command_id,
        )
        task = plan["tasks"][0]
        accepted = store.transition_task(
            plan_id=plan["plan_id"],
            task_id=task["task_id"],
            action="accept",
            action_date=self.day.isoformat(),
            expected_version=plan["version"],
            expected_task_version=task["version"],
            command_id=test_command_id("accept-legacy-contract"),
        )
        store.close()

        def legacy_task(payload: dict) -> dict:
            migrated = json.loads(json.dumps(payload))
            migrated["activity_ref"].pop("novelty_status", None)
            migrated["success_criterion"] = (
                "在无提示的新题中作答，并用证据支持或反驳该候选错因。"
            )
            migrated["skip_consequence"] = (
                "若跳过，该错因仍保持未确认，并在下一学习日重新出现。"
            )
            return migrated

        legacy_projection = legacy_task(accepted["tasks"][0])
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        try:
            connection.executescript(
                """
                DROP TRIGGER review_schedule_definition_immutable;
                DROP TRIGGER schedule_command_results_no_update;
                """
            )
            connection.execute(
                """
                UPDATE review_schedule_tasks
                SET activity_ref_json = ?, success_criterion = ?, skip_consequence = ?
                WHERE task_id = ?
                """,
                (
                    json.dumps(
                        legacy_projection["activity_ref"],
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    legacy_projection["success_criterion"],
                    legacy_projection["skip_consequence"],
                    task["task_id"],
                ),
            )
            connection.execute(
                """
                UPDATE today_plan_tasks SET task_snapshot_json = ?
                WHERE plan_id = ? AND task_id = ?
                """,
                (
                    json.dumps(
                        legacy_projection,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    plan["plan_id"],
                    task["task_id"],
                ),
            )
            for row in connection.execute(
                "SELECT command_id, response_json FROM schedule_command_results"
            ).fetchall():
                response = json.loads(row["response_json"])
                response["tasks"] = [legacy_task(item) for item in response["tasks"]]
                connection.execute(
                    """
                    UPDATE schedule_command_results SET response_json = ?
                    WHERE command_id = ?
                    """,
                    (
                        json.dumps(
                            response,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        str(row["command_id"]),
                    ),
                )
            connection.commit()
        finally:
            connection.close()

        recovered = ScheduleStore(self.database)
        migrated_task = recovered.review_schedule()["items"][0]
        self.assertEqual(
            migrated_task["activity_ref"]["novelty_status"],
            "same_fixture_retest_not_novel_item",
        )
        self.assertNotIn("无提示的新题", migrated_task["success_criterion"])
        self.assertNotIn("下一学习日", migrated_task["skip_consequence"])
        migrated_plan = recovered.load_plan(plan["plan_id"])
        self.assertEqual(migrated_plan["version"], accepted["version"] + 1)
        self.assertEqual(
            migrated_plan["tasks"][0]["version"],
            accepted["tasks"][0]["version"] + 1,
        )
        self.assertEqual(
            recovered.events("review_task", task["task_id"])[-1].kind,
            "task_contract_migrated",
        )
        self.assertEqual(
            recovered.events("today_plan", plan["plan_id"])[-1].kind,
            "today_plan_contract_migrated",
        )
        self.assertTrue(
            recovered.replay("review_task", task["task_id"])["projection_verified"]
        )
        self.assertTrue(
            recovered.replay("today_plan", plan["plan_id"])["projection_verified"]
        )
        migration = recovered._connection.execute(
            "SELECT * FROM schedule_migrations"
        ).fetchone()
        self.assertEqual(migration["kind"], "pre_release_schedule_contract_v2")
        with self.assertRaises(ScheduleCommandConflict):
            recovered.replay_create_today_plan_command(
                plan_date=self.day.isoformat(),
                exam_date=(self.day + timedelta(days=30)).isoformat(),
                daily_budget_minutes=60,
                expected_version=0,
                command_id=create_command_id,
            )
        with self.assertRaises(ScheduleCommandConflict):
            recovered.transition_task(
                plan_id=plan["plan_id"],
                task_id=task["task_id"],
                action="accept",
                action_date=self.day.isoformat(),
                expected_version=plan["version"],
                expected_task_version=task["version"],
                command_id=test_command_id("accept-legacy-contract"),
            )
        recovered.close()

        healthy_reopen = ScheduleStore(self.database)
        self.assertEqual(healthy_reopen._connection.total_changes, 0)
        healthy_reopen.close()

    def test_legacy_workload_limit_basis_migrates_even_for_empty_plan_receipt(self) -> None:
        store = ScheduleStore(self.database)
        create_command_id = test_command_id("create-legacy-workload-basis")
        plan = self.create(
            store,
            [],
            command_id=create_command_id,
        )
        self.assertEqual(plan["tasks"], [])
        store.close()

        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        try:
            connection.executescript(
                """
                DROP TRIGGER today_plan_context_immutable;
                DROP TRIGGER schedule_command_results_no_update;
                """
            )
            basis = plan["basis"]
            basis["workload_guardrail"]["max_new_tasks"] = basis[
                "workload_guardrail"
            ].pop("max_non_accepted_tasks")
            connection.execute(
                "UPDATE today_plans SET basis_json = ? WHERE plan_id = ?",
                (
                    json.dumps(
                        basis,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    plan["plan_id"],
                ),
            )
            receipt_row = connection.execute(
                """
                SELECT response_json FROM schedule_command_results
                WHERE command_id = ?
                """,
                (create_command_id,),
            ).fetchone()
            receipt = json.loads(receipt_row["response_json"])
            receipt["basis"]["workload_guardrail"]["max_new_tasks"] = receipt[
                "basis"
            ]["workload_guardrail"].pop("max_non_accepted_tasks")
            connection.execute(
                """
                UPDATE schedule_command_results SET response_json = ?
                WHERE command_id = ?
                """,
                (
                    json.dumps(
                        receipt,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    create_command_id,
                ),
            )
            connection.commit()
        finally:
            connection.close()

        recovered = ScheduleStore(self.database)
        migrated = recovered.load_plan(plan["plan_id"])
        guardrail = migrated["basis"]["workload_guardrail"]
        self.assertEqual(guardrail["max_non_accepted_tasks"], 3)
        self.assertNotIn("max_new_tasks", guardrail)
        self.assertEqual(migrated["version"], plan["version"] + 1)
        self.assertEqual(
            recovered.events("today_plan", plan["plan_id"])[-1].kind,
            "today_plan_workload_contract_migrated",
        )
        self.assertTrue(
            recovered.replay("today_plan", plan["plan_id"])["projection_verified"]
        )
        migration = recovered._connection.execute(
            """
            SELECT * FROM schedule_migrations
            WHERE kind = 'pre_release_workload_limit_contract_v2'
            """
        ).fetchone()
        self.assertIsNotNone(migration)
        with self.assertRaises(ScheduleCommandConflict):
            recovered.replay_create_today_plan_command(
                plan_date=self.day.isoformat(),
                exam_date=(self.day + timedelta(days=30)).isoformat(),
                daily_budget_minutes=60,
                expected_version=0,
                command_id=create_command_id,
            )
        recovered.close()

        healthy_reopen = ScheduleStore(self.database)
        self.assertEqual(healthy_reopen._connection.total_changes, 0)
        healthy_reopen.close()

    def test_recorded_local_date_prevents_utc_midnight_off_by_one(self) -> None:
        store = ScheduleStore(
            self.database, planning_timezone=timezone(timedelta(hours=8))
        )
        evidence = self.evidence(
            "utc-midnight",
            kind="trace_skill_evidence",
            effective=False,
            failed=True,
            event_time="2026-07-10T16:30:00+00:00",
            timezone_offset_minutes=480,
        )
        plan = self.create(store, [evidence], command_id="create-local-date")
        self.assertEqual(plan["empty_reason"], "no_task_due_today")
        task = store.review_schedule()["items"][0]
        self.assertEqual(task["due_on"], "2026-07-12")
        self.assertEqual(
            plan["basis"]["workload_guardrail"][
                "event_timezone_offsets_minutes"
            ],
            [480],
        )
        store.close()

    def test_review_after_exam_is_withheld_instead_of_silently_clamped(self) -> None:
        store = ScheduleStore(self.database)
        evidence = self.evidence(
            "exam-boundary",
            kind="trace_skill_evidence",
            occurred_on=self.day,
            effective=True,
            failed=False,
        )
        plan = store.create_today_plan(
            plan_date=self.day.isoformat(),
            exam_date=self.day.isoformat(),
            daily_budget_minutes=60,
            expected_version=0,
            command_id=test_command_id("create-exam-boundary"),
            evidence=[evidence],
        )
        self.assertEqual(plan["tasks"], [])
        self.assertEqual(plan["empty_reason"], "task_due_after_exam")
        self.assertEqual(store.review_schedule()["count"], 0)
        self.assertEqual(
            plan["basis"]["workload_guardrail"][
                "withheld_exam_deadline_count"
            ],
            1,
        )
        store.close()

    def test_forged_provenance_is_rejected_before_any_schedule_write(self) -> None:
        store = ScheduleStore(self.database)
        evidence = self.evidence("forged-provenance")
        primary = evidence.evidence_ref
        with self.assertRaises(ScheduleValidationError):
            store.create_today_plan(
                plan_date=self.day.isoformat(),
                exam_date=(self.day + timedelta(days=30)).isoformat(),
                daily_budget_minutes=60,
                expected_version=0,
                command_id=test_command_id("duplicate-planning-evidence"),
                evidence=[evidence, evidence],
            )
        with self.assertRaises(ScheduleValidationError):
            replace(
                primary,
                kind="trace_skill_evidence",
                semantic="verification_effective",
                event_kind="phase_completed",
                phase="observe",
                json_pointer="/output/score/passed",
                subject_id=None,
                claim_status=None,
                confirmation_status=None,
                ref=(
                    f"trace:{primary.run_id}:event:{primary.event_seq}:"
                    f"{primary.event_hash}#pointer=/output/score/passed"
                ),
            )

        forged_hash = replace(
            primary,
            event_hash="0" * 64,
            ref=(
                f"trace:{primary.run_id}:event:{primary.event_seq}:{'0' * 64}"
                f"#pointer={primary.json_pointer}"
            ),
        )
        unresolved_pointer = "/assessments/99/claim_status"
        forged_pointer = replace(
            primary,
            json_pointer=unresolved_pointer,
            ref=(
                f"trace:{primary.run_id}:event:{primary.event_seq}:{primary.event_hash}"
                f"#pointer={unresolved_pointer}"
            ),
        )
        wrong_subject = replace(primary, subject_id="different-cause")
        nonexistent_pointer = primary.json_pointer
        nonexistent_ref = replace(
            primary,
            event_seq=99,
            event_hash="f" * 64,
            ref=(
                f"trace:{primary.run_id}:event:99:{'f' * 64}"
                f"#pointer={nonexistent_pointer}"
            ),
        )
        missing_snapshot = replace(
            evidence.activity_ref,
            fixture_content_sha256="b" * 64,
        )
        other_store = EventStore(self.database)
        other_hash = other_store.put_content_snapshot(
            "domain_fixture",
            {
                "fixture_id": "interview.other.synthetic-01",
                "domain": "interview",
                "skills": [{"skill_id": "interview.other", "weight": 1.0}],
                "diagnosis": {"candidate_causes": []},
            },
        )
        other_store.close()
        other_activity = ActivityRef(
            fixture_id="interview.other.synthetic-01",
            fixture_content_sha256=other_hash,
            availability="launchable",
        )
        forged_time = "2026-07-01T00:00:00+00:00"
        variants = [
            replace(evidence, evidence_ref=forged_hash),
            replace(evidence, evidence_ref=forged_pointer),
            replace(evidence, evidence_ref=wrong_subject),
            replace(evidence, activity_ref=missing_snapshot),
            replace(
                evidence,
                domain="interview",
                skill_id="interview.other",
                activity_ref=other_activity,
            ),
            replace(evidence, skill_id="xingce.skill.not-authored"),
            replace(evidence, cause_label="伪造错因标签"),
            replace(
                evidence,
                occurred_at=forged_time,
                occurred_on="2026-07-01",
                timezone_offset_minutes=0,
            ),
            replace(evidence, attempt_failed=False),
            replace(
                evidence,
                evidence_ref=nonexistent_ref,
                activity_ref=replace(
                    self.activity, availability="activity_unavailable"
                ),
            ),
        ]
        with self.assertRaises(ScheduleValidationError):
            replace(
                evidence,
                supporting_refs=tuple(
                    ref
                    for ref in evidence.supporting_refs
                    if ref.kind != "trace_terminal"
                ),
            )
        for index, variant in enumerate(variants):
            with self.assertRaises(ScheduleError):
                store.create_today_plan(
                    plan_date=self.day.isoformat(),
                    exam_date=(self.day + timedelta(days=30)).isoformat(),
                    daily_budget_minutes=60,
                    expected_version=0,
                    command_id=test_command_id(f"forged-provenance-{index}"),
                    evidence=[variant],
                )
            for table in (
                "review_schedule_tasks",
                "today_plans",
                "today_plan_tasks",
                "schedule_events",
                "schedule_command_results",
            ):
                count = store._connection.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]
                self.assertEqual(count, 0, table)
        store.close()

    def test_synthetic_origin_cannot_enter_the_human_review_schedule(self) -> None:
        store = ScheduleStore(self.database)
        evidence = self.evidence(
            "synthetic-origin",
            evidence_origin="synthetic_isolated",
        )
        with self.assertRaises(ScheduleError):
            self.create(store, [evidence], command_id="create-synthetic-origin")
        self.assertEqual(store.review_schedule()["count"], 0)
        self.assertEqual(
            store._connection.execute("SELECT COUNT(*) FROM today_plans").fetchone()[0],
            0,
        )
        store.close()

    def test_stale_update_and_latest_refuted_cause_are_rejected(self) -> None:
        store = ScheduleStore(self.database)
        stale_update = self.evidence(
            "stale-update",
            kind="trace_skill_evidence",
            effective=True,
            failed=False,
            later_verification_effective=False,
        )
        with self.assertRaises(ScheduleError):
            self.create(
                store,
                [stale_update],
                command_id="create-stale-update",
            )

        refuted = self.evidence(
            "latest-refuted",
            later_claim_status="refuted_hypothesis",
        )
        with self.assertRaises(ScheduleError):
            self.create(
                store,
                [refuted],
                command_id="create-latest-refuted",
            )
        self.assertEqual(store.review_schedule()["count"], 0)
        self.assertEqual(
            store._connection.execute("SELECT COUNT(*) FROM today_plans").fetchone()[0],
            0,
        )
        store.close()

    def test_unlaunchable_activity_is_withheld_and_sensitive_command_ids_fail(self) -> None:
        unavailable = replace(self.activity, availability="activity_unavailable")
        store = ScheduleStore(self.database)
        plan = self.create(
            store,
            [self.evidence("withheld", activity=unavailable)],
            command_id="create-withheld",
        )
        self.assertEqual(plan["tasks"], [])
        self.assertEqual(store.review_schedule()["count"], 0)
        self.assertEqual(
            plan["basis"]["workload_guardrail"]["withheld_activity_count"], 1
        )
        with self.assertRaises(ScheduleValidationError):
            self.create(
                store,
                [],
                day=self.day + timedelta(days=1),
                command_id="cmd-13800138000",
                raw_command_id=True,
            )
        store.close()

    def test_persistence_rejects_every_nonopaque_command_id_without_writes(self) -> None:
        invalid_ids = (
            "legacy-command",
            "13800138000",
            "sk-" + "a" * 24,
            "ghp_" + "a" * 24,
            "github_pat_" + "A" * 82,
            "AIzaSy" + "A" * 33,
            "npm_" + "A" * 36,
            "xoxb-" + "A" * 24 + "-" + "B" * 24,
        )
        store = ScheduleStore(self.database)
        for command_id in invalid_ids:
            with self.subTest(create_command_id=command_id):
                with self.assertRaises(ScheduleValidationError):
                    self.create(
                        store,
                        [],
                        command_id=command_id,
                        raw_command_id=True,
                    )
                for table in (
                    "review_schedule_tasks",
                    "today_plans",
                    "today_plan_tasks",
                    "schedule_events",
                    "schedule_command_results",
                ):
                    self.assertEqual(
                        store._connection.execute(
                            f"SELECT COUNT(*) FROM {table}"
                        ).fetchone()[0],
                        0,
                        table,
                    )

        plan = self.create(
            store,
            [self.evidence("opaque-command-transition")],
            command_id=opaque_public_id("c", "create valid plan"),
        )
        task = plan["tasks"][0]
        before = store.load_plan(plan["plan_id"])
        before_event_counts = {
            stream: len(store.events(stream, stream_id))
            for stream, stream_id in (
                ("today_plan", plan["plan_id"]),
                ("review_task", task["task_id"]),
            )
        }
        before_receipts = store._connection.execute(
            "SELECT COUNT(*) FROM schedule_command_results"
        ).fetchone()[0]
        for command_id in invalid_ids:
            with self.subTest(transition_command_id=command_id):
                with self.assertRaises(ScheduleValidationError):
                    store.transition_task(
                        plan_id=plan["plan_id"],
                        task_id=task["task_id"],
                        action="accept",
                        action_date=self.day.isoformat(),
                        expected_version=plan["version"],
                        expected_task_version=task["version"],
                        command_id=command_id,
                    )
                self.assertEqual(store.load_plan(plan["plan_id"]), before)
                self.assertEqual(
                    len(store.events("today_plan", plan["plan_id"])),
                    before_event_counts["today_plan"],
                )
                self.assertEqual(
                    len(store.events("review_task", task["task_id"])),
                    before_event_counts["review_task"],
                )
                self.assertEqual(
                    store._connection.execute(
                        "SELECT COUNT(*) FROM schedule_command_results"
                    ).fetchone()[0],
                    before_receipts,
                )
        store.close()


if __name__ == "__main__":
    unittest.main()
