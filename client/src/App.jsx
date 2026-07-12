import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowRight,
  BookOpen,
  BookmarkSimple,
  Books,
  CaretDown,
  CaretLeft,
  CaretRight,
  ChartBar,
  ChatCircleDots,
  CheckCircle,
  ClipboardText,
  Gear,
  House,
  Info,
  ListChecks,
  MagnifyingGlass,
  Microphone,
  NotePencil,
  Question,
  Target,
  Toolbox,
  X,
} from "@phosphor-icons/react";
import {
  commandTodayPlanTask,
  continueAttempt,
  createTodayPlan,
  fetchHealth,
  fetchMisconceptionDossier,
  fetchProductActivityBundle,
  fetchReviewSchedule,
  fetchSkillReport,
  fetchTodayPlan,
  requestNextAssistance,
  submitAttempt,
} from "./hermesApi";
import { assertIndependentTransferBinding } from "./productActivityAdapter.js";
import { normalizeCompletedLearningResult, probeChoicesFromPrompt } from "./learningResultAdapter.js";
import { ProductActivityLoadState, ProductActivityQuestion } from "./ProductActivityViews.jsx";
import {
  ASSISTANCE_ACTIONS,
  appendAssistance,
  createAssistanceCommandId,
  createAssistanceState,
  normalizeMisconceptionDossier,
} from "./learningSupportAdapter";
import { reportGroupsFromSidecar } from "./reportEvidenceAdapter";
import { classifyCreatePlanError, resolveClientNow } from "./todayPlanAdapter";
import {
  ReviewScheduleReport,
  ReviewScheduleSummary,
  TodayPlanOverview,
  TodayPracticeScreen,
} from "./TodayPlanViews";
import { StudyPackMaterials } from "./StudyPackViews.jsx";
import { JudgmentWorkspace } from "./JudgmentWorkspace.jsx";

const NAV_ITEMS = [
  { id: "judgment", label: "学习空间", icon: Target },
  { id: "overview", label: "历史总览", icon: House },
  { id: "practice", label: "练习任务", icon: ListChecks },
  { id: "tools", label: "训练工具", icon: Toolbox },
  { id: "materials", label: "学习资料", icon: Books },
  { id: "reports", label: "技能报告", icon: ChartBar },
];

const TOOLS = [
  { category: "诊断", title: "错因辨析", description: "用一组短题验证一个具体的错因假设。", available: true },
  { category: "练习", title: "同类变式", description: "围绕一个技能完成无提示的独立作答。", available: false },
  { category: "复习", title: "间隔复习", description: "复习已到期、但曾经学会的技能。", available: false },
  { category: "复盘", title: "要点复盘", description: "对照材料与评分点逐项核查答案。", available: false },
  { category: "复盘", title: "局部改写", description: "只重写一个问题句或一个答案段落。", available: false },
  { category: "复盘", title: "二次作答", description: "保留原题，重新计时组织并作答。", available: false },
  { category: "计划", title: "今日计划", description: "按到期任务与可用时间安排今天的顺序。", available: false },
  { category: "复盘", title: "错题复盘", description: "查看原题、作答、评分和待确认错因。", available: false },
  { category: "复习", title: "方法清单", description: "回看已确认的方法、公式与易混点。", available: false },
  { category: "诊断", title: "迁移验证", description: "更换题面，检查方法能否独立使用。", available: false },
  { category: "练习", title: "材料定位", description: "练习从申论材料中定位可用信息。", available: false },
  { category: "复盘", title: "提纲复盘", description: "检查面试回答的观点、层次与例证。", available: false },
];

const CONNECTED_SKILL_NAME = "增长率与基期量";
const CONNECTED_SKILL_IDS = new Set([
  "xingce.data.growth.identify-base-current",
  "xingce.data.growth.compute-rate",
]);

const INITIAL_SIDECAR_STATE = {
  phase: "checking",
  health: null,
  report: null,
  error: null,
};

const INITIAL_PLANNING_STATE = {
  phase: "loading",
  plan: null,
  schedule: null,
  error: null,
  notice: null,
  processing: null,
};

function connectionCopy(sidecar) {
  if (sidecar.phase === "connected") return ["本机服务已连接", `${sidecar.health?.run_count || 0} 条运行轨迹`];
  if (sidecar.phase === "checking") return ["正在连接本机服务", "读取本机记录"];
  if (sidecar.phase === "error") return ["本机服务响应异常", "训练不可用"];
  return ["本机服务未连接", "训练不可用"];
}

function diagnosisDecisionCopy(value) {
  if (value === "disambiguate_hypotheses") return "候选原因仍需区分";
  if (value === "confirm_top_hypothesis") return "需要继续验证首位候选";
  if (value === "retention_probe") return "未形成错因判断，转入保持性验证";
  return value || "未返回诊断决策";
}

function Sidebar({ page, setPage, collapsed, setCollapsed, onUtility, sidecar, onRetrySidecar }) {
  const [connectionTitle, connectionDetail] = connectionCopy(sidecar);
  const connectionContent = (
    <>
      {sidecar.phase === "connected" ? <CheckCircle size={14} weight="fill" /> : <Info size={14} />}
      <span><strong>{connectionTitle}</strong><small>{connectionDetail}</small></span>
    </>
  );
  return (
    <aside className={collapsed ? "sidebar collapsed" : "sidebar"}>
      <div className="brand-row">
        <button className="brand-identity" onClick={() => collapsed && setCollapsed(false)} aria-label={collapsed ? "展开侧栏" : "Lumi 学习"}>
          <span className="brand-mark"><BookOpen weight="fill" /></span>
          {!collapsed && <strong>Lumi</strong>}
        </button>
        {!collapsed && (
          <button className="icon-button brand-close" onClick={() => setCollapsed(true)} aria-label="收起侧栏">
            <X size={14} />
          </button>
        )}
      </div>

      <nav className="primary-nav" aria-label="主导航">
        {NAV_ITEMS.map(({ id, label, icon: Icon }) => (
          <button
            className={page === id ? "nav-item active" : "nav-item"}
            key={id}
            onClick={() => setPage(id)}
            aria-label={label}
            aria-current={page === id ? "page" : undefined}
            title={collapsed ? label : undefined}
          >
            <Icon size={15} />
            {!collapsed && <span>{label}</span>}
          </button>
        ))}
      </nav>

      <div className="sidebar-spacer" />

      {sidecar.phase === "offline" || sidecar.phase === "error" ? (
        <button className={`connection-status ${sidecar.phase}`} onClick={onRetrySidecar} aria-label={`${connectionTitle}，${connectionDetail}，点击重试`} data-testid="sidecar-status" data-state={sidecar.phase} title={collapsed ? connectionTitle : undefined}>
          {connectionContent}
        </button>
      ) : (
        <div className={`connection-status ${sidecar.phase}`} data-testid="sidecar-status" data-state={sidecar.phase} title={collapsed ? connectionTitle : undefined}>
          {connectionContent}
        </div>
      )}

      <nav className="secondary-nav" aria-label="辅助导航">
        <button className="nav-item" onClick={() => onUtility("settings")} aria-label="设置" title={collapsed ? "设置" : undefined}><Gear size={15} />{!collapsed && <span>设置</span>}</button>
        <button className="nav-item" onClick={() => onUtility("feedback")} aria-label="意见反馈" title={collapsed ? "意见反馈" : undefined}><ChatCircleDots size={15} />{!collapsed && <span>意见反馈</span>}</button>
        <button className="nav-item" onClick={() => onUtility("help")} aria-label="使用帮助" title={collapsed ? "使用帮助" : undefined}><Question size={15} />{!collapsed && <span>使用帮助</span>}</button>
      </nav>

      <button className="profile-row" onClick={() => onUtility("profile")} aria-label="本机学习者" title={collapsed ? "本机学习者" : undefined}>
        <span className="avatar">本</span>
        {!collapsed && <><span>本机学习者</span><CaretRight size={15} /></>}
      </button>
    </aside>
  );
}

function Topbar({ page, setPage, onSearch, onUtility }) {
  const tabs = [
    ["overview", "总览"],
    ["practice", "任务"],
    ["reports", "报告"],
    ["settings", "设置"],
  ];

  const onTab = (id) => {
    if (id === "settings") onUtility("settings");
    else setPage(id);
  };

  return (
    <header className="topbar">
      <label className="scope-select">
        <span className="sr-only">当前训练范围</span>
        <select value="训练范围未设置" disabled>
          <option>训练范围未设置</option>
        </select>
      </label>
      <nav className="top-tabs" aria-label="页面标签">
        {tabs.map(([id, label]) => (
          <button
            className={page === id ? "top-tab active" : "top-tab"}
            key={id}
            onClick={() => onTab(id)}
            aria-current={page === id ? "page" : undefined}
          >
            {label}
          </button>
        ))}
      </nav>
      <button className="global-search" onClick={onSearch} aria-label="打开全局搜索">
        <MagnifyingGlass size={14} />
        <span>搜索题目、技能或学习记录…</span>
      </button>
    </header>
  );
}

