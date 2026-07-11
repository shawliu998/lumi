import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowRight,
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
  SignOut,
  Target,
  Toolbox,
  X,
} from "@phosphor-icons/react";
import lumiMark from "./assets/lumi-mark.png";
import lumiWordmark from "./assets/lumi-wordmark.png";
import {
  continueAttempt,
  fetchHealth,
  fetchSkillReport,
  submitAttempt,
} from "./hermesApi";

const NAV_ITEMS = [
  { id: "overview", label: "今日学习", icon: House },
  { id: "practice", label: "练习任务", icon: ListChecks },
  { id: "tools", label: "训练工具", icon: Toolbox },
  { id: "materials", label: "学习资料", icon: Books },
  { id: "reports", label: "技能报告", icon: ChartBar },
];

const TOOLS = [
  { category: "诊断", title: "错因辨析", description: "用一组短题验证一个具体的错因假设。" },
  { category: "练习", title: "同类变式", description: "围绕一个技能完成无提示的独立作答。" },
  { category: "复习", title: "间隔复习", description: "复习已到期、但曾经学会的技能。" },
  { category: "复盘", title: "要点复盘", description: "对照材料与评分点逐项核查答案。" },
  { category: "复盘", title: "局部改写", description: "只重写一个问题句或一个答案段落。" },
  { category: "复盘", title: "二次作答", description: "保留原题，重新计时组织并作答。" },
  { category: "计划", title: "今日计划", description: "按到期任务与可用时间安排今天的顺序。" },
  { category: "复盘", title: "错题复盘", description: "查看原题、作答、评分和待确认错因。" },
  { category: "复习", title: "方法清单", description: "回看已确认的方法、公式与易混点。" },
  { category: "诊断", title: "迁移验证", description: "更换题面，检查方法能否独立使用。" },
  { category: "练习", title: "材料定位", description: "练习从申论材料中定位可用信息。" },
  { category: "复盘", title: "提纲复盘", description: "检查面试回答的观点、层次与例证。" },
];

const SKILL_GROUPS = [
  {
    id: "verbal",
    title: "言语理解与表达",
    skills: [
      { id: "main-idea", name: "主旨概括", level: 2, attempts: 18, state: "学习中", last: "7 月 9 日", due: false },
      { id: "intent", name: "意图判断", level: 1, attempts: 9, state: "初步理解", last: "7 月 6 日", due: true },
      { id: "cloze", name: "逻辑填空", level: 3, attempts: 27, state: "基本稳定", last: "7 月 10 日", due: false },
    ],
  },
  {
    id: "data",
    title: "资料分析",
    skills: [
      { id: "base-value", name: "增长率与基期量", level: 1, attempts: 12, state: "待验证", last: "7 月 10 日", due: true },
      { id: "proportion", name: "比重与倍数", level: 2, attempts: 16, state: "学习中", last: "7 月 8 日", due: true },
      { id: "average", name: "平均数与增长量", level: 2, attempts: 14, state: "学习中", last: "7 月 7 日", due: false },
    ],
  },
  {
    id: "judgment",
    title: "判断推理",
    skills: [
      { id: "necessary", name: "必要条件", level: 2, attempts: 11, state: "学习中", last: "7 月 5 日", due: true },
      { id: "figures", name: "图形规律", level: 3, attempts: 22, state: "基本稳定", last: "7 月 10 日", due: false },
    ],
  },
];

const ACTIVITY_ROWS = [
  ["7 月 10 日 20:14", "增长率与基期量 · 独立作答", "4 题中 2 题需复验", "已记录"],
  ["7 月 10 日 19:42", "图形规律 · 间隔复习", "4 题独立完成", "已记录"],
  ["7 月 9 日 21:05", "主旨概括 · 同类变式", "6 题中 4 题独立完成", "已记录"],
];

const REVIEW_ROWS = [
  ["今天", "意图判断", "距上次验证 5 天", "待复习"],
  ["今天", "比重与倍数", "距上次验证 3 天", "待复习"],
  ["7 月 13 日", "平均数与增长量", "按当前间隔安排", "已安排"],
];

const INITIAL_SIDECAR_STATE = {
  phase: "checking",
  health: null,
  report: null,
  error: null,
};

const SKILL_NAMES = {
  "xingce.data.growth.identify-base-current": "增长率与基期量",
  "xingce.data.growth.compute-rate": "增长率计算",
  "xingce.verbal.main-idea.integrate": "主旨概括",
  "xingce.verbal.scope-control": "范围控制",
  "xingce.judgment.logic.necessary-condition": "必要条件",
  "xingce.judgment.logic.symbolize": "逻辑符号化",
};

