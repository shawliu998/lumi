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
  continueAttempt,
  fetchHealth,
  fetchMisconceptionDossier,
  fetchSkillReport,
  requestNextAssistance,
  submitAttempt,
} from "./hermesApi";
import {
  ASSISTANCE_ACTIONS,
  appendAssistance,
  createAssistanceCommandId,
  createAssistanceState,
  normalizeMisconceptionDossier,
} from "./learningSupportAdapter";
import { reportGroupsFromSidecar } from "./reportEvidenceAdapter";

const NAV_ITEMS = [
  { id: "overview", label: "今日学习", icon: House },
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

const CONNECTED_FIXTURE_ID = "xingce.data-analysis.growth-rate.synthetic-01";
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
        <button className={`connection-status ${sidecar.phase}`} onClick={onRetrySidecar} data-testid="sidecar-status" data-state={sidecar.phase} title={collapsed ? connectionTitle : undefined}>
          {connectionContent}
        </button>
      ) : (
        <div className={`connection-status ${sidecar.phase}`} data-testid="sidecar-status" data-state={sidecar.phase} title={collapsed ? connectionTitle : undefined}>
          {connectionContent}
        </div>
      )}

      <nav className="secondary-nav" aria-label="辅助导航">
        <button className="nav-item" onClick={() => onUtility("settings")} title={collapsed ? "设置" : undefined}><Gear size={15} />{!collapsed && <span>设置</span>}</button>
        <button className="nav-item" onClick={() => onUtility("feedback")} title={collapsed ? "意见反馈" : undefined}><ChatCircleDots size={15} />{!collapsed && <span>意见反馈</span>}</button>
        <button className="nav-item" onClick={() => onUtility("help")} title={collapsed ? "使用帮助" : undefined}><Question size={15} />{!collapsed && <span>使用帮助</span>}</button>
      </nav>

      <button className="profile-row" onClick={() => onUtility("profile")} title={collapsed ? "本机学习者" : undefined}>
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
      <button className="global-search" onClick={onSearch}>
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
                <em>{item.probability === null ? claimStatusCopy(item.claimStatus) : `${Math.round(item.probability * 100)}% · ${claimStatusCopy(item.claimStatus)}`}</em>
              </li>
            ))}
          </ol>
        ) : <p className="dossier-empty">首答通过，规则要求不生成错误原因。</p>}
        {dossier.rankedHypotheses.length > 0 && <p className="dossier-rank-note">百分比只表示本轮候选的相对排序，不是群体统计。</p>}
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
  }).formatToParts(new Date());
  const value = (type) => parts.find((item) => item.type === type)?.value || "";
  return `${value("month")} 月 ${value("day")} 日 · ${value("weekday")}`;
}