function SidePanel({ title, eyebrow, onClose, children }) {
  return (
    <div className="panel-scrim" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <aside className="side-panel" role="dialog" aria-modal="true" aria-label={title}>
        <header className="panel-header">
          <div>{eyebrow && <small>{eyebrow}</small>}<h2>{title}</h2></div>
          <button className="icon-button panel-close" onClick={onClose} aria-label="关闭"><X size={16} /></button>
        </header>
        <div className="panel-body">{children}</div>
      </aside>
    </div>
  );
}

function AssistanceLadder({ state, promptAvailable, onRequest }) {
  const current = state.items[state.items.length - 1] || null;
  const currentOrdinal = Number(current?.ordinal) || 0;
  const next = ASSISTANCE_ACTIONS[currentOrdinal] || null;
  return (
    <section className="assistance-ladder" data-testid="assistance-ladder" data-level={currentOrdinal} data-state={state.status} data-persistence={promptAvailable ? "sidecar" : "unavailable"}>
      <div className="assistance-heading">
        <div><Question size={14} /><strong>渐进帮助</strong></div>
        <small>{currentOrdinal} / {ASSISTANCE_ACTIONS.length}</small>
      </div>
      <ol className="assistance-steps" aria-label="帮助级别">
        {ASSISTANCE_ACTIONS.map((item) => (
          <li key={item.action} className={item.ordinal < currentOrdinal ? "used" : item.ordinal === currentOrdinal ? "current" : "locked"} title={item.label}>
            <span>{item.ordinal}</span><small>{item.label}</small>
          </li>
        ))}
      </ol>
      {current ? (
        <div className="assistance-content" role="status" data-ordinal={current.ordinal} data-policy-version={current.policy_version} data-diagnostic-evidence-weight={current.diagnostic_evidence_weight} data-calibration-status={current.calibration_status}>
          <small>第 {current.ordinal} 级 · {current.title}</small>
          <p>{current.content}</p>
          <span>诊断证据权重 {Number(current.diagnostic_evidence_weight).toFixed(2)} · 工程策略未校准</span>
        </div>
      ) : (
        <p className="assistance-independent">尚未请求帮助；服务会从“再试一次”开始逐级推进。</p>
      )}
      <div className="assistance-boundary">
        <Info size={13} />
        <span>{promptAvailable ? "每次请求都会写入本机轨迹并推进状态版本；档位和证据权重由服务决定。" : "当前服务未返回 prompt_instance_id；帮助写入不可用。"}</span>
      </div>
      {state.status === "error" && <p className="assistance-error" role="alert">{state.error?.message || "帮助请求失败，未推进当前版本。"}</p>}
      {state.status === "ready" && next ? (
        <button className="button secondary assistance-action" type="button" onClick={onRequest}>
          请求下一档 · {next.label}<CaretRight size={12} />
        </button>
      ) : state.status === "requesting" ? (
        <button className="button secondary assistance-action" type="button" disabled>正在写入帮助事件</button>
      ) : state.status === "error" ? (
        <button className="button secondary assistance-action" type="button" onClick={onRequest}>重试请求下一档</button>
      ) : state.status === "unavailable" ? (
        <button className="button secondary assistance-action" type="button" disabled>帮助不可用 · 缺少题目实例</button>
      ) : (
        <p className="assistance-exhausted">六级帮助已用尽；再次请求将由服务拒绝。</p>
      )}
      {current && <small className="assistance-policy">策略 {current.policy_version}</small>}
    </section>
  );
}

function claimStatusCopy(value) {
  if (value === "supported_hypothesis") return "有支持证据 · 尚未确认";
  if (value === "refuted_hypothesis") return "有反驳证据 · 尚未确认";
  if (value === "unconfirmed_hypothesis") return "尚未确认";
  return "状态不可用";
}

function learningStatusCopy(value) {
  if (value === "awaiting_probe") return "待定向探查";
  if (value === "processing_probe_response") return "探查处理未完成";
  if (value === "awaiting_independent_verification") return "待独立验证";
  if (value === "processing_verification_response") return "验证处理未完成";
  if (value === "remediated_by_independent_transfer") return "已完成独立迁移";
  if (value === "needs_targeted_retry") return "需要定向重试";
  if (value === "inconclusive_needs_fresh_independent_verification") return "需要新的独立验证";
  if (value === "no_error_candidate") return "无需错因探查";
  if (value === "no_misconception_observed") return "未观察到错因候选";
  return value || "状态不可用";
}

function dossierContinuationGate(dossierState, phase, promptInstanceId) {
  if (["idle", "loading"].includes(dossierState.phase)) {
    return { kind: "loading", reason: "正在核对本机档案与题目实例，暂不开放写入。" };
  }
  if (dossierState.phase !== "connected" || !dossierState.dossier) {
    return { kind: "blocked", reason: "无法确认服务端当前状态；为避免重复写入，原题已锁定。" };
  }
  const dossier = dossierState.dossier;
  if (dossier.requiresRestart) {
    const reason = dossier.serviceState === "processing_probe"
      ? "上一次探查作答已被服务消费，但后续处理未完成；原探查题不能再次提交。"
      : "上一次独立验证作答已被服务消费，但后续处理未完成；原验证题不能再次提交。";
    return { kind: "restart", reason, serviceState: dossier.serviceState };
  }
  const expected = phase === "probe"
    ? { state: "awaiting_probe", action: "answer_targeted_probe" }
    : { state: "awaiting_verification", action: "answer_independent_verification" };
  if (
    dossier.serviceState === expected.state
    && dossier.nextAction?.action === expected.action
    && dossier.nextAction?.prompt_instance_id === promptInstanceId
  ) return { kind: "ready", reason: "" };
  return { kind: "blocked", reason: "服务端状态与当前题目实例不一致；原题已锁定。" };
}

function ContinuationBoundary({ gate, onRestart }) {
  return (
    <section className={`continuation-boundary ${gate.kind}`} data-testid="continuation-boundary" data-state={gate.kind} data-service-state={gate.serviceState || "unavailable"}>
      <Info size={15} />
      <div>
        <strong>{gate.kind === "loading" ? "正在确认可写状态" : gate.kind === "restart" ? "本题需要重新开始" : "当前题目已锁定"}</strong>
        <p>{gate.reason}</p>
      </div>
      {gate.kind !== "loading" && <button className="button primary" type="button" onClick={onRestart}>重新开始本题</button>}
    </section>
  );
}