function connectionCopy(sidecar) {
  if (sidecar.phase === "connected") return ["本机服务已连接", `${sidecar.health?.run_count || 0} 条运行轨迹`];
  if (sidecar.phase === "checking") return ["正在连接本机服务", "读取本机记录"];
  if (sidecar.phase === "error") return ["本机服务响应异常", "演示数据"];
  return ["本机服务未连接", "演示数据"];
}

function reportGroupsFromSidecar(report) {
  if (!report?.items?.length) return [];
  const definitions = {
    verbal: { id: "verbal", title: "言语理解与表达", skills: [] },
    data: { id: "data", title: "资料分析", skills: [] },
    judgment: { id: "judgment", title: "判断推理", skills: [] },
  };
  report.items.forEach((item) => {
    const groupId = item.skill_id.includes(".verbal.")
      ? "verbal"
      : item.skill_id.includes(".judgment.")
        ? "judgment"
        : "data";
    const mastery = Number(item.latest_mastery);
    const uncertainty = Number(item.latest_uncertainty);
    let state = "暂不判断";
    let level = 1;
    if (Number.isFinite(mastery) && Number.isFinite(uncertainty) && uncertainty < 0.7) {
      if (mastery >= 0.68) {
        state = "基本稳定";
        level = 3;
      } else if (mastery >= 0.45) {
        state = "学习中";
        level = 2;
      } else {
        state = "待验证";
      }
    }
    definitions[groupId].skills.push({
      id: item.skill_id,
      name: SKILL_NAMES[item.skill_id] || item.skill_id.split(".").slice(-2).join(" · "),
      level,
      attempts: Number(item.run_count) || 0,
      state,
      last: formatLocalDate(item.latest_at),
      due: false,
      live: item,
    });
  });
  return Object.values(definitions).filter((group) => group.skills.length > 0);
}

function formatLocalDate(value) {
  if (!value) return "暂无";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "暂无";
  return `${date.getMonth() + 1} 月 ${date.getDate()} 日`;
}

function diagnosisDecisionCopy(value) {
  if (value === "disambiguate_hypotheses") return "候选原因仍需区分";
  if (value === "confirm_top_hypothesis") return "需要继续验证首位候选";
  if (value === "retention_probe") return "未形成错因判断，转入保持性验证";
  return value || "未返回诊断决策";
}

function diagnosisCandidates(trace) {
  const diagnose = trace?.events?.find((event) => event?.payload?.phase === "diagnose");
  const hypotheses = diagnose?.payload?.output?.diagnosis?.hypotheses;
  return Array.isArray(hypotheses) ? hypotheses.slice(0, 3) : [];
}

const DIAGNOSIS_CAUSE_COPY = {
  "ratio-growth-confusion": "只算现期/基期而未减 1",
  "denominator-current-base-confusion": "增长率分母误用现期量",
  "increment-rate-confusion": "把增长量当作增长率",
};

function diagnosisCandidateCopy(candidate) {
  return DIAGNOSIS_CAUSE_COPY[candidate?.cause_id] || candidate?.label || "待进一步辨析的线索";
}

function diagnosisCandidateProbability(candidate) {
  const value = Number(candidate?.probability ?? candidate?.confidence ?? candidate?.synthetic_prior);
  return Number.isFinite(value) ? `${Math.round(value * 100)}%` : "概率未提供";
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
          <span className="brand-mark"><img src={lumiMark} alt="" /></span>
          {!collapsed && <img className="brand-wordmark" src={lumiWordmark} alt="" />}
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

      <button className="profile-row" onClick={() => onUtility("profile")} title={collapsed ? "林同学" : undefined}>
        <span className="avatar">林</span>
        {!collapsed && <><span>林同学</span><SignOut size={15} /></>}
      </button>
    </aside>
  );
}

