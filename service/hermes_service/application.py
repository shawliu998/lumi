from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone, tzinfo
import hashlib
import json
from pathlib import Path
import secrets
import threading
from typing import Any, Callable, Mapping

from lumi_study_pack import StudyPackError, StudyPackStore
from lumi_study_pack.models import validate_command_id, validate_entity_id
from lumi_study_pack.parsing import PdfBackend
from lumi_study_pack.store import (
    ATTEMPT_EVIDENCE_ORIGINS,
    HUMAN_ATTEMPT_EVIDENCE_ORIGIN,
)

from hermes_integration.loop import (
    SCENARIOS,
    ContinuationError,
    attempt_state_name,
    continue_attempt,
    run_attempt,
    run_scenario,
)
from hermes_integration.learning_support import (
    assistance_events_for_prompt,
    authored_assistance_step,
    fixture_content_hash,
    prompt_instance_id,
)
from hermes_runtime.diff import state_diff
from hermes_runtime.state import RunStatus
from hermes_runtime.schedule import (
    ActivityRef,
    EvidenceRef,
    PlanningEvidence,
    ScheduleBudgetBelowAcceptedCommitment,
    ScheduleCommandConflict,
    ScheduleError,
    ScheduleHistoricalPlan,
    ScheduleNotFound,
    ScheduleStore,
    ScheduleTaskVersionConflict,
    ScheduleTransitionError,
    ScheduleValidationError,
    ScheduleVersionConflict,
    valid_public_command_identifier,
    valid_public_run_identifier,
    valid_stored_run_identifier,
)
from hermes_runtime.store import EventStore, TraceVersionConflict
from hermes_domains.xingce_coverage import load_coverage_matrix

from .catalog import ProductActivityCatalog, ScenarioCatalog
from .dossier import project_misconception_dossier
from .judgment_session import (
    HUMAN_ORIGIN as JUDGMENT_HUMAN_ORIGIN,
    JudgmentContentUnavailable,
    JudgmentSessionConfig,
    JudgmentSessionConflict,
    JudgmentSessionError,
    JudgmentSessionService,
    judgment_pack_status,
)
from .xingce_catalog import XingceCoverageCatalog
from .xingce_adaptive_session import XingceAdaptiveSessionError, XingceAdaptiveSessionService
from .xingce_question_bank import (
    QuestionBankAssetUnavailable,
    QuestionBankConflict,
    QuestionBankNotFound,
    QuestionBankRequestError,
    QuestionBankUnavailable,
    XingceQuestionBankCatalog,
)


SERVICE_VERSION = "0.3.0"

class ServiceError(RuntimeError):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