function MisconceptionDossier({ state }) {
  const dossier = state.dossier;
  if (!dossier) {
    const copy = state.phase === "loading"
      ? "正在读取本机事件档案。"
      : state.phase === "error"
        ? `档案响应异常：${state.error?.message || "无法读取"}`
        : "本机事件档案当前不可用；不会用首答候选代替。";
    return (
      <section className="misconception-dossier dossier-unavailable" data-testid="misconception-dossier" data-status={state.phase} data-persistence="unavailable">
        <header className="dossier-heading"><div><strong>题型错因档案</strong><small>事件证据</small></div><span>不可用</span></header>
        <div className={`dossier-source-state ${state.phase}`} role={state.phase === "error" ? "alert" : "status"}><Info size={13} /><span>{copy}</span></div>
      </section>
    );
  }
  return (
    <section className="misconception-dossier" data-testid="misconception-dossier" data-status={state.phase} data-service-state={dossier.serviceState} data-learning-status={dossier.status} data-next-action={dossier.nextAction?.action} data-persistence={dossier.persistence}>
      <header className="dossier-heading">
        <div><strong>题型错因档案</strong><small>{dossier.skill}</small></div>
        <span>{dossier.statusCopy}</span>
      </header>
      {state.phase !== "connected" && (
        <div className={`dossier-source-state ${state.phase}`} role={state.phase === "error" ? "alert" : "status"}>
          <Info size={13} />
          <span>{state.phase === "loading" ? "正在刷新本机错因档案。" : state.phase === "error" ? `档案响应异常：${state.error?.message || "无法读取"}` : "本机事件档案当前不可用；保留上次已读取版本。"}</span>
        </div>
      )}
      <div className="dossier-section">
        <strong>观察</strong>
        {dossier.observations.map((item) => (
          <div className="dossier-observation" key={item.id}><span>{item.label}</span><p>{item.value}</p><small>{item.source}</small></div>
        ))}
      </div>
      <div className="dossier-section">
        <strong>候选原因（按当前返回排序）</strong>
        {dossier.rankedHypotheses.length > 0 ? (
          <ol className="dossier-candidates">
            {dossier.rankedHypotheses.map((item) => (
              <li key={item.id} data-claim-status={item.claimStatus} data-learning-status={item.learningStatus}>
                <span>{item.rank}</span>
                <div><strong>{item.label}</strong><small>{item.subtype}</small></div>
                <em>候选 / 待验证 · {claimStatusCopy(item.claimStatus)}</em>
              </li>
            ))}
          </ol>
        ) : <p className="dossier-empty">首答通过，规则要求不生成错误原因。</p>}
        {dossier.rankedHypotheses.length > 0 && <p className="dossier-rank-note">返回顺序只用于决定下一步探查；所有候选均未确认，不显示概率。</p>}
      </div>
      {dossier.rankedHypotheses.length > 0 && (
        <div className="dossier-section dossier-evidence">
          <strong>候选证据引用</strong>
          <div className="dossier-evidence-list">
            {dossier.rankedHypotheses.map((item) => (
              <dl key={item.id} data-candidate-id={item.id} data-claim-status={item.claimStatus}>
                <div><dt>{item.rank} · {item.label}</dt><dd>{claimStatusCopy(item.claimStatus)}</dd></div>
                <div><dt>支持</dt><dd>{item.supportingEvidence.length ? item.supportingEvidence.join("、") : "当前响应未提供"}</dd></div>
                <div><dt>反证</dt><dd>{item.refutingEvidence.length ? item.refutingEvidence.join("、") : "当前响应未提供"}</dd></div>
              </dl>
            ))}
          </div>
          {dossier.nextProbe && <dl><div><dt>下一探查</dt><dd>{dossier.nextProbe}</dd></div></dl>}
        </div>
      )}
      {dossier.cohortEvidence && (
        <div className="dossier-section dossier-cohort">
          <strong>群体证据</strong>
          <p>不可用 · 样本量 0；不用于当前判断。</p>
        </div>
      )}
      <footer className="dossier-confirmation">
        <div><strong>确认状态</strong><span>{dossier.statusCopy}</span></div>
        <div><strong>学习状态</strong><span>{learningStatusCopy(dossier.status)}</span></div>
        <small>档案由事件证据推进；客户端不能直接确认候选。</small>
      </footer>
    </section>
  );
}

function overviewDateCopy() {
  const parts = new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
    weekday: "long",
  }).formatToParts(resolveClientNow());
  const value = (type) => parts.find((item) => item.type === type)?.value || "";
  return `${value("month")} 月 ${value("day")} 日 · ${value("weekday")}`;
}

function Overview({ setPage, sidecar, planning }) {
  const [query, setQuery] = useState("");
  const [searchResult, setSearchResult] = useState("");
  const connected = sidecar.phase === "connected";
  const liveGroups = useMemo(
    () => connected ? reportGroupsFromSidecar(sidecar.report) : [],
    [connected, sidecar.report],
  );
  const liveSkills = useMemo(() => liveGroups.flatMap((group) => group.skills), [liveGroups]);
  const runCount = connected ? Number(sidecar.health?.run_count) || 0 : 0;
  const searchMatches = searchResult
    ? liveSkills.filter((skill) => skill.name.includes(searchResult))
    : [];
  const runSearch = (event) => {
    event.preventDefault();
    const normalized = query.trim();
    if (normalized) setSearchResult(normalized);
  };

  return (
    <div className="screen overview-screen">
      <div className="page-heading row-between overview-heading">
        <div>
          <span className="eyebrow">{overviewDateCopy()}</span>
          <h1>今日学习</h1>
        </div>
        <strong className="exam-label">考试目标未设置</strong>
      </div>

      <div className="overview-grid">
        <div className="overview-main">
          <form className="overview-search" onSubmit={runSearch}>
            <MagnifyingGlass size={20} />
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索题目、技能或学习记录" aria-label="搜索题目、技能或学习记录" />
            <button className="search-mic" type="button" aria-label="语音输入"><Microphone size={15} /></button>
            <button className="search-submit" type="submit" aria-label="提交搜索"><ArrowRight size={14} /></button>
          </form>

          <div className="quick-actions">
            <button className="button primary" disabled={["loading", "offline", "error"].includes(planning.phase)} onClick={() => setPage("practice")}>{planning.phase === "not-created" ? "创建今日计划" : planning.phase === "connected" ? "查看今日任务" : "今日计划不可用"}</button>
            <button className="button secondary" onClick={() => setPage("reports")}>查看技能报告</button>
          </div>

          {searchResult && (
            <div className="search-feedback" role="status">
              <span>{connected ? `本机技能报告中找到 ${searchMatches.length} 条与“${searchResult}”相关的记录。` : "本机记录当前不可用，未执行本地搜索。"}</span>
              {connected && searchMatches.length > 0 && <button className="text-link" onClick={() => setPage("reports")}>查看结果 <ArrowRight size={12} /></button>}
              <button className="icon-button" onClick={() => setSearchResult("")} aria-label="关闭搜索结果"><X size={13} /></button>
            </div>
          )}

          <section className="content-section">
            <div className="section-title row-between">
              <h2>学习科目</h2>
              <div className="carousel-controls" aria-label="科目翻页">
                <button disabled aria-label="上一组"><CaretLeft size={12} /></button>
                <button disabled aria-label="下一组"><CaretRight size={12} /></button>
              </div>
            </div>
            <div className="subject-cards">
              {[
                { name: "行测", description: connected ? (liveSkills.length ? `${liveSkills.length} 个本机报告技能` : "暂无本机技能记录") : "本机记录不可用", Icon: Target, enabled: true },
                { name: "申论", description: "P0.1 尚未接通", Icon: NotePencil, enabled: false },
                { name: "面试", description: "P0.1 尚未接通", Icon: Microphone, enabled: false },
              ].map(({ name, description, Icon, enabled }) => (
                <button className={enabled ? "subject-card" : "subject-card unavailable"} key={name} disabled={!enabled} onClick={() => setPage("reports")}>
                  <span className="subject-icon"><Icon size={15} /></span>
                  <span className="subject-copy"><small>科目</small><strong>{name}</strong><em>{description}</em></span>
                  {enabled ? <CaretRight size={13} /> : <small className="phase-copy">分阶段开放</small>}
                </button>
              ))}
            </div>
            <button className="text-link subject-more" onClick={() => setPage("reports")}>查看全部学习科目 <ArrowRight size={12} /></button>
          </section>

          <TodayPlanOverview planning={planning} setPage={setPage} />
        </div>
        <ReviewScheduleSummary planning={planning} onOpenReport={() => setPage("reports")} />
      </div>
    </div>
  );
}