function Overview({ setPage, onOpenTool, sidecar }) {
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
  const sourceStateCopy = connected
    ? runCount > 0
      ? `${runCount} 条本机运行轨迹 · ${liveSkills.length} 个有报告技能`
      : "本机服务已连接，尚无运行轨迹"
    : sidecar.phase === "checking"
      ? "正在读取本机证据"
      : sidecar.phase === "error"
        ? "本机服务响应异常，记录不可用"
        : "本机服务未连接，记录不可用";

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
            <button className="button primary" disabled={!connected} onClick={() => onOpenTool("错因辨析")}>{connected ? "开始错因辨析" : "本机服务不可用"}</button>
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

          <section className="assignments-section">
            <div className="section-title row-between">
              <h2>今日安排</h2>
              <div className="section-actions">
                <button className="text-link" onClick={() => setPage("practice")}>查看任务状态</button>
              </div>
            </div>
            <div className="table-shell" role="table" aria-label="今日安排">
              <div className="table-row table-head" role="row"><span>任务</span><span>类型</span><span>预计时间</span><span>状态</span></div>
              <div className="table-empty-row" role="row"><span>{connected ? "任务编排 API 尚未接通；不会依据技能报告生成虚构任务。" : "本机任务记录当前不可用。"}</span></div>
            </div>
          </section>
        </div>

        <aside className="daily-panel">
          <div className="row-between"><strong>本机证据</strong><span>{connected ? "已连接" : "不可用"}</span></div>
          <p className="daily-source-copy">{sourceStateCopy}</p>
          <dl><div><dt>运行轨迹</dt><dd>{connected ? `${runCount} 条` : "—"}</dd></div><div><dt>报告技能</dt><dd>{connected ? `${liveSkills.length} 个` : "—"}</dd></div></dl>
          <hr />
          <strong>下一步</strong>
          <p>{connected ? (runCount > 0 ? "只在技能报告中查看已完成运行形成的证据。" : "完成一次真实错因辨析后，这里才会出现本机证据。") : "恢复本机服务后才能开始真实训练。"}</p>
          {connected && <button className="text-link" onClick={() => onOpenTool("错因辨析")}>开始真实训练 <ArrowRight size={12} /></button>}
        </aside>
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
  const [attemptStartedAt, setAttemptStartedAt] = useState(0);
  const [phaseAnswer, setPhaseAnswer] = useState("");
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

  const openTool = (tool) => {
    if (!tool.available || sidecar.phase !== "connected") return;
    setSelectedTool(tool);
    setToolStage("ready");
    setAnswer("");
    setConfidence("");
    setPhaseAnswer("");
    setPhaseConfidence("");
    setRunEvidence(null);
    setRunError(null);
    setAssistance(createAssistanceState());
    setDossierState({ phase: "idle", dossier: null, error: null });
  };

  const closeTool = () => {
    setSelectedTool(null);
    setToolStage("ready");
    setAnswer("");
    setConfidence("");
    setPhaseAnswer("");
    setPhaseConfidence("");
    setRunEvidence(null);
    setRunError(null);
    setAssistance(createAssistanceState());
    setDossierState({ phase: "idle", dossier: null, error: null });
  };

  const startConfiguredRun = () => {
    if (sidecar.phase !== "connected") return;
    setToolStage("active");
    setAnswer("");
    setConfidence("");
    setAttemptStartedAt(Date.now());
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
    if (sidecar.phase !== "connected") return;
    setToolStage("running");
    setRunEvidence(null);
    setRunError(null);
    const confidenceValues = { low: 0.35, medium: 0.65, high: 0.9 };
    try {
      const evidence = await submitAttempt({
        fixtureId: CONNECTED_FIXTURE_ID,
        response: answer,
        confidence: confidenceValues[confidence],
        responseTimeSeconds: (Date.now() - attemptStartedAt) / 1000,
      });
      setRunEvidence(evidence);
      setPhaseAnswer("");
      setPhaseConfidence("");
      setPhaseStartedAt(Date.now());
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
    if (gate.kind !== "ready") return;
    setToolStage("running");
    setRunError(null);
    const confidenceValues = { low: 0.35, medium: 0.65, high: 0.9 };
    const session = phase === "probe" ? runEvidence?.attempt : runEvidence?.continuation;
    try {
      const next = await continueAttempt({
        session,
        phase,
        response: phaseAnswer,
        confidence: confidenceValues[phaseConfidence],
        responseTimeSeconds: (Date.now() - phaseStartedAt) / 1000,
      });
      setRunEvidence((current) => ({ ...current, ...next }));
      setPhaseAnswer("");
      setPhaseConfidence("");
      if (phase === "probe") {
        setPhaseStartedAt(Date.now());
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
    setPhaseAnswer("");
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
    setPhaseAnswer("");
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
              <article className={operable ? "tool-card" : "tool-card unavailable"} key={tool.title} data-tool-title={tool.title} data-availability={operable ? "connected" : tool.available ? "service-unavailable" : "phased"} data-fixture-id={tool.available ? CONNECTED_FIXTURE_ID : undefined}>
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
              <div className="evidence-note"><Info size={15} /><span>{sidecar.phase === "connected" ? "先提交作答与信心；服务只会依据这次真实输入生成轨迹。" : "本机服务不可用；真实训练暂不能开始，也不会创建本机轨迹。"}</span></div>
              <button className="button primary panel-primary" disabled={sidecar.phase !== "connected"} onClick={startConfiguredRun}>{sidecar.phase === "connected" ? "开始作答" : "本机服务不可用"}</button>
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
            <>
              <div className="run-progress"><span>步骤 1 / 3</span><strong>{CONNECTED_SKILL_NAME}</strong></div>
              <div className="prompt-block">
                <small>请独立作答</small>
                <p>某园区产值由 2024 年的 200 亿元增至 2025 年的 230 亿元，同比增长率约为多少？</p>
              </div>
              <div className="independent-boundary"><Info size={13} /><span>初答不提供帮助；提交后如需辨析，服务会在定向探查题上开放渐进帮助。</span></div>
              <label className="answer-field"><span>你的答案</span><select value={answer} onChange={(event) => setAnswer(event.target.value)}><option value="">请选择</option><option value="A">A · 13.0%</option><option value="B">B · 15.0%</option><option value="C">C · 30.0%</option><option value="D">D · 115.0%</option></select></label>
              <label className="answer-field"><span>作答信心</span><select value={confidence} onChange={(event) => setConfidence(event.target.value)}><option value="">请选择</option><option value="low">不太确定</option><option value="medium">基本确定</option><option value="high">非常确定</option></select></label>
              <button className="button primary panel-primary" disabled={!answer || !confidence} onClick={submitConfiguredAttempt}>提交本机验证</button>
            </>
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
                  <label className="answer-field"><span>你的判断</span><textarea value={phaseAnswer} onChange={(event) => setPhaseAnswer(event.target.value)} placeholder="写下公式或判断依据" /></label>
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
              {verificationGate.kind === "ready" ? (
                <>
                  <section className="teaching-block"><small>针对性提示</small><p>{runEvidence.continuation.teaching.prompt}</p><span>{runEvidence.continuation.teaching.strategy === "worked-example-fading" ? "先标出基期，再独立完成一题。" : "请按提示完成后续验证。"}</span></section>
                  <div className="independent-boundary"><Info size={13} /><span>独立验证不提供帮助；只有这一步完成后，服务才可能更新掌握状态。</span></div>
                  <div className="prompt-block probe-prompt"><small>独立验证题</small><p>{runEvidence.continuation.verification.prompt}</p></div>
                  <label className="answer-field"><span>你的答案</span><select value={phaseAnswer} onChange={(event) => setPhaseAnswer(event.target.value)}><option value="">请选择</option><option value="A">A · 12%</option><option value="B">B · 13%</option><option value="C">C · 15%</option><option value="D">D · 115%</option></select></label>
                  <label className="answer-field"><span>作答信心</span><select value={phaseConfidence} onChange={(event) => setPhaseConfidence(event.target.value)}><option value="">请选择</option><option value="low">不太确定</option><option value="medium">基本确定</option><option value="high">非常确定</option></select></label>
                  <button className="button primary panel-primary" disabled={!phaseAnswer || !phaseConfidence} onClick={() => submitContinuation("verification")}>提交独立验证</button>
                </>
              ) : null}
            </div>
          )}
          {toolStage === "result" && runEvidence && (
            <div className="run-result" role="status" data-testid="run-status" data-state="completed" data-version={runEvidence.continuation?.state_version}>
              <div className="run-result-heading"><CheckCircle size={20} weight="fill" /><div><h3>本轮验证已完成</h3><small>{runEvidence.attempt.run_id}</small></div></div>
              <dl className="run-result-list">
                <div><dt>运行状态</dt><dd>{runEvidence.continuation?.state === "completed" ? "已完成" : runEvidence.continuation?.state}</dd></div>
                <div><dt>作答评分</dt><dd>{runEvidence.attempt.score?.passed ? "通过" : "未通过"} · {runEvidence.attempt.score?.score}/{runEvidence.attempt.score?.max_score}</dd></div>
                <div><dt>诊断决策</dt><dd>{diagnosisDecisionCopy(runEvidence.attempt.diagnosis?.decision)}</dd></div>
                <div><dt>独立验证</dt><dd>{runEvidence.continuation?.verification?.effective ? "通过" : "未通过"}</dd></div>
                <div><dt>本轮轨迹变化</dt><dd>{Number(runEvidence.continuation?.mastery_update?.mastery_delta) >= 0 ? "+" : ""}{Number(runEvidence.continuation?.mastery_update?.mastery_delta || 0).toFixed(3)} · 非纵向掌握</dd></div>
                <div><dt>轨迹校验</dt><dd>{traceVerified ? "已通过" : "未通过"}</dd></div>
                <div><dt>轨迹 / 回放</dt><dd>{runEvidence.trace.event_count} 个事件 · {runEvidence.replay.frame_count} 帧</dd></div>
              </dl>
              <MisconceptionDossier state={dossierState} />
              <button className="button primary panel-primary" onClick={() => { closeTool(); setPage("reports"); }}>查看技能报告</button>
            </div>
          )}
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

function ReportsScreen({ setPage, sidecar }) {
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
        <section className="report-list-section"><div className="report-list-heading"><h2>复习安排</h2><p>当前 sidecar 尚未提供复习计划合同。</p></div><div className="empty-state report-empty"><strong>复习记录不可用</strong><p>客户端不会根据技能报告自行推算到期时间。</p></div></section>
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
  const [page, setPage] = useState("overview");
  const [collapsed, setCollapsed] = useState(false);
  const [favorites, setFavorites] = useState([]);
  const [selectedTool, setSelectedTool] = useState(null);
  const [toolStage, setToolStage] = useState("ready");
  const [commandOpen, setCommandOpen] = useState(false);
  const [utility, setUtility] = useState(null);
  const [sidecar, setSidecar] = useState(INITIAL_SIDECAR_STATE);

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
  }, []);

  useEffect(() => {
    refreshSidecar();
  }, [refreshSidecar]);

  const openToolByTitle = (title) => {
    const tool = TOOLS.find((item) => item.title === title);
    setPage("tools");
    setSelectedTool(tool?.available && sidecar.phase === "connected" ? tool : null);
    setToolStage("ready");
  };

  return (
    <main className="desktop-canvas">
      <div className={collapsed ? "app-window sidebar-collapsed" : "app-window"}>
        <Sidebar page={page} setPage={setPage} collapsed={collapsed} setCollapsed={setCollapsed} onUtility={setUtility} sidecar={sidecar} onRetrySidecar={refreshSidecar} />
        <section className="app-main">
          {page !== "tools" && <Topbar page={page} setPage={setPage} onSearch={() => setCommandOpen(true)} onUtility={setUtility} />}
          {page === "overview" && <Overview setPage={setPage} onOpenTool={openToolByTitle} sidecar={sidecar} />}
          {page === "tools" && <ToolsScreen favorites={favorites} setFavorites={setFavorites} selectedTool={selectedTool} setSelectedTool={setSelectedTool} toolStage={toolStage} setToolStage={setToolStage} sidecar={sidecar} onRefreshSkills={refreshSkills} setPage={setPage} />}
          {page === "reports" && <ReportsScreen setPage={setPage} sidecar={sidecar} />}
          {(page === "practice" || page === "materials") && <AuxiliaryScreen page={page} setPage={setPage} />}
        </section>

        {commandOpen && <CommandPalette onClose={() => setCommandOpen(false)} setPage={setPage} onOpenTool={openToolByTitle} />}
        {utility && <UtilityPanel type={utility} onClose={() => setUtility(null)} />}
      </div>
    </main>
  );
}