class SidecarApplication:
    def __init__(
        self,
        database: str | Path,
        *,
        today_provider: Callable[[], date] | None = None,
        planning_timezone: tzinfo | None = None,
        study_pack_pdf_backend: PdfBackend | None = None,
        study_pack_attempt_evidence_origin: str = HUMAN_ATTEMPT_EVIDENCE_ORIGIN,
        attempt_evidence_origin: str = "human_local_interactive",
        product_activity_payload_path: str | Path | None = None,
        product_activity_catalog: ProductActivityCatalog | None = None,
        review_commit_evidence_origins: frozenset[str] | None = None,
        evaluation_projection_enabled: bool = False,
        judgment_pack_root: str | Path | None = None,
        judgment_session_service: JudgmentSessionService | None = None,
        xingce_adaptive_session_services: Mapping[str, XingceAdaptiveSessionService] | None = None,
        xingce_full_bank_export: str | Path | None = None,
        xingce_asset_export: str | Path | None = None,
        xingce_question_bank_catalog: XingceQuestionBankCatalog | None = None,
    ) -> None:
        if study_pack_attempt_evidence_origin not in ATTEMPT_EVIDENCE_ORIGINS:
            raise ValueError("unsupported Study Pack attempt evidence origin")
        if attempt_evidence_origin not in {
            "human_local_interactive",
            "evaluation_fixture",
            "synthetic_isolated",
        }:
            raise ValueError("unsupported learning attempt evidence origin")
        if (
            not isinstance(evaluation_projection_enabled, bool)
            or evaluation_projection_enabled
            and attempt_evidence_origin != "evaluation_fixture"
        ):
            raise ValueError(
                "evaluation projection requires the explicit evaluation_fixture origin"
            )
        self.database = str(database)
        self.catalog = ScenarioCatalog()
        if product_activity_catalog is not None and product_activity_payload_path is not None:
            raise ValueError("provide either product activity catalog or payload path")
        self.product_activities = product_activity_catalog or (
            ProductActivityCatalog()
            if product_activity_payload_path is None
            else ProductActivityCatalog(product_activity_payload_path)
        )
        self._continuation_lock = threading.Lock()
        self._today_provider = today_provider or date.today
        self._planning_timezone = (
            planning_timezone
            or datetime.now().astimezone().tzinfo
            or timezone.utc
        )
        self._study_pack_pdf_backend = study_pack_pdf_backend
        self._study_pack_attempt_evidence_origin = (
            study_pack_attempt_evidence_origin
        )
        self._attempt_evidence_origin = attempt_evidence_origin
        self._evaluation_projection_enabled = evaluation_projection_enabled
        self._review_commit_evidence_origins = (
            frozenset({"human_local_interactive"})
            if review_commit_evidence_origins is None
            else frozenset(review_commit_evidence_origins)
        )
        if not self._review_commit_evidence_origins.issubset(
            {"human_local_interactive", "evaluation_fixture"}
        ):
            raise ValueError("review commit origins may contain only human or explicit evaluation evidence")
        if judgment_session_service is not None and judgment_pack_root is not None:
            raise ValueError("provide either a JudgmentSessionService or a reviewed pack root")
        if judgment_session_service is not None:
            if judgment_session_service.config.evidence_origin != attempt_evidence_origin:
                raise ValueError("judgment session origin must match the sidecar attempt origin")
            self._judgment_sessions = judgment_session_service
            self._judgment_content_status = {"available": True}
        elif judgment_pack_root is not None and attempt_evidence_origin in {
            "human_local_interactive",
            "evaluation_fixture",
        }:
            evidence_origin = attempt_evidence_origin
            namespace = (
                "human:local-lumi"
                if evidence_origin == JUDGMENT_HUMAN_ORIGIN
                else "eval:judgment-session"
            )
            try:
                self._judgment_sessions = JudgmentSessionService(
                    self.database,
                    reviewed_pack_root=judgment_pack_root,
                    config=JudgmentSessionConfig(
                        namespace_id=namespace,
                        evidence_origin=evidence_origin,
                        learner_id="local-lumi",
                    ),
                    allow_test_only_reviewed_pack=evidence_origin == "evaluation_fixture",
                )
                self._judgment_content_status = {"available": True}
            except JudgmentContentUnavailable:
                self._judgment_sessions = None
                self._judgment_content_status = judgment_pack_status(
                    judgment_pack_root, allow_test_only=evidence_origin == "evaluation_fixture"
                )
        else:
            self._judgment_sessions = None
            self._judgment_content_status = judgment_pack_status(None)
        self._xingce_adaptive_sessions = dict(xingce_adaptive_session_services or {})
        if any(service.pack["subtype_id"] != subtype_id for subtype_id, service in self._xingce_adaptive_sessions.items()):
            raise ValueError("adaptive session registry key must match its reviewed pack subtype")
        if not self._evaluation_projection_enabled:
            reviewed_releases = {
                row["id"]: row["release"]
                for row in load_coverage_matrix()["subtypes"]
                if row.get("release", {}).get("state") in {"released", "reviewed_release_ready"}
            }
            for subtype_id, service in self._xingce_adaptive_sessions.items():
                release = reviewed_releases.get(subtype_id)
                if release is None or release["pack_id"] != service.pack["pack_id"] or release["pack_version"] != service.pack["pack_version"]:
                    raise ValueError("production Xingce adaptive pack must exactly match a reviewed coverage row")
        available_xingce_subtypes = set(self._xingce_adaptive_sessions)
        if self._judgment_sessions is not None:
            available_xingce_subtypes.add("xingce.judgment.conditional_logic")
        self.xingce_coverage = XingceCoverageCatalog(
            available_subtype_ids=available_xingce_subtypes,
        )
        if xingce_question_bank_catalog is not None and (
            xingce_full_bank_export is not None or xingce_asset_export is not None
        ):
            raise ValueError("provide either a full-bank catalog or export roots")
        self.xingce_question_bank = xingce_question_bank_catalog or XingceQuestionBankCatalog(
            xingce_full_bank_export,
            attempt_database=self.database,
            asset_export_root=xingce_asset_export,
        )

    def health(self) -> dict[str, Any]:
        store = EventStore(self.database)
        try:
            run_count = len(self._projectable_attempt_run_ids(store))
        finally:
            store.close()
        return {
            "status": "ok",
            "service": "hermes-local-sidecar",
            "version": SERVICE_VERSION,
            "storage": "sqlite-append-only",
            "run_count": run_count,
            "local_only": True,
        }

    def capabilities(self) -> dict[str, Any]:
        scenarios = self.catalog.list()
        product_activities = self.product_activities.list()
        return {
            "service_version": SERVICE_VERSION,
            "api_version": "v1",
            "local_only": True,
            "domains": sorted({item["domain"] for item in scenarios}),
            "scenario_count": len(scenarios),
            "product_activity_count": len(product_activities),
            "features": [
                "representative-scenario-catalog",
                "local-product-activity-catalog-v1",
                "domain-engine-runtime-loop",
                "real-learner-attempt-v1",
                "optimistic-attempt-continuation-v1",
                "progressive-assistance-v1",
                "event-sourced-misconception-dossier-v1",
                "explainable-today-plan-v1",
                "independent-review-schedule-v1",
                "local-cited-study-pack-v1",
                "append-only-trace",
                "hash-verified-replay",
                "skill-summary",
                "judgment-reasoning-workspace-v1",
                "xingce-coverage-catalog-v1",
                "xingce-adaptive-session-v1",
                "xingce-full-question-bank-v1",
            ],
            "endpoints": {
                "health": "GET /v1/health",
                "capabilities": "GET /v1/capabilities",
                "scenarios": "GET /v1/scenarios",
                "product_activities": "GET /v1/product-activities",
                "product_activity": "GET /v1/product-activities/{activity_id}",
                "attempt": "POST /v1/attempts",
                "attempt_response": "POST /v1/attempts/{run_id}/responses",
                "assistance": "POST /v1/attempts/{run_id}/assistance",
                "misconception": "GET /v1/misconceptions/{run_id}",
                "today_plan_create": "POST /v1/today-plans",
                "today_plan": "GET /v1/today-plans/{plan_id}",
                "today_plan_command": "POST /v1/today-plans/{plan_id}/tasks/{task_id}/commands",
                "today_plan_replay": "GET /v1/today-plans/{plan_id}/replay",
                "review_schedule": "GET /v1/review-schedule",
                "review_task_replay": "GET /v1/review-schedule/{task_id}/replay",
                "study_pack_create": "POST /v1/study-packs",
                "study_packs": "GET /v1/study-packs",
                "study_pack": "GET /v1/study-packs/{pack_id}",
                "study_pack_command": "POST /v1/study-packs/{pack_id}/commands",
                "study_pack_citation": "GET /v1/study-packs/{pack_id}/citations/{span_id}",
                "study_pack_replay": "GET /v1/study-packs/{pack_id}/replay",
                "study_pack_item_launch": "GET /v1/study-pack-items/{artifact_id}/launch",
                "study_pack_item_attempt": "POST /v1/study-pack-items/{artifact_id}/attempts",
                "trace": "GET /v1/runs/{run_id}/trace",
                "replay": "GET /v1/runs/{run_id}/replay",
                "review_commit": "POST /v1/runs/{run_id}/review-commit",
                "skills": "GET /v1/skills/report",
                "judgment_workspace": "GET /v1/judgment/workspace",
                "judgment_session": "POST /v1/judgment/sessions",
                "judgment_probe": "POST /v1/judgment/sessions/{session_id}/probe",
                "judgment_transfer": "POST /v1/judgment/sessions/{session_id}/transfer",
                "judgment_replay": "GET /v1/judgment/sessions/{session_id}/replay",
                "xingce_coverage": "GET /v1/xingce/coverage",
                "xingce_adaptive_workspace": "GET /v1/xingce/adaptive/{subtype_id}/workspace",
                "xingce_adaptive_session": "POST /v1/xingce/adaptive/{subtype_id}/sessions",
                "xingce_question_bank": "GET /v1/xingce/question-bank",
                "xingce_question_bank_papers": "GET /v1/xingce/question-bank/papers",
                "xingce_question_bank_questions": "GET /v1/xingce/question-bank/questions",
                "xingce_question_bank_question": "GET /v1/xingce/question-bank/questions/{question_id}",
                "xingce_question_bank_attempt": "POST /v1/xingce/question-bank/questions/{question_id}/attempts",
                "xingce_question_bank_asset": "GET /v1/xingce/question-bank/assets/{asset_id}",
            },
        }

    def xingce_coverage_catalog(self) -> dict[str, Any]:
        return self.xingce_coverage.public_projection()

    def xingce_question_bank_status(self) -> dict[str, Any]:
        return self.xingce_question_bank.status()

    def xingce_question_bank_questions(self, **query: Any) -> dict[str, Any]:
        try:
            return self.xingce_question_bank.list_questions(**query)
        except (QuestionBankUnavailable, QuestionBankRequestError, QuestionBankNotFound, QuestionBankConflict, QuestionBankAssetUnavailable) as exc:
            raise _question_bank_service_error(exc) from None

    def xingce_question_bank_papers(self, **query: Any) -> dict[str, Any]:
        try:
            return self.xingce_question_bank.list_papers(**query)
        except (
            QuestionBankUnavailable,
            QuestionBankRequestError,
            QuestionBankNotFound,
            QuestionBankConflict,
            QuestionBankAssetUnavailable,
        ) as exc:
            raise _question_bank_service_error(exc) from None

    def xingce_question_bank_question(self, question_id: Any) -> dict[str, Any]:
        try:
            return self.xingce_question_bank.question(question_id)
        except (QuestionBankUnavailable, QuestionBankRequestError, QuestionBankNotFound, QuestionBankConflict, QuestionBankAssetUnavailable) as exc:
            raise _question_bank_service_error(exc) from None

    def attempt_xingce_question_bank_question(self, question_id: Any, **payload: Any) -> dict[str, Any]:
        try:
            return self.xingce_question_bank.attempt(question_id, **payload)
        except (QuestionBankUnavailable, QuestionBankRequestError, QuestionBankNotFound, QuestionBankConflict, QuestionBankAssetUnavailable) as exc:
            raise _question_bank_service_error(exc) from None

    def xingce_question_bank_asset(self, asset_id: Any) -> dict[str, Any]:
        try:
            return self.xingce_question_bank.asset_binary(asset_id)
        except (
            QuestionBankAssetUnavailable,
            QuestionBankNotFound,
            QuestionBankRequestError,
            QuestionBankUnavailable,
        ) as exc:
            raise _question_bank_service_error(exc) from None

    def xingce_adaptive_workspace(self, subtype_id: Any) -> dict[str, Any]:
        return self._xingce_adaptive_service(subtype_id).workspace()

    def start_xingce_adaptive_session(self, subtype_id: Any, **payload: Any) -> dict[str, Any]:
        try:
            return self._xingce_adaptive_service(subtype_id).start(**payload)
        except XingceAdaptiveSessionError as exc:
            raise _xingce_adaptive_service_error(exc) from None

    def answer_xingce_adaptive_probe(self, subtype_id: Any, session_id: Any, **payload: Any) -> dict[str, Any]:
        try:
            return self._xingce_adaptive_service(subtype_id).answer_probe(session_id=session_id, **payload)
        except XingceAdaptiveSessionError as exc:
            raise _xingce_adaptive_service_error(exc) from None

    def answer_xingce_adaptive_transfer(self, subtype_id: Any, session_id: Any, **payload: Any) -> dict[str, Any]:
        try:
            return self._xingce_adaptive_service(subtype_id).answer_transfer(session_id=session_id, **payload)
        except XingceAdaptiveSessionError as exc:
            raise _xingce_adaptive_service_error(exc) from None

    def xingce_adaptive_replay(self, subtype_id: Any, session_id: Any) -> dict[str, Any]:
        try:
            return self._xingce_adaptive_service(subtype_id).replay(session_id)
        except XingceAdaptiveSessionError as exc:
            raise _xingce_adaptive_service_error(exc) from None

    def _xingce_adaptive_service(self, subtype_id: Any) -> XingceAdaptiveSessionService:
        if not isinstance(subtype_id, str) or subtype_id not in self._xingce_adaptive_sessions:
            raise ServiceError(409, "content_review_required", "该行测子型尚无已审核的本地自适应题包。")
        return self._xingce_adaptive_sessions[subtype_id]

    def judgment_workspace(self) -> dict[str, Any]:
        """Return the public workspace, or the review gate without draft text."""

        if self._judgment_sessions is None:
            return {
                "schema_version": "lumi.judgment-workspace.v1",
                "available": False,
                "reason": "content_review_required",
                "message": self._judgment_content_status.get(
                    "message",
                    "判断推理题包尚未通过审核，不能开始学习记录。",
                ),
            }
        try:
            return self._judgment_sessions.workspace()
        except JudgmentSessionError as exc:
            raise _judgment_service_error(exc) from None

    def start_judgment_session(
        self,
        entry_record_id: Any,
        selected_option: Any,
        confidence: Any,
        elapsed_seconds: Any,
        rationale: Any,
        command_id: Any,
    ) -> dict[str, Any]:
        service = self._judgment_service()
        try:
            return service.start(
                entry_record_id=entry_record_id,
                selected_option=selected_option,
                confidence=confidence,
                elapsed_seconds=elapsed_seconds,
                rationale=rationale,
                command_id=command_id,
            )
        except JudgmentSessionError as exc:
            raise _judgment_service_error(exc) from None

    def answer_judgment_probe(
        self,
        session_id: Any,
        expected_version: Any,
        expected_stage: Any,
        selected_option: Any,
        confidence: Any,
        elapsed_seconds: Any,
        command_id: Any,
    ) -> dict[str, Any]:
        service = self._judgment_service()
        try:
            return service.answer_probe(
                session_id=session_id,
                expected_version=expected_version,
                expected_stage=expected_stage,
                selected_option=selected_option,
                confidence=confidence,
                elapsed_seconds=elapsed_seconds,
                command_id=command_id,
            )
        except JudgmentSessionError as exc:
            raise _judgment_service_error(exc) from None

    def answer_judgment_transfer(
        self,
        session_id: Any,
        expected_version: Any,
        expected_stage: Any,
        selected_option: Any,
        confidence: Any,
        elapsed_seconds: Any,
        command_id: Any,
    ) -> dict[str, Any]:
        service = self._judgment_service()
        try:
            return service.answer_transfer(
                session_id=session_id,
                expected_version=expected_version,
                expected_stage=expected_stage,
                selected_option=selected_option,
                confidence=confidence,
                elapsed_seconds=elapsed_seconds,
                command_id=command_id,
            )
        except JudgmentSessionError as exc:
            raise _judgment_service_error(exc) from None

    def judgment_session_replay(self, session_id: Any) -> dict[str, Any]:
        service = self._judgment_service()
        try:
            return service.replay(session_id)
        except JudgmentSessionError as exc:
            raise _judgment_service_error(exc) from None

    def _judgment_service(self) -> JudgmentSessionService:
        if self._judgment_sessions is None:
            raise ServiceError(
                409,
                "content_review_required",
                "判断推理题包尚未通过逻辑与编辑/权属审核，不能开始学习记录。",
            )
        return self._judgment_sessions

    def create_study_pack(
        self,
        title: Any,
        source: Any,
        command_id: Any,
    ) -> dict[str, Any]:
        _validate_study_pack_command(command_id)
        store = self._study_pack_store()
        try:
            try:
                result = store.create_pack(
                    title=title,
                    source=source,
                    command_id=command_id,
                )
            except StudyPackError as exc:
                raise _study_pack_service_error(exc) from None
            return _public_study_pack_projection(result)
        finally:
            store.close()

    def study_packs(self) -> dict[str, Any]:
        store = self._study_pack_store()
        try:
            result = store.list_packs()
        finally:
            store.close()
        return {
            **result,
            "items": [
                {
                    **item,
                    "links": {"self": f"/v1/study-packs/{item['pack_id']}"},
                }
                for item in result["items"]
            ],
        }

    def study_pack(self, pack_id: Any) -> dict[str, Any]:
        _validate_study_pack_entity(pack_id, "p_", "invalid_pack_id")
        store = self._study_pack_store()
        try:
            try:
                result = store.get_pack(pack_id)
            except StudyPackError as exc:
                raise _study_pack_service_error(
                    exc,
                    not_found_code="study_pack_not_found",
                ) from None
            return _public_study_pack_projection(result)
        finally:
            store.close()

    def command_study_pack(
        self,
        pack_id: Any,
        action: Any,
        expected_version: Any,
        command_id: Any,
    ) -> dict[str, Any]:
        _validate_study_pack_entity(pack_id, "p_", "invalid_pack_id")
        _validate_study_pack_command(command_id)
        store = self._study_pack_store()
        try:
            try:
                result = store.command_pack(
                    pack_id=pack_id,
                    action=action,
                    expected_version=expected_version,
                    command_id=command_id,
                )
            except StudyPackError as exc:
                raise _study_pack_service_error(
                    exc,
                    not_found_code="study_pack_not_found",
                ) from None
            return _public_study_pack_projection(result)
        finally:
            store.close()

    def study_pack_citation(self, pack_id: Any, span_id: Any) -> dict[str, Any]:
        _validate_study_pack_entity(pack_id, "p_", "invalid_pack_id")
        _validate_study_pack_entity(span_id, "s_", "invalid_span_id")
        store = self._study_pack_store()
        try:
            try:
                result = store.resolve_citation(pack_id, span_id)
            except StudyPackError as exc:
                raise _study_pack_service_error(
                    exc,
                    not_found_code="study_pack_not_found",
                ) from None
        finally:
            store.close()
        return {
            **result,
            "verified": True,
            "links": {"pack": f"/v1/study-packs/{pack_id}"},
        }

    def study_pack_replay(self, pack_id: Any) -> dict[str, Any]:
        _validate_study_pack_entity(pack_id, "p_", "invalid_pack_id")
        store = self._study_pack_store()
        try:
            try:
                result = store.replay(pack_id)
            except StudyPackError as exc:
                raise _study_pack_service_error(
                    exc,
                    not_found_code="study_pack_not_found",
                ) from None
        finally:
            store.close()
        if _contains_private_study_pack_key(result):
            raise ServiceError(
                500,
                "unsafe_study_pack_projection",
                "Study Pack replay contains a private field",
            )
        return result

    def launch_study_pack_item(self, artifact_id: Any) -> dict[str, Any]:
        _validate_study_pack_entity(
            artifact_id,
            "a_",
            "invalid_artifact_id",
        )
        store = self._study_pack_store()
        try:
            try:
                result = store.launch_item(artifact_id)
            except StudyPackError as exc:
                raise _study_pack_service_error(
                    exc,
                    not_found_code="artifact_unsupported",
                ) from None
        finally:
            store.close()
        allowed = {
            "schema_version",
            "pack_id",
            "pack_version",
            "artifact_id",
            "artifact_version",
            "item_kind",
            "prompt",
            "scorer",
            "evidence_origin",
            "activity_kind",
        }
        if set(result) != allowed:
            raise ServiceError(
                500,
                "unsafe_study_pack_projection",
                "Study Pack launch contract contains an unsupported field",
            )
        return {
            **result,
            "links": {
                "attempts": f"/v1/study-pack-items/{artifact_id}/attempts",
                "pack": f"/v1/study-packs/{result['pack_id']}",
            },
        }

    def attempt_study_pack_item(
        self,
        artifact_id: Any,
        learner_answer: Any,
        expected_pack_version: Any,
        expected_artifact_version: Any,
        command_id: Any,
    ) -> dict[str, Any]:
        _validate_study_pack_entity(
            artifact_id,
            "a_",
            "invalid_artifact_id",
        )
        _validate_study_pack_command(command_id)
        store = self._study_pack_store()
        try:
            try:
                result = store.attempt_item(
                    artifact_id=artifact_id,
                    learner_answer=learner_answer,
                    expected_pack_version=expected_pack_version,
                    expected_artifact_version=expected_artifact_version,
                    command_id=command_id,
                )
            except StudyPackError as exc:
                raise _study_pack_service_error(
                    exc,
                    not_found_code="artifact_unsupported",
                ) from None
        finally:
            store.close()
        if _contains_private_attempt_key(result):
            raise ServiceError(
                500,
                "unsafe_study_pack_projection",
                "Study Pack attempt response contains private learner input",
            )
        return {
            **result,
            "schema_version": "lumi.study-pack-attempt-result.v1",
            "links": {
                "pack": f"/v1/study-packs/{result['pack_id']}",
                "replay": f"/v1/study-packs/{result['pack_id']}/replay",
            },
        }

    def _study_pack_store(self) -> StudyPackStore:
        return StudyPackStore(
            self.database,
            pdf_backend=self._study_pack_pdf_backend,
            attempt_evidence_origin=self._study_pack_attempt_evidence_origin,
        )

    def scenarios(self, domain: str | None = None, mode: str | None = None) -> dict[str, Any]:
        if domain is not None and (
            not isinstance(domain, str) or domain not in {"xingce", "shenlun", "interview"}
        ):
            raise ServiceError(400, "invalid_domain", "domain must be xingce, shenlun, or interview")
        if mode is not None and (
            not isinstance(mode, str) or mode not in {"success", "ambiguous", "offline"}
        ):
            raise ServiceError(400, "invalid_mode", "mode must be success, ambiguous, or offline")
        items = self.catalog.list(domain=domain, mode=mode)
        return {"count": len(items), "items": items}

    def list_product_activities(
        self,
        release_id: str | None = None,
        diagnostic_role: str | None = None,
    ) -> dict[str, Any]:
        for value, code, label in (
            (release_id, "invalid_release_id", "release_id"),
            (diagnostic_role, "invalid_diagnostic_role", "diagnostic_role"),
        ):
            if value is not None and (
                not isinstance(value, str) or not value or len(value) > 200
            ):
                raise ServiceError(400, code, f"{label} must be non-empty text")
        items = self.product_activities.list(
            release_id=release_id,
            diagnostic_role=diagnostic_role,
        )
        return {"count": len(items), "items": items}

    def product_activity(self, activity_id: str) -> dict[str, Any]:
        if not isinstance(activity_id, str) or not activity_id or len(activity_id) > 200:
            raise ServiceError(
                400,
                "invalid_activity_id",
                "activity_id must be a non-empty catalog identifier",
            )
        try:
            return self.product_activities.get(activity_id)
        except KeyError:
            raise ServiceError(
                404,
                "product_activity_not_found",
                "activity_id is not in the local product catalog",
            ) from None

    def submit_attempt(
        self,
        fixture_id: str,
        response: str,
        confidence: float,
        response_time_seconds: float,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(fixture_id, str) or not fixture_id or len(fixture_id) > 200:
            raise ServiceError(400, "invalid_fixture_id", "fixture_id must be a non-empty catalog identifier")
        if self._attempt_evidence_origin == "human_local_interactive":
            # Production learner activity is deliberately narrower than the
            # representative ScenarioCatalog.  The latter remains available
            # only to explicit evaluation namespaces; it must never create a
            # human learner trace or seed a production review task.
            try:
                fixture = self.product_activities.resolve_fixture(fixture_id)
            except KeyError:
                raise ServiceError(
                    404,
                    "product_activity_required",
                    "human local attempts require a launchable versioned product activity",
                ) from None
        else:
            try:
                fixture = self.catalog.resolve(fixture_id)
            except KeyError:
                try:
                    fixture = self.product_activities.resolve_fixture(fixture_id)
                except KeyError:
                    raise ServiceError(
                        404,
                        "fixture_not_found",
                        "fixture_id is not in an available attempt catalog",
                    ) from None
        if not isinstance(response, str) or not response.strip():
            raise ServiceError(400, "invalid_response", "response must be non-empty text")
        if len(response) > 20_000:
            raise ServiceError(413, "response_too_large", "response exceeds the 20000-character limit")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            raise ServiceError(400, "invalid_confidence", "confidence must be a number in [0, 1]")
        if (
            isinstance(response_time_seconds, bool)
            or not isinstance(response_time_seconds, (int, float))
            or not 0 <= response_time_seconds <= 7200
        ):
            raise ServiceError(
                400,
                "invalid_response_time",
                "response_time_seconds must be a number in [0, 7200]",
            )
        if run_id is not None and not valid_public_run_identifier(run_id):
            raise ServiceError(400, "invalid_run_id", "run_id contains unsupported characters")
        public_run_id = run_id or _new_public_run_id()
        try:
            session, result = run_attempt(
                fixture,
                response,
                float(confidence),
                float(response_time_seconds),
                self.database,
                run_id=public_run_id,
                evidence_origin=self._attempt_evidence_origin,
            )
        except ValueError as exc:
            if "already exists" in str(exc):
                raise ServiceError(409, "run_exists", "a run with this identifier already exists") from None
            raise ServiceError(422, "attempt_rejected", "the learner attempt could not be processed") from None
        try:
            artifacts = result.state.artifacts
            score = artifacts["observe"][-1]["score"]
            diagnosis = artifacts["diagnose"][-1]
            version = session.store.events(result.state.run_id)[-1].seq
            return {
                "schema_version": "hermes.attempt-session.v1",
                "run_id": result.state.run_id,
                "fixture_id": fixture_id,
                "domain": fixture["domain"],
                "mode": fixture["mode"],
                "status": result.state.status.value,
                "state": attempt_state_name(result.state),
                "state_version": version,
                "steps": result.state.step_count,
                "score": {
                    "score": score["score"],
                    "max_score": score["max_score"],
                    "passed": score["passed"],
                    "adapter_version": score["adapter_version"],
                },
                "diagnosis": {
                    "decision": diagnosis["decision"],
                    "hypotheses": diagnosis["diagnosis"]["hypotheses"],
                    "uncertainty": diagnosis["diagnosis"]["uncertainty"],
                    "semantics": "ranked_unconfirmed_hypotheses",
                    "model_version": diagnosis["model_version"],
                },
                "response_evidence": artifacts["observe"][-1]["response_evidence"],
                "probe": {
                    "prompt_instance_id": artifacts["probe"][-1]["prompt_instance_id"],
                    "prompt": artifacts["probe"][-1]["prompt"],
                    "targets": artifacts["probe"][-1]["targets"],
                    "selection": artifacts["probe"][-1]["selection"],
                },
                "teaching": None,
                "verification": None,
                "mastery_update": None,
                "execution": {
                    "connectivity": fixture["execution"]["connectivity"],
                    "cloud_calls": 0,
                },
                "trace_verified": session.store.verify(result.state.run_id),
                "links": {
                    "trace": f"/v1/runs/{result.state.run_id}/trace",
                    "replay": f"/v1/runs/{result.state.run_id}/replay",
                    "skill_report": "/v1/skills/report",
                    "respond": f"/v1/attempts/{result.state.run_id}/responses",
                    "assist": f"/v1/attempts/{result.state.run_id}/assistance",
                    "misconception": f"/v1/misconceptions/{result.state.run_id}",
                },
            }
        finally:
            session.store.close()

    def continue_attempt_session(
        self,
        run_id: str,
        phase: str,
        expected_version: int,
        expected_state: str,
        prompt_instance: str,
        response: str,
        confidence: float,
        response_time_seconds: float,
    ) -> dict[str, Any]:
        # One sidecar owns the SQLite writer. Serializing compare-version + append
        # makes optimistic concurrency fail closed even under simultaneous clicks.
        with self._continuation_lock:
            return self._continue_attempt_session_locked(
                run_id,
                phase,
                expected_version,
                expected_state,
                prompt_instance,
                response,
                confidence,
                response_time_seconds,
            )

    def _continue_attempt_session_locked(
        self,
        run_id: str,
        phase: str,
        expected_version: int,
        expected_state: str,
        prompt_instance: str,
        response: str,
        confidence: float,
        response_time_seconds: float,
    ) -> dict[str, Any]:
        if not _valid_stored_run_id(run_id):
            raise ServiceError(400, "invalid_run_id", "run_id contains unsupported characters")
        if not isinstance(phase, str) or phase not in {"probe", "verification"}:
            raise ServiceError(400, "invalid_phase", "phase must be probe or verification")
        if isinstance(expected_version, bool) or not isinstance(expected_version, int) or expected_version < 1:
            raise ServiceError(400, "invalid_version", "expected_version must be a positive integer")
        if not isinstance(expected_state, str) or expected_state not in {
            "awaiting_probe",
            "awaiting_verification",
        }:
            raise ServiceError(400, "invalid_state", "expected_state is not a writable attempt state")
        if not isinstance(prompt_instance, str) or not prompt_instance or len(prompt_instance) > 160:
            raise ServiceError(400, "invalid_prompt_instance", "prompt_instance_id is invalid")
        self._validate_attempt_evidence(response, confidence, response_time_seconds)
        store = EventStore(self.database)
        try:
            try:
                state = store.load_state(run_id)
            except KeyError:
                raise ServiceError(404, "run_not_found", "attempt session does not exist") from None
            fixture = self._session_fixture(state, store)
        finally:
            store.close()
        try:
            session, result = continue_attempt(
                fixture,
                self.database,
                run_id,
                phase=phase,
                expected_version=expected_version,
                expected_state=expected_state,
                prompt_instance=prompt_instance,
                response=response,
                confidence=float(confidence),
                response_time_seconds=float(response_time_seconds),
            )
        except ContinuationError as exc:
            status = 404 if exc.code == "run_not_found" else 409
            raise ServiceError(status, exc.code, exc.message) from None
        try:
            artifacts = result.state.artifacts
            version = session.store.events(run_id)[-1].seq
            state_name = attempt_state_name(result.state)
            payload: dict[str, Any] = {
                "schema_version": "hermes.attempt-continuation-result.v1",
                "run_id": run_id,
                "accepted_phase": phase,
                "status": result.state.status.value,
                "state": state_name,
                "state_version": version,
                "steps": result.state.step_count,
                "trace_verified": session.store.verify(run_id),
                "links": {
                    "trace": f"/v1/runs/{run_id}/trace",
                    "replay": f"/v1/runs/{run_id}/replay",
                    "skill_report": "/v1/skills/report",
                    "respond": f"/v1/attempts/{run_id}/responses",
                    "assist": f"/v1/attempts/{run_id}/assistance",
                    "misconception": f"/v1/misconceptions/{run_id}",
                    "review_commit": f"/v1/runs/{run_id}/review-commit",
                },
            }
            if phase == "probe":
                teaching = artifacts["teach"][-1]
                transfer_item = teaching.get("independent_verification_item")
                if transfer_item is not None:
                    if _contains_product_answer_key(transfer_item):
                        raise ServiceError(
                            500,
                            "unsafe_product_activity_projection",
                            "independent verification item contains a private answer field",
                        )
                    provenance = fixture.get("provenance", {})
                    if (
                        isinstance(provenance, dict)
                        and provenance.get("content_origin")
                        == "local_versioned_export"
                    ):
                        _validate_public_transfer_item(transfer_item)
                payload.update(
                    {
                        "teaching": teaching,
                        "verification": {
                            "prompt": teaching["independent_verification_prompt"],
                            "prompt_instance_id": teaching[
                                "independent_verification_prompt_instance_id"
                            ],
                            "response_mode": teaching["independent_verification_response_mode"],
                            "status": "awaiting_learner_response",
                            **(
                                {"item": transfer_item}
                                if transfer_item is not None
                                else {}
                            ),
                        },
                        "mastery_update": None,
                        "reflection": None,
                    }
                )
            else:
                verification = artifacts["verify"][-1]["verification"]
                mastery_update = artifacts["update"][-1]
                payload.update(
                    {
                        "teaching": artifacts["teach"][-1],
                        "verification": verification,
                        "mastery_update": (
                            mastery_update
                            if mastery_update.get("commit_status", "committed") == "committed"
                            else None
                        ),
                        "reflection": artifacts["reflect"][-1],
                    }
                )
                payload["mastery_commit"] = _public_mastery_commit(mastery_update)
                provenance = fixture.get("provenance", {})
                payload["review_schedule_commit"] = (
                    self._commit_completed_run_review(run_id)
                    if isinstance(provenance, dict)
                    and provenance.get("content_origin")
                    == "local_versioned_export"
                    else {
                        "status": "withheld",
                        "code": "not_a_versioned_product_activity",
                        "retryable": False,
                    }
                )
            return payload
        finally:
            session.store.close()

    def deliver_assistance(
        self,
        run_id: str,
        phase: str,
        expected_version: int,
        expected_state: str,
        prompt_instance: str,
        action: str,
        elapsed_time_seconds: float,
        command_id: str,
    ) -> dict[str, Any]:
        with self._continuation_lock:
            return self._deliver_assistance_locked(
                run_id,
                phase,
                expected_version,
                expected_state,
                prompt_instance,
                action,
                elapsed_time_seconds,
                command_id,
            )

    def _deliver_assistance_locked(
        self,
        run_id: str,
        phase: str,
        expected_version: int,
        expected_state: str,
        prompt_instance: str,
        action: str,
        elapsed_time_seconds: float,
        command_id: str,
    ) -> dict[str, Any]:
        if not _valid_stored_run_id(run_id):
            raise ServiceError(400, "invalid_run_id", "run_id contains unsupported characters")
        if not isinstance(phase, str) or phase not in {"probe", "verification"}:
            raise ServiceError(400, "invalid_phase", "phase must be probe or verification")
        if isinstance(expected_version, bool) or not isinstance(expected_version, int) or expected_version < 1:
            raise ServiceError(400, "invalid_version", "expected_version must be a positive integer")
        if not isinstance(expected_state, str) or expected_state not in {
            "awaiting_probe",
            "awaiting_verification",
        }:
            raise ServiceError(400, "invalid_state", "expected_state is not a writable attempt state")
        if not isinstance(prompt_instance, str) or not prompt_instance or len(prompt_instance) > 160:
            raise ServiceError(400, "invalid_prompt_instance", "prompt_instance_id is invalid")
        if action != "next":
            raise ServiceError(400, "invalid_action", "action must be next")
        if (
            isinstance(elapsed_time_seconds, bool)
            or not isinstance(elapsed_time_seconds, (int, float))
            or not 0 <= elapsed_time_seconds <= 7200
        ):
            raise ServiceError(400, "invalid_elapsed_time", "elapsed_time_seconds must be in [0, 7200]")
        if not valid_public_command_identifier(command_id):
            raise ServiceError(400, "invalid_command_id", "command_id contains unsupported characters")
        fingerprint = _assistance_fingerprint(
            run_id,
            phase,
            expected_version,
            expected_state,
            prompt_instance,
            action,
            float(elapsed_time_seconds),
            command_id,
        )
        store = EventStore(self.database)
        try:
            events = store.events(run_id)
            if not events:
                raise ServiceError(404, "run_not_found", "attempt session does not exist")
            prior_command = next(
                (
                    event
                    for event in events
                    if event.kind == "assistance_delivered"
                    and event.payload.get("command_id") == command_id
                ),
                None,
            )
            if prior_command:
                if prior_command.payload.get("request_fingerprint") != fingerprint:
                    raise ServiceError(
                        409, "command_conflict", "command_id was already used for another request"
                    )
                response = dict(prior_command.payload["response"])
                response["idempotent_replay"] = True
                response["trace_verified"] = store.verify(run_id)
                return response
            if events[-1].seq != expected_version:
                raise ServiceError(409, "stale_version", "expected_version does not match current trace version")
            state = store.load_state(run_id)
            actual_state = attempt_state_name(state)
            if actual_state != expected_state:
                raise ServiceError(409, "state_mismatch", "expected_state does not match current session state")
            required_state = "awaiting_probe" if phase == "probe" else "awaiting_verification"
            if actual_state != required_state:
                raise ServiceError(409, "out_of_order", "assistance is not accepted in the current state")
            required_prompt = prompt_instance_id(run_id, phase)
            if prompt_instance != required_prompt:
                raise ServiceError(
                    409,
                    "prompt_mismatch",
                    "prompt_instance_id does not match the current assistance prompt",
                )
            if phase == "verification":
                raise ServiceError(
                    409,
                    "independent_verification_help_forbidden",
                    "the current verification must remain unassisted; start a targeted retry instead",
                )
            fixture = self._session_fixture(state, store)
            delivered = assistance_events_for_prompt(events, prompt_instance)
            try:
                assistance = authored_assistance_step(fixture, len(delivered) + 1)
            except LookupError:
                raise ServiceError(409, "assistance_exhausted", "all six assistance levels were delivered") from None
            before = state.to_dict()
            summaries = dict(state.context.get("assistance_summary", {}))
            summaries[prompt_instance] = {
                "phase": phase,
                "delivered_count": len(delivered) + 1,
                "strongest_action": assistance["action"],
                "diagnostic_evidence_weight": assistance["diagnostic_evidence_weight"],
                "policy_version": assistance["policy_version"],
            }
            state.context["assistance_summary"] = summaries
            after = state.to_dict()
            projected_version = expected_version + 1
            response = {
                "schema_version": "hermes.assistance-result.v1",
                "run_id": run_id,
                "state": actual_state,
                "state_version": projected_version,
                "prompt_instance_id": prompt_instance,
                "assistance": {
                    **assistance,
                    "phase": phase,
                    "independence_effect": "discounts_probe_evidence",
                },
                "remaining_levels": 6 - assistance["ordinal"],
                "idempotent_replay": False,
                "trace_verified": True,
                "links": {
                    "respond": f"/v1/attempts/{run_id}/responses",
                    "misconception": f"/v1/misconceptions/{run_id}",
                    "trace": f"/v1/runs/{run_id}/trace",
                },
            }
            try:
                event = store.append_if_version(
                    run_id,
                    expected_version,
                    "assistance_delivered",
                    {
                        "schema_version": "hermes.assistance-event.v1",
                        "command_id": command_id,
                        "request_fingerprint": fingerprint,
                        "phase": phase,
                        "expected_state": expected_state,
                        "prompt_instance_id": prompt_instance,
                        "elapsed_time_seconds": float(elapsed_time_seconds),
                        "timing_source": "client_self_reported",
                        **assistance,
                        "independence_effect": "discounts_probe_evidence",
                        "state_diff": state_diff(before, after),
                        "state_after": after,
                        "response": response,
                    },
                )
            except TraceVersionConflict:
                concurrent_command = next(
                    (
                        current
                        for current in store.events(run_id)
                        if current.kind == "assistance_delivered"
                        and current.payload.get("command_id") == command_id
                    ),
                    None,
                )
                if concurrent_command is not None:
                    if concurrent_command.payload.get("request_fingerprint") != fingerprint:
                        raise ServiceError(
                            409,
                            "command_conflict",
                            "command_id was already used for another request",
                        ) from None
                    replay = dict(concurrent_command.payload["response"])
                    replay["idempotent_replay"] = True
                    replay["trace_verified"] = store.verify(run_id)
                    return replay
                raise ServiceError(
                    409, "stale_version", "expected_version does not match current trace version"
                ) from None
            response["state_version"] = event.seq
            response["trace_verified"] = store.verify(run_id)
            return response
        finally:
            store.close()

    def misconception_dossier(self, run_id: str) -> dict[str, Any]:
        if not _valid_stored_run_id(run_id):
            raise ServiceError(400, "invalid_run_id", "run_id contains unsupported characters")
        store = EventStore(self.database)
        try:
            try:
                state = store.load_state(run_id)
            except KeyError:
                raise ServiceError(404, "run_not_found", "attempt session does not exist") from None
            if not self._is_projectable_attempt_state(state):
                raise ServiceError(404, "run_not_found", "attempt session does not exist")
            fixture = self._session_fixture(state, store)
            return project_misconception_dossier(store, run_id, fixture)
        finally:
            store.close()

    def misconception_report(self) -> dict[str, Any]:
        store = EventStore(self.database)
        try:
            items = []
            for run_id in store.run_ids():
                try:
                    state = store.load_state(run_id)
                    if not self._is_projectable_attempt_state(state):
                        continue
                    fixture = self._session_fixture(state, store)
                    dossier = project_misconception_dossier(store, run_id, fixture)
                except (KeyError, ValueError):
                    continue
                except ServiceError as exc:
                    if exc.code not in {
                        "fixture_snapshot_unavailable",
                        "fixture_snapshot_invalid",
                    }:
                        raise
                    continue
                items.append(
                    {
                        "run_id": run_id,
                        "fixture_id": dossier["fixture_id"],
                        "domain": dossier["domain"],
                        "module": dossier["module"],
                        "state": dossier["state"],
                        "learning_status": dossier["learning_status"],
                        "hypothesis_count": len(dossier["hypotheses"]),
                        "source_trace_version": dossier["provenance"]["source_trace_version"],
                        "link": f"/v1/misconceptions/{run_id}",
                    }
                )
            return {
                "schema_version": "hermes.misconception-report.v1",
                "count": len(items),
                "items": items,
                "cohort_evidence_status": "unavailable",
            }
        finally:
            store.close()

    def create_today_plan(
        self,
        plan_date: Any,
        exam_date: Any,
        daily_budget_minutes: Any,
        expected_version: Any,
        command_id: Any,
    ) -> dict[str, Any]:
        if not isinstance(plan_date, str):
            raise ServiceError(400, "invalid_plan_date", "plan_date must be YYYY-MM-DD")
        try:
            parsed_plan_date = date.fromisoformat(plan_date)
        except ValueError:
            raise ServiceError(
                400, "invalid_plan_date", "plan_date must be YYYY-MM-DD"
            ) from None
        if parsed_plan_date.isoformat() != plan_date:
            raise ServiceError(
                400, "invalid_plan_date", "plan_date must be YYYY-MM-DD"
            )
        if exam_date is not None and not isinstance(exam_date, str):
            raise ServiceError(400, "invalid_exam_date", "exam_date must be null or YYYY-MM-DD")
        if isinstance(exam_date, str):
            try:
                parsed_exam_date = date.fromisoformat(exam_date)
            except ValueError:
                raise ServiceError(
                    400,
                    "invalid_exam_date",
                    "exam_date must be null or YYYY-MM-DD",
                ) from None
            if parsed_exam_date.isoformat() != exam_date:
                raise ServiceError(
                    400,
                    "invalid_exam_date",
                    "exam_date must be null or YYYY-MM-DD",
                )
        if (
            isinstance(daily_budget_minutes, bool)
            or not isinstance(daily_budget_minutes, int)
        ):
            raise ServiceError(
                400,
                "invalid_daily_budget",
                "daily_budget_minutes must be an integer in [5, 240]",
            )
        if (
            isinstance(expected_version, bool)
            or not isinstance(expected_version, int)
        ):
            raise ServiceError(400, "invalid_version", "expected_version must be 0 for a new plan")
        if not valid_public_command_identifier(command_id):
            raise ServiceError(400, "invalid_command_id", "command_id contains unsupported characters")
        server_today = self._today_provider()
        if not isinstance(server_today, date):
            raise ServiceError(500, "clock_unavailable", "local date provider is unavailable")
        if plan_date != server_today.isoformat():
            store = ScheduleStore(
                self.database,
                planning_timezone=self._planning_timezone,
                allowed_evidence_origins=self._review_commit_evidence_origins,
            )
            try:
                try:
                    replay = store.replay_create_today_plan_command(
                        plan_date=plan_date,
                        exam_date=exam_date,
                        daily_budget_minutes=daily_budget_minutes,
                        expected_version=expected_version,
                        command_id=command_id,
                    )
                except ScheduleError as exc:
                    raise _schedule_service_error(exc) from None
            finally:
                store.close()
            if replay is not None:
                return replay
            raise ServiceError(
                409,
                "plan_date_mismatch",
                "plan_date must equal the local service date",
            )
        try:
            evidence = self._planning_evidence(plan_date)
            store = ScheduleStore(
                self.database,
                planning_timezone=self._planning_timezone,
                allowed_evidence_origins=self._review_commit_evidence_origins,
            )
            try:
                return store.create_today_plan(
                    plan_date=plan_date,
                    exam_date=exam_date,
                    daily_budget_minutes=daily_budget_minutes,
                    expected_version=expected_version,
                    command_id=command_id,
                    evidence=evidence,
                )
            finally:
                store.close()
        except ScheduleError as exc:
            raise _schedule_service_error(exc) from None

    def today_plan(self, plan_id: str) -> dict[str, Any]:
        if not _valid_plan_id(plan_id):
            raise ServiceError(400, "invalid_plan_id", "plan_id contains unsupported characters")
        store = ScheduleStore(
            self.database,
            planning_timezone=self._planning_timezone,
            allowed_evidence_origins=self._review_commit_evidence_origins,
        )
        try:
            try:
                return store.load_plan(plan_id)
            except ScheduleError as exc:
                raise _schedule_service_error(exc) from None
        finally:
            store.close()

    def transition_today_plan_task(
        self,
        plan_id: str,
        task_id: str,
        action: Any,
        expected_version: Any,
        expected_task_version: Any,
        command_id: Any,
        postpone_until: Any = None,
    ) -> dict[str, Any]:
        if not _valid_plan_id(plan_id):
            raise ServiceError(400, "invalid_plan_id", "plan_id contains unsupported characters")
        if not _valid_task_id(task_id):
            raise ServiceError(400, "invalid_task_id", "task_id contains unsupported characters")
        if not isinstance(action, str):
            raise ServiceError(400, "invalid_action", "action must be a supported schedule action")
        if action not in {"accept", "complete", "postpone", "skip"}:
            raise ServiceError(
                400,
                "invalid_action",
                "action must be accept, complete, postpone, or skip",
            )
        if (
            isinstance(expected_version, bool)
            or not isinstance(expected_version, int)
        ):
            raise ServiceError(400, "invalid_version", "expected_version must be a positive integer")
        if (
            isinstance(expected_task_version, bool)
            or not isinstance(expected_task_version, int)
        ):
            raise ServiceError(
                400,
                "invalid_task_version",
                "expected_task_version must be a positive integer",
            )
        if not valid_public_command_identifier(command_id):
            raise ServiceError(400, "invalid_command_id", "command_id contains unsupported characters")
        if postpone_until is not None and not isinstance(postpone_until, str):
            raise ServiceError(400, "invalid_postpone_until", "postpone_until must be YYYY-MM-DD")
        server_today = self._today_provider()
        if not isinstance(server_today, date):
            raise ServiceError(500, "clock_unavailable", "local date provider is unavailable")
        store = ScheduleStore(
            self.database,
            planning_timezone=self._planning_timezone,
            allowed_evidence_origins=self._review_commit_evidence_origins,
        )
        try:
            try:
                return store.transition_task(
                    plan_id=plan_id,
                    task_id=task_id,
                    action=action,
                    action_date=server_today.isoformat(),
                    expected_version=expected_version,
                    expected_task_version=expected_task_version,
                    command_id=command_id,
                    postpone_until=postpone_until,
                )
            except ScheduleError as exc:
                raise _schedule_service_error(exc) from None
        finally:
            store.close()

    def review_schedule(self) -> dict[str, Any]:
        store = ScheduleStore(
            self.database,
            planning_timezone=self._planning_timezone,
            allowed_evidence_origins=self._review_commit_evidence_origins,
        )
        try:
            return store.review_schedule()
        finally:
            store.close()

    def schedule_replay(self, stream_type: str, stream_id: str) -> dict[str, Any]:
        if stream_type not in {"today_plan", "review_task"}:
            raise ServiceError(400, "invalid_stream_type", "schedule stream type is invalid")
        valid_stream_id = (
            _valid_plan_id(stream_id)
            if stream_type == "today_plan"
            else _valid_task_id(stream_id)
        )
        if not valid_stream_id:
            raise ServiceError(400, "invalid_stream_id", "stream identifier is invalid")
        store = ScheduleStore(
            self.database,
            planning_timezone=self._planning_timezone,
            allowed_evidence_origins=self._review_commit_evidence_origins,
        )
        try:
            try:
                return store.replay(stream_type, stream_id)
            except ScheduleError as exc:
                raise _schedule_service_error(exc) from None
        finally:
            store.close()

    def _planning_evidence(
        self, plan_date: str, *, only_run_id: str | None = None
    ) -> list[PlanningEvidence]:
        """Project only trace-backed, per-run evidence allowed by scheduler v1."""

        store = EventStore(self.database)
        try:
            projected: list[PlanningEvidence] = []
            for run_id in store.run_ids():
                if only_run_id is not None and run_id != only_run_id:
                    continue
                events = store.events(run_id)
                if not events or not store.verify(run_id):
                    continue
                try:
                    state = store.load_state(run_id)
                    fixture = self._session_fixture(state, store)
                except (KeyError, ServiceError, ValueError):
                    continue
                # Batch/demo scenarios are evaluation fixtures, not learner
                # activity. Only a completed real staged attempt may seed Today.
                if (
                    state.context.get("scenario") != "attempt"
                    or state.context.get("evidence_origin")
                    not in self._review_commit_evidence_origins
                    or state.status is not RunStatus.COMPLETED
                ):
                    continue
                if (
                    state.context.get("evidence_origin") == "human_local_interactive"
                    and not self._is_launchable_versioned_product_fixture(fixture)
                ):
                    # Legacy representative fixtures may remain in a local
                    # database from earlier builds. They are traceable, but
                    # cannot become human ReviewSchedule evidence.
                    continue
                domain = str(fixture["domain"])
                fixture_skills = {
                    str(item["skill_id"]): float(item["weight"])
                    for item in fixture["skills"]
                }
                fallback_skill_id = min(
                    fixture_skills,
                    key=lambda item: (-fixture_skills[item], item),
                )
                fixture_hash = str(state.context["fixture_content_sha256"])
                activity_ref = ActivityRef(
                    fixture_id=str(fixture["fixture_id"]),
                    fixture_content_sha256=fixture_hash,
                    availability=self._review_activity_availability(
                        str(fixture["fixture_id"])
                    ),
                )
                terminal_event = next(
                    (
                        event
                        for event in reversed(events)
                        if event.kind == "phase_completed"
                        and event.payload.get("phase") == "reflect"
                        and event.payload.get("state_after", {}).get("status")
                        == "completed"
                    ),
                    None,
                )
                if terminal_event is None:
                    continue
                terminal_ref = _trace_evidence_ref(
                    run_id,
                    terminal_event,
                    kind="trace_terminal",
                    json_pointer="/state_after/status",
                    semantic="terminal_completed",
                    phase="reflect",
                )
                observe_event = next(
                    (
                        event
                        for event in reversed(events)
                        if event.kind == "phase_completed"
                        and event.payload.get("phase") == "observe"
                    ),
                    None,
                )
                if observe_event is None:
                    continue
                observe_ref = _trace_evidence_ref(
                    run_id,
                    observe_event,
                    kind="trace_observation",
                    json_pointer="/output/score/passed",
                    semantic="initial_answer_passed",
                    phase="observe",
                )
                update_event = next(
                    (
                        event
                        for event in reversed(events)
                        if event.kind == "phase_completed"
                        and event.payload.get("phase") == "update"
                    ),
                    None,
                )
                initial_failed = (
                    observe_event.payload.get("output", {})
                    .get("score", {})
                    .get("passed")
                    is not True
                )
                if update_event is not None:
                    update = update_event.payload.get("output", {})
                    update_skill_id = update.get("skill_id")
                    update_evidence = update.get("evidence", {})
                    verification_effective = (
                        update_evidence.get("verification_effective")
                        if isinstance(update_evidence, dict)
                        else None
                    )
                    schedulable_update = (
                        update.get("policy_version")
                        == "integration-learning-policy-v2"
                        and update.get("commit_status") in {
                            "committed",
                            "withheld_failed_verification",
                        }
                    ) or (
                        # Legacy v1 incorrectly wrote failed verification as a
                        # KT commit.  Keep it out of skill_report, but retain
                        # its immutable failed-transfer fact for a retry task.
                        update.get("policy_version")
                        == "integration-learning-policy-v1"
                        and update.get("commit_status") == "committed"
                        and verification_effective is False
                    )
                    if (
                        schedulable_update
                        and isinstance(update_skill_id, str)
                        and update_skill_id in fixture_skills
                    ):
                        effective = verification_effective
                        occurred_on, timezone_offset = self._event_local_basis(
                            update_event.occurred_at
                        )
                        projected.append(
                            PlanningEvidence(
                                evidence_ref=_trace_evidence_ref(
                                    run_id,
                                    update_event,
                                    kind="trace_skill_evidence",
                                    json_pointer="/output/evidence/verification_effective",
                                    semantic="verification_effective",
                                    phase="update",
                                ),
                                supporting_refs=(observe_ref, terminal_ref),
                                occurred_at=update_event.occurred_at,
                                occurred_on=occurred_on,
                                timezone_offset_minutes=timezone_offset,
                                domain=domain,
                                skill_id=update_skill_id,
                                verification_effective=(
                                    effective if isinstance(effective, bool) else None
                                ),
                                # The review kind follows independent transfer,
                                # not whether the learner's first answer was wrong.
                                attempt_failed=effective is not True,
                                activity_ref=activity_ref,
                            )
                        )

                diagnose_event = next(
                    (
                        event
                        for event in reversed(events)
                        if event.kind == "phase_completed"
                        and event.payload.get("phase") == "diagnose"
                    ),
                    None,
                )
                # A correct first answer does not provide an observed error from
                # which to project a cause hypothesis. A later failed transfer
                # remains a generic independent-retry signal in P0.2.
                if diagnose_event is None or not initial_failed:
                    continue
                ranked = (
                    diagnose_event.payload.get("output", {})
                    .get("diagnosis", {})
                    .get("hypotheses", [])
                )
                assessments_event = next(
                    (event for event in reversed(events) if event.kind == "probe_assessed"),
                    None,
                )
                assessment_by_cause = {
                    str(item.get("cause_id")): (index, item)
                    for index, item in enumerate(
                        assessments_event.payload.get("assessments", [])
                        if assessments_event is not None
                        else []
                    )
                    if isinstance(item, dict) and isinstance(item.get("cause_id"), str)
                }
                authored_causes = {
                    str(item["cause_id"]): str(item["label"])
                    for item in fixture["diagnosis"]["candidate_causes"]
                }
                for hypothesis_index, hypothesis in enumerate(ranked):
                    if not isinstance(hypothesis, dict) or not isinstance(
                        hypothesis.get("cause_id"), str
                    ):
                        continue
                    cause_id = str(hypothesis["cause_id"])
                    assessment = assessment_by_cause.get(cause_id)
                    claim_status = (
                        str(assessment[1].get("claim_status", "unconfirmed_hypothesis"))
                        if assessment is not None
                        else "unconfirmed_hypothesis"
                    )
                    if (
                        claim_status == "refuted_hypothesis"
                        or cause_id not in authored_causes
                    ):
                        continue
                    diagnose_ref = _trace_evidence_ref(
                        run_id,
                        diagnose_event,
                        kind="candidate_cause",
                        json_pointer=(
                            f"/output/diagnosis/hypotheses/{hypothesis_index}/status"
                        ),
                        semantic="candidate_hypothesis",
                        phase="diagnose",
                        subject_id=cause_id,
                        claim_status="unconfirmed_hypothesis",
                        confirmation_status="unconfirmed",
                    )
                    if assessment is not None and assessments_event is not None:
                        primary_ref = _trace_evidence_ref(
                            run_id,
                            assessments_event,
                            kind="candidate_cause",
                            json_pointer=f"/assessments/{assessment[0]}/claim_status",
                            semantic="candidate_claim_status",
                            subject_id=cause_id,
                            claim_status=claim_status,
                            confirmation_status="unconfirmed",
                        )
                        supporting_refs = (diagnose_ref, observe_ref, terminal_ref)
                        occurred_at = assessments_event.occurred_at
                    else:
                        primary_ref = diagnose_ref
                        supporting_refs = (observe_ref, terminal_ref)
                        occurred_at = diagnose_event.occurred_at
                    occurred_on, timezone_offset = self._event_local_basis(occurred_at)
                    projected.append(
                        PlanningEvidence(
                            evidence_ref=primary_ref,
                            supporting_refs=supporting_refs,
                            occurred_at=occurred_at,
                            occurred_on=occurred_on,
                            timezone_offset_minutes=timezone_offset,
                            domain=domain,
                            skill_id=(
                                str(update_event.payload.get("output", {}).get("skill_id"))
                                if update_event is not None
                                and update_event.payload.get("output", {}).get("skill_id")
                                in fixture_skills
                                else fallback_skill_id
                            ),
                            verification_effective=None,
                            attempt_failed=initial_failed,
                            cause_id=cause_id,
                            cause_label=authored_causes[cause_id],
                            activity_ref=activity_ref,
                        )
                    )
                    break
            return projected
        finally:
            store.close()

    def _commit_completed_run_review(self, run_id: str) -> dict[str, Any]:
        """Commit scheduling as a separate, retry-safe projection.

        The learning trace is already complete when this runs.  A scheduling
        failure is therefore returned as an explicit retryable projection
        status and never rewrites or rolls back the learner's trace.
        """

        trace_store = EventStore(self.database)
        try:
            try:
                state = trace_store.load_state(run_id)
                fixture = self._session_fixture(state, trace_store)
            except (KeyError, ServiceError, ValueError):
                return {
                    "status": "withheld",
                    "code": "run_or_fixture_unavailable",
                    "retryable": False,
                }
            origin = state.context.get("evidence_origin")
            if (
                origin == "human_local_interactive"
                and not self._is_launchable_versioned_product_fixture(fixture)
            ):
                return {
                    "status": "withheld",
                    "code": "not_launchable_versioned_product_activity",
                    "retryable": False,
                }
            if (
                origin == "evaluation_fixture"
                and not self._evaluation_projection_enabled
            ):
                return {
                    "status": "withheld",
                    "code": "evaluation_projection_disabled",
                    "retryable": False,
                }
        finally:
            trace_store.close()

        today = self._today_provider()
        if not isinstance(today, date):
            return {
                "status": "retry_required",
                "code": "clock_unavailable",
                "retryable": True,
            }

        try:
            evidence = self._planning_evidence(
                today.isoformat(), only_run_id=run_id
            )
            if not evidence:
                return {
                    "status": "withheld",
                    "code": "ineligible_evidence_origin_or_incomplete_run",
                    "retryable": False,
                }
            store = ScheduleStore(
                self.database,
                planning_timezone=self._planning_timezone,
                allowed_evidence_origins=self._review_commit_evidence_origins,
            )
            try:
                result = store.commit_review_tasks(
                    as_of_date=today.isoformat(),
                    command_id=_deterministic_review_command_id(run_id),
                    evidence=evidence,
                )
            finally:
                store.close()
            return {
                "status": "committed",
                "code": "review_task_committed",
                "retryable": False,
                "task": result["task"],
            }
        except Exception:
            return {
                "status": "retry_required",
                "code": "review_schedule_commit_failed",
                "retryable": True,
            }

    def commit_completed_run_review(self, run_id: str) -> dict[str, Any]:
        """Explicit retry entrypoint for the post-completion projection."""

        if not _valid_stored_run_id(run_id):
            raise ServiceError(400, "invalid_run_id", "run_id contains unsupported characters")
        store = EventStore(self.database)
        try:
            try:
                state = store.load_state(run_id)
            except KeyError:
                raise ServiceError(404, "run_not_found", "attempt session does not exist") from None
            if state.status is not RunStatus.COMPLETED:
                raise ServiceError(
                    409,
                    "run_incomplete",
                    "review scheduling requires a completed learning run",
                )
        finally:
            store.close()
        return self._commit_completed_run_review(run_id)

    def _review_activity_availability(self, fixture_id: str) -> str:
        if fixture_id == "xingce.data-analysis.growth-rate.synthetic-01":
            return "launchable"
        return (
            "launchable"
            if self.product_activities.is_launchable_fixture(fixture_id)
            else "activity_unavailable"
        )

    def _is_launchable_versioned_product_fixture(
        self, fixture: dict[str, Any]
    ) -> bool:
        """Return true only for the exact currently launchable product release.

        A persisted run is bound to its immutable snapshot. Matching only an
        identifier would let a stale or legacy fixture be projected into the
        human review schedule after an activity release changed.
        """

        provenance = fixture.get("provenance")
        fixture_id = fixture.get("fixture_id")
        if (
            not isinstance(provenance, dict)
            or provenance.get("content_origin") != "local_versioned_export"
            or not isinstance(fixture_id, str)
            or not self.product_activities.is_launchable_fixture(fixture_id)
        ):
            return False
        try:
            current = self.product_activities.resolve_launchable_fixture(fixture_id)
        except KeyError:
            return False
        return fixture_content_hash(current) == fixture_content_hash(fixture)

    def _is_projectable_attempt_state(self, state: Any) -> bool:
        context = getattr(state, "context", None)
        if not isinstance(context, dict) or context.get("scenario") != "attempt":
            return False
        origin = context.get("evidence_origin")
        return origin == "human_local_interactive" or (
            self._evaluation_projection_enabled and origin == "evaluation_fixture"
        )

    def _projectable_attempt_run_ids(self, store: EventStore) -> list[str]:
        run_ids: list[str] = []
        for run_id in store.run_ids():
            try:
                state = store.load_state(run_id)
            except (KeyError, ValueError):
                continue
            if self._is_projectable_attempt_state(state):
                run_ids.append(run_id)
        return run_ids

    def _event_local_basis(self, occurred_at: str) -> tuple[str, int]:
        parsed = datetime.fromisoformat(occurred_at.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("trace event time must include a timezone")
        local = parsed.astimezone(self._planning_timezone)
        offset = local.utcoffset()
        if offset is None:
            raise ValueError("planning timezone offset is unavailable")
        return local.date().isoformat(), int(offset.total_seconds() // 60)

    @staticmethod
    def _session_fixture(state: Any, store: EventStore) -> dict[str, Any]:
        content_hash = state.context.get("fixture_content_sha256")
        if not isinstance(content_hash, str) or len(content_hash) != 64:
            raise ServiceError(
                409,
                "fixture_snapshot_unavailable",
                "attempt session does not contain an immutable fixture binding",
            )
        try:
            snapshot = store.load_content_snapshot(content_hash, kind="domain_fixture")
        except KeyError:
            raise ServiceError(
                409,
                "fixture_snapshot_unavailable",
                "the immutable fixture snapshot for this attempt is unavailable",
            ) from None
        fixture = snapshot.get("content")
        if (
            not isinstance(fixture, dict)
            or fixture_content_hash(fixture) != content_hash
            or fixture.get("fixture_id") != state.context.get("fixture_id")
        ):
            raise ServiceError(
                409,
                "fixture_snapshot_invalid",
                "the immutable fixture binding failed integrity validation",
            )
        return fixture

    @staticmethod
    def _validate_attempt_evidence(response: Any, confidence: Any, response_time_seconds: Any) -> None:
        if not isinstance(response, str) or not response.strip():
            raise ServiceError(400, "invalid_response", "response must be non-empty text")
        if len(response) > 20_000:
            raise ServiceError(413, "response_too_large", "response exceeds the 20000-character limit")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            raise ServiceError(400, "invalid_confidence", "confidence must be a number in [0, 1]")
        if (
            isinstance(response_time_seconds, bool)
            or not isinstance(response_time_seconds, (int, float))
            or not 0 <= response_time_seconds <= 7200
        ):
            raise ServiceError(400, "invalid_response_time", "response_time_seconds must be a number in [0, 7200]")

    def run_learning_loop(self, mode: str, run_id: str | None = None) -> dict[str, Any]:
        if not isinstance(mode, str) or mode not in SCENARIOS:
            raise ServiceError(400, "invalid_mode", "mode must be success, ambiguous, or offline")
        if run_id is not None and not _valid_stored_run_id(run_id):
            raise ServiceError(400, "invalid_run_id", "run_id contains unsupported characters")
        try:
            session, result = run_scenario(mode, self.database, run_id=run_id)
        except ValueError as exc:
            if "already exists" in str(exc):
                raise ServiceError(409, "run_exists", "a run with this identifier already exists") from None
            raise ServiceError(422, "run_rejected", "the learning run could not be started") from None
        try:
            artifacts = result.state.artifacts
            return {
                "run_id": result.state.run_id,
                "mode": mode,
                "status": result.state.status.value,
                "steps": result.state.step_count,
                "summary": {
                    "diagnosis_decision": artifacts["diagnose"][-1]["decision"],
                    "verification_effective": artifacts["verify"][-1]["verification"]["effective"],
                    "mastery_delta": artifacts["update"][-1]["mastery_delta"],
                    "outcome": artifacts["reflect"][-1]["outcome"],
                },
                "trace_verified": session.store.verify(result.state.run_id),
                "links": {
                    "trace": f"/v1/runs/{result.state.run_id}/trace",
                    "replay": f"/v1/runs/{result.state.run_id}/replay",
                },
            }
        finally:
            session.store.close()

    def trace(self, run_id: str) -> dict[str, Any]:
        events, verified = self._events(run_id)
        return {
            "run_id": run_id,
            "trace_verified": verified,
            "event_count": len(events),
            "events": [
                {
                    "seq": event.seq,
                    "occurred_at": event.occurred_at,
                    "kind": event.kind,
                    "event_hash": event.event_hash,
                    "previous_hash": event.previous_hash,
                    "payload": public_safe(event.payload),
                }
                for event in events
            ],
        }

    def replay(self, run_id: str) -> dict[str, Any]:
        if not _valid_stored_run_id(run_id):
            raise ServiceError(400, "invalid_run_id", "run_id contains unsupported characters")
        store = EventStore(self.database)
        try:
            if not store.events(run_id):
                raise ServiceError(404, "run_not_found", "the requested run does not exist")
            frames = list(store.replay(run_id))
            return {
                "run_id": run_id,
                "trace_verified": True,
                "frame_count": len(frames),
                "frames": public_safe(frames),
            }
        finally:
            store.close()

    def skill_report(self) -> dict[str, Any]:
        store = EventStore(self.database)
        try:
            aggregates: dict[str, dict[str, Any]] = defaultdict(
                lambda: {
                    "run_ids": [],
                    "deltas": [],
                    "verified_transfers": 0,
                    "failed_or_inconclusive": 0,
                    "latest_mastery": None,
                    "latest_uncertainty": None,
                    "latest_at": "",
                }
            )
            for run_id in store.run_ids():
                try:
                    state = store.load_state(run_id)
                except KeyError:
                    continue
                if not self._is_projectable_attempt_state(state):
                    continue
                for event in store.events(run_id):
                    if event.kind != "phase_completed" or event.payload.get("phase") != "update":
                        continue
                    update = event.payload.get("output", {})
                    if update.get("commit_status", "committed") != "committed":
                        continue
                    evidence = update.get("evidence", {})
                    if not _is_valid_mastery_commit(update):
                        # Preserve the immutable legacy trace, but never project
                        # an invalid old failed/assisted commit as current KT.
                        continue
                    skill_id = update.get("skill_id")
                    if not isinstance(skill_id, str):
                        continue
                    row = aggregates[skill_id]
                    row["run_ids"].append(run_id)
                    row["deltas"].append(float(update["mastery_delta"]))
                    effective = evidence.get("verification_effective")
                    if effective is True:
                        row["verified_transfers"] += 1
                    else:
                        row["failed_or_inconclusive"] += 1
                    if event.occurred_at >= row["latest_at"]:
                        row["latest_at"] = event.occurred_at
                        row["latest_mastery"] = update.get("new_mastery")
                        row["latest_uncertainty"] = update.get("uncertainty")
            items = []
            for skill_id, row in sorted(aggregates.items()):
                deltas = row.pop("deltas")
                run_ids = row.pop("run_ids")
                items.append(
                    {
                        "skill_id": skill_id,
                        "run_count": len(set(run_ids)),
                        "average_mastery_delta": round(sum(deltas) / len(deltas), 12),
                        **row,
                    }
                )
            return {
                "policy": "trace-summary-v1",
                "note": "Latest mastery is per-run evidence, not a fabricated longitudinal merge.",
                "skill_count": len(items),
                "items": items,
            }
        finally:
            store.close()

    def _events(self, run_id: str) -> tuple[list[Any], bool]:
        if not _valid_stored_run_id(run_id):
            raise ServiceError(400, "invalid_run_id", "run_id contains unsupported characters")
        store = EventStore(self.database)
        try:
            events = store.events(run_id)
            if not events:
                raise ServiceError(404, "run_not_found", "the requested run does not exist")
            return events, store.verify(run_id)
        finally:
            store.close()


def _judgment_service_error(error: JudgmentSessionError) -> ServiceError:
    if isinstance(error, JudgmentContentUnavailable):
        return ServiceError(409, "content_review_required", str(error))
    if isinstance(error, JudgmentSessionConflict):
        return ServiceError(409, "judgment_session_conflict", str(error))
    return ServiceError(400, "invalid_judgment_session", str(error))


def _xingce_adaptive_service_error(error: XingceAdaptiveSessionError) -> ServiceError:
    if str(error) == "content_review_required":
        return ServiceError(409, "content_review_required", "该行测子型尚无已审核的本地自适应题包。")
    if "stale" in str(error) or "out-of-order" in str(error) or "bound" in str(error):
        return ServiceError(409, "xingce_adaptive_session_conflict", str(error))
    return ServiceError(400, "invalid_xingce_adaptive_session", str(error))


def _question_bank_service_error(error: Exception) -> ServiceError:
    if isinstance(error, QuestionBankUnavailable):
        return ServiceError(
            409,
            "question_bank_unavailable",
            "完整行测题库未安装或未通过完整性校验。",
        )
    if isinstance(error, QuestionBankNotFound):
        return ServiceError(404, "question_not_found", "题目不存在或尚未通过内容审核。")
    if isinstance(error, QuestionBankConflict):
        if str(error) == "paper source order is unavailable":
            return ServiceError(409, "question_bank_paper_sequence_unavailable", "该套卷的来源题序尚未核验，不能进入整卷练习。")
        return ServiceError(409, "question_bank_attempt_conflict", str(error))
    if isinstance(error, QuestionBankAssetUnavailable):
        return ServiceError(409, "question_assets_not_bundled", "题目所需图片尚未作为本地资源打包，当前不能作答。")
    return ServiceError(400, "invalid_question_bank_request", str(error))


def _schedule_service_error(error: ScheduleError) -> ServiceError:
    if isinstance(error, ScheduleNotFound):
        return ServiceError(404, "schedule_not_found", "the requested schedule record does not exist")
    if isinstance(error, ScheduleVersionConflict):
        return ServiceError(
            409,
            "stale_schedule_version",
            "expected_version does not match the current TodayPlan version",
        )
    if isinstance(error, ScheduleTaskVersionConflict):
        return ServiceError(
            409,
            "stale_task_version",
            "the TodayPlan task snapshot no longer matches the ReviewSchedule task",
        )
    if isinstance(error, ScheduleHistoricalPlan):
        return ServiceError(
            409,
            "historical_plan_read_only",
            "historical TodayPlans are read-only; create or open the current local date plan",
        )
    if isinstance(error, ScheduleBudgetBelowAcceptedCommitment):
        return ServiceError(
            409,
            "budget_below_accepted_commitment",
            (
                "daily_budget_minutes must be at least "
                f"{error.required_minutes} to keep accepted commitments actionable"
            ),
        )
    if isinstance(error, ScheduleCommandConflict):
        return ServiceError(
            409,
            "command_conflict",
            "command_id was already used for a different schedule command",
        )
    if isinstance(error, ScheduleTransitionError):
        return ServiceError(
            409,
            "invalid_schedule_transition",
            "the requested task transition is not allowed from its current state",
        )
    if isinstance(error, ScheduleValidationError):
        return ServiceError(400, "invalid_schedule_command", str(error))
    return ServiceError(409, "schedule_rejected", "the schedule command was rejected")


def _study_pack_service_error(
    error: StudyPackError,
    *,
    not_found_code: str = "study_pack_not_found",
) -> ServiceError:
    code = error.code
    if code in {"invalid_source_body", "invalid_command_id", "invalid_answer"}:
        return ServiceError(400, code, _study_pack_error_message(code))
    if code == "invalid_entity_id":
        return ServiceError(404, not_found_code, _study_pack_error_message(not_found_code))
    if code in {"source_too_large", "answer_too_large"}:
        return ServiceError(413, code, _study_pack_error_message(code))
    if code in {
        "pdf_parse_failed",
        "pdf_encrypted_unsupported",
        "pdf_text_unavailable_ocr_required",
    }:
        return ServiceError(422, code, _study_pack_error_message(code))
    if code in {
        "artifact_unsupported",
        "artifact_quarantined",
        "artifact_not_published",
        "citation_unresolved",
        "attempt_history_invalid",
        "stale_version",
        "command_conflict",
        "invalid_transition",
    }:
        status = 404 if code == "artifact_unsupported" else 409
        return ServiceError(status, code, _study_pack_error_message(code))
    return ServiceError(
        409,
        "study_pack_rejected",
        "the Study Pack operation was rejected",
    )


def _study_pack_error_message(code: str) -> str:
    messages = {
        "invalid_source_body": "Study Pack input is invalid",
        "invalid_command_id": "command_id must use the opaque Study Pack command profile",
        "invalid_answer": "learner_answer must be non-empty text",
        "study_pack_not_found": "the requested Study Pack does not exist",
        "source_too_large": "Study Pack input exceeds a fixed local resource limit",
        "answer_too_large": "learner_answer exceeds the fixed local resource limit",
        "pdf_parse_failed": "the local PDF text parser could not read this file",
        "pdf_encrypted_unsupported": "encrypted PDFs are not supported",
        "pdf_text_unavailable_ocr_required": "this PDF has no usable text layer and OCR is unavailable",
        "artifact_unsupported": "the requested Study Pack practice item does not exist",
        "artifact_quarantined": "the requested Study Pack artifact is quarantined",
        "artifact_not_published": "the requested Study Pack artifact is not published",
        "citation_unresolved": "the cited frozen source span could not be verified",
        "attempt_history_invalid": "saved Study Pack attempt history could not be verified",
        "stale_version": "the expected Study Pack or artifact version is stale",
        "command_conflict": "command_id was already used for a different Study Pack mutation",
        "invalid_transition": "the requested Study Pack lifecycle transition is not allowed",
    }
    return messages.get(code, "the Study Pack operation was rejected")


def _validate_study_pack_entity(value: Any, prefix: str, code: str) -> None:
    try:
        validate_entity_id(value, prefix)
    except StudyPackError:
        raise ServiceError(
            400,
            code,
            "the Study Pack route identifier is invalid",
        ) from None


def _validate_study_pack_command(value: Any) -> None:
    try:
        validate_command_id(value)
    except StudyPackError:
        raise ServiceError(
            400,
            "invalid_command_id",
            _study_pack_error_message("invalid_command_id"),
        ) from None


def _public_study_pack_projection(value: dict[str, Any]) -> dict[str, Any]:
    # Copy through JSON so a caller cannot retain or mutate the store projection.
    result = json.loads(json.dumps(value, ensure_ascii=False))
    result["schema_version"] = "lumi.study-pack-detail.v1"
    pack_id = result.get("pack_id")
    if not isinstance(pack_id, str):
        raise ServiceError(
            500,
            "unsafe_study_pack_projection",
            "Study Pack projection is missing its opaque identifier",
        )
    artifacts = result.get("artifacts")
    if not isinstance(artifacts, list):
        raise ServiceError(
            500,
            "unsafe_study_pack_projection",
            "Study Pack projection has an invalid artifact collection",
        )
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise ServiceError(
                500,
                "unsafe_study_pack_projection",
                "Study Pack projection contains an invalid artifact",
            )
        artifact.pop("answer", None)
        artifact.pop("explanation", None)
        artifact.pop("citations", None)
        if artifact.get("artifact_type") == "study_pack.practice_item":
            content = artifact.get("content")
            if not isinstance(content, dict):
                raise ServiceError(
                    500,
                    "unsafe_study_pack_projection",
                    "Study Pack practice projection is unavailable",
                )
            allowed_content = {
                "schema_version",
                "item_kind",
                "prompt",
                "scorer",
            }
            if set(content) != allowed_content:
                raise ServiceError(
                    500,
                    "unsafe_study_pack_projection",
                    "Study Pack practice projection contains a private field",
                )
            artifact["content"] = {key: content[key] for key in sorted(allowed_content)}
            artifact_id = artifact.get("artifact_id")
            artifact["links"] = {
                "launch": f"/v1/study-pack-items/{artifact_id}/launch",
            }
    result["links"] = {
        "self": f"/v1/study-packs/{pack_id}",
        "commands": f"/v1/study-packs/{pack_id}/commands",
        "replay": f"/v1/study-packs/{pack_id}/replay",
    }
    return result


def _contains_private_study_pack_key(value: Any) -> bool:
    forbidden = {
        "answer",
        "explanation",
        "citations",
        "cited_source_context",
        "content_json",
        "learner_answer_text",
        "normalized_text",
        "original_blob",
        "segments_json",
    }
    if isinstance(value, dict):
        return bool(forbidden.intersection(value)) or any(
            _contains_private_study_pack_key(item) for item in value.values()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_private_study_pack_key(item) for item in value)
    return False


def _contains_private_attempt_key(value: Any) -> bool:
    if isinstance(value, dict):
        if "learner_answer_text" in value or "raw_learner_answer" in value:
            return True
        return any(_contains_private_attempt_key(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_private_attempt_key(item) for item in value)
    return False


def _validate_public_transfer_item(value: Any) -> None:
    allowed = {"item_id", "content_signature", "novelty_status", "options"}
    if not isinstance(value, dict) or set(value) != allowed:
        raise ServiceError(
            500,
            "unsafe_product_activity_projection",
            "independent verification item has an invalid public contract",
        )
    if not all(
        isinstance(value[key], str) and bool(value[key])
        for key in ("item_id", "content_signature", "novelty_status")
    ):
        raise ServiceError(
            500,
            "unsafe_product_activity_projection",
            "independent verification item identifiers are invalid",
        )
    options = value["options"]
    if not isinstance(options, (dict, list)) or not options:
        raise ServiceError(
            500,
            "unsafe_product_activity_projection",
            "independent verification item options are invalid",
        )


def _contains_product_answer_key(value: Any) -> bool:
    forbidden = {
        "answer",
        "answer_labels",
        "correct_answer",
        "correct_option",
        "explanation",
        "explanation_text",
        "is_correct",
    }
    if isinstance(value, dict):
        return bool(forbidden.intersection(value)) or any(
            _contains_product_answer_key(item) for item in value.values()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_product_answer_key(item) for item in value)
    return False


def _trace_evidence_ref(
    run_id: str,
    event: Any,
    *,
    kind: str,
    json_pointer: str,
    semantic: str,
    subject_id: str | None = None,
    phase: str | None = None,
    claim_status: str | None = None,
    confirmation_status: str | None = None,
) -> EvidenceRef:
    ref = (
        f"trace:{run_id}:event:{event.seq}:{event.event_hash}"
        f"#pointer={json_pointer}"
    )
    return EvidenceRef(
        ref=ref,
        kind=kind,
        source_type="trace_event",
        run_id=run_id,
        event_seq=event.seq,
        event_hash=event.event_hash,
        event_kind=event.kind,
        json_pointer=json_pointer,
        semantic=semantic,
        subject_id=subject_id,
        phase=phase,
        claim_status=claim_status,
        confirmation_status=confirmation_status,
    )


def _valid_stored_run_id(value: Any) -> bool:
    return valid_stored_run_identifier(value)


def _new_public_run_id() -> str:
    alphabet = "ABCDEFGHIJKLMNOP"
    return "r_" + "".join(
        f"{alphabet[byte >> 4]}{alphabet[byte & 15]}"
        for byte in secrets.token_bytes(20)
    )


def _deterministic_review_command_id(run_id: str) -> str:
    alphabet = "ABCDEFGHIJKLMNOP"
    digest = hashlib.sha256(f"review-schedule:{run_id}".encode("utf-8")).digest()[:20]
    return "c_" + "".join(
        f"{alphabet[byte >> 4]}{alphabet[byte & 15]}" for byte in digest
    )


def _public_mastery_commit(update: Any) -> dict[str, Any]:
    if not isinstance(update, dict):
        return {
            "status": "withheld",
            "reason_code": "inconclusive_verification",
            "skill_id": None,
            "previous_mastery": None,
            "new_mastery": None,
            "mastery_delta": 0,
        }
    raw_status = update.get("commit_status")
    reason_by_status = {
        "committed": "verified_independent_transfer",
        "withheld_failed_verification": "failed_verification",
        "withheld_assisted_verification": "assisted_verification",
        "withheld_inconclusive_verification": "inconclusive_verification",
    }
    committed = raw_status == "committed"
    previous = update.get("previous_mastery")
    new = update.get("new_mastery") if committed else previous
    return {
        "status": "committed" if committed else "withheld",
        "reason_code": reason_by_status.get(
            raw_status, "inconclusive_verification"
        ),
        "skill_id": update.get("skill_id"),
        "previous_mastery": previous,
        "new_mastery": new,
        "mastery_delta": update.get("mastery_delta", 0) if committed else 0,
    }


def _is_valid_mastery_commit(update: Any) -> bool:
    if not isinstance(update, dict) or update.get("commit_status") != "committed":
        return False
    evidence = update.get("evidence")
    if (
        not isinstance(evidence, dict)
        or evidence.get("verification_effective") is not True
        or evidence.get("independently_verified") is not True
    ):
        return False
    if update.get("policy_version") == "integration-learning-policy-v2":
        return (
            evidence.get("scorer_passed") is True
            and evidence.get("independently_answered_without_help") is True
        )
    return True


def _is_human_local_attempt_state(state: Any) -> bool:
    context = getattr(state, "context", None)
    return (
        isinstance(context, dict)
        and context.get("scenario") == "attempt"
        and context.get("evidence_origin") == "human_local_interactive"
    )


def _human_attempt_run_ids(store: EventStore) -> list[str]:
    run_ids: list[str] = []
    for run_id in store.run_ids():
        try:
            state = store.load_state(run_id)
        except (KeyError, ValueError):
            continue
        if _is_human_local_attempt_state(state):
            run_ids.append(run_id)
    return run_ids


def _valid_plan_id(value: Any) -> bool:
    if not isinstance(value, str) or not value.startswith("today-"):
        return False
    raw_date = value.removeprefix("today-")
    try:
        parsed = date.fromisoformat(raw_date)
    except ValueError:
        return False
    return parsed.isoformat() == raw_date


def _valid_task_id(value: Any) -> bool:
    return (
        isinstance(value, str)
        and value.startswith("review-")
        and len(value) == len("review-") + 24
        and all(character in "0123456789abcdef" for character in value[7:])
    )


def _assistance_fingerprint(
    run_id: str,
    phase: str,
    expected_version: int,
    expected_state: str,
    prompt_instance: str,
    action: str,
    elapsed_time_seconds: float,
    command_id: str,
) -> str:
    encoded = json.dumps(
        {
            "run_id": run_id,
            "phase": phase,
            "expected_version": expected_version,
            "expected_state": expected_state,
            "prompt_instance_id": prompt_instance,
            "action": action,
            "elapsed_time_seconds": elapsed_time_seconds,
            "command_id": command_id,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def public_safe(value: Any) -> Any:
    """Defense in depth: never serialize protected repository or bulk-data paths."""
    forbidden = ("shenlun-agent-platform", "/users/", "xingcetiku", "155gb")
    if isinstance(value, str):
        lowered = value.lower()
        if any(fragment in lowered for fragment in forbidden):
            return "[REDACTED_LOCAL_PATH]"
        return value
    if isinstance(value, dict):
        return {str(key): public_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [public_safe(item) for item in value]
    return value