function ToolsScreen({
  favorites,
  setFavorites,
  selectedTool,
  setSelectedTool,
  toolStage,
  setToolStage,
  sidecar,
  onRefreshSkills,
  setPage,
}) {
  const filters = ["全部", "已收藏", "诊断", "练习", "复盘", "计划", "复习"];
  const [filter, setFilter] = useState("全部");
  const [query, setQuery] = useState("");
  const [answer, setAnswer] = useState("");
  const [confidence, setConfidence] = useState("");
  const [workNotes, setWorkNotes] = useState("");
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [activityState, setActivityState] = useState({ phase: "idle", bundle: null, error: null });
  const [attemptStartedAt, setAttemptStartedAt] = useState(0);
  const [phaseAnswer, setPhaseAnswer] = useState("");
  const [probeReason, setProbeReason] = useState("");
  const [phaseConfidence, setPhaseConfidence] = useState("");
  const [phaseStartedAt, setPhaseStartedAt] = useState(0);
  const [runEvidence, setRunEvidence] = useState(null);
  const [runError, setRunError] = useState(null);
  const [assistance, setAssistance] = useState(createAssistanceState);
  const [dossierState, setDossierState] = useState({ phase: "idle", dossier: null, error: null });
  const probeGate = dossierContinuationGate(
    dossierState,
    "probe",
    runEvidence?.attempt?.probe?.prompt_instance_id,
  );
  const verificationGate = dossierContinuationGate(
    dossierState,
    "verification",
    runEvidence?.continuation?.verification?.prompt_instance_id,
  );
  const transferBinding = useMemo(() => {
    if (!runEvidence?.continuation || !activityState.bundle) return { ready: false, error: null };
    try {
      return {
        ready: true,
        activity: assertIndependentTransferBinding(
          runEvidence.continuation,
          activityState.bundle.independentTransfer,
        ),
        error: null,
      };
    } catch (error) {
      return { ready: false, activity: null, error };
    }
  }, [activityState.bundle, runEvidence?.continuation]);
  const probeChoices = useMemo(
    () => probeChoicesFromPrompt(runEvidence?.attempt?.probe?.prompt),
    [runEvidence?.attempt?.probe?.prompt],
  );
  const completedResult = useMemo(() => {
    if (toolStage !== "result" || !runEvidence?.attempt || !runEvidence?.continuation || !activityState.bundle) return null;
    try {
      return normalizeCompletedLearningResult({
        attempt: runEvidence.attempt,
        continuation: runEvidence.continuation,
        firstActivity: activityState.bundle.firstAnswer,
        transferActivity: activityState.bundle.independentTransfer,
      });
    } catch {
      return null;
    }
  }, [activityState.bundle, runEvidence, toolStage]);

  useEffect(() => {
    if (!["active", "probe", "verification"].includes(toolStage) || !phaseStartedAt && !attemptStartedAt) return undefined;
    const startedAt = toolStage === "active" ? attemptStartedAt : phaseStartedAt;
    const update = () => setElapsedSeconds(Math.max(0, Math.floor((Date.now() - startedAt) / 1000)));
    update();
    const timer = window.setInterval(update, 1000);
    return () => window.clearInterval(timer);
  }, [attemptStartedAt, phaseStartedAt, toolStage]);

  const visible = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase("zh-CN");
    return TOOLS.filter((tool) => {
      const categoryMatch = filter === "全部" || (filter === "已收藏" ? favorites.includes(tool.title) : tool.category === filter);
      const queryMatch = !normalized || `${tool.title}${tool.description}${tool.category}`.toLocaleLowerCase("zh-CN").includes(normalized);
      return categoryMatch && queryMatch;
    });
  }, [favorites, filter, query]);

  const toggleFavorite = (title) => {
    setFavorites((items) => items.includes(title) ? items.filter((item) => item !== title) : [...items, title]);
  };

  const loadProductActivities = async () => {
    setActivityState({ phase: "loading", bundle: null, error: null });
    try {
      const bundle = await fetchProductActivityBundle();
      setActivityState({ phase: "ready", bundle, error: null });
      return bundle;
    } catch (error) {
      setActivityState({ phase: "error", bundle: null, error });
      return null;
    }
  };

  const openTool = (tool) => {
    if (!tool.available || sidecar.phase !== "connected") return;
    setSelectedTool(tool);
    setToolStage("ready");
    setAnswer("");
    setConfidence("");
    setPhaseAnswer("");
    setProbeReason("");
    setPhaseConfidence("");
    setRunEvidence(null);
    setRunError(null);
    setWorkNotes("");
    setElapsedSeconds(0);
    setAssistance(createAssistanceState());
    setDossierState({ phase: "idle", dossier: null, error: null });
    loadProductActivities();
  };

  useEffect(() => {
    if (
      selectedTool?.available
      && sidecar.phase === "connected"
      && toolStage === "ready"
      && activityState.phase === "idle"
    ) {
      openTool(selectedTool);
    }
  }, [activityState.phase, selectedTool, sidecar.phase, toolStage]);

  const closeTool = () => {
    setSelectedTool(null);
    setToolStage("ready");
    setAnswer("");
    setConfidence("");
    setPhaseAnswer("");
    setProbeReason("");
    setPhaseConfidence("");
    setRunEvidence(null);
    setRunError(null);
    setWorkNotes("");
    setElapsedSeconds(0);
    setAssistance(createAssistanceState());
    setDossierState({ phase: "idle", dossier: null, error: null });
    setActivityState({ phase: "idle", bundle: null, error: null });
  };

  const startConfiguredRun = () => {
    if (sidecar.phase !== "connected" || activityState.phase !== "ready") return;
    setToolStage("active");
    setAnswer("");
    setConfidence("");
    setAttemptStartedAt(Date.now());
    setElapsedSeconds(0);
    setAssistance(createAssistanceState());
    setDossierState({ phase: "idle", dossier: null, error: null });
  };

  const loadDossier = async (runId) => {
    setDossierState((current) => ({ ...current, phase: "loading", error: null }));
    try {
      const payload = await fetchMisconceptionDossier(runId);
      const dossier = normalizeMisconceptionDossier(payload);
      setDossierState((current) => current.dossier?.sourceTraceVersion > dossier.sourceTraceVersion
        ? current
        : { phase: "connected", dossier, error: null });
      return dossier;
    } catch (error) {
      const unavailable = error?.kind === "unavailable"
        || error?.status === 404
        || ["dossier_unavailable", "misconception_dossier_unavailable"].includes(error?.code);
      setDossierState((current) => ({ phase: unavailable ? "unavailable" : "error", dossier: current.dossier, error }));
      return null;
    }
  };

  const requestProbeAssistance = async () => {
    const session = runEvidence?.attempt;
    if (probeGate.kind !== "ready" || !session?.probe?.prompt_instance_id) {
      setAssistance({ ...assistance, status: "unavailable", error: null, pendingCommandId: null });
      return;
    }
    const commandId = assistance.pendingCommandId || createAssistanceCommandId();
    setAssistance((current) => ({ ...current, status: "requesting", error: null, pendingCommandId: commandId }));
    try {
      const result = await requestNextAssistance({
        session,
        elapsedTimeSeconds: (Date.now() - phaseStartedAt) / 1000,
        commandId,
      });
      setRunEvidence((current) => ({
        ...current,
        attempt: { ...current.attempt, state_version: result.state_version },
      }));
      setAssistance((current) => appendAssistance(current, result));
      loadDossier(session.run_id);
    } catch (error) {
      const refreshedDossier = await loadDossier(session.run_id);
      if (refreshedDossier?.requiresRestart) {
        setAssistance((current) => ({ ...current, status: "unavailable", error: null, pendingCommandId: null }));
        return;
      }
      if (error?.code === "assistance_exhausted") {
        setAssistance((current) => ({ ...current, status: "exhausted", error, pendingCommandId: null }));
      } else if (["stale_version", "state_mismatch", "out_of_order"].includes(error?.code)) {
        setRunError(error);
        setToolStage("error");
      } else {
        setAssistance((current) => ({ ...current, status: "error", error }));
      }
    }
  };

  const submitConfiguredAttempt = async () => {
    if (sidecar.phase !== "connected" || activityState.phase !== "ready" || !activityState.bundle) return;
    setToolStage("running");
    setRunEvidence(null);
    setRunError(null);
    const confidenceValues = { low: 0.35, medium: 0.65, high: 0.9 };
    try {
      const evidence = await submitAttempt({
        fixtureId: activityState.bundle.firstAnswer.activityId,
        response: answer,
        confidence: confidenceValues[confidence],
        responseTimeSeconds: (Date.now() - attemptStartedAt) / 1000,
      });
      setRunEvidence(evidence);
      setPhaseAnswer("");
      setProbeReason("");
      setPhaseConfidence("");
      setPhaseStartedAt(Date.now());
      setElapsedSeconds(0);
      setWorkNotes("");
      setAssistance(createAssistanceState({ available: Boolean(evidence.attempt?.probe?.prompt_instance_id) }));
      setToolStage("probe");
      loadDossier(evidence.attempt.run_id);
    } catch (error) {
      setRunError(error);
      setToolStage("error");
    }
  };

  const submitContinuation = async (phase) => {
    const gate = phase === "probe" ? probeGate : verificationGate;
    if (gate.kind !== "ready" || phase === "verification" && !transferBinding.ready) return;
    setToolStage("running");
    setRunError(null);
    const confidenceValues = { low: 0.35, medium: 0.65, high: 0.9 };
    const session = phase === "probe" ? runEvidence?.attempt : runEvidence?.continuation;
    try {
      const next = await continueAttempt({
        session,
        phase,
        response: phase === "probe" && probeReason.trim() ? `${phaseAnswer}；${probeReason.trim()}` : phaseAnswer,
        confidence: confidenceValues[phaseConfidence],
        responseTimeSeconds: (Date.now() - phaseStartedAt) / 1000,
      });
      setRunEvidence((current) => ({ ...current, ...next }));
      setPhaseAnswer("");
      setPhaseConfidence("");
      if (phase === "probe") {
        setPhaseStartedAt(Date.now());
        setElapsedSeconds(0);
        setWorkNotes("");
        setToolStage("verification");
      } else {
        setToolStage("result");
        await onRefreshSkills();
      }
      loadDossier(next.continuation.run_id);
    } catch (error) {
      const refreshedDossier = session?.run_id ? await loadDossier(session.run_id) : null;
      if (refreshedDossier?.requiresRestart) {
        setRunError(null);
        setToolStage(phase === "probe" ? "probe" : "verification");
        return;
      }
      setRunError(error);
      setToolStage("error");
    }
  };

  const restartAttempt = () => {
    setRunEvidence(null);
    setRunError(null);
    setAnswer("");
    setConfidence("");
    setWorkNotes("");
    setElapsedSeconds(0);
    setPhaseAnswer("");
    setProbeReason("");
    setPhaseConfidence("");
    setAssistance(createAssistanceState());
    setDossierState({ phase: "idle", dossier: null, error: null });
    setToolStage("ready");
  };

  const restartWithFreshRun = () => {
    setRunEvidence(null);
    setRunError(null);
    setAnswer("");
    setConfidence("");
    setWorkNotes("");
    setElapsedSeconds(0);
    setPhaseAnswer("");
    setProbeReason("");
    setPhaseConfidence("");
    setAssistance(createAssistanceState());
    setDossierState({ phase: "idle", dossier: null, error: null });
    setAttemptStartedAt(Date.now());
    setToolStage("active");
  };

  const traceVerified = Boolean(
    runEvidence?.continuation?.trace_verified
    && runEvidence?.trace?.trace_verified
    && runEvidence?.replay?.trace_verified,
  );
  const recoverableConflict = ["stale_version", "state_mismatch", "out_of_order"].includes(runError?.code);
  return (
    <div className="screen tools-screen">
      <div className="page-heading"><h1>训练工具</h1><p>从一个明确问题开始，完成可核查的短训练。</p></div>

      <div className="tool-controls">
        <div className="filter-tabs" aria-label="工具分类">
          {filters.map((item) => (
            <button key={item} className={filter === item ? "filter-tab active" : "filter-tab"} onClick={() => setFilter(item)} aria-pressed={filter === item}>{item}</button>
          ))}
        </div>
        <label className="small-search"><MagnifyingGlass size={14} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索工具" /></label>
      </div>

      {visible.length > 0 ? (
        <div className="tool-grid">
          {visible.map((tool) => {
            const liked = favorites.includes(tool.title);
            const operable = tool.available && sidecar.phase === "connected";
            return (
              <article className={operable ? "tool-card" : "tool-card unavailable"} key={tool.title} data-tool-title={tool.title} data-availability={operable ? "connected" : tool.available ? "service-unavailable" : "phased"}>
                <button className="tool-card-main" disabled={!operable} onClick={() => openTool(tool)}>
                  <small>{tool.category}</small>
                  <strong>{tool.title}</strong>
                  <span>{tool.description}</span>
                  {!operable && <em>{tool.available ? "本机服务不可用" : "分阶段开放"}</em>}
                </button>
                <button className={liked ? "bookmark-button active" : "bookmark-button"} onClick={() => toggleFavorite(tool.title)} aria-label={liked ? `取消收藏${tool.title}` : `收藏${tool.title}`}>
                  <BookmarkSimple size={15} weight={liked ? "fill" : "regular"} />
                </button>
              </article>
            );
          })}
        </div>
      ) : (
        <div className="empty-state">
          <strong>{query.trim() ? `没有找到“${query.trim()}”` : "还没有收藏训练工具"}</strong>
          <p>{query.trim() ? "请尝试技能名或训练类型。" : "点击工具卡右上角的收藏图标即可加入。"}</p>
          {(query || filter !== "全部") && <button className="button secondary" onClick={() => { setQuery(""); setFilter("全部"); }}>清除筛选</button>}
        </div>
      )}

      {selectedTool && (
        <SidePanel title={selectedTool.title} eyebrow={selectedTool.category} onClose={closeTool}>
          {toolStage === "ready" && (
            <>
              <p className="panel-intro">{selectedTool.description}</p>
              <div className="form-stack">
                <label><span>科目</span><select value="行测" disabled><option>行测</option></select></label>
                <label><span>技能</span><select value={CONNECTED_SKILL_NAME} disabled><option>{CONNECTED_SKILL_NAME}</option></select></label>
                <label><span>本次验证</span><input value="公式方向是否混淆" readOnly /></label>
                <label><span>本轮步骤</span><input value="3 · 首答、探查、独立验证" readOnly /></label>
              </div>
              {activityState.phase === "ready" && <p className="activity-ready-summary">已核对 {activityState.bundle.firstAnswer.source.year} 年真题与独立迁移题 · 题目版本 {activityState.bundle.releaseId}</p>}
              {activityState.phase === "loading" && <ProductActivityLoadState phase="loading" />}
              {activityState.phase === "error" && <ProductActivityLoadState phase="error" error={activityState.error} onRetry={loadProductActivities} />}
              <div className="evidence-note"><Info size={15} /><span>{sidecar.phase === "connected" ? "先查看首题；只有选择答案与信心并提交首答后，才会创建本机学习记录。未提交前不读取答案或解析。" : "本机服务不可用；真实训练暂不能开始，也不会创建本机轨迹。"}</span></div>
              <button className="button primary panel-primary" disabled={sidecar.phase !== "connected" || activityState.phase !== "ready"} onClick={startConfiguredRun}>{activityState.phase === "loading" ? "正在读取真题" : activityState.phase === "error" ? "真题不可用" : sidecar.phase === "connected" ? "查看首题（尚未创建记录）" : "本机服务不可用"}</button>
            </>
          )}
          {toolStage === "running" && (
            <div className="run-waiting" role="status" data-testid="run-status" data-state="running">
              <strong>正在记录本次作答</strong>
              <p>核对当前步骤与本机轨迹版本，请稍候。</p>
              <small>数据仅写入本机 sidecar。</small>
            </div>
          )}
          {toolStage === "active" && (
            activityState.bundle ? <ProductActivityQuestion
              activity={activityState.bundle.firstAnswer}
              answer={answer}
              onAnswer={setAnswer}
              confidence={confidence}
              onConfidence={setConfidence}
              workNotes={workNotes}
              onWorkNotes={setWorkNotes}
              elapsedSeconds={elapsedSeconds}
              stepLabel="步骤 1 / 3 · 独立首答"
              independentCopy="初答不提供帮助；点击提交首答后，才会把你的选项、信心与用时写入本机轨迹。"
              submitLabel="提交首答并创建本机记录"
              submitHelp="提交后才会创建本机学习记录，并进入错因探查。"
              onSubmit={submitConfiguredAttempt}
            /> : <ProductActivityLoadState phase="error" error={activityState.error} onRetry={loadProductActivities} />
          )}
          {toolStage === "probe" && runEvidence?.attempt && (
            <div className="continuation-stage" data-testid="attempt-stage" data-state="awaiting-probe" data-version={runEvidence.attempt.state_version} data-run-id={runEvidence.attempt.run_id}>
              <div className="stage-kicker"><span>步骤 2 / 3</span><strong>探查当前线索</strong></div>
              <dl className="compact-result"><div><dt>首答评分</dt><dd>{runEvidence.attempt.score?.passed ? "通过" : "未通过"} · {runEvidence.attempt.score?.score}/{runEvidence.attempt.score?.max_score}</dd></div><div><dt>诊断决策</dt><dd>{diagnosisDecisionCopy(runEvidence.attempt.diagnosis?.decision)}</dd></div></dl>
              {probeGate.kind !== "ready" && <ContinuationBoundary gate={probeGate} onRestart={restartWithFreshRun} />}
              <MisconceptionDossier state={dossierState} />
              {probeGate.kind === "ready" ? (
                <>
                  <div className="prompt-block probe-prompt"><small>探查题</small><p>{runEvidence.attempt.probe.prompt}</p></div>
                  <AssistanceLadder state={assistance} promptAvailable={Boolean(runEvidence.attempt.probe?.prompt_instance_id)} onRequest={requestProbeAssistance} />
                  {probeChoices.length === 2 ? (
                    <fieldset className="probe-choice-field"><legend>选择你会使用的公式</legend><div>{probeChoices.map((choice) => <label className={phaseAnswer === choice.value ? "selected" : ""} key={choice.id}><input type="radio" name="probe-formula" value={choice.value} checked={phaseAnswer === choice.value} onChange={(event) => setPhaseAnswer(event.target.value)} /><span>{choice.value}</span></label>)}</div></fieldset>
                  ) : (
                    <label className="answer-field"><span>写下你的公式或判断</span><textarea value={phaseAnswer} onChange={(event) => setPhaseAnswer(event.target.value)} placeholder="回答上面的探查题，不是填写网络或连接状态" /></label>
                  )}
                  <label className="answer-field probe-reason"><span>补充一句理由（可选）</span><textarea value={probeReason} onChange={(event) => setProbeReason(event.target.value)} placeholder="例如：要求的是变化前的量，所以……" /></label>
                  <label className="answer-field"><span>作答信心</span><select value={phaseConfidence} onChange={(event) => setPhaseConfidence(event.target.value)}><option value="">请选择</option><option value="low">不太确定</option><option value="medium">基本确定</option><option value="high">非常确定</option></select></label>
                  <button className="button primary panel-primary" disabled={phaseAnswer.trim().length < 2 || !phaseConfidence} onClick={() => submitContinuation("probe")}>提交探查作答</button>
                </>
              ) : null}
            </div>
          )}
          {toolStage === "verification" && runEvidence?.continuation && (
            <div className="continuation-stage" data-testid="attempt-stage" data-state="awaiting-verification" data-version={runEvidence.continuation.state_version} data-run-id={runEvidence.continuation.run_id}>
              <div className="stage-kicker"><span>步骤 3 / 3</span><strong>独立验证</strong></div>
              {verificationGate.kind !== "ready" && <ContinuationBoundary gate={verificationGate} onRestart={restartWithFreshRun} />}
              <MisconceptionDossier state={dossierState} />
              {verificationGate.kind === "ready" && transferBinding.ready ? (
                <>
                  <section className="teaching-block"><small>针对性提示</small><p>{runEvidence.continuation.teaching.prompt}</p><span>{runEvidence.continuation.teaching.strategy === "worked-example-fading" ? "先标出基期，再独立完成一题。" : "请按提示完成后续验证。"}</span></section>
                  <ProductActivityQuestion
                    activity={transferBinding.activity}
                    answer={phaseAnswer}
                    onAnswer={setPhaseAnswer}
                    confidence={phaseConfidence}
                    onConfidence={setPhaseConfidence}
                    workNotes={workNotes}
                    onWorkNotes={setWorkNotes}
                    elapsedSeconds={elapsedSeconds}
                    stepLabel="步骤 3 / 3 · 未见迁移题"
                    independentCopy="这是一道不同题号的真题，不提供帮助；只有独立作答后，服务才可能更新掌握状态。"
                    submitLabel="提交独立验证"
                    submitHelp="提交后完成本轮验证；只有无提示且回答正确时，才可能更新掌握状态。"
                    onSubmit={() => submitContinuation("verification")}
                  />
                </>
              ) : verificationGate.kind === "ready" ? <div className="continuation-boundary blocked" role="alert" data-testid="transfer-binding-error"><Info size={15} /><div><strong>迁移题绑定未通过</strong><p>服务返回的 item_id 或内容签名与本机真题投影不一致；为避免错题评分，本题已锁定。</p></div></div> : null}
            </div>
          )}
          {toolStage === "result" && runEvidence && completedResult && (
            <div className="run-result" role="status" data-testid="run-status" data-state="completed" data-version={runEvidence.continuation?.state_version}>
              <div className={`run-result-heading ${completedResult.transfer.correct ? "passed" : "needs-review"}`}>{completedResult.transfer.correct ? <CheckCircle size={20} weight="fill" /> : <Info size={20} />}<div><h3>{completedResult.transfer.correct ? "迁移题回答正确" : "本轮完成，还需要再练"}</h3><small>{runEvidence.attempt.run_id}</small></div></div>
              <section className="answer-review"><div><small>首题</small><strong>{completedResult.initial.correct ? "回答正确" : "回答错误"}</strong><p>{completedResult.initial.title}</p><span>你的答案：{completedResult.initial.answer}</span><details><summary>查看题目材料</summary><p>{completedResult.initial.material}</p></details></div><div><small>迁移题</small><strong>{completedResult.transfer.correct ? "回答正确" : "回答错误"}</strong><p>{completedResult.transfer.title}</p><span>你的答案：{completedResult.transfer.answer}</span><details><summary>查看题目材料</summary><p>{completedResult.transfer.material}</p></details></div></section>
              <section className={`result-notice ${completedResult.probe.status}`}><strong>{completedResult.probe.title}</strong><p>{completedResult.probe.detail}</p></section>
              <section className={`result-notice ${completedResult.mastery.status}`}><strong>{completedResult.mastery.title}</strong><p>{completedResult.mastery.detail}</p></section>
              <section className={`result-notice ${completedResult.review.status}`}><strong>{completedResult.review.title}</strong><p>{completedResult.review.detail}</p></section>
              <dl className="run-result-list"><div><dt>轨迹校验</dt><dd>{traceVerified ? "已通过" : "未通过"}</dd></div><div><dt>轨迹 / 回放</dt><dd>{runEvidence.trace.event_count} 个事件 · {runEvidence.replay.frame_count} 帧</dd></div></dl>
              <MisconceptionDossier state={dossierState} />
              <button className="button primary panel-primary" onClick={() => { closeTool(); setPage("reports"); }}>查看技能报告</button>
            </div>
          )}
          {toolStage === "result" && runEvidence && !completedResult && <div className="continuation-boundary blocked" role="alert"><Info size={15} /><div><strong>结果详情未通过核验</strong><p>本轮轨迹仍保存在本机，但客户端不会猜测答案、KT 或复习安排。</p></div></div>}
          {toolStage === "error" && (
            <div className="run-error" role="alert" data-testid="run-status" data-state="error">
              <Info size={20} />
              <h3>{recoverableConflict ? "训练状态已变化" : "本次未写入完整轨迹"}</h3>
              <p>{recoverableConflict ? "本机中的步骤版本已更新。为避免重复写入，请重新开始本轮训练。" : (runError?.message || "本机服务返回错误。")}</p>
              {runError?.requestId && <small>请求编号：{runError.requestId}</small>}
              <button className="button primary panel-primary" onClick={recoverableConflict ? restartAttempt : () => setToolStage(runEvidence?.continuation ? "verification" : runEvidence?.attempt ? "probe" : "active")}>{recoverableConflict ? "重新开始" : "返回当前步骤"}</button>
              <button className="button text-button" onClick={closeTool}>关闭</button>
            </div>
          )}
        </SidePanel>
      )}
    </div>
  );
}

