export const SMART_PRACTICE_SCOPE_TARGET = 80;
export const SMART_PRACTICE_BANK_ID = "lumi.xingce.core-320.practice-v3";
export const SMART_PRACTICE_BANK_VERSION = "1.0.1";
export const SMART_PRACTICE_BANK_SHA256 = "854ba5e483454718408cfbf8b428881333130d2224cfd4b5db3499cd54baf117";
export const SMART_PRACTICE_SESSION_TARGET = 8;

export const DEFAULT_SMART_PRACTICE_SCOPE_ID = "xingce.data-analysis.core";

export const SMART_PRACTICE_SCOPES = Object.freeze([
  Object.freeze({
    key: "verbal",
    scopeId: "xingce.verbal.core",
    label: "言语理解",
    focus: "片段阅读 · 逻辑填空 · 语句表达",
    description: "围绕主旨、意图、细节与语句关系连续作答；只在重复错误形成证据后增加讲解。",
    poolSize: SMART_PRACTICE_SCOPE_TARGET,
  }),
  Object.freeze({
    key: "judgment",
    scopeId: "xingce.judgment.core",
    label: "判断推理",
    focus: "图形 · 定义 · 类比 · 逻辑",
    description: "覆盖规则识别、概念匹配与条件推理，用跨题型证据区分偶然失误和重复模式。",
    poolSize: SMART_PRACTICE_SCOPE_TARGET,
  }),
  Object.freeze({
    key: "quantitative",
    scopeId: "xingce.quantitative.core",
    label: "数量关系",
    focus: "工程 · 行程 · 比例 · 计数",
    description: "从题意建模到快速计算连续训练，解析默认折叠，不打断当前 8 题节奏。",
    poolSize: SMART_PRACTICE_SCOPE_TARGET,
  }),
  Object.freeze({
    key: "data-analysis",
    scopeId: DEFAULT_SMART_PRACTICE_SCOPE_ID,
    label: "资料分析",
    focus: "增长 · 比重 · 平均 · 倍数",
    description: "覆盖读数、列式、估算与比较，后续验证题自然混入同一固定 8 题练习。",
    poolSize: SMART_PRACTICE_SCOPE_TARGET,
  }),
  Object.freeze({
    key: "mixed",
    scopeId: "xingce.mixed.core",
    label: "混合练习",
    focus: "四模块交叉出题",
    description: "从四个模块交叉选取，适合整组训练与检验方法能否在题型切换后独立使用。",
    poolSize: SMART_PRACTICE_SCOPE_TARGET * 4,
    mixed: true,
  }),
]);

const SCOPE_BY_ID = new Map(SMART_PRACTICE_SCOPES.map((scope) => [scope.scopeId, scope]));

export function validateSmartPracticeCapabilities(payload) {
  const bank = payload?.smart_practice_bank;
  const counts = bank?.counts;
  const scopes = Array.isArray(bank?.scopes) ? bank.scopes : [];
  const scopeById = new Map(scopes.map((scope) => [scope?.scope_id, scope]));
  const validModules = SMART_PRACTICE_SCOPES
    .filter((scope) => !scope.mixed)
    .every((scope) => scopeById.get(scope.scopeId)?.question_count === scope.poolSize);
  const mixed = SMART_PRACTICE_SCOPES.find((scope) => scope.mixed);
  const digest = String(bank?.generated_sha256 || "");

  if (
    bank?.bank_id !== SMART_PRACTICE_BANK_ID
    || bank?.version !== SMART_PRACTICE_BANK_VERSION
    || bank?.target_count !== SMART_PRACTICE_SESSION_TARGET
    || counts?.questions !== SMART_PRACTICE_SCOPE_TARGET * 4
    || counts?.questions_per_module !== SMART_PRACTICE_SCOPE_TARGET
    || counts?.module_scopes !== 4
    || counts?.scopes !== SMART_PRACTICE_SCOPES.length
    || scopes.length !== SMART_PRACTICE_SCOPES.length
    || !validModules
    || scopeById.get(mixed.scopeId)?.question_count !== mixed.poolSize
    || digest !== SMART_PRACTICE_BANK_SHA256
  ) {
    throw new TypeError("Unsupported Core-320 capability contract");
  }

  return bank;
}

export function getSmartPracticeScope(scopeId) {
  return SCOPE_BY_ID.get(scopeId) || SCOPE_BY_ID.get(DEFAULT_SMART_PRACTICE_SCOPE_ID);
}

export function createSmartPracticeStartBody(scopeId = DEFAULT_SMART_PRACTICE_SCOPE_ID) {
  if (!SCOPE_BY_ID.has(scopeId)) {
    throw new TypeError("Unsupported smart-practice scope_id");
  }
  return { scope_id: scopeId };
}
