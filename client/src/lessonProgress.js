export function normalizeLessonPolicy(policy = {}, itemCount = 0) {
  const fallbackQuestions = Math.max(3, Math.max(0, Number(itemCount) || 0) * 2);
  const minimumQuestions = Number.isInteger(policy.minimum_questions)
    ? Math.max(3, policy.minimum_questions)
    : fallbackQuestions;
  const requiredTransfers = Number.isInteger(policy.consecutive_verified_transfers)
    ? Math.max(1, policy.consecutive_verified_transfers)
    : 2;
  return { minimumQuestions, requiredTransfers };
}

export function lessonCompletionKey(lesson) {
  if (!lesson?.lesson_id || !lesson?.version) return "";
  return `${lesson.lesson_id}@${lesson.version}`;
}

export function initialLessonProgress() {
  return { answeredCount: 0, verifiedStreak: 0, mistakeCount: 0 };
}

export function recordInitialAnswer(progress, passed) {
  return {
    answeredCount: progress.answeredCount + 1,
    verifiedStreak: progress.verifiedStreak,
    mistakeCount: progress.mistakeCount + (passed ? 0 : 1),
  };
}

export function recordVerification(progress, effective, policy) {
  const next = {
    answeredCount: progress.answeredCount + 1,
    verifiedStreak: effective ? progress.verifiedStreak + 1 : 0,
    mistakeCount: progress.mistakeCount + (effective ? 0 : 1),
  };
  return {
    ...next,
    complete: next.answeredCount >= policy.minimumQuestions
      && next.verifiedStreak >= policy.requiredTransfers,
    revealTeaching: !effective && next.mistakeCount >= 2,
  };
}
