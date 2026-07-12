import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowClockwise,
  CaretRight,
  CheckCircle,
  Clock,
  Info,
  ListMagnifyingGlass,
  MapTrifold,
  Receipt,
  SealCheck,
  WarningCircle,
} from "@phosphor-icons/react";
import {
  answerJudgmentProbe,
  answerJudgmentTransfer,
  fetchJudgmentReplay,
  fetchJudgmentWorkspace,
  startJudgmentSession,
} from "./hermesApi.js";
import { createCommandId } from "./publicLearningId.js";
import {
  candidateStatusCopy,
  JUDGMENT_CONFIDENCE_OPTIONS,
  judgmentFormReadiness,
  normalizeJudgmentAnswer,
  normalizeJudgmentConfidence,
  reviewTaskCopy,
  stageProgress,
} from "./judgmentWorkspaceAdapter.js";

const LEARNING_MAP = [
  ["条件方向", "把“只有 / 才 / 除非”译成可检验的方向"],
  ["必要与充分", "区分必要前提与充分条件"],
  ["推理有效性", "识别可推出、不可推出与逆否"],
];

const EMPTY_DRAFT = { selectedOption: "", confidence: "", rationale: "" };

function optionEntries(record) {
  if (Array.isArray(record?.options)) return record.options;
  return Object.entries(record?.options || {}).map(([label, text]) => ({ label, text }));
}

function elapsedSeconds(startedAt) {
  if (!startedAt) return 0;
  return Math.max(0, Math.floor((Date.now() - startedAt) / 1000));
}