function EvidenceSummary({ skill }) {
  return (
    <div className="evidence-summary" aria-label={`独立验证证据：${skill.evidenceTitle}`}>
      <strong>{skill.evidenceTitle}</strong>
      <span>{skill.verifiedTransfers} 次通过 · {skill.failedOrInconclusive} 次未通过或不确定</span>
    </div>
  );
}

function ReportsScreen({ setPage, sidecar, planning }) {
  const [tab, setTab] = useState("skills");
  const [subject, setSubject] = useState("xingce");
  const [module, setModule] = useState("all");
  const [evidenceFilter, setEvidenceFilter] = useState("all");
  const [dueOnly, setDueOnly] = useState(false);
  const [openGroups, setOpenGroups] = useState(["data"]);
  const [openSkill, setOpenSkill] = useState(null);
  const usingLiveReport = sidecar.phase === "connected";
  const sourceGroups = useMemo(
    () => usingLiveReport ? reportGroupsFromSidecar(sidecar.report) : [],
    [sidecar.report, usingLiveReport],
  );

  const groups = useMemo(() => {
    if (subject !== "xingce") return [];
    return sourceGroups
      .filter((group) => module === "all" || group.id === module)
      .map((group) => ({
        ...group,
        skills: group.skills.filter((skill) => {
          const evidenceMatch = evidenceFilter === "all" || skill.evidenceKind === evidenceFilter;
          return evidenceMatch && !dueOnly;
        }),
      }))
      .filter((group) => group.skills.length > 0);
  }, [subject, module, evidenceFilter, dueOnly, sourceGroups]);

  const totals = useMemo(() => groups.reduce((result, group) => ({
    modules: result.modules + 1,
    skills: result.skills + group.skills.length,
    runs: result.runs + group.skills.reduce((sum, skill) => sum + skill.completedRuns, 0),
  }), { modules: 0, skills: 0, runs: 0 }), [groups]);

  const clearFilters = () => {
    setSubject("xingce");
    setModule("all");
    setEvidenceFilter("all");
    setDueOnly(false);
  };

  return (
    <div className="screen reports-screen">
      <div className="page-heading"><h1>技能报告</h1></div>
      <div className="sub-tabs" role="tablist" aria-label="报告类型">
        <button className={tab === "activity" ? "active" : ""} onClick={() => setTab("activity")} role="tab" aria-selected={tab === "activity"}>学习活动</button>
        <button className={tab === "skills" ? "active" : ""} onClick={() => setTab("skills")} role="tab" aria-selected={tab === "skills"}>技能证据</button>
        <button className={tab === "reviews" ? "active" : ""} onClick={() => setTab("reviews")} role="tab" aria-selected={tab === "reviews"}>复习记录</button>
      </div>

      {tab === "skills" && (
        <>
          <p className="report-note" data-testid="report-source" data-source={usingLiveReport ? "sidecar" : "unavailable"}>`trace-summary-v1` 只汇总已完成本机运行和独立验证计数，不代表纵向知识追踪或掌握结论。{usingLiveReport ? " 数据源：本机服务。" : " 本机数据源当前不可用，不显示替代数据。"}</p>
          <div className="report-filters">
            <select value={subject} onChange={(event) => setSubject(event.target.value)} aria-label="科目" disabled><option value="xingce">行测 · P0.1</option></select>
            <select value={module} onChange={(event) => setModule(event.target.value)} aria-label="模块" disabled={subject !== "xingce"}><option value="all">全部模块</option><option value="verbal">言语理解</option><option value="data">资料分析</option><option value="judgment">判断推理</option></select>
            <select value={evidenceFilter} onChange={(event) => setEvidenceFilter(event.target.value)} aria-label="验证证据" disabled={subject !== "xingce"}><option value="all">全部证据</option><option value="verified">有通过记录</option><option value="not_verified">仅未通过或不确定</option><option value="insufficient">证据不足</option></select>
            <label className="check-label unavailable"><input type="checkbox" checked={dueOnly} onChange={(event) => setDueOnly(event.target.checked)} disabled /> 到期状态尚未接通</label>
          </div>

          {groups.length > 0 ? (
            <>
              <div className="report-summary"><strong>行测</strong><span>{totals.modules} 个有记录模块 · {totals.skills} 个技能 · {totals.runs} 次已完成本机运行</span></div>
              <div className="skills-table">
                {groups.map((group) => {
                  const isOpen = openGroups.includes(group.id);
                  return (
                    <section className="skill-group" key={group.id}>
                      <button className="group-row" onClick={() => setOpenGroups((items) => items.includes(group.id) ? items.filter((item) => item !== group.id) : [...items, group.id])} aria-expanded={isOpen}>
                        {isOpen ? <CaretDown size={13} /> : <CaretRight size={13} />}
                        <strong>{group.title}</strong><small>{group.skills.length} 个技能</small>
                      </button>
                      {isOpen && (
                        <>
                          <div className="skills-head"><span>技能</span><span>独立验证证据</span><span>本机运行</span></div>
                          {group.skills.map((skill) => {
                            const detailOpen = openSkill === skill.id;
                            return (
                              <div className="skill-entry" key={skill.id}>
                                <button className="skill-row" onClick={() => setOpenSkill(detailOpen ? null : skill.id)} aria-expanded={detailOpen}>
                                  <span className="skill-name">{detailOpen ? <CaretDown size={12} /> : <CaretRight size={12} />}<span>{skill.name}</span></span>
                                  <EvidenceSummary skill={skill} />
                                  <span className="evidence-count"><strong>{skill.completedRuns}</strong> 次<br /><small>最近 {skill.last}</small></span>
                                </button>
                                {detailOpen && (
                                  <div className="skill-detail">
                                    <div><small>验证计数</small><p>{`${skill.completedRuns} 次已完成本机运行；${skill.verifiedTransfers} 次独立验证通过，${skill.failedOrInconclusive} 次未通过或不确定。`}</p></div>
                                    <div><small>服务轨迹字段</small><p>{skill.latestTraceValue === null ? "本机服务未返回单次轨迹值。" : `latest_mastery ${skill.latestTraceValue.toFixed(2)}，latest_uncertainty ${skill.latestTraceUncertainty?.toFixed(2) ?? "—"}；均为最近单次 run 证据，非纵向掌握。${skill.averageTraceDelta === null ? "" : ` average_mastery_delta ${skill.averageTraceDelta >= 0 ? "+" : ""}${skill.averageTraceDelta.toFixed(3)}。`}`}</p></div>
                                    <div className="skill-detail-actions"><button className="button compact secondary" disabled={!CONNECTED_SKILL_IDS.has(skill.id)} onClick={() => setPage("tools")}>{CONNECTED_SKILL_IDS.has(skill.id) ? "前往错因辨析" : "尚未接通"}</button></div>
                                  </div>
                                )}
                              </div>
                            );
                          })}
                        </>
                      )}
                    </section>
                  );
                })}
              </div>
            </>
          ) : (
            <div className="empty-state report-empty" data-testid="report-empty" data-source={usingLiveReport ? "sidecar" : "unavailable"}><strong>{!usingLiveReport ? "本机技能报告不可用" : module === "all" && evidenceFilter === "all" && !dueOnly ? "本机服务还没有技能轨迹" : "当前筛选下没有技能记录"}</strong><p>{!usingLiveReport ? "恢复本机服务后才能读取真实报告；当前不会显示演示或替代记录。" : module === "all" && evidenceFilter === "all" && !dueOnly ? "完成一次真实独立验证后，轨迹汇总才会显示在这里。" : "可以清除筛选后查看全部本机技能记录。"}</p>{usingLiveReport && !(module === "all" && evidenceFilter === "all" && !dueOnly) && <button className="button secondary" onClick={clearFilters}>清除筛选</button>}</div>
          )}
        </>
      )}

      {tab === "activity" && (
        <section className="report-list-section"><div className="report-list-heading"><h2>最近学习活动</h2><p>当前 sidecar 尚未提供活动列表合同。</p></div><div className="empty-state report-empty"><strong>活动记录不可用</strong><p>技能报告不会被转换成虚构的活动时间线。</p></div></section>
      )}

      {tab === "reviews" && (
        <section className="report-list-section"><div className="report-list-heading"><h2>复习安排</h2><p>只展示独立 ReviewSchedule 投影与其结构化轨迹引用。</p></div><ReviewScheduleReport planning={planning} /></section>
      )}
    </div>
  );
}

