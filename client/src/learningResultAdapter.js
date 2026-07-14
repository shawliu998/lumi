function requiredText(value, path) {
  if (typeof value !== "string" || !value.trim()) throw new TypeError(`${path} is required`);
  return value.trim();
}

function selectedInitialOption(attempt) {
  const observation = attempt?.score?.observations?.find((item) =>
    item?.kind === "response" && item?.observation_id === "selected_option",
  );
  return requiredText(observation?.value, "attempt.score.observations.selected_option");
}

export function probeChoicesFromPrompt(prompt) {
  if (typeof prompt !== "string") return [];
  const quoted = [...prompt.matchAll(/[“"]([^”"]{2,80})[”"]/g)].map((match) => match[1].trim());
  if (quoted.length !== 2 || !prompt.includes("还是")) return [];
  return quoted.map((value, index) => ({ id: `probe-choice-${index + 1}`, value }));
}

export function probeEvidenceSummary(continuation) {
  const assessment = continuation?.teaching?.based_on?.probe_assessment;
  const items = assessment?.assessments;
  if (!Array.isArray(items) || items.length === 0) {
    return {
      status: "unavailable",
      title: "探查结论不可用",
      detail: "服务没有返回可核查的探查评估；后续教学不能视为针对已确认错因。",
    };
  }
  const directions = items.map((item) => item?.evidence_direction);
  if (directions.every((value) => value === "insufficient_or_mixed")) {
    return {
      status: "insufficient",
      title: "这次探查没有区分出错因",
      detail: "教学按首位候选提供，不代表该候选已经确认。",
    };
  }
  if (directions.includes("supports")) {
    return {
      status: "supports-candidate",
      title: "探查支持了一项候选",
      detail: "它仍是待验证假设，需要结合独立迁移表现继续判断。",
    };
  }
  return {
    status: "narrows-candidates",
    title: "探查排除了一部分候选",
    detail: "剩余候选仍未确认，教学只按当前证据选择。",
  };
}

export function reviewCommitSummary(commit) {
  if (!commit || typeof commit !== "object") {
    return { status: "unavailable", title: "复习任务未确认排程", detail: "本轮结果没有返回 ReviewSchedule 写入回执。" };
  }
  if (commit.status === "committed") {
    const task = commit.task;
    return {
      status: "committed",
      title: commit.created === false ? "复习任务已在安排中" : "复习任务已排入日程",
      detail: task && typeof task === "object"
        ? `${requiredText(task.reason, "review_schedule_commit.task.reason")} · ${Number(task.expected_duration_minutes)} 分钟 · ${requiredText(task.success_criterion, "review_schedule_commit.task.success_criterion")}`
        : "ReviewSchedule 已写入，但任务详情不可用。",
    };
  }
  if (commit.status === "withheld") {
    return { status: "withheld", title: "本轮未生成复习任务", detail: `排程条件未满足（${requiredText(commit.code, "review_schedule_commit.code")}）。` };
  }
  if (commit.status === "retry_required" && commit.retryable === true) {
    return { status: "retry-required", title: "复习任务尚未写入", detail: "学习轨迹已保存；排程投影需要重试。当前客户端没有安全的单独重试操作，请稍后重新查看复习安排。" };
  }
  throw new TypeError("unsupported review_schedule_commit contract");
}

export function masteryCommitSummary(commit) {
  if (!commit || typeof commit !== "object") throw new TypeError("mastery_commit is required");
  const allowedReasons = new Set([
    "verified_independent_transfer",
    "failed_verification",
    "assisted_verification",
    "inconclusive_verification",
  ]);
  if (!allowedReasons.has(commit.reason_code)) throw new TypeError("unsupported mastery_commit reason_code");
  requiredText(commit.skill_id, "mastery_commit.skill_id");
  for (const field of ["previous_mastery", "new_mastery", "mastery_delta"]) {
    if (!Number.isFinite(commit[field])) throw new TypeError(`mastery_commit.${field} is required`);
  }
  if (commit.status === "committed" && commit.reason_code === "verified_independent_transfer") {
    return {
      status: "committed",
      title: "KT 已写入",
      detail: `独立迁移达到提交条件；掌握变化 ${commit.mastery_delta >= 0 ? "+" : ""}${commit.mastery_delta.toFixed(3)}。`,
    };
  }
  if (commit.status !== "withheld" || commit.reason_code === "verified_independent_transfer") {
    throw new TypeError("mastery_commit status and reason are inconsistent");
  }
  const reasons = {
    failed_verification: "独立迁移未通过",
    assisted_verification: "验证过程使用了帮助，不构成独立证据",
    inconclusive_verification: "验证证据不足",
  };
  return {
    status: "withheld",
    title: "KT 未写入",
    detail: `${reasons[commit.reason_code]}，因此本轮掌握状态保持不变。`,
  };
}

export function normalizeCompletedLearningResult({ attempt, continuation, firstActivity, transferActivity }) {
  if (continuation?.state !== "completed") throw new TypeError("continuation must be completed");
  const verificationAttempt = continuation?.verification?.provenance?.verification_attempt;
  const transferAnswer = requiredText(verificationAttempt?.selected_option, "verification.provenance.verification_attempt.selected_option");
  const transferCorrect = verificationAttempt?.correct;
  if (typeof transferCorrect !== "boolean") throw new TypeError("verification attempt correctness is required");
  const nextAction = continuation?.reflection?.next_action;
  return {
    initial: {
      material: requiredText(firstActivity?.materialText, "firstActivity.materialText"),
      title: requiredText(firstActivity?.stemText, "firstActivity.stemText"),
      answer: selectedInitialOption(attempt),
      correct: attempt?.score?.passed === true,
    },
    probe: probeEvidenceSummary(continuation),
    transfer: {
      material: requiredText(transferActivity?.materialText, "transferActivity.materialText"),
      title: requiredText(transferActivity?.stemText, "transferActivity.stemText"),
      answer: transferAnswer,
      correct: transferCorrect,
      independentlyAnswered: verificationAttempt?.independently_answered === true,
    },
    mastery: masteryCommitSummary(continuation.mastery_commit),
    nextAction,
    review: reviewCommitSummary(continuation.review_schedule_commit),
  };
}