function formatElapsed(seconds) {
  const total = Math.max(0, Math.floor(Number(seconds) || 0));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

function stageCopy(stage) {
  if (stage === "awaiting_probe") return "最小探查";
  if (stage === "awaiting_transfer") return "无提示迁移";
  if (stage === "completed") return "状态收据";
  if (stage === "completed_no_error") return "本题结束";
  return "首答";
}

function factCopy(fact) {
  const kind = {
    selected_option: "已选择的选项",
    correctness: "本题评分",
    confidence: "作答信心",
    response_time: "作答用时",
  }[fact?.kind] || "观察事实";
  return [kind, String(fact?.value ?? "已记录")];
}

function SubmissionNotice({ state, onSafeRetry, onReplay }) {
  if (!state?.error) return null;
  const safeRetry = state.kind === "entry" || state.kind === "probe" || state.kind === "transfer";
  return (
    <section className={`judgment-notice ${state.uncertain ? "uncertain" : "error"}`} role="alert">
      <WarningCircle size={17} />
      <div>
        <strong>{state.uncertain ? "首答提交状态未确认" : "本机步骤没有完成"}</strong>
        <p>{state.uncertain
          ? "本机未确认是否已收到这次作答。Lumi 不会自动重发；你可以用原命令安全重试，或先读取已写入的本机回放。"
          : (state.error?.message || "服务没有接受本次操作，当前页面不会猜测学习状态。")}</p>
      </div>
      <div className="judgment-notice-actions">
        {safeRetry && <button className="button secondary compact" type="button" onClick={onSafeRetry}>使用原命令安全重试</button>}
        {onReplay && <button className="button text-button compact" type="button" onClick={onReplay}>读取证据回放</button>}
      </div>
    </section>
  );
}

function LearningMap({ stage }) {
  const progress = stageProgress(stage);
  return (
    <section className="judgment-panel learning-map" aria-labelledby="learning-map-heading">
      <header><div><MapTrifold size={16} /><h2 id="learning-map-heading">本版能力地图</h2></div><small>条件推理</small></header>
      <ol>
        {LEARNING_MAP.map(([title, description], index) => (
          <li key={title} data-state={index + 1 < progress ? "visited" : index + 1 === progress ? "current" : "upcoming"}>
            <span>{index + 1}</span><div><strong>{title}</strong><p>{description}</p></div>
          </li>
        ))}
      </ol>
      <p className="learning-map-note">这里不是掌握度仪表盘。只有无提示、未见过的迁移作答才会产生状态收据。</p>
    </section>
  );
}

function SavedReviewPlan({ tasks }) {
  if (!Array.isArray(tasks) || tasks.length === 0) return null;
  return (
    <section className="judgment-panel saved-review-plan" aria-labelledby="saved-review-heading">
      <header><div><Clock size={16} /><h2 id="saved-review-heading">已登记的复习</h2></div><small>本机证据</small></header>
      <ul>{tasks.map((task) => <li key={task.task_id}><strong>{task.kind === "delayed_retention" ? "延后保持性复测" : "独立重试"}</strong><span>{task.due_on}</span><p>{task.success_criterion}</p></li>)}</ul>
    </section>
  );
}

function JudgmentQuestion({
  record,
  draft,
  onDraft,
  elapsed,
  label,
  boundary,
  submitLabel,
  onSubmit,
  inFlight,
  lockInputs = false,
  showRationale = false,
}) {
  const readiness = judgmentFormReadiness({ ...draft, inFlight });
  const update = (key, value) => onDraft((current) => ({ ...current, [key]: value }));
  return (
    <form className="judgment-question" onSubmit={(event) => { event.preventDefault(); if (readiness.ready) onSubmit(); }}>
      <header className="judgment-question-meta">
        <div><span>{label}</span><strong>判断推理</strong></div>
        <span aria-label={`本题已用时 ${formatElapsed(elapsed)}`}><Clock size={14} />{formatElapsed(elapsed)}</span>
      </header>
      <h2>{record.title}</h2>
      <fieldset>
        <legend>{record.prompt}</legend>
        <div className="judgment-options">
          {optionEntries(record).map((option) => (
            <label key={option.label} className={normalizeJudgmentAnswer(draft.selectedOption) === option.label ? "selected" : ""}>
              <input
                type="radio"
                name={`${record.record_id}-answer`}
                value={option.label}
                checked={normalizeJudgmentAnswer(draft.selectedOption) === option.label}
                onChange={() => update("selectedOption", option.label)}
                disabled={lockInputs || inFlight}
              />
              <span>{option.label}</span><strong>{option.text}</strong>
            </label>
          ))}
        </div>
      </fieldset>
      <div className="judgment-boundary"><Info size={14} /><span>{boundary}</span></div>
      <fieldset className="judgment-confidence">
        <legend>作答信心</legend>
        <div>
          {JUDGMENT_CONFIDENCE_OPTIONS.map(([value, text]) => (
            <label key={value} className={normalizeJudgmentConfidence(draft.confidence) === value ? "selected" : ""}>
              <input
                type="radio"
                name={`${record.record_id}-confidence`}
                value={value}
                checked={normalizeJudgmentConfidence(draft.confidence) === value}
                onChange={() => update("confidence", value)}
                disabled={lockInputs || inFlight}
              />
              {text}
            </label>
          ))}
        </div>
      </fieldset>
      {showRationale && (
        <details className="judgment-rationale">
          <summary>补充作答过程（可选）</summary>
          <label><span>你是怎样判断的？</span><textarea value={draft.rationale} onChange={(event) => update("rationale", event.target.value)} maxLength={1200} disabled={lockInputs || inFlight} placeholder="例如：先把“只有”改写成箭头，再检查能否反推。" /></label>
          <small>这段文字会随首答保存在本机轨迹中，但不代替选项评分。</small>
        </details>
      )}
      <footer className="judgment-submit-bar">
        <p className={readiness.ready ? "" : "pending"} role="status">{readiness.reason}</p>
        <button className="button primary" type="submit" disabled={!readiness.ready}>{inFlight ? "正在写入本机记录" : submitLabel}</button>
      </footer>
    </form>
  );
}

function DiagnosisPanel({ session }) {
  if (!session?.observed_facts) return null;
  const selectedAction = session.policy?.candidate_actions?.find((item) => item.selected);
  const priorObservationCopy = (prior) => {
    if (!prior || !(prior.supported_count || prior.refuted_count || prior.insufficient_count)) return null;
    return `既往探查：支持 ${prior.supported_count} 次、反驳 ${prior.refuted_count} 次、证据不足 ${prior.insufficient_count} 次。仅作当前探查后的同分排序，不单独归因。`;
  };
  return (
    <section className="judgment-panel diagnosis-panel" aria-labelledby="diagnosis-heading">
      <header><div><ListMagnifyingGlass size={16} /><h2 id="diagnosis-heading">本次诊断</h2></div><small>候选均未确认</small></header>
      <div className="diagnosis-columns">
        <div>
          <h3>观察事实</h3>
          <dl className="judgment-facts">
            {session.observed_facts.map((fact) => {
              const [label, value] = factCopy(fact);
              return <div key={fact.fact_id}><dt>{label}</dt><dd>{value}</dd><small>{fact.evidence}</small></div>;
            })}
          </dl>
        </div>
        <div>
          <h3>尚未确认的候选</h3>
          {session.candidate_causes?.length ? <ol className="judgment-candidates">
            {session.candidate_causes.map((candidate) => <li key={candidate.cause_id}><span>{candidate.rank}</span><div><strong>{candidate.cause_id}</strong><p>{candidate.rationale}</p><small>{candidateStatusCopy(candidate.status)}</small>{priorObservationCopy(candidate.prior_probe_observations) && <p className="judgment-history-note">{priorObservationCopy(candidate.prior_probe_observations)}</p>}</div></li>)}
          </ol> : <p className="judgment-quiet-copy">本题没有生成错因候选；一次正确首答不等于已掌握。</p>}
        </div>
      </div>
      {session.policy && (
        <div className="probe-policy">
          <h3>为什么是这道探查题</h3>
          <p>{session.policy.why_selected}</p>
          <ul>
            {(session.policy.candidate_actions || []).map((action) => (
              <li key={action.record_id} data-selected={action.selected ? "true" : "false"}>
                <strong>{action.record_id}{action.selected ? " · 已选择" : " · 未选择"}</strong>
                <span>{action.selected ? action.why_selected : action.why_not_selected}</span>
              </li>
            ))}
          </ul>
          {selectedAction && <small>覆盖候选：{selectedAction.coverage.join("、") || "服务未声明"}</small>}
        </div>
      )}
    </section>
  );
}

function TeachingPanel({ session }) {
  const teaching = session?.teaching;
  if (!teaching?.asset) return null;
  return (
    <section className="judgment-panel teaching-panel" aria-labelledby="teaching-heading">
      <header><div><SealCheck size={16} /><h2 id="teaching-heading">针对性微课</h2></div><small>不计入独立证据</small></header>
      <h3>{teaching.asset.title}</h3>
      <p>{teaching.asset.teaching_content}</p>
      <dl><div><dt>规则</dt><dd>{teaching.asset.logic_rule}</dd></div><div><dt>选择理由</dt><dd>{teaching.why_selected}</dd></div></dl>
    </section>
  );
}

function ProbeOutcomePanel({ session }) {
  const updates = session?.probe?.evidence_updates || [];
  if (!updates.length) return null;
  return (
    <section className="judgment-panel probe-outcome-panel" aria-labelledby="probe-outcome-heading">
      <header><div><ListMagnifyingGlass size={16} /><h2 id="probe-outcome-heading">探查后的证据变化</h2></div><small>不是最终归因</small></header>
      <ul>
        {updates.map((update) => <li key={update.cause_id}><strong>{update.cause_id}</strong><span>{update.outcome === "support" ? "得到支持" : update.outcome === "refute" ? "得到反驳" : "证据仍不足"}</span><p>{update.evidence}</p><small>{candidateStatusCopy(update.status)}</small></li>)}
      </ul>
    </section>
  );
}

function ReceiptPanel({ session }) {
  const task = reviewTaskCopy(session?.review_task);
  if (!session?.state_receipts) return null;
  return (
    <section className="judgment-panel receipt-panel" aria-labelledby="receipt-heading">
      <header><div><Receipt size={16} /><h2 id="receipt-heading">状态收据</h2></div><small>确定性写入</small></header>
      <p>{session.transfer?.correct ? "本次无提示迁移通过；下列收据说明哪些技能状态已被允许更新。" : "本次无提示迁移未通过；下列收据说明状态更新被保留，而不是被强行提高。"}</p>
      <ul className="receipt-list">
        {session.state_receipts.map((receipt) => <li key={receipt.skill_id}><strong>{receipt.skill_id}</strong><span>{receipt.state_delta?.commit_status === "committed" ? "已提交" : "已保留"}</span><small>{receipt.verification?.state_update_eligibility || receipt.verification?.withheld_reason || "服务未返回说明"}</small></li>)}
      </ul>
      {task && <div className="review-task"><strong>{task.title}</strong><dl><div><dt>复习日期</dt><dd>{task.dueOn}</dd></div><div><dt>成功标准</dt><dd>{task.criterion}</dd></div><div><dt>跳过后果</dt><dd>{task.consequence}</dd></div></dl></div>}
    </section>
  );
}

function ReplayPanel({ replay, state, onLoad }) {
  const eventDetail = (event) => {
    const result = event?.result;
    const item = result?.entry || result?.probe || result?.transfer;
    if (!item) return null;
    const outcome = typeof item.correct === "boolean"
      ? (item.correct ? "本次判断正确" : "本次判断未通过")
      : "已记录";
    return <p className="replay-event-detail"><strong>{item.title || "本轮项目"}</strong><span>你的作答：{item.selected_option || "已记录"} · {outcome}</span></p>;
  };
  return (
    <section className="judgment-panel replay-panel" aria-labelledby="replay-heading">
      <header><div><ArrowClockwise size={16} /><h2 id="replay-heading">证据回放</h2></div><small>{replay?.trace_verified ? "轨迹已校验" : "尚未读取"}</small></header>
      {!replay && <><p>回放只读取已写入的本机事件，不生成补充解释。</p><button className="button secondary compact" type="button" onClick={onLoad} disabled={state === "loading"}>{state === "loading" ? "正在读取回放" : "读取本机回放"}</button></>}
      {replay && <ol className="replay-timeline">{replay.timeline.map((event) => <li key={`${event.seq}-${event.kind}`}><span>{event.seq}</span><div><strong>{event.kind.replaceAll("judgment_", "")}</strong><small>{event.stage_after || "已记录"} · {event.occurred_at}</small>{eventDetail(event)}</div></li>)}</ol>}
    </section>
  );
}

function UnavailableWorkspace({ state, onRetry }) {
  if (state.phase === "loading") return <div className="judgment-state loading" role="status"><strong>正在读取判断推理工作台</strong><p>只接受本机服务返回的审核状态与题目投影。</p></div>;
  const isReview = state.phase === "review_required";
  const isOffline = state.phase === "offline";
  return (
    <div className="judgment-state" role={isReview ? "status" : "alert"} data-state={state.phase}>
      {isReview ? <SealCheck size={25} /> : <WarningCircle size={25} />}
      <h1>{isReview ? "判断推理内容仍待审核" : isOffline ? "本机服务未连接" : "判断推理工作台暂不可用"}</h1>
      <p>{isReview
        ? "当前题包还缺逻辑审核与编辑/权属审核。Lumi 不会回退到旧资料分析、展示草稿题目，或创建学习记录。"
        : (state.error?.message || "没有读取到可信的本机工作台状态。")}</p>
      {isReview && <dl className="review-gate-copy"><div><dt>仍需完成</dt><dd>逻辑唯一答案检查；编辑、原创性与权属审核。</dd></div><div><dt>当前行为</dt><dd>不展示草稿题面，不写入任何学习状态。</dd></div></dl>}
      <button className="button secondary" type="button" onClick={onRetry}>重新读取本机状态</button>
    </div>
  );
}

export function JudgmentWorkspace() {
  const [workspace, setWorkspace] = useState({ phase: "loading", data: null, error: null });
  const [selectedEntryId, setSelectedEntryId] = useState(null);
  const [entryDraft, setEntryDraft] = useState(EMPTY_DRAFT);
  const [probeDraft, setProbeDraft] = useState(EMPTY_DRAFT);
  const [transferDraft, setTransferDraft] = useState(EMPTY_DRAFT);
  const [session, setSession] = useState(null);
  const [startedAt, setStartedAt] = useState(Date.now());
  const [elapsed, setElapsed] = useState(0);
  const [submission, setSubmission] = useState({ inFlight: false, error: null, kind: null, uncertain: false });
  const [pendingCommand, setPendingCommand] = useState(null);
  const [replay, setReplay] = useState(null);
  const [replayState, setReplayState] = useState("idle");

  const reloadWorkspace = useCallback(async () => {
    setWorkspace({ phase: "loading", data: null, error: null });
    setSession(null);
    setSubmission({ inFlight: false, error: null, kind: null, uncertain: false });
    setPendingCommand(null);
    setReplay(null);
    try {
      const result = await fetchJudgmentWorkspace();
      if (!result.available) {
        setWorkspace({ phase: "review_required", data: result, error: null });
        return;
      }
      setWorkspace({ phase: "available", data: result, error: null });
      setEntryDraft(EMPTY_DRAFT);
      setProbeDraft(EMPTY_DRAFT);
      setTransferDraft(EMPTY_DRAFT);
      setSelectedEntryId(result.entry_items[0]?.record_id || null);
      setStartedAt(Date.now());
      setElapsed(0);
    } catch (error) {
      setWorkspace({ phase: error?.kind === "unavailable" ? "offline" : "error", data: null, error });
    }
  }, []);

  useEffect(() => { reloadWorkspace(); }, [reloadWorkspace]);
  useEffect(() => {
    if (workspace.phase !== "available" || submission.inFlight || session?.stage === "completed" || session?.stage === "completed_no_error") return undefined;
    const timer = window.setInterval(() => setElapsed(elapsedSeconds(startedAt)), 1000);
    return () => window.clearInterval(timer);
  }, [session?.stage, startedAt, submission.inFlight, workspace.phase]);

  const entryItems = workspace.data?.entry_items || [];
  const entry = entryItems.find((item) => item.record_id === selectedEntryId) || entryItems[0] || null;
  const activeRecord = useMemo(() => {
    if (session?.stage === "awaiting_probe") return session.probe;
    if (session?.stage === "awaiting_transfer") return session.transfer;
    return entry;
  }, [entry, session]);

  const loadReplay = useCallback(async () => {
    if (!session?.session_id) return;
    setReplayState("loading");
    try {
      setReplay(await fetchJudgmentReplay(session.session_id));
      setReplayState("ready");
    } catch (error) {
      setReplayState("error");
      setSubmission((current) => ({ ...current, error, kind: current.kind || "replay", uncertain: false }));
    }
  }, [session?.session_id]);

  const submitEntry = async () => {
    const reusing = pendingCommand?.kind === "entry";
    if (!entry || (!reusing && !judgmentFormReadiness({ ...entryDraft, inFlight: submission.inFlight }).ready)) return;
    const command = reusing ? pendingCommand : {
      kind: "entry",
      commandId: createCommandId(),
      entryRecordId: entry.record_id,
      selectedOption: entryDraft.selectedOption,
      confidence: entryDraft.confidence,
      elapsedSeconds: elapsedSeconds(startedAt),
      rationale: entryDraft.rationale,
    };
    setPendingCommand(command);
    setSubmission({ inFlight: true, error: null, kind: "entry", uncertain: false });
    try {
      const result = await startJudgmentSession(command);
      setSession(result);
      setPendingCommand(null);
      setSubmission({ inFlight: false, error: null, kind: null, uncertain: false });
      setStartedAt(Date.now());
      setElapsed(0);
    } catch (error) {
      setSubmission({ inFlight: false, error, kind: "entry", uncertain: true });
    }
  };

  const submitContinuation = async (kind) => {
    const draft = kind === "probe" ? probeDraft : transferDraft;
    if (!session || !judgmentFormReadiness({ ...draft, inFlight: submission.inFlight }).ready) return;
    const reusing = pendingCommand?.kind === kind;
    const command = reusing ? pendingCommand : {
      kind,
      commandId: createCommandId(),
      selectedOption: draft.selectedOption,
      confidence: draft.confidence,
      elapsedSeconds: elapsedSeconds(startedAt),
    };
    setPendingCommand(command);
    setSubmission({ inFlight: true, error: null, kind, uncertain: false });
    try {
      const result = kind === "probe"
        ? await answerJudgmentProbe({ session, ...command })
        : await answerJudgmentTransfer({ session, ...command });
      setSession(result);
      setPendingCommand(null);
      setSubmission({ inFlight: false, error: null, kind: null, uncertain: false });
      setStartedAt(Date.now());
      setElapsed(0);
    } catch (error) {
      setSubmission({ inFlight: false, error, kind, uncertain: false });
    }
  };

  if (workspace.phase !== "available") return <div className="screen judgment-workspace"><UnavailableWorkspace state={workspace} onRetry={reloadWorkspace} /></div>;

  const currentStage = session?.stage || "entry";
  const showingEntry = !session;
  const showingProbe = session?.stage === "awaiting_probe";
  const showingTransfer = session?.stage === "awaiting_transfer";
  const completed = session?.stage === "completed";
  const noError = session?.stage === "completed_no_error";
  const retryCommand = pendingCommand?.kind === submission.kind
    ? (submission.kind === "entry" ? submitEntry : () => submitContinuation(submission.kind))
    : undefined;

  return (
    <div className="screen judgment-workspace" data-testid="judgment-workspace" data-stage={currentStage}>
      <div className="page-heading judgment-heading">
        <div><span className="eyebrow">Lumi · 可解释自适应学习</span><h1>判断推理学习空间</h1><p>从一次真实首答开始；候选错因、教学与状态更新都必须有本机证据。</p></div>
        <button className="button secondary compact" type="button" onClick={reloadWorkspace} disabled={submission.inFlight}>重新读取工作台</button>
      </div>

      <div className="judgment-layout">
        <aside className="judgment-rail"><LearningMap stage={currentStage} /><section className="judgment-panel current-step"><header><div><CheckCircle size={16} /><h2>当前步骤</h2></div></header><strong>{stageCopy(currentStage)}</strong><p>{showingEntry ? "选择一个答案、标记信心，并可补充自己的判断过程。" : showingProbe ? "用最小探查支持或反驳候选，不作最终归因。" : showingTransfer ? "不提供提示；这次作答才有资格进入状态收据。" : "查看收据和后续复习要求。"}</p></section><SavedReviewPlan tasks={workspace.data?.review_plan} /></aside>
        <main className="judgment-main">
          {showingEntry && entryItems.length > 1 && <section className="entry-selector" aria-labelledby="entry-selector-heading"><div><h2 id="entry-selector-heading">选择本轮起点</h2><p>从一个未完成的条件推理诊断开始；两条路径都遵守相同的证据与验证规则。</p></div><div role="list" aria-label="可选判断推理起点">{entryItems.map((item) => <button key={item.record_id} className={entry?.record_id === item.record_id ? "selected" : ""} type="button" role="listitem" aria-pressed={entry?.record_id === item.record_id} onClick={() => { setSelectedEntryId(item.record_id); setEntryDraft(EMPTY_DRAFT); setStartedAt(Date.now()); setElapsed(0); }} disabled={submission.inFlight}><strong>{item.role === "routing_diagnostic" ? "推理有效性" : "条件方向"}</strong><span>{item.title}</span></button>)}</div></section>}
          {showingEntry && activeRecord && <JudgmentQuestion record={activeRecord} draft={entryDraft} onDraft={setEntryDraft} elapsed={elapsed} label="第一步 · 首答" boundary="请先独立判断。提交后才会创建本机记录并计算候选错因。" submitLabel="提交首答并创建本机记录" onSubmit={submitEntry} inFlight={submission.inFlight} showRationale />}
          {showingProbe && <><DiagnosisPanel session={session} /><JudgmentQuestion record={activeRecord} draft={probeDraft} onDraft={setProbeDraft} elapsed={elapsed} label="第二步 · 最小探查" boundary="这题只用来区分候选原因。无论结果如何，候选都不会被直接确认。" submitLabel="提交探查作答" onSubmit={() => submitContinuation("probe")} inFlight={submission.inFlight} lockInputs={submission.kind === "probe" && Boolean(submission.error)} /></>}
          {showingTransfer && <><ProbeOutcomePanel session={session} /><TeachingPanel session={session} /><JudgmentQuestion record={activeRecord} draft={transferDraft} onDraft={setTransferDraft} elapsed={elapsed} label="第三步 · 无提示迁移" boundary="这是一道未见过的平行题。请不要请求提示；只有独立作答才可能更新状态。" submitLabel="提交无提示迁移" onSubmit={() => submitContinuation("transfer")} inFlight={submission.inFlight} lockInputs={submission.kind === "transfer" && Boolean(submission.error)} /></>}
          {(completed || noError) && <section className="judgment-complete"><header><CheckCircle size={21} weight="fill" /><div><h2>{completed ? "本轮学习已完成" : "本题学习已结束"}</h2><p>{completed ? "迁移题评分与状态写入已由本机服务返回收据。" : "首答没有产生可解释的错因候选；Lumi 不会虚构诊断或迁移。"}</p></div></header>{completed && <ReceiptPanel session={session} />}<button className="button secondary" type="button" onClick={reloadWorkspace}>开始新的独立检查</button></section>}
          <SubmissionNotice state={submission} onSafeRetry={retryCommand} onReplay={session?.session_id ? loadReplay : undefined} />
          {session?.session_id && <ReplayPanel replay={replay} state={replayState} onLoad={loadReplay} />}
        </main>
      </div>
    </div>
  );
}
