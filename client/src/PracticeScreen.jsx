import { useEffect, useMemo, useState } from "react";
import {
  ArrowRight,
  ChartBar,
  CalendarCheck,
  CheckCircle,
  ClipboardText,
  Clock,
  Info,
  LockKey,
  MagnifyingGlass,
  Plus,
  Trash,
  X,
} from "@phosphor-icons/react";
import {
  continueAttempt,
  endSmartPracticeSession,
  fetchLesson,
  fetchPracticeOverview,
  fetchPracticeProfile,
  startSmartPracticeSession,
  submitAttempt,
  submitSmartPracticeAnswer,
  submitSmartPracticeProbe,
  fetchWrongQuestionBook,
} from "./hermesApi";
import { LessonWorkspace } from "./LessonWorkspace";
import { lessonCompletionKey } from "./lessonProgress";
import {
  DEFAULT_SMART_PRACTICE_SCOPE_ID,
  getSmartPracticeScope,
  SMART_PRACTICE_SCOPES,
  SMART_PRACTICE_SCOPE_TARGET,
} from "./practiceScopes";
import { SmartPracticeWorkspace } from "./SmartPracticeWorkspace";

const PLAN_STORAGE_KEY = "lumi.practice-plan.v1";
const COMPLETE_STORAGE_KEY = "lumi.practice-completed.v1";
const LESSON_COMPLETE_STORAGE_KEY = "lumi.lesson-completed.v1";
const CONFIDENCE_VALUES = { low: 0.35, medium: 0.65, high: 0.9 };

const DOMAIN_COPY = {
  xingce: { label: "行测", order: 0 },
  shenlun: { label: "申论", order: 1 },
  interview: { label: "面试", order: 2 },
};

const PATH_COPY = {
  verbal: "言语理解",
  judgment: "判断推理",
  quantitative: "数量关系",
  data_analysis: "资料分析",
  common_sense: "常识判断",
  common_political_knowledge: "常识判断",
  summary: "归纳概括",
  analysis: "综合分析",
  countermeasure: "提出对策",
  official_writing: "公文写作",
  essay: "文章写作",
  comprehensive_analysis: "综合分析",
  organization: "组织管理",
  interpersonal: "人际沟通",
  emergency: "应急应变",
};

function readStoredList(key) {
  try {
    const value = window.localStorage.getItem(key);
    if (value === null) return null;
    const parsed = JSON.parse(value);
    return Array.isArray(parsed) ? parsed.filter((item) => typeof item === "string") : null;
  } catch {
    return null;
  }
}

function writeStoredList(key, value) {
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // The practice flow remains usable when localStorage is unavailable.
  }
}

function estimatedMinutes(item) {
  if (item.domain === "interview") return 15;
  if (item.domain === "shenlun") return item.path === "essay" ? 30 : 20;
  return 8;
}

function defaultPlan(items) {
  return ["data_analysis", "verbal", "judgment"]
    .map((path) => items.find((item) => item.path === path)?.fixture_id)
    .filter(Boolean);
}

