const EVIDENCE_LABELS = new Map([
  ["trace_skill_evidence:verification_effective", "独立验证结果"],
  ["trace_observation:initial_answer_passed", "首答评分"],
  ["trace_terminal:terminal_completed", "本轮完成记录"],
]);

export function evidenceDisplayLabel(ref) {
  if (ref?.kind === "candidate_cause") return "候选错因证据";
  return EVIDENCE_LABELS.get(`${ref?.kind}:${ref?.semantic}`) || "记录证据";
}