function Topbar({ page, setPage, scope, setScope, onSearch, onUtility }) {
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
        <span className="sr-only">当前备考科目</span>
        <select value={scope} onChange={(event) => setScope(event.target.value)}>
          <option>行测备考</option>
          <option>申论备考</option>
          <option>面试备考</option>
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

function Overview({ setPage, taskStatus, onOpenTask, onOpenTool, onOpenRecords }) {
  const [query, setQuery] = useState("");
  const [searchResult, setSearchResult] = useState("");
  const completed = taskStatus === "complete" ? 2 : 1;
  const taskButton = taskStatus === "ready" ? "开始今日任务" : taskStatus === "in_progress" ? "继续基期量验证" : "查看今日记录";

  const runSearch = (event) => {
    event.preventDefault();
    const normalized = query.trim();
    if (normalized) setSearchResult(normalized);
  };

  const taskRows = [
    ["主旨概括 · 间隔复习", "行测", "10 分钟", "已完成", "done"],
    ["基期量 · 公式方向验证", "行测", "12 分钟", taskStatus === "ready" ? "未开始" : taskStatus === "in_progress" ? "进行中" : "已完成", taskStatus],
    ["概括归纳 · 要点复盘", "申论", "20 分钟", "未开始", "ready"],
    ["综合分析 · 二次作答", "面试", "15 分钟", "未开始", "ready"],
  ];

  return (
    <div className="screen overview-screen">
      <div className="page-heading row-between overview-heading">
        <div>
          <span className="eyebrow">7 月 11 日 · 星期六</span>
          <h1>今日学习</h1>
        </div>
        <strong className="exam-label">广东省考 · 行测</strong>
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
            <button className="button primary" onClick={onOpenTask}>{taskButton}</button>
            <button className="button secondary" onClick={() => onOpenTool("错因辨析")}>错因辨析</button>
            <button className="button secondary" onClick={() => setPage("reports")}>查看待复验技能</button>
          </div>

          {searchResult && (
            <div className="search-feedback" role="status">
              <span>找到与“{searchResult}”相关的 3 条本机记录。</span>
              <button className="text-link" onClick={() => setPage("reports")}>查看结果 <ArrowRight size={12} /></button>
              <button className="icon-button" onClick={() => setSearchResult("")} aria-label="关闭搜索结果"><X size={13} /></button>
            </div>
          )}

          <section className="content-section">
            <div className="section-title row-between">
              <h2>学习科目</h2>
              <div className="carousel-controls" aria-label="科目翻页">
                <button disabled aria-label="上一组"><CaretLeft size={12} /></button>
                <button aria-label="下一组"><CaretRight size={12} /></button>
              </div>
            </div>
            <div className="subject-cards">
              {[
                ["行测", "8 个有记录技能", Target, "reports"],
                ["申论", "最近练习：概括归纳 · 7 月 9 日", NotePencil, "tools"],
                ["面试", "下次任务：综合分析 · 15 分钟", Microphone, "tools"],
              ].map(([name, description, Icon, target]) => (
                <button className="subject-card" key={name} onClick={() => setPage(target)}>
                  <span className="subject-icon"><Icon size={15} /></span>
                  <span className="subject-copy"><small>科目</small><strong>{name}</strong><em>{description}</em></span>
                  <CaretRight size={13} />
                </button>
              ))}
            </div>
            <button className="text-link subject-more" onClick={() => setPage("reports")}>查看全部学习科目 <ArrowRight size={12} /></button>
          </section>

          <section className="assignments-section">
            <div className="section-title row-between">
              <h2>今日安排</h2>
              <div className="section-actions">
                <button className="button compact secondary" onClick={() => setPage("practice")}>添加任务</button>
                <button className="text-link" onClick={() => setPage("practice")}>查看全部任务</button>
              </div>
            </div>
            <div className="table-shell" role="table" aria-label="今日安排">
              <div className="table-row table-head" role="row"><span>任务</span><span>类型</span><span>预计时间</span><span>状态</span></div>
              {taskRows.map(([title, type, duration, state, stateKey], index) => (
                <button className="table-row" key={title} onClick={index === 1 ? onOpenTask : index === 0 ? onOpenRecords : () => setPage("tools")}>
                  <span>{title}</span><span>{type}</span><span>{duration}</span><span className={`status ${stateKey}`}>{state}</span>
                </button>
              ))}
            </div>
          </section>
        </div>

        <aside className="daily-panel">
          <div className="row-between"><strong>今日进度</strong><span>{completed} / 4</span></div>
          <div className="simple-progress" aria-label={`今日任务已完成 ${completed} 项，共 4 项`}><span style={{ width: `${completed * 25}%` }} /></div>
          <dl><div><dt>已完成</dt><dd>{completed} 项</dd></div><div><dt>剩余</dt><dd>{4 - completed} 项</dd></div></dl>
          <hr />
          <strong>优先复习</strong>
          <p>近 3 次“基期量”作答有 2 次公式方向相反，暂列为待确认。</p>
          <button className="text-link" onClick={onOpenRecords}>查看作答记录 <ArrowRight size={12} /></button>
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
  const [targetSkill, setTargetSkill] = useState("增长率与基期量");
  const [runEvidence, setRunEvidence] = useState(null);
  const [runError, setRunError] = useState(null);

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
    setSelectedTool(tool);
    setToolStage("ready");
    setAnswer("");
    setConfidence("");
    setPhaseAnswer("");
    setPhaseConfidence("");
    setRunEvidence(null);
    setRunError(null);
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
  };

  const startConfiguredRun = () => {
    setToolStage("active");
    setAnswer("");
    setConfidence("");
    setAttemptStartedAt(Date.now());
  };

  const submitConfiguredAttempt = async () => {
    if (sidecar.phase !== "connected") {
      setToolStage("done");
      return;
    }
    setToolStage("running");
    setRunEvidence(null);
    setRunError(null);
    const confidenceValues = { low: 0.35, medium: 0.65, high: 0.9 };
    try {
      const evidence = await submitAttempt({
        fixtureId: "xingce.data-analysis.growth-rate.synthetic-01",
        response: answer,
        confidence: confidenceValues[confidence],
        responseTimeSeconds: (Date.now() - attemptStartedAt) / 1000,
      });
      setRunEvidence(evidence);
      setPhaseAnswer("");
      setPhaseConfidence("");
      setPhaseStartedAt(Date.now());
      setToolStage("probe");
    } catch (error) {
      setRunError(error);
      setToolStage("error");
    }
  };

  const submitContinuation = async (phase) => {
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
    } catch (error) {
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
    setToolStage("ready");
  };

  const candidates = runEvidence?.attempt?.diagnosis?.hypotheses || diagnosisCandidates(runEvidence?.trace);
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
            return (
              <article className="tool-card" key={tool.title}>
                <button className="tool-card-main" onClick={() => openTool(tool)}>
                  <small>{tool.category}</small>
                  <strong>{tool.title}</strong>
                  <span>{tool.description}</span>
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
                <label><span>科目</span><select defaultValue="行测"><option>行测</option><option>申论</option><option>面试</option></select></label>
                <label><span>技能</span><select value={targetSkill} onChange={(event) => setTargetSkill(event.target.value)}><option>增长率与基期量</option><option>意图判断</option><option>必要条件</option></select></label>
                <label><span>本次验证</span><input value="公式方向是否混淆" readOnly /></label>
                <label><span>本轮步骤</span><input value="3 · 首答、探查、独立验证" readOnly /></label>
              </div>
              <div className="evidence-note"><Info size={15} /><span>{sidecar.phase === "connected" ? "先提交作答与信心；服务只会依据这次真实输入生成轨迹。" : "本机服务未连接；下面是演示流程，不会写入真实轨迹。"}</span></div>
              <button className="button primary panel-primary" onClick={startConfiguredRun}>{sidecar.phase === "connected" ? "开始作答" : "查看演示流程"}</button>
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
              {sidecar.phase !== "connected" && <div className="demo-notice"><Info size={14} /><span>演示数据 · 不会写入本机轨迹</span></div>}
              <div className="run-progress"><span>步骤 1 / 3</span><strong>{targetSkill}</strong></div>
              <div className="prompt-block">
                <small>请独立作答</small>
                <p>某园区产值由 2024 年的 200 亿元增至 2025 年的 230 亿元，同比增长率约为多少？</p>
              </div>
              <label className="answer-field"><span>你的答案</span><select value={answer} onChange={(event) => setAnswer(event.target.value)}><option value="">请选择</option><option value="A">A · 13.0%</option><option value="B">B · 15.0%</option><option value="C">C · 30.0%</option><option value="D">D · 115.0%</option></select></label>
              <label className="answer-field"><span>作答信心</span><select value={confidence} onChange={(event) => setConfidence(event.target.value)}><option value="">请选择</option><option value="low">不太确定</option><option value="medium">基本确定</option><option value="high">非常确定</option></select></label>
              <button className="button primary panel-primary" disabled={!answer || !confidence} onClick={submitConfiguredAttempt}>{sidecar.phase === "connected" ? "提交本机验证" : "记录演示作答"}</button>
            </>
          )}
          {toolStage === "probe" && runEvidence?.attempt && (
            <div className="continuation-stage" data-testid="attempt-stage" data-state="awaiting-probe" data-version={runEvidence.attempt.state_version} data-run-id={runEvidence.attempt.run_id}>
              <div className="stage-kicker"><span>步骤 2 / 3</span><strong>探查当前线索</strong></div>
              <dl className="compact-result"><div><dt>首答评分</dt><dd>{runEvidence.attempt.score?.passed ? "通过" : "未通过"} · {runEvidence.attempt.score?.score}/{runEvidence.attempt.score?.max_score}</dd></div><div><dt>诊断决策</dt><dd>{diagnosisDecisionCopy(runEvidence.attempt.diagnosis?.decision)}</dd></div></dl>
              {candidates.length > 0 && (
                <div className="candidate-list">
                  <strong>候选线索（未确认）</strong>
                  {candidates.map((candidate) => <span key={candidate.cause_id}>{diagnosisCandidateCopy(candidate)}<small>{diagnosisCandidateProbability(candidate)}</small></span>)}
                  <p>请用下面的短题区分线索，不能据此直接确认原因。</p>
                </div>
              )}
              <div className="prompt-block probe-prompt"><small>探查题</small><p>{runEvidence.attempt.probe.prompt}</p></div>
              <label className="answer-field"><span>你的判断</span><textarea value={phaseAnswer} onChange={(event) => setPhaseAnswer(event.target.value)} placeholder="写下公式或判断依据" /></label>
              <label className="answer-field"><span>作答信心</span><select value={phaseConfidence} onChange={(event) => setPhaseConfidence(event.target.value)}><option value="">请选择</option><option value="low">不太确定</option><option value="medium">基本确定</option><option value="high">非常确定</option></select></label>
              <button className="button primary panel-primary" disabled={phaseAnswer.trim().length < 2 || !phaseConfidence} onClick={() => submitContinuation("probe")}>提交探查作答</button>
            </div>
          )}
          {toolStage === "verification" && runEvidence?.continuation && (
            <div className="continuation-stage" data-testid="attempt-stage" data-state="awaiting-verification" data-version={runEvidence.continuation.state_version} data-run-id={runEvidence.continuation.run_id}>
              <div className="stage-kicker"><span>步骤 3 / 3</span><strong>独立验证</strong></div>
              <section className="teaching-block"><small>针对性提示</small><p>{runEvidence.continuation.teaching.prompt}</p><span>{runEvidence.continuation.teaching.strategy === "worked-example-fading" ? "先标出基期，再独立完成一题。" : "请按提示完成后续验证。"}</span></section>
              <div className="prompt-block probe-prompt"><small>独立验证题</small><p>{runEvidence.continuation.verification.prompt}</p></div>
              <label className="answer-field"><span>你的答案</span><select value={phaseAnswer} onChange={(event) => setPhaseAnswer(event.target.value)}><option value="">请选择</option><option value="A">A · 12%</option><option value="B">B · 13%</option><option value="C">C · 15%</option><option value="D">D · 115%</option></select></label>
              <label className="answer-field"><span>作答信心</span><select value={phaseConfidence} onChange={(event) => setPhaseConfidence(event.target.value)}><option value="">请选择</option><option value="low">不太确定</option><option value="medium">基本确定</option><option value="high">非常确定</option></select></label>
              <button className="button primary panel-primary" disabled={!phaseAnswer || !phaseConfidence} onClick={() => submitContinuation("verification")}>提交独立验证</button>
            </div>
          )}
          {toolStage === "done" && (
            <div className="completion-state" role="status">
              <CheckCircle size={22} weight="fill" />
              <h3>演示作答已记录</h3>
              <p>这条演示记录没有写入本机，也不会形成错因或掌握度判断。</p>
              <button className="button primary" onClick={() => { setAnswer(""); setToolStage("active"); }}>继续下一题</button>
              <button className="button text-button" onClick={closeTool}>结束本轮</button>
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
                <div><dt>掌握变化</dt><dd>{Number(runEvidence.continuation?.mastery_update?.mastery_delta) >= 0 ? "+" : ""}{Number(runEvidence.continuation?.mastery_update?.mastery_delta || 0).toFixed(3)}</dd></div>
                <div><dt>轨迹校验</dt><dd>{traceVerified ? "已通过" : "未通过"}</dd></div>
                <div><dt>轨迹 / 回放</dt><dd>{runEvidence.trace.event_count} 个事件 · {runEvidence.replay.frame_count} 帧</dd></div>
              </dl>
              {candidates.length > 0 && (
                <div className="candidate-list">
                  <strong>候选线索（未确认）</strong>
                  {candidates.map((candidate) => (
                    <span key={candidate.cause_id}>
                      {diagnosisCandidateCopy(candidate)}
                      <small>{diagnosisCandidateProbability(candidate)}</small>
                    </span>
                  ))}
                  <p>这些候选只解释当前诊断路由，不能作为已确认原因。</p>
                </div>
              )}
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

function MasteryTrack({ level, state }) {
  const widths = {
    1: [8, 7, 85],
    2: [6, 40, 54],
    3: [4, 69, 27],
    4: [2, 88, 10],
  }[level] || [0, 0, 100];

  return (
    <div className="mastery-wrap" aria-label={`当前判断：${state}`}>
      <div className="mastery-track">
        <span className="mastery-caution" style={{ width: `${widths[0]}%` }} />
        <span className="mastery-confirmed" style={{ width: `${widths[1]}%` }} />
        <span className="mastery-unseen" style={{ width: `${widths[2]}%` }} />
      </div>
      <div className="mastery-copy"><strong>{state}</strong><span>{level < 2 ? "需要独立复验" : level < 3 ? "仍需跨题验证" : "近期表现稳定"}</span></div>
    </div>
  );
}

function ReportsScreen({ setPage, sidecar }) {
  const [tab, setTab] = useState("skills");
  const [subject, setSubject] = useState("xingce");
  const [module, setModule] = useState("all");
  const [judgment, setJudgment] = useState("all");
  const [dueOnly, setDueOnly] = useState(false);
  const [openGroups, setOpenGroups] = useState(["data"]);
  const [openSkill, setOpenSkill] = useState(null);
  const usingLiveReport = sidecar.phase === "connected";
  const sourceGroups = useMemo(
    () => usingLiveReport ? reportGroupsFromSidecar(sidecar.report) : SKILL_GROUPS,
    [sidecar.report, usingLiveReport],
  );

  const groups = useMemo(() => {
    if (subject !== "xingce") return [];
    return sourceGroups
      .filter((group) => module === "all" || group.id === module)
      .map((group) => ({
        ...group,
        skills: group.skills.filter((skill) => {
          const judgmentMatch = judgment === "all" || (judgment === "verify" ? skill.level === 1 : judgment === "learning" ? skill.level === 2 : skill.level >= 3);
          return judgmentMatch && (!dueOnly || skill.due);
        }),
      }))
      .filter((group) => group.skills.length > 0);
  }, [subject, module, judgment, dueOnly, sourceGroups]);

  const totals = useMemo(() => groups.reduce((result, group) => ({
    modules: result.modules + 1,
    skills: result.skills + group.skills.length,
    attempts: result.attempts + group.skills.reduce((sum, skill) => sum + skill.attempts, 0),
  }), { modules: 0, skills: 0, attempts: 0 }), [groups]);

  const clearFilters = () => {
    setSubject("xingce");
    setModule("all");
    setJudgment("all");
    setDueOnly(false);
  };

  return (
    <div className="screen reports-screen">
      <div className="page-heading"><h1>技能报告</h1></div>
      <div className="sub-tabs" role="tablist" aria-label="报告类型">
        <button className={tab === "activity" ? "active" : ""} onClick={() => setTab("activity")} role="tab" aria-selected={tab === "activity"}>学习活动</button>
        <button className={tab === "skills" ? "active" : ""} onClick={() => setTab("skills")} role="tab" aria-selected={tab === "skills"}>技能掌握</button>
        <button className={tab === "reviews" ? "active" : ""} onClick={() => setTab("reviews")} role="tab" aria-selected={tab === "reviews"}>复习记录</button>
      </div>

      {tab === "skills" && (
        <>
          <p className="report-note" data-testid="report-source" data-source={usingLiveReport ? "sidecar" : "demo"}>掌握判断只使用已评分作答和复验记录；证据不足时显示“暂不判断”。{usingLiveReport ? " 数据源：本机服务。" : " 当前显示演示数据。"}</p>
          <div className="report-filters">
            <select value={subject} onChange={(event) => setSubject(event.target.value)} aria-label="科目"><option value="xingce">行测</option><option value="shenlun">申论</option><option value="interview">面试</option></select>
            <select value={module} onChange={(event) => setModule(event.target.value)} aria-label="模块" disabled={subject !== "xingce"}><option value="all">全部模块</option><option value="verbal">言语理解</option><option value="data">资料分析</option><option value="judgment">判断推理</option></select>
            <select value={judgment} onChange={(event) => setJudgment(event.target.value)} aria-label="当前判断" disabled={subject !== "xingce"}><option value="all">全部判断</option><option value="verify">待验证</option><option value="learning">学习中</option><option value="stable">基本稳定</option></select>
            <label className="check-label"><input type="checkbox" checked={dueOnly} onChange={(event) => setDueOnly(event.target.checked)} disabled={subject !== "xingce"} /> 只看已到复习时间</label>
          </div>

          {groups.length > 0 ? (
            <>
              <div className="report-summary"><strong>{subject === "xingce" ? "行测" : "当前科目"}</strong><span>{totals.modules} 个有记录模块 · {totals.skills} 个技能 · {totals.attempts} {usingLiveReport ? "次本机运行" : "次已评分作答"}</span></div>
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
                          <div className="skills-head"><span>技能</span><span>当前判断</span><span>作答记录</span></div>
                          {group.skills.map((skill) => {
                            const detailOpen = openSkill === skill.id;
                            return (
                              <div className="skill-entry" key={skill.id}>
                                <button className="skill-row" onClick={() => setOpenSkill(detailOpen ? null : skill.id)} aria-expanded={detailOpen}>
                                  <span className="skill-name">{detailOpen ? <CaretDown size={12} /> : <CaretRight size={12} />}<span>{skill.name}</span></span>
                                  <MasteryTrack level={skill.level} state={skill.state} />
                                  <span className="evidence-count"><strong>{skill.attempts}</strong> 次<br /><small>最近 {skill.last}</small></span>
                                </button>
                                {detailOpen && (
                                  <div className="skill-detail">
                                    <div><small>判断依据</small><p>{skill.live ? `来自 ${skill.live.run_count} 次本机运行；最新不确定性 ${Number(skill.live.latest_uncertainty || 0).toFixed(2)}。这里只报告轨迹结果，不确认具体错因。` : skill.id === "base-value" ? "最近 3 次中有 2 次公式方向相反；这只能说明存在混淆迹象，尚未确认原因。" : "根据最近的独立作答与间隔复验记录形成当前判断。"}</p></div>
                                    <div><small>{skill.live ? "轨迹变化" : "下一步"}</small><p>{skill.live ? `单次轨迹值 ${Number(skill.live.latest_mastery || 0).toFixed(2)} · 平均变化 ${Number(skill.live.average_mastery_delta || 0) >= 0 ? "+" : ""}${Number(skill.live.average_mastery_delta || 0).toFixed(3)}` : skill.level === 1 ? "4 道无提示短题" : "按到期时间安排跨题复验"}</p></div>
                                    <div className="skill-detail-actions"><button className="text-link">查看作答记录</button><button className="button compact secondary" onClick={() => setPage("tools")}>安排验证</button></div>
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
            <div className="empty-state report-empty"><strong>{usingLiveReport && subject === "xingce" && module === "all" && judgment === "all" && !dueOnly ? "本机服务还没有技能轨迹" : "当前筛选下没有技能记录"}</strong><p>{usingLiveReport && subject === "xingce" && module === "all" && judgment === "all" && !dueOnly ? "完成一次本机验证后，轨迹汇总会显示在这里。" : subject === "xingce" ? "可以清除筛选后查看全部已记录技能。" : "完成首组独立作答后，才会显示掌握判断。"}</p>{!(usingLiveReport && subject === "xingce" && module === "all" && judgment === "all" && !dueOnly) && <button className="button secondary" onClick={clearFilters}>清除筛选</button>}</div>
          )}
        </>
      )}

      {tab === "activity" && (
        <ReportList title="最近学习活动" description="以下记录来自本机已完成并评分的任务。" headers={["时间", "活动", "结果", "状态"]} rows={ACTIVITY_ROWS} />
      )}

      {tab === "reviews" && (
        <ReportList title="复习安排" description="复习时间由最近一次独立作答和既往间隔共同决定。" headers={["时间", "技能", "安排依据", "状态"]} rows={REVIEW_ROWS} />
      )}
    </div>
  );
}

function ReportList({ title, description, headers, rows }) {
  return (
    <section className="report-list-section">
      <div className="report-list-heading"><h2>{title}</h2><p>{description}</p></div>
      <div className="report-list">
        <div className="report-list-row head">{headers.map((header) => <span key={header}>{header}</span>)}</div>
        {rows.map((row) => <div className="report-list-row" key={row[0] + row[1]}>{row.map((cell) => <span key={cell}>{cell}</span>)}</div>)}
      </div>
    </section>
  );
}

function AuxiliaryScreen({ page, setPage }) {
  if (page === "practice") {
    return (
      <div className="screen auxiliary-screen">
        <div className="page-heading"><h1>练习任务</h1><p>按日期查看已安排、进行中和已完成的任务。</p></div>
        <div className="aux-list">
          <div className="aux-row head"><span>任务</span><span>科目</span><span>时间</span><span>状态</span></div>
          <button className="aux-row" onClick={() => setPage("overview")}><span>基期量 · 公式方向验证</span><span>行测</span><span>今天 · 12 分钟</span><span>未开始</span></button>
          <button className="aux-row" onClick={() => setPage("tools")}><span>概括归纳 · 要点复盘</span><span>申论</span><span>今天 · 20 分钟</span><span>未开始</span></button>
        </div>
      </div>
    );
  }

  return (
    <div className="screen auxiliary-screen">
      <div className="page-heading"><h1>学习资料</h1><p>保存的方法、公式和个人笔记会显示在这里。</p></div>
      <div className="empty-state auxiliary-empty"><ClipboardText size={23} /><strong>还没有保存的学习资料</strong><p>完成一次复盘后，可以把确认过的方法保存到这里。</p><button className="button secondary" onClick={() => setPage("tools")}>查看复盘工具</button></div>
    </div>
  );
}

function CommandPalette({ onClose, setPage, onOpenTool }) {
  const [query, setQuery] = useState("");
  const items = [
    { label: "今日学习", meta: "页面", action: () => setPage("overview") },
    { label: "增长率与基期量", meta: "技能", action: () => setPage("reports") },
    { label: "错因辨析", meta: "训练工具", action: () => onOpenTool("错因辨析") },
    { label: "7 月 10 日作答记录", meta: "学习记录", action: () => setPage("reports") },
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

function TaskPanel({ taskStatus, setTaskStatus, onClose }) {
  return (
    <SidePanel title="基期量 · 公式方向验证" eyebrow="今日任务 · 12 分钟" onClose={onClose}>
      <p className="panel-intro">用 4 道无提示短题检查公式方向是否稳定。结果只记录事实，不提前确认错因。</p>
      <dl className="task-facts"><div><dt>科目</dt><dd>行测 · 资料分析</dd></div><div><dt>依据</dt><dd>近 3 次中有 2 次方向相反</dd></div><div><dt>记录</dt><dd>保存在此 Mac</dd></div></dl>
      {taskStatus === "ready" && <button className="button primary panel-primary" onClick={() => setTaskStatus("in_progress")}>开始计时</button>}
      {taskStatus === "in_progress" && <><div className="in-progress-note"><span className="state-marker" />任务进行中 · 已记录 1 题</div><button className="button primary panel-primary" onClick={() => setTaskStatus("complete")}>完成本次验证</button></>}
      {taskStatus === "complete" && <div className="completion-state"><CheckCircle size={22} weight="fill" /><h3>本次任务已完成</h3><p>4 道作答已写入本机记录。新的判断将在技能报告中显示。</p><button className="button primary" onClick={onClose}>返回总览</button></div>}
    </SidePanel>
  );
}

function UtilityPanel({ type, onClose }) {
  const content = {
    settings: ["设置", "学习记录默认保存在此 Mac。云端能力尚未启用。"],
    feedback: ["意见反馈", "可以记录遇到的问题；当前原型不会发送到外部服务。"],
    help: ["使用帮助", "从今日任务开始练习，在技能报告中查看作答依据与复验安排。"],
    profile: ["林同学", "本机学习档案 · 广东省考"],
    records: ["作答记录", "最近 3 次“基期量”作答中，有 2 次公式方向相反。当前仅作为待确认迹象。"],
  }[type];
  return (
    <SidePanel title={content[0]} onClose={onClose}>
      <p className="panel-intro">{content[1]}</p>
      {type === "settings" && <div className="setting-row"><span><strong>本机记录</strong><small>练习、评分与复验安排</small></span><span className="plain-state">已开启</span></div>}
      {type === "feedback" && <label className="answer-field"><span>反馈内容</span><textarea placeholder="请描述具体页面和问题" /></label>}
      {type === "records" && <div className="record-list"><div><span>7 月 10 日</span><strong>108 ÷ (1 − 8%)</strong><small>公式方向相反</small></div><div><span>7 月 8 日</span><strong>104 ÷ (1 + 4%)</strong><small>方向正确</small></div><div><span>7 月 6 日</span><strong>96 × (1 + 6%)</strong><small>公式方向相反</small></div></div>}
    </SidePanel>
  );
}

export function App() {
  const [page, setPage] = useState("overview");
  const [scope, setScope] = useState("行测备考");
  const [collapsed, setCollapsed] = useState(false);
  const [taskStatus, setTaskStatus] = useState("ready");
  const [taskPanelOpen, setTaskPanelOpen] = useState(false);
  const [favorites, setFavorites] = useState(["间隔复习"]);
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
    setSelectedTool(tool || null);
    setToolStage("ready");
  };

  return (
    <main className="desktop-canvas">
      <div className={collapsed ? "app-window sidebar-collapsed" : "app-window"}>
        <Sidebar page={page} setPage={setPage} collapsed={collapsed} setCollapsed={setCollapsed} onUtility={setUtility} sidecar={sidecar} onRetrySidecar={refreshSidecar} />
        <section className="app-main">
          {page !== "tools" && <Topbar page={page} setPage={setPage} scope={scope} setScope={setScope} onSearch={() => setCommandOpen(true)} onUtility={setUtility} />}
          {page === "overview" && <Overview setPage={setPage} taskStatus={taskStatus} onOpenTask={() => setTaskPanelOpen(true)} onOpenTool={openToolByTitle} onOpenRecords={() => setUtility("records")} />}
          {page === "tools" && <ToolsScreen favorites={favorites} setFavorites={setFavorites} selectedTool={selectedTool} setSelectedTool={setSelectedTool} toolStage={toolStage} setToolStage={setToolStage} sidecar={sidecar} onRefreshSkills={refreshSkills} setPage={setPage} />}
          {page === "reports" && <ReportsScreen setPage={setPage} sidecar={sidecar} />}
          {(page === "practice" || page === "materials") && <AuxiliaryScreen page={page} setPage={setPage} />}
        </section>

        {taskPanelOpen && <TaskPanel taskStatus={taskStatus} setTaskStatus={setTaskStatus} onClose={() => setTaskPanelOpen(false)} />}
        {commandOpen && <CommandPalette onClose={() => setCommandOpen(false)} setPage={setPage} onOpenTool={openToolByTitle} />}
        {utility && <UtilityPanel type={utility} onClose={() => setUtility(null)} />}
      </div>
    </main>
  );
}