function PracticePanel({ item, onClose, onCompleted, onRefreshSkills }) {
  const [stage, setStage] = useState("question");
  const [answer, setAnswer] = useState("");
  const [confidence, setConfidence] = useState("");
  const [startedAt, setStartedAt] = useState(Date.now());
  const [session, setSession] = useState(null);
  const [error, setError] = useState(null);

  const submitInitial = async () => {
    setStage("submitting");
    setError(null);
    try {
      const result = await submitAttempt({
        fixtureId: item.fixture_id,
        response: answer,
        confidence: CONFIDENCE_VALUES[confidence],
        responseTimeSeconds: (Date.now() - startedAt) / 1000,
      });
      setSession(result);
      setAnswer("");
      setConfidence("");
      setStartedAt(Date.now());
      setStage("probe");
    } catch (nextError) {
      setError(nextError);
      setStage("error");
    }
  };

  const submitPhase = async (phase) => {
    setStage("submitting");
    setError(null);
    try {
      const current = phase === "probe" ? session?.attempt : session?.continuation;
      const result = await continueAttempt({
        session: current,
        phase,
        response: answer,
        confidence: CONFIDENCE_VALUES[confidence],
        responseTimeSeconds: (Date.now() - startedAt) / 1000,
      });
      const nextSession = { ...session, ...result };
      setSession(nextSession);
      setAnswer("");
      setConfidence("");
      setStartedAt(Date.now());
      if (phase === "probe") {
        setStage("verification");
      } else {
        setStage("result");
        onCompleted(item.fixture_id);
        await onRefreshSkills();
      }
    } catch (nextError) {
      setError(nextError);
      setStage("error");
    }
  };

  const activePrompt = stage === "probe"
    ? session?.attempt?.probe?.prompt
    : stage === "verification"
      ? session?.continuation?.verification?.prompt
      : item.prompt;
  const activeOptions = stage === "question"
    ? item.options
    : stage === "verification"
      ? session?.continuation?.verification?.options
      : {};
  const canSubmit = answer.trim() && confidence;

  return (
    <div className="panel-scrim" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <aside className="side-panel practice-panel" role="dialog" aria-modal="true" aria-label={item.title}>
        <header className="panel-header">
          <div><small>{DOMAIN_COPY[item.domain]?.label} · {PATH_COPY[item.path] || item.path}</small><h2>{item.title}</h2></div>
          <button className="icon-button panel-close" onClick={onClose} aria-label="关闭"><X size={16} /></button>
        </header>
        <div className="panel-body">
          {stage === "submitting" && (
            <div className="practice-waiting" role="status"><span className="practice-spinner" /><strong>正在核对并保存</strong><p>本次作答只写入此 Mac。</p></div>
          )}

          {["question", "probe", "verification"].includes(stage) && (
            <>
              <div className="practice-step">
                <span>{stage === "question" ? "先自己做" : stage === "probe" ? "关键一步" : "换一道新题"}</span>
                <small><Clock size={12} />建议 {estimatedMinutes(item)} 分钟</small>
              </div>
              {stage === "verification" && session?.continuation?.teaching?.prompt && (
                <section className="practice-teaching"><small>针对性提示</small><p>{session.continuation.teaching.prompt}</p></section>
              )}
              <section className="practice-question">
                <small>{stage === "probe" ? "请写出判断依据" : "题目"}</small>
                <p>{activePrompt}</p>
              </section>
              {activeOptions && Object.keys(activeOptions).length > 0 ? (
                <fieldset className="practice-options">
                  <legend>请选择一个答案</legend>
                  {Object.entries(activeOptions).map(([key, value]) => (
                    <label className={answer === key ? "selected" : ""} key={key}>
                      <input type="radio" name="practice-answer" value={key} checked={answer === key} onChange={(event) => setAnswer(event.target.value)} />
                      <strong>{key}</strong><span>{value}</span>
                    </label>
                  ))}
                </fieldset>
              ) : (
                <label className="answer-field practice-answer"><span>你的回答</span><textarea value={answer} onChange={(event) => setAnswer(event.target.value)} placeholder={item.response_mode === "spoken_text" ? "输入口述回答文本" : "写下答案与必要依据"} /></label>
              )}
              <label className="answer-field"><span>作答信心</span><select value={confidence} onChange={(event) => setConfidence(event.target.value)}><option value="">请选择</option><option value="low">不太确定</option><option value="medium">基本确定</option><option value="high">非常确定</option></select></label>
              <button className="button primary panel-primary" disabled={!canSubmit} onClick={stage === "question" ? submitInitial : () => submitPhase(stage)}>{stage === "verification" ? "提交并完成" : "提交并继续"}</button>
              <p className="practice-privacy"><Info size={12} />作答与验证轨迹保存在本机；未验证的推断不会作为事实显示。</p>
            </>
          )}

          {stage === "result" && (
            <div className="practice-result" role="status">
              <CheckCircle size={28} weight="fill" />
              <h3>本次练习已完成</h3>
              <p>{session?.continuation?.verification?.effective ? "独立验证通过，证据已写入技能报告。" : "独立验证尚未通过，Lumi 已保留证据供后续安排。"}</p>
              <dl>
                <div><dt>首答</dt><dd>{session?.attempt?.score?.passed ? "通过" : "未通过"}</dd></div>
                <div><dt>新题验证</dt><dd>{session?.continuation?.verification?.effective ? "通过" : "待加强"}</dd></div>
                <div><dt>学习记录</dt><dd>已保存</dd></div>
              </dl>
              <button className="button primary panel-primary" onClick={onClose}>返回今日计划</button>
            </div>
          )}

          {stage === "error" && (
            <div className="practice-error" role="alert">
              <Info size={24} />
              <h3>这次作答还没有保存</h3>
              <p>{error?.message || "本机服务暂时无法处理本次作答。"}</p>
              <button className="button primary panel-primary" onClick={() => setStage(session?.continuation ? "verification" : session?.attempt ? "probe" : "question")}>返回重试</button>
            </div>
          )}
        </div>
      </aside>
    </div>
  );
}