function AuxiliaryScreen({ page, setPage }) {
  if (page === "practice") {
    return (
      <div className="screen auxiliary-screen">
        <div className="page-heading"><h1>练习任务</h1><p>只展示由本机任务合同返回的安排。</p></div>
        <div className="empty-state auxiliary-empty"><ClipboardText size={23} /><strong>任务编排尚未接通</strong><p>当前版本不会根据技能报告生成日期、题量或完成状态。</p><button className="button secondary" onClick={() => setPage("tools")}>查看已接通训练</button></div>
      </div>
    );
  }

  return (
    <div className="screen auxiliary-screen">
      <div className="page-heading"><h1>学习资料</h1><p>保存的方法、公式和个人笔记会显示在这里。</p></div>
      <div className="empty-state auxiliary-empty"><ClipboardText size={23} /><strong>资料合同尚未接通</strong><p>当前版本不会把训练提示自动保存成学习资料。</p><button className="button secondary" onClick={() => setPage("tools")}>查看已接通训练</button></div>
    </div>
  );
}

function CommandPalette({ onClose, setPage, onOpenTool }) {
  const [query, setQuery] = useState("");
  const items = [
    { label: "判断推理学习空间", meta: "当前主线", action: () => setPage("judgment") },
    { label: "今日学习", meta: "页面", action: () => setPage("overview") },
    { label: "错因辨析", meta: "训练工具", action: () => onOpenTool("错因辨析") },
    { label: "技能报告", meta: "页面", action: () => setPage("reports") },
  ];
  const visible = items.filter((item) => !query.trim() || item.label.includes(query.trim()));
  return (
    <div className="command-scrim" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section className="command-palette" role="dialog" aria-modal="true" aria-label="全局搜索">
        <label className="command-input"><MagnifyingGlass size={17} /><input autoFocus value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索题目、技能或学习记录" /><button className="icon-button" onClick={onClose} aria-label="关闭"><X size={15} /></button></label>
        <div className="command-results">
          {visible.map((item) => <button key={item.label} onClick={() => { item.action(); onClose(); }}><span>{item.label}</span><small>{item.meta}</small><CaretRight size={13} /></button>)}
          {visible.length === 0 && <p>没有匹配的本机记录。</p>}
        </div>
      </section>
    </div>
  );
}

