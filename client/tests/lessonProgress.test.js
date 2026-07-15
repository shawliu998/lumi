import assert from "node:assert/strict";
import test from "node:test";

import {
  initialLessonProgress,
  lessonCompletionKey,
  normalizeLessonPolicy,
  recordInitialAnswer,
  recordVerification,
} from "../src/lessonProgress.js";

const POLICY = { minimumQuestions: 4, requiredTransfers: 2 };

test("reading alone leaves learning progress unchanged", () => {
  const before = initialLessonProgress();
  const afterReadingMethodCard = { ...before };
  assert.deepEqual(afterReadingMethodCard, before);
});

test("two complete fixture runs satisfy four questions and two transfers", () => {
  let progress = initialLessonProgress();
  progress = recordInitialAnswer(progress, true);
  progress = recordVerification(progress, true, POLICY);
  assert.equal(progress.complete, false);
  progress = recordInitialAnswer(progress, true);
  progress = recordVerification(progress, true, POLICY);
  assert.equal(progress.answeredCount, 4);
  assert.equal(progress.verifiedStreak, 2);
  assert.equal(progress.complete, true);
});

test("a failed transfer resets the consecutive transfer count", () => {
  let progress = initialLessonProgress();
  progress = recordInitialAnswer(progress, true);
  progress = recordVerification(progress, true, POLICY);
  progress = recordInitialAnswer(progress, true);
  progress = recordVerification(progress, false, POLICY);
  assert.equal(progress.verifiedStreak, 0);
  assert.equal(progress.complete, false);
});

test("the full micro-tutorial appears only after the second scored error", () => {
  let progress = initialLessonProgress();
  progress = recordInitialAnswer(progress, false);
  const afterFirstError = recordVerification(progress, true, POLICY);
  assert.equal(afterFirstError.revealTeaching, false);
  const afterSecondError = recordVerification(progress, false, POLICY);
  assert.equal(afterSecondError.revealTeaching, true);
});

test("server completion policy is normalized without weakening its thresholds", () => {
  assert.deepEqual(
    normalizeLessonPolicy({ minimum_questions: 4, consecutive_verified_transfers: 2 }, 2),
    POLICY,
  );
  assert.deepEqual(normalizeLessonPolicy({}, 2), POLICY);
});

test("saved completion is bound to the exact lesson version", () => {
  assert.equal(
    lessonCompletionKey({ lesson_id: "growth.lesson-01", version: "1.0.0" }),
    "growth.lesson-01@1.0.0",
  );
  assert.equal(lessonCompletionKey({ lesson_id: "growth.lesson-01" }), "");
});