function LegacyPracticeScreen({ sidecar, onRetrySidecar, onRefreshSkills }) {
  const items = sidecar.catalog?.items || [];
  const lessonItems = sidecar.lessons?.items || [];
  const [planIds, setPlanIds] = useState(() => readStoredList(PLAN_STORAGE_KEY));
  const [completedIds, setCompletedIds] = useState(() => readStoredList(COMPLETE_STORAGE_KEY) || []);
  const [completedLessonIds, setCompletedLessonIds] = useState(() => readStoredList(LESSON_COMPLETE_STORAGE_KEY) || []);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState(null);
  const [selectedLesson, setSelectedLesson] = useState(null);
  const [lessonLoadingId, setLessonLoadingId] = useState("");
  const [lessonError, setLessonError] = useState(null);

  useEffect(() => {
    if (planIds === null && items.length > 0) {
      const next = defaultPlan(items);
      setPlanIds(next);
      writeStoredList(PLAN_STORAGE_KEY, next);
    }
  }, [items, planIds]);

  const validPlanIds = (planIds || []).filter((id) => items.some((item) => item.fixture_id === id));
  const planItems = validPlanIds.map((id) => items.find((item) => item.fixture_id === id)).filter(Boolean);
  const visibleItems = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase("zh-CN");
    return items
      .filter((item) => !normalized || `${item.title}${item.module}${item.prompt}`.toLocaleLowerCase("zh-CN").includes(normalized))
      .sort((a, b) => (DOMAIN_COPY[a.domain]?.order || 0) - (DOMAIN_COPY[b.domain]?.order || 0));
  }, [items, query]);

  const savePlan = (next) => {
    setPlanIds(next);
    writeStoredList(PLAN_STORAGE_KEY, next);
  };
  const togglePlan = (id) => {
    const current = planIds || [];
    savePlan(current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);
  };
  const markCompleted = (id) => {
    const next = [...new Set([...completedIds, id])];
    setCompletedIds(next);
    writeStoredList(COMPLETE_STORAGE_KEY, next);
  };

  const openLesson = async (summary) => {
    setLessonLoadingId(summary.lesson_id);
    setLessonError(null);
    try {
      setSelectedLesson(await fetchLesson(summary.lesson_id));
    } catch (error) {
      setLessonError(error);
    } finally {
      setLessonLoadingId("");
    }
  };

  const markLessonCompleted = (lesson) => {
    const completionKey = lessonCompletionKey(lesson);
    if (!completionKey) return;
    const next = [...new Set([...completedLessonIds, completionKey])];
    setCompletedLessonIds(next);
    writeStoredList(LESSON_COMPLETE_STORAGE_KEY, next);
  };

  if (sidecar.phase !== "connected") {
    return (
      <div className="screen practice-screen">
        <div className="page-heading"><h1>行测练习</h1><p>题目、作答与学习计划保存在此 Mac。</p></div>
        <div className="practice-offline">
          <Info size={26} />
          <h2>{sidecar.phase === "checking" ? "正在读取本机题目" : "本机题目服务未连接"}</h2>
          <p>{sidecar.phase === "checking" ? "首次启动通常只需片刻。" : "连接恢复后，题目和今天的计划会自动显示；不会请求云端。"}</p>
          {sidecar.phase !== "checking" && <button className="button primary" onClick={onRetrySidecar}>重新连接</button>}
        </div>
      </div>
    );
  }

  const completedCount = planItems.filter((item) => completedIds.includes(item.fixture_id)).length;
  return (
    <div className="screen practice-screen">
      <div className="page-heading practice-heading"><div><span className="eyebrow">{new Intl.DateTimeFormat("zh-CN", { month: "long", day: "numeric", weekday: "long" }).format(new Date())}</span><h1>行测练习</h1><p>先完成今天的短计划，也可以从五大模块自由选题。</p></div><div className="practice-summary"><strong>{completedCount} / {planItems.length}</strong><span>今日完成</span></div></div>

      {lessonItems.length > 0 && (
        <section className="lesson-entry-section" aria-labelledby="lesson-entry-title">
          <div className="practice-section-title">
            <div><span><strong id="lesson-entry-title">先学一个方法</strong><small>短方法卡 · 原创例题 · 真实迁移题</small></span></div>
          </div>
          <div className="lesson-entry-list">
            {lessonItems.map((lesson) => {
              const complete = completedLessonIds.includes(lessonCompletionKey(lesson));
              const loading = lessonLoadingId === lesson.lesson_id;
              return (
                <article className="lesson-entry" key={lesson.lesson_id}>
                  <div>
                    <small>资料分析 · {lesson.estimated_minutes} 分钟</small>
                    <strong>{lesson.title}</strong>
                    <p>{lesson.practice_count} 组循序练习，完成后用新题验证。</p>
                  </div>
                  {complete && <span className="lesson-entry-complete"><CheckCircle size={13} weight="fill" />已完成</span>}
                  <button className="button primary compact" disabled={Boolean(lessonLoadingId)} onClick={() => openLesson(lesson)}>{loading ? "正在打开…" : complete ? "再学一次" : "开始学习"}</button>
                </article>
              );
            })}
          </div>
          {lessonError && <p className="lesson-entry-error" role="alert">{lessonError.message || "教程暂时无法打开，请稍后重试。"}</p>}
        </section>
      )}

      <section className="today-plan">
        <div className="practice-section-title"><div><CalendarCheck size={17} /><span><strong>今日计划</strong><small>可调整 · 仅保存在此 Mac</small></span></div><em>{planItems.reduce((total, item) => total + estimatedMinutes(item), 0)} 分钟</em></div>
        {planItems.length > 0 ? (
          <div className="plan-list">
            {planItems.map((item, index) => {
              const complete = completedIds.includes(item.fixture_id);
              return (
                <div className="plan-item" key={item.fixture_id}>
                  <span className={complete ? "plan-index complete" : "plan-index"}>{complete ? <CheckCircle size={16} weight="fill" /> : index + 1}</span>
                  <button className="plan-main" onClick={() => setSelected(item)}><small>{DOMAIN_COPY[item.domain]?.label} · {PATH_COPY[item.path] || item.path}</small><strong>{item.title}</strong><span>{item.prompt}</span></button>
                  <span className="plan-time">{estimatedMinutes(item)} 分钟</span>
                  <button className="icon-button plan-remove" onClick={() => togglePlan(item.fixture_id)} aria-label={`从计划移除${item.title}`}><Trash size={14} /></button>
                  <button className="button secondary compact" onClick={() => setSelected(item)}>{complete ? "再练一次" : "开始"}</button>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="plan-empty"><strong>今天还没有安排</strong><span>从下面的本机题库加入一项即可开始。</span></div>
        )}
      </section>

      <section className="question-bank">
        <div className="practice-section-title"><div><span><strong>行测题库</strong><small>{items.length} 道可练题 · 覆盖五大模块</small></span></div></div>
        <div className="bank-controls">
          <div className="filter-tabs" aria-label="题目科目">
            {["言语理解", "判断推理", "数量关系", "资料分析", "常识判断"].map((label) => <span className="module-chip" key={label}>{label}</span>)}
          </div>
          <label className="small-search"><MagnifyingGlass size={14} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索题目" /></label>
        </div>
        <div className="bank-list">
          {visibleItems.map((item) => {
            const planned = validPlanIds.includes(item.fixture_id);
            return (
              <article className="bank-item" key={item.fixture_id}>
                <div><small>{DOMAIN_COPY[item.domain]?.label} · {PATH_COPY[item.path] || item.path}</small><strong>{item.title}</strong><p>{item.prompt}</p></div>
                <span className="bank-duration"><Clock size={12} />{estimatedMinutes(item)} 分钟</span>
                <button className={planned ? "button text-button compact" : "button secondary compact"} onClick={() => togglePlan(item.fixture_id)}>{planned ? "移出计划" : <><Plus size={12} />加入计划</>}</button>
                <button className="bank-start" onClick={() => setSelected(item)} aria-label={`开始${item.title}`}><ArrowRight size={15} /></button>
              </article>
            );
          })}
          {visibleItems.length === 0 && <div className="plan-empty"><strong>没有匹配的题目</strong><span>试试其他科目或关键词。</span></div>}
        </div>
      </section>

      {selected && <PracticePanel item={selected} onClose={() => setSelected(null)} onCompleted={markCompleted} onRefreshSkills={onRefreshSkills} />}
      {selectedLesson && (
        <LessonWorkspace
          lesson={selectedLesson}
          onClose={() => setSelectedLesson(null)}
          onCompleted={() => markLessonCompleted(selectedLesson)}
          onRefreshSkills={onRefreshSkills}
        />
      )}
    </div>
  );
}

function formatAccuracy(value) {
  return typeof value === "number" && Number.isFinite(value)
    ? `${Math.round(value * 100)}%`
    : "暂无证据";
}

function formatResponseTime(value) {
  return typeof value === "number" && Number.isFinite(value)
    ? `${Math.round(value)} 秒`
    : "暂无记录";
}

function practiceReadError(error, kind) {
  const label = kind === "wrong" ? "错题本" : "学习档案";
  if (error?.status === 404) return `当前本机服务版本尚未提供${label}。`;
  if (error?.kind === "contract") return `${label}数据格式暂不兼容，未展示任何替代数据。`;
  return `暂时无法读取${label}；现有刷题记录不会受影响。`;
}

function PracticeInsightsPanel({ kind, onClose }) {
  const [state, setState] = useState({ phase: "loading", data: null, error: "" });
  const isWrongBook = kind === "wrong";

  useEffect(() => {
    let active = true;
    setState({ phase: "loading", data: null, error: "" });
    const loader = isWrongBook ? fetchWrongQuestionBook : fetchPracticeProfile;
    loader()
      .then((data) => active && setState({ phase: "ready", data, error: "" }))
      .catch((error) => active && setState({
        phase: "error",
        data: null,
        error: practiceReadError(error, kind),
      }));
    return () => { active = false; };
  }, [isWrongBook, kind]);

  const title = isWrongBook ? "错题本" : "学习档案";
  const wrongItems = isWrongBook ? state.data?.items || [] : [];
  const profile = !isWrongBook ? state.data : null;

  return (
    <div className="panel-scrim" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <aside className="side-panel smart-practice-insight-panel" role="dialog" aria-modal="true" aria-label={title}>
        <header className="panel-header">
          <div><small>行测 · 本机学习记录</small><h2>{title}</h2></div>
          <button type="button" className="icon-button panel-close" onClick={onClose} aria-label="关闭"><X size={16} /></button>
        </header>
        <div className="panel-body">
          {state.phase === "loading" && (
            <div className="practice-waiting" role="status">
              <span className="practice-spinner" />
              <strong>正在读取{title}</strong>
              <p>只读取保存在此 Mac 的作答证据。</p>
            </div>
          )}

          {state.phase === "error" && (
            <div className="practice-offline smart-practice-read-error" role="alert">
              <Info size={24} />
              <h3>没有显示记录</h3>
              <p>{state.error}</p>
            </div>
          )}

          {state.phase === "ready" && isWrongBook && (
            <>
              <p className="smart-practice-insight-intro">这里只收录真实答错且仍需复习的题目；解析默认折叠。</p>
              {wrongItems.length > 0 ? (
                <div className="smart-practice-book-list">
                  {wrongItems.map((item) => (
                    <details key={`${item.id}-${item.questionVersionId}`}>
                      <summary>
                        <span><small>{item.moduleLabel}</small><strong>{item.prompt}</strong></span>
                        <em>{item.wrongAttempts} 次答错</em>
                      </summary>
                      <div>
                        <p>最近答案：{item.lastSelectedOption || "未记录"}</p>
                        {item.correctOption && <p>正确答案：{item.correctOption}</p>}
                        {item.keyPrinciple && <p><strong>关键点：</strong>{item.keyPrinciple}</p>}
                        {item.explanation && <p><strong>解析：</strong>{item.explanation}</p>}
                        <small>独立题位答错 {item.independentWrongAttempts} 次 · 版本 {item.questionVersionId}</small>
                      </div>
                    </details>
                  ))}
                </div>
              ) : (
                <div className="smart-practice-record-empty">
                  <CheckCircle size={25} />
                  <strong>暂无待复习错题</strong>
                  <p>完成练习并出现真实错题后，这里才会显示记录。</p>
                </div>
              )}
            </>
          )}

          {state.phase === "ready" && profile && (
            <>
              <p className="smart-practice-insight-intro">正确率和速度只在存在对应作答记录时展示，不用空数据补零。</p>
              <dl className="smart-practice-profile-overall">
                <div><dt>已判分作答</dt><dd>{profile.overall.scored_attempt_count}</dd></div>
                <div><dt>整体正确率</dt><dd>{formatAccuracy(profile.overall.accuracy)}</dd></div>
                <div><dt>平均作答时间</dt><dd>{formatResponseTime(profile.overall.average_response_time_seconds)}</dd></div>
              </dl>
              <section className="smart-practice-profile-modules" aria-labelledby="smart-practice-profile-modules-title">
                <h3 id="smart-practice-profile-modules-title">四模块记录</h3>
                {profile.modules.map((module) => (
                  <div key={module.module_id}>
                    <span><strong>{module.module_label}</strong><small>{module.facts.attempt_count} 次作答</small></span>
                    <span><strong>{formatAccuracy(module.facts.accuracy)}</strong><small>正确率</small></span>
                  </div>
                ))}
              </section>
              {profile.overall.scored_attempt_count === 0 && (
                <div className="smart-practice-record-empty compact">
                  <strong>暂无可汇总的作答证据</strong>
                  <p>完成第一组练习后再查看即可。</p>
                </div>
              )}
            </>
          )}
        </div>
      </aside>
    </div>
  );
}

export function PracticeScreen({ sidecar, onRetrySidecar, onRefreshSkills }) {
  const [workspaceOpen, setWorkspaceOpen] = useState(false);
  const [closeError, setCloseError] = useState("");
  const [selectedScopeId, setSelectedScopeId] = useState(DEFAULT_SMART_PRACTICE_SCOPE_ID);
  const [insightKind, setInsightKind] = useState("");
  const [overviewState, setOverviewState] = useState({ phase: "idle", data: null, error: "" });
  const selectedScope = getSmartPracticeScope(selectedScopeId);
  const moduleScopes = SMART_PRACTICE_SCOPES.filter((scope) => !scope.mixed);
  const mixedScope = SMART_PRACTICE_SCOPES.find((scope) => scope.mixed);
  const activeSession = overviewState.phase === "ready" ? overviewState.data.activeSession : null;
  const activeScope = activeSession ? getSmartPracticeScope(activeSession.scopeId) : null;
  const entryScope = activeScope || selectedScope;

  useEffect(() => {
    if (sidecar.phase !== "connected") {
      setOverviewState({ phase: "idle", data: null, error: "" });
      return undefined;
    }
    let active = true;
    setOverviewState((current) => ({ ...current, phase: "loading", error: "" }));
    fetchPracticeOverview()
      .then((data) => active && setOverviewState({ phase: "ready", data, error: "" }))
      .catch((error) => active && setOverviewState({
        phase: "error",
        data: null,
        error: practiceReadError(error, "profile"),
      }));
    return () => { active = false; };
  }, [sidecar.phase]);

  useEffect(() => {
    if (activeSession?.scopeId) setSelectedScopeId(activeSession.scopeId);
  }, [activeSession?.scopeId]);

  const refreshPracticeOverview = async () => {
    try {
      const data = await fetchPracticeOverview();
      setOverviewState({ phase: "ready", data, error: "" });
      return data;
    } catch (error) {
      setOverviewState({ phase: "error", data: null, error: practiceReadError(error, "profile") });
      return null;
    }
  };

  const startContinuousSession = async ({ nextGroup = false } = {}) => {
    let scopeId = selectedScope.scopeId;
    if (nextGroup) {
      const overview = await refreshPracticeOverview();
      if (overview?.activeSession?.scopeId) {
        scopeId = overview.activeSession.scopeId;
        setSelectedScopeId(scopeId);
      } else if (overview?.recommendedScopeId) {
        scopeId = overview.recommendedScopeId;
        setSelectedScopeId(scopeId);
      }
    } else {
      const overview = overviewState.phase === "ready"
        ? overviewState.data
        : await refreshPracticeOverview();
      if (overview?.activeSession?.scopeId) {
        scopeId = overview.activeSession.scopeId;
        setSelectedScopeId(scopeId);
      }
    }
    return startSmartPracticeSession({ scopeId });
  };

  const closeSmartPractice = async ({ reason, sessionId } = {}) => {
    setWorkspaceOpen(false);
    setCloseError("");
    try {
      if (sessionId && reason !== "completed") {
        await endSmartPracticeSession({ sessionId, reason: "learner_ended_early" });
      }
      await onRefreshSkills?.();
      await refreshPracticeOverview();
    } catch (error) {
      setCloseError(error?.message || "本组结束状态暂未保存；再次打开时会尝试恢复。");
    }
  };

  if (sidecar.phase !== "connected") {
    return (
      <div className="screen practice-screen smart-practice-page">
        <div className="page-heading"><h1>行测智能刷题</h1><p>题目、决策与作答轨迹只在此 Mac 处理。</p></div>
        <div className="practice-offline">
          <Info size={26} />
          <h2>{sidecar.phase === "checking" ? "正在准备本机题目" : "本机题目服务未连接"}</h2>
          <p>{sidecar.phase === "checking" ? "首次启动通常只需片刻。" : "连接恢复后可以继续上次未完成的 8 题练习；不会请求云端。"}</p>
          {sidecar.phase !== "checking" && <button className="button primary" onClick={onRetrySidecar}>重新连接</button>}
        </div>
      </div>
    );
  }

  return (
    <div className="screen practice-screen smart-practice-page">
      <div className="page-heading practice-heading">
        <div>
          <span className="eyebrow">行测 · 四模块题池</span>
          <h1>行测智能刷题</h1>
          <p>直接做题；系统只在错误模式跨独立题族重复时增加干预。</p>
        </div>
        <span className="smart-practice-local-state"><LockKey size={13} />本机运行</span>
      </div>

      <section className="smart-practice-picker-section" aria-labelledby="smart-practice-picker-title">
        <div className="practice-section-title">
          <div>
            <span>
              <strong id="smart-practice-picker-title">选择本组范围</strong>
              <small>每次仍固定 8 题；切换模块不会增加训练步骤</small>
            </span>
          </div>
        </div>
        <fieldset className="smart-practice-scope-picker" disabled={Boolean(activeSession)}>
          <legend className="sr-only">选择练习模块</legend>
          <div className="smart-practice-module-options">
            {moduleScopes.map((scope) => (
              <label className={selectedScopeId === scope.scopeId ? "selected" : ""} key={scope.scopeId}>
                <input
                  className="sr-only"
                  type="radio"
                  name="smart-practice-scope"
                  value={scope.scopeId}
                  checked={selectedScopeId === scope.scopeId}
                  onChange={(event) => setSelectedScopeId(event.target.value)}
                />
                <span>
                  <strong>{scope.label}</strong>
                  <small>{scope.focus}</small>
                </span>
                <em>{scope.poolSize} 题</em>
              </label>
            ))}
          </div>
          {mixedScope && (
            <label className={`smart-practice-mixed-option ${selectedScopeId === mixedScope.scopeId ? "selected" : ""}`}>
              <input
                className="sr-only"
                type="radio"
                name="smart-practice-scope"
                value={mixedScope.scopeId}
                checked={selectedScopeId === mixedScope.scopeId}
                onChange={(event) => setSelectedScopeId(event.target.value)}
              />
              <span>
                <strong>{mixedScope.label}</strong>
                <small>{mixedScope.focus}，从四个模块的版本化题目中选取</small>
              </span>
              <em>可选</em>
            </label>
          )}
        </fieldset>
      </section>

      <section className="smart-practice-entry" aria-labelledby="smart-practice-entry-title">
        <div className="smart-practice-entry-copy">
          <span>{activeSession ? `未完成本组 · 已答 ${activeSession.answeredCount} / ${activeSession.targetCount}` : `当前选择 · ${entryScope.focus}`}</span>
          <h2 id="smart-practice-entry-title">{activeSession ? `继续${entryScope.label}本组` : `${entryScope.label} · 固定 8 题`}</h2>
          <p>{entryScope.description} 答案是唯一必填项，完整解析按需展开。</p>
          <div className="smart-practice-promises" aria-label="本组练习规则">
            <span><CheckCircle size={13} />只需选择答案</span>
            <span><CheckCircle size={13} />错误重复才讲</span>
            <span><CheckCircle size={13} />可以随时结束</span>
          </div>
        </div>
        <div className="smart-practice-entry-action">
          <strong>{activeSession ? `还剩 ${activeSession.targetCount - activeSession.answeredCount} 个题位` : "约 6–8 分钟"}</strong>
          <small>{activeSession ? "从上次中断处继续，不会新建一组" : entryScope.mixed ? "跨四模块题池按证据规则选取" : `${entryScope.poolSize} 道版本化题目中选取`}</small>
          <button className="button primary" onClick={() => { setCloseError(""); setWorkspaceOpen(true); }}>
            {activeSession ? `继续本组 ${activeSession.answeredCount} / ${activeSession.targetCount}` : `开始${entryScope.label} 8 题`} <ArrowRight size={14} />
          </button>
        </div>
      </section>

      <section className="smart-practice-insight-links" aria-label="学习记录">
        <button type="button" onClick={() => setInsightKind("wrong")}>
          <ClipboardText size={18} />
          <span>
            <strong>错题本</strong>
            <small>
              {overviewState.phase === "loading"
                ? "正在读取本机记录"
                : overviewState.phase === "ready"
                  ? overviewState.data.wrongQuestionPreview.length > 0
                    ? `近期 ${overviewState.data.wrongQuestionPreview.length} 道真实错题`
                    : "暂无待复习错题"
                  : overviewState.phase === "error"
                    ? "暂时无法读取"
                    : "查看待复习错题"}
            </small>
          </span>
          <ArrowRight size={14} />
        </button>
        <button type="button" onClick={() => setInsightKind("profile")}>
          <ChartBar size={18} />
          <span>
            <strong>学习档案</strong>
            <small>
              {overviewState.phase === "loading"
                ? "正在读取本机证据"
                : overviewState.phase === "ready"
                  ? overviewState.data.profile.overall.scored_attempt_count > 0
                    ? `${overviewState.data.profile.overall.scored_attempt_count} 次已判分作答`
                    : "暂无可汇总的作答证据"
                  : overviewState.phase === "error"
                    ? "暂时无法读取"
                    : "查看四模块作答证据"}
            </small>
          </span>
          <ArrowRight size={14} />
        </button>
      </section>

      {overviewState.phase === "error" && (
        <p className="smart-practice-page-error" role="status"><Info size={13} />学习记录暂未显示；刷题功能仍可正常使用。</p>
      )}

      {closeError && <p className="smart-practice-page-error" role="alert"><Info size={13} />{closeError}</p>}

      <section className="smart-practice-scope" aria-labelledby="smart-practice-scope-title">
        <div className="practice-section-title">
          <div><span><strong id="smart-practice-scope-title">版本化内容池</strong><small>四模块共 {SMART_PRACTICE_SCOPE_TARGET * 4} 题；混合练习复用同一题池</small></span></div>
        </div>
        <div className="smart-practice-module-list">
          {moduleScopes.map((scope) => (
            <div className="ready" key={scope.scopeId}>
              <span>{scope.label}</span>
              <strong>{scope.focus}</strong>
              <em>{scope.poolSize} 题</em>
            </div>
          ))}
        </div>
        <p className="smart-practice-scope-note"><Info size={12} />本包题干、数据、选项与解析均为原创内部样本；外部发布仍需人工内容与权利复核。</p>
      </section>

      {workspaceOpen && (
        <SmartPracticeWorkspace
          startSession={startContinuousSession}
          submitAnswer={submitSmartPracticeAnswer}
          submitProbe={submitSmartPracticeProbe}
          close={closeSmartPractice}
        />
      )}
      {insightKind && <PracticeInsightsPanel kind={insightKind} onClose={() => setInsightKind("")} />}
    </div>
  );
}