function UtilityPanel({ type, onClose }) {
  const content = {
    settings: ["设置", "学习记录默认保存在此 Mac。云端能力尚未启用。"],
    feedback: ["意见反馈", "可以记录遇到的问题；当前原型不会发送到外部服务。"],
    help: ["使用帮助", "从已接通的错因辨析开始训练，在技能报告中查看真实本机证据。"],
    profile: ["本机学习者", "考试目标与地区尚未设置。"],
  }[type];
  return (
    <SidePanel title={content[0]} onClose={onClose}>
      <p className="panel-intro">{content[1]}</p>
      {type === "settings" && <div className="setting-row"><span><strong>本机记录</strong><small>练习、评分与验证证据</small></span><span className="plain-state">已开启</span></div>}
      {type === "feedback" && <label className="answer-field"><span>反馈内容</span><textarea placeholder="请描述具体页面和问题" /></label>}
    </SidePanel>
  );
}

export function App() {
  const [page, setPage] = useState("judgment");
  const [collapsed, setCollapsed] = useState(false);
  const [favorites, setFavorites] = useState([]);
  const [selectedTool, setSelectedTool] = useState(null);
  const [toolStage, setToolStage] = useState("ready");
  const [commandOpen, setCommandOpen] = useState(false);
  const [utility, setUtility] = useState(null);
  const [sidecar, setSidecar] = useState(INITIAL_SIDECAR_STATE);
  const [planning, setPlanning] = useState(INITIAL_PLANNING_STATE);

  const refreshPlanning = useCallback(async ({ notice = null } = {}) => {
    setPlanning((current) => ({ ...current, phase: "loading", error: null, notice, processing: null }));
    try {
      const schedule = await fetchReviewSchedule();
      try {
        const plan = await fetchTodayPlan({ now: resolveClientNow() });
        setPlanning({ phase: "connected", plan, schedule, error: null, notice, processing: null });
        return { plan, schedule };
      } catch (error) {
        if (error?.status === 404 && error?.code === "schedule_not_found") {
          setPlanning({ phase: "not-created", plan: null, schedule, error: null, notice, processing: null });
          return { plan: null, schedule };
        }
        throw error;
      }
    } catch (error) {
      const phase = error?.kind === "unavailable" ? "offline" : "error";
      setPlanning({
        phase,
        plan: null,
        schedule: null,
        error,
        notice: notice || {
          kind: "error",
          title: phase === "offline" ? "本机服务未连接" : "计划读取失败",
          message: phase === "offline" ? "计划操作已关闭；不会读取缓存或演示数据。" : "响应未通过合同校验，请恢复服务后重新读取。",
        },
        processing: null,
      });
      return null;
    }
  }, []);

  const refreshSidecar = useCallback(async () => {
    setSidecar((current) => ({ ...current, phase: "checking", error: null }));
    try {
      const health = await fetchHealth();
      const report = await fetchSkillReport();
      setSidecar({ phase: "connected", health, report, error: null });
    } catch (error) {
      setSidecar({
        phase: error?.kind === "unavailable" ? "offline" : "error",
        health: null,
        report: null,
        error,
      });
    }
  }, []);

  const refreshSkills = useCallback(async () => {
    try {
      const [health, report] = await Promise.all([fetchHealth(), fetchSkillReport()]);
      setSidecar({ phase: "connected", health, report, error: null });
      await refreshPlanning();
      return report;
    } catch (error) {
      setSidecar((current) => ({
        ...current,
        phase: error?.kind === "unavailable" ? "offline" : "error",
        report: null,
        error,
      }));
      return null;
    }
  }, [refreshPlanning]);

  useEffect(() => {
    refreshSidecar();
    refreshPlanning();
  }, [refreshPlanning, refreshSidecar]);

  const retryAll = useCallback(() => {
    refreshSidecar();
    refreshPlanning();
  }, [refreshPlanning, refreshSidecar]);

  const handleCreatePlan = useCallback(async ({ examDate, dailyBudgetMinutes }) => {
    setPlanning((current) => ({ ...current, processing: "create", notice: null }));
    try {
      const plan = await createTodayPlan({
        now: resolveClientNow(),
        examDate,
        dailyBudgetMinutes,
      });
      const schedule = await fetchReviewSchedule();
      setPlanning({
        phase: "connected",
        plan,
        schedule,
        error: null,
        notice: {
          kind: "success",
          title: plan.status === "empty" ? "今日计划已生成" : "今日任务已生成",
          message: plan.status === "empty" ? "计划真实为空；未生成任何替代任务。" : `已读取 ${plan.tasks.length} 项有证据来源的任务。`,
        },
        processing: null,
      });
    } catch (error) {
      const recovery = classifyCreatePlanError(error);
      if (recovery === "retry_with_higher_budget") {
        setPlanning((current) => ({
          ...current,
          phase: "not-created",
          plan: null,
          error: null,
          notice: {
            kind: "conflict",
            code: "budget_below_accepted_commitment",
            title: "今日预算不足以覆盖已接受任务",
            message: "已接受任务会优先保留。请提高今日可用时间后重试；本次请求没有创建或修改计划。",
          },
          processing: null,
        }));
        return;
      }
      const conflict = recovery === "refresh";
      await refreshPlanning({
        notice: {
          kind: conflict ? "conflict" : "error",
          code: error?.code || "unknown",
          title: conflict ? "计划状态已变化" : "今日计划未创建",
          message: conflict
            ? (error?.code === "historical_plan_read_only" ? "本机日期或计划状态已变化；已重新读取本机当前计划。" : "已重新读取本机当天计划；请基于当前版本继续。")
            : (error?.message || "本机服务没有接受这次创建请求。"),
        },
      });
    }
  }, [refreshPlanning]);

  const handleTaskCommand = useCallback(async (task, action, postponeUntil) => {
    const plan = planning.plan;
    if (!plan || planning.phase !== "connected") return;
    setPlanning((current) => ({ ...current, processing: task.id, notice: null }));
    try {
      const updatedPlan = await commandTodayPlanTask({
        plan,
        task,
        action,
        postponeUntil,
      });
      const schedule = await fetchReviewSchedule();
      const copy = {
        accept: ["任务已接受", "可从绑定的活动开始真实练习。"],
        complete: ["已标记处理", "这不是学习效果证据，也没有更新 KT。"],
        postpone: ["任务已推迟", "所选日期是最早恢复到期日/进入轮候日；实际展示仍受预算、公平轮转与已接受承诺影响。"],
        skip: ["任务已跳过", "任务保留在 ReviewSchedule，并按后续学习日公平轮候；不承诺下一学习日展示。"],
      }[action];
      setPlanning({ phase: "connected", plan: updatedPlan, schedule, error: null, notice: { kind: "success", title: copy[0], message: copy[1] }, processing: null });
    } catch (error) {
      const conflict = [
        "historical_plan_read_only",
        "stale_task_version",
        "stale_schedule_version",
        "command_conflict",
      ].includes(error?.code);
      const conflictMessage = {
        historical_plan_read_only: "原计划已经成为历史快照；已读取本机当天计划。",
        stale_task_version: "任务已在其他操作中变化；已重新读取最新任务版本。",
        stale_schedule_version: "计划版本已变化；已重新读取最新计划。",
        command_conflict: "随机命令编号已被用于不同操作；状态已重新读取，可安全重试。",
      }[error?.code];
      await refreshPlanning({
        notice: {
          kind: conflict ? "conflict" : "error",
          title: conflict ? "任务状态已变化" : "任务操作未完成",
          message: conflict ? conflictMessage : (error?.message || "本机服务没有接受这次操作。"),
        },
      });
    }
  }, [planning.phase, planning.plan, refreshPlanning]);

  const openToolByTitle = (title) => {
    const tool = TOOLS.find((item) => item.title === title);
    setPage("tools");
    setSelectedTool(tool?.available && sidecar.phase === "connected" ? tool : null);
    setToolStage("ready");
  };

  const launchTask = (task) => {
    if (!task?.launchable || sidecar.phase !== "connected") {
      setPlanning((current) => ({ ...current, notice: { kind: "error", title: "练习不可用", message: "只有可启动且绑定当前增长率题的活动可以进入练习。" } }));
      return;
    }
    openToolByTitle("错因辨析");
  };

  return (
    <main className="desktop-canvas">
      <div className={collapsed ? "app-window sidebar-collapsed" : "app-window"}>
        <Sidebar page={page} setPage={setPage} collapsed={collapsed} setCollapsed={setCollapsed} onUtility={setUtility} sidecar={sidecar} onRetrySidecar={retryAll} />
        <section className="app-main">
          {page !== "tools" && page !== "judgment" && <Topbar page={page} setPage={setPage} onSearch={() => setCommandOpen(true)} onUtility={setUtility} />}
          {page === "judgment" && <JudgmentWorkspace />}
          {page === "overview" && <Overview setPage={setPage} sidecar={sidecar} planning={planning} />}
          {page === "practice" && <TodayPracticeScreen planning={planning} onCreate={handleCreatePlan} onCommand={handleTaskCommand} onLaunchTask={launchTask} />}
          {page === "tools" && <ToolsScreen favorites={favorites} setFavorites={setFavorites} selectedTool={selectedTool} setSelectedTool={setSelectedTool} toolStage={toolStage} setToolStage={setToolStage} sidecar={sidecar} onRefreshSkills={refreshSkills} setPage={setPage} />}
          {page === "reports" && <ReportsScreen setPage={setPage} sidecar={sidecar} planning={planning} />}
          {page === "materials" && <StudyPackMaterials />}
        </section>

        {commandOpen && <CommandPalette onClose={() => setCommandOpen(false)} setPage={setPage} onOpenTool={openToolByTitle} />}
        {utility && <UtilityPanel type={utility} onClose={() => setUtility(null)} />}
      </div>
    </main>
  );
}
