import assert from "node:assert/strict";
import test from "node:test";

import {
  normalizePracticeOverview,
  normalizePracticeProfile,
  normalizeWrongQuestionBook,
} from "../src/practiceInsights.js";

function moduleRecord(moduleId, moduleLabel, attemptCount = 0) {
  return {
    module_id: moduleId,
    module_label: moduleLabel,
    facts: {
      attempt_count: attemptCount,
      correct_count: 0,
      incorrect_count: 0,
      accuracy: null,
      recorded_response_time_count: 0,
      average_response_time_seconds: null,
    },
    independent_evidence: {
      attempt_count: 0,
      correct_count: 0,
      incorrect_count: 0,
      accuracy: null,
      distinct_family_count: 0,
      verified_transfer_count: 0,
    },
    ignored_non_independent_count: 0,
    evidence_status: "insufficient",
    reason_codes: ["no_scored_attempts"],
  };
}

function embeddedProfile() {
  return {
    overall: {
      session_count: 0,
      completed_session_count: 0,
      scored_attempt_count: 0,
      correct_count: 0,
      incorrect_count: 0,
      accuracy: null,
      independent_attempt_count: 0,
      ignored_non_independent_attempt_count: 0,
      recorded_response_time_count: 0,
      average_response_time_seconds: null,
    },
    modules: [
      moduleRecord("verbal", "言语理解"),
      moduleRecord("judgment", "判断推理"),
      moduleRecord("quantitative", "数量关系"),
      moduleRecord("data-analysis", "资料分析"),
    ],
    error_hypotheses: [],
    evidence_policy: { semantics: "observed-facts-only" },
  };
}

function wrongQuestion() {
  return {
    question_ref: { question_id: "q-1", question_version_id: "q-1@1" },
    module_id: "verbal",
    module_label: "言语理解",
    diagnostic_unit_id: "verbal.main-idea",
    review_state: "needs_review",
    question: { prompt: "请选择最合适的主旨。", response_mode: "choice", options: { A: "甲", B: "乙" } },
    answer_review: { correct_option: "A", key_principle: "先找共同话题。", explanation: "解析内容。" },
    attempts: {
      total_count: 2,
      wrong_count: 1,
      independent_wrong_count: 1,
      last_selected_option: "B",
      last_wrong_at: "2026-07-15T10:00:00+08:00",
      last_attempt_at: "2026-07-15T10:00:00+08:00",
    },
    diagnosis_hypotheses: [],
  };
}

test("practice overview keeps null metrics and accepts only known recommended scopes", () => {
  const payload = {
    schema_version: "lumi.practice-overview.v1",
    profile: embeddedProfile(),
    recent_sessions: [],
    wrong_question_preview: [wrongQuestion()],
    recommendation: {
      decision: {
        recommended_scope_id: "xingce.judgment.core",
        current_scope_id: "xingce.verbal.core",
        reason_codes: ["independent_errors_observed"],
        evidence_refs: ["attempt-1"],
      },
    },
    audit: {},
  };
  const normalized = normalizePracticeOverview(payload);
  assert.equal(normalized.recommendedScopeId, "xingce.judgment.core");
  assert.equal(normalized.profile.overall.accuracy, null);
  assert.equal(normalized.wrongQuestionPreview[0].lastSelectedOption, "B");

  const unknown = normalizePracticeOverview({
    ...payload,
    recommendation: {
      decision: { ...payload.recommendation.decision, recommended_scope_id: "unknown.scope" },
    },
  });
  assert.equal(unknown.recommendedScopeId, "");
});

test("practice overview exposes only a valid resumable Core-320 session", () => {
  const base = {
    schema_version: "lumi.practice-overview.v1",
    profile: embeddedProfile(),
    wrong_question_preview: [],
    recommendation: {
      decision: {
        recommended_scope_id: "xingce.mixed.core",
        current_scope_id: "xingce.verbal.core",
        reason_codes: [],
        evidence_refs: [],
      },
    },
    audit: {},
  };
  const active = normalizePracticeOverview({
    ...base,
    recent_sessions: [{
      session_id: "practice-active",
      scope_id: "xingce.verbal.core",
      status: "active",
      answered_count: 3,
      target_count: 8,
      title: "言语理解",
      module_label: "言语理解",
      started_at: "2026-07-15T10:00:00+08:00",
    }],
  });
  assert.deepEqual(active.activeSession, {
    sessionId: "practice-active",
    scopeId: "xingce.verbal.core",
    answeredCount: 3,
    targetCount: 8,
    title: "言语理解",
    moduleLabel: "言语理解",
    startedAt: "2026-07-15T10:00:00+08:00",
  });

  const incompatible = normalizePracticeOverview({
    ...base,
    recent_sessions: [{
      session_id: "practice-unknown",
      scope_id: "unknown.scope",
      status: "active",
      answered_count: 3,
      target_count: 8,
    }],
  });
  assert.equal(incompatible.activeSession, null);
});

test("empty wrong-question and profile responses stay explicit empty records", () => {
  const book = normalizeWrongQuestionBook({
    schema_version: "lumi.wrong-question-book.v1",
    total: 0,
    count: 0,
    items: [],
  });
  assert.deepEqual(book.items, []);

  const profile = normalizePracticeProfile({
    schema_version: "lumi.practice-profile.v1",
    ...embeddedProfile(),
    audit: {},
  });
  assert.equal(profile.overall.scored_attempt_count, 0);
  assert.equal(profile.overall.average_response_time_seconds, null);
  assert.equal(profile.modules.length, 4);
});

test("read models fail closed instead of filling malformed evidence with demo values", () => {
  assert.throws(
    () => normalizeWrongQuestionBook({
      schema_version: "lumi.wrong-question-book.v1",
      total: 1,
      count: 1,
      items: [{ ...wrongQuestion(), attempts: { wrong_count: 1 } }],
    }),
    /Invalid wrong-question record/,
  );
  const profile = embeddedProfile();
  profile.overall.accuracy = "0%";
  assert.throws(
    () => normalizePracticeProfile({ schema_version: "lumi.practice-profile.v1", ...profile }),
    /Invalid practice profile overall metrics/,
  );
});
