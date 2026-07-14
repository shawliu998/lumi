const SKILL_NAMES = {
  "xingce.data.growth.identify-base-current": "增长率与基期量",
  "xingce.data.growth.compute-rate": "增长率计算",
  "xingce.verbal.main-idea.integrate": "主旨概括",
  "xingce.verbal.scope-control": "范围控制",
  "xingce.judgment.logic.necessary-condition": "必要条件",
  "xingce.judgment.logic.symbolize": "逻辑符号化",
};

export function reportGroupsFromSidecar(report) {
  if (report?.policy !== "trace-summary-v1" || !report?.items?.length) return [];

  const definitions = {
    verbal: { id: "verbal", title: "言语理解与表达", skills: [] },
    data: { id: "data", title: "资料分析", skills: [] },
    judgment: { id: "judgment", title: "判断推理", skills: [] },
  };

  report.items
    .filter((item) => (
      typeof item?.skill_id === "string"
      && item.skill_id.startsWith("xingce.")
      && isNonNegativeCount(item.run_count)
      && isNonNegativeCount(item.verified_transfers)
      && isNonNegativeCount(item.failed_or_inconclusive)
    ))
    .forEach((item) => {
      const groupId = item.skill_id.includes(".verbal.")
        ? "verbal"
        : item.skill_id.includes(".judgment.")
          ? "judgment"
          : "data";
      const completedRuns = nonNegativeCount(item.run_count);
      const verifiedTransfers = nonNegativeCount(item.verified_transfers);
      const failedOrInconclusive = nonNegativeCount(item.failed_or_inconclusive);
      const evidenceKind = verifiedTransfers > 0
        ? "verified"
        : failedOrInconclusive > 0
          ? "not_verified"
          : "insufficient";

      definitions[groupId].skills.push({
        id: item.skill_id,
        name: SKILL_NAMES[item.skill_id] || item.skill_id.split(".").slice(-2).join(" · "),
        completedRuns,
        verifiedTransfers,
        failedOrInconclusive,
        evidenceKind,
        evidenceTitle: evidenceKind === "verified"
          ? "有独立验证通过记录"
          : evidenceKind === "not_verified"
            ? "仅有未通过或不确定记录"
            : "证据不足",
        last: formatLocalDate(item.latest_at),
        latestTraceValue: finiteNumberOrNull(item.latest_mastery),
        latestTraceUncertainty: finiteNumberOrNull(item.latest_uncertainty),
        averageTraceDelta: finiteNumberOrNull(item.average_mastery_delta),
        live: item,
      });
    });

  return Object.values(definitions).filter((group) => group.skills.length > 0);
}

function nonNegativeCount(value) {
  return Number(value);
}

function isNonNegativeCount(value) {
  if (value === null || value === undefined || value === "") return false;
  const count = Number(value);
  return Number.isInteger(count) && count >= 0;
}

function finiteNumberOrNull(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function formatLocalDate(value) {
  if (!value) return "暂无";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "暂无";
  return `${date.getMonth() + 1} 月 ${date.getDate()} 日`;
}
