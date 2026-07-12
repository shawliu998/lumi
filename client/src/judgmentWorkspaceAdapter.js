const CONFIDENCE_VALUES = new Set(["low", "medium", "high"]);
const OPTION_VALUES = new Set(["A", "B", "C", "D"]);

export const JUDGMENT_CONFIDENCE_OPTIONS = Object.freeze([
  ["low", "不太确定"],
  ["medium", "基本确定"],
  ["high", "非常确定"],
]);

export const JUDGMENT_STAGE_COPY = Object.freeze({
  awaiting_probe: "先用一题短探查区分候选原因",
  awaiting_transfer: "看完针对性讲解后，完成无提示迁移",
  completed: "本轮证据已写入本机收据",
  completed_no_error: "本题没有观察到需要辨析的错误候选",
});

export function isJudgmentOption(value) {
  return OPTION_VALUES.has(String(value || "").trim().toUpperCase());
}

export function isJudgmentConfidence(value) {
  return CONFIDENCE_VALUES.has(String(value || "").trim().toLowerCase());
}

export function normalizeJudgmentAnswer(value) {
  return String(value || "").trim().toUpperCase();
}

export function normalizeJudgmentConfidence(value) {
  return String(value || "").trim().toLowerCase();
}

export function judgmentFormReadiness({ selectedOption, confidence, inFlight = false } = {}) {
  if (inFlight) return { ready: false, reason: "正在写入本机记录，请勿重复提交。" };
  if (!isJudgmentOption(selectedOption)) return { ready: false, reason: "请选择一个答案后再提交。" };
  if (!isJudgmentConfidence(confidence)) return { ready: false, reason: "请选择作答信心后再提交。" };
  return { ready: true, reason: "提交后会创建本机学习记录。" };
}

export function candidateStatusCopy(status) {
  if (status === "supported") return "有支持证据，仍待后续验证";
  if (status === "refuted") return "当前证据不支持，仍非最终结论";
  return "候选 / 未确认";
}

export function reviewTaskCopy(task) {
  if (!task) return null;
  return {
    title: task.kind === "delayed_retention" ? "延后保持性复习" : "独立重试",
    dueOn: task.due_on || "待服务返回",
    criterion: task.success_criterion || "无提示、独立、可确定评分的作答",
    consequence: task.skip_consequence || "不会自动提高掌握状态。",
  };
}

export function stageProgress(stage) {
  if (stage === "awaiting_probe") return 2;
  if (stage === "awaiting_transfer") return 4;
  if (stage === "completed" || stage === "completed_no_error") return 5;
  return 1;
}
