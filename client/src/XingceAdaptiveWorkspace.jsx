import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowClockwise,
  CheckCircle,
  Clock,
  Info,
  Lightbulb,
  ListMagnifyingGlass,
  SealCheck,
  WarningCircle,
} from "@phosphor-icons/react";
import {
  answerXingceAdaptiveProbe,
  answerXingceAdaptiveTransfer,
  fetchXingceAdaptiveWorkspace,
  startXingceAdaptiveSession,
} from "./xingceAdaptiveApi.js";
import { createCommandId } from "./publicLearningId.js";

const EMPTY_DRAFT = { selectedResponse: "", confidence: "", rationale: "" };
const CONFIDENCE = [["low", "不太确定"], ["medium", "有些把握"], ["high", "很有把握"]];

function elapsedSeconds(startedAt) {
  return startedAt ? Math.max(0, Math.floor((Date.now() - startedAt) / 1000)) : 0;
}

function elapsedCopy(value) {
  const seconds = Math.max(0, Math.floor(Number(value) || 0));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

function stageCopy(stage) {
  return {
    entry: "首答",
    awaiting_probe: "最小探查",
    awaiting_transfer: "独立迁移",
    completed: "状态收据",
    completed_no_error: "本轮结束",
  }[stage] || "读取中";
}

function currentRecord(workspace, session) {
  if (!session) return workspace?.entry_items?.[0] || null;
  if (session.stage === "awaiting_probe") return session.probe;
  if (session.stage === "awaiting_transfer") return session.transfer;
  return null;
}

function currentKind(session) {
  if (!session) return "entry";
  if (session.stage === "awaiting_probe") return "probe";
  if (session.stage === "awaiting_transfer") return "transfer";
  return null;
}

function formReadiness(record, draft, kind) {
  if (!record || !kind || !draft.selectedResponse.trim() || !draft.confidence) return false;
  return kind !== "entry" || draft.rationale.length <= 1200;
}

function StageRail({ stage, pack, title, directVerification = false }) {
  const steps = [["entry", "首答"], ["awaiting_probe", directVerification ? "无需探查" : "探查"], ["awaiting_transfer", "迁移"], ["completed", "收据"]];
  const ordinal = { entry: 0, awaiting_probe: 1, awaiting_transfer: 2, completed: 3, completed_no_error: 3 }[stage] ?? 0;
  return <aside className="adaptive-rail" aria-label="本轮学习步骤">
    <section className="adaptive-panel adaptive-pack-summary">
      <span>本地题型</span>
      <strong>{title || pack?.subtype_id?.replace(/^xingce\./, "") || "行测"}</strong>
      <small>题包 {pack?.pack_version || "—"}</small>
    </section>
    <ol className="adaptive-steps">
      {steps.map(([id, label], index) => <li key={id} data-state={index < ordinal ? "visited" : index === ordinal ? "current" : "future"}>
        <span>{index + 1}</span><strong>{label}</strong>
      </li>)}
    </ol>
    <section className="adaptive-panel adaptive-boundary">
      <Info size={15} />
      <p>候选错因只用于决定下一步，始终保持“未确认”。只有未见、无提示的迁移作答才可能产生有限状态收据。</p>
    </section>
  </aside>;
}

function CandidatePanel({ session }) {
  if (session?.stage !== "awaiting_probe") return null;
  return <section className="adaptive-panel adaptive-candidates" aria-labelledby="candidate-heading">
    <header><ListMagnifyingGlass size={16} /><h2 id="candidate-heading">候选原因</h2></header>
    <p>首答只提供待区分的线索，不是诊断结论。</p>
    <ul>{session.candidate_causes.map((cause) => <li key={cause.cause_id}><span>{cause.rank}</span><div><strong>{cause.label}</strong><small>状态：未确认</small></div></li>)}</ul>
  </section>;
}

function ProbeEvidence({ session }) {
  if (session?.stage !== "awaiting_transfer" || !session?.probe) return null;
  return <section className="adaptive-panel adaptive-evidence" aria-labelledby="probe-evidence-heading">
    <header><Info size={16} /><h2 id="probe-evidence-heading">探查结果</h2></header>
    <p>探查只支持或反驳候选；不会将任何原因确认为事实。</p>
    <ul>{session.probe.evidence_updates.map((item) => <li key={item.cause_id}><strong>{item.label}</strong><span>{item.outcome === "support" ? "获得支持" : item.outcome === "refute" ? "暂被反驳" : "证据不足"}</span></li>)}</ul>
  </section>;
}

function DirectVerificationPanel({ session }) {
  if (session?.stage !== "awaiting_transfer" || session?.entry?.correct !== true || session?.probe) return null;
  return <section className="adaptive-panel adaptive-evidence" aria-labelledby="direct-verification-heading">
    <header><CheckCircle size={16} /><h2 id="direct-verification-heading">首答正确，继续独立验证</h2></header>
    <p>这一题没有产生错因候选，也还不足以提高掌握状态。请用不同题面的无提示迁移题确认能否独立应用。</p>
  </section>;
}

function TeachingPanel({ teaching }) {
  if (!teaching) return null;
  return <section className="adaptive-teaching" aria-labelledby="teaching-heading">
    <header><Lightbulb size={17} /><div><small>针对当前候选的最小帮助</small><h2 id="teaching-heading">{teaching.title}</h2></div></header>
    <p>{teaching.teaching_content}</p>
    <small>下一题不提供提示，并使用不同题面验证能否独立应用。</small>
  </section>;
}

function SourceMaterial({ material, nested = false }) {
  if (!material) return null;
  if (material.kind === "text") return <section className="adaptive-material adaptive-material-text" aria-label={material.title}>
    <header><small>{nested ? "材料节选" : "题目材料"}</small><strong>{material.title}</strong></header>
    <p>{material.body}</p><footer>{material.scope_note}</footer>
  </section>;
  if (material.kind === "table") return <section className="adaptive-material adaptive-material-table" aria-label={material.title}>
    <header><small>{nested ? "材料表格" : "题目材料"}</small><strong>{material.title}</strong></header>
    <div className="adaptive-material-scroll"><table><caption>{material.scope_note}</caption><thead><tr>{material.columns.map((column) => <th key={column} scope="col">{column}</th>)}</tr></thead><tbody>{material.rows.map((row, index) => <tr key={`${row.join("-")}-${index}`}>{row.map((cell, cellIndex) => <td key={`${index}-${cellIndex}`}>{cell}</td>)}</tr>)}</tbody></table></div>
  </section>;
  if (material.kind === "chart") {
    const values = material.series.flatMap((series) => series.values);
    const maximum = Math.max(1, ...values);
    return <figure className="adaptive-material adaptive-material-chart" aria-label={material.alt_text}>
      <figcaption><small>{nested ? "材料图形" : "题目材料"}</small><strong>{material.title}</strong><span>{material.unit_scope}</span></figcaption>
      <div className="adaptive-chart-values" role="img" aria-label={material.alt_text}>{material.categories.map((category, index) => <div key={category} className="adaptive-chart-row"><b>{category}</b><div>{material.series.map((series) => <span key={series.label}><i style={{ width: `${Math.max(4, (series.values[index] / maximum) * 100)}%` }} /><em>{series.label} {series.values[index]}</em></span>)}</div></div>)}</div>
    </figure>;
  }
  if (material.kind === "diagram") return <figure className="adaptive-material adaptive-material-diagram" aria-label={material.alt_text}>
    <figcaption><small>{nested ? "图形节选" : "题目图形"}</small><strong>{material.title}</strong><span>{material.alt_text}</span></figcaption>
    <div className="adaptive-diagram-panels">{material.panels.map((panel) => <div key={panel.label} className="adaptive-diagram-panel"><small>{panel.label}</small><div>{panel.tokens.map((token, index) => <span key={`${token}-${index}`}>{token}</span>)}</div></div>)}</div>
  </figure>;
  return <section className="adaptive-material adaptive-material-composite" aria-label={material.title}><header><small>综合材料</small><strong>{material.title}</strong></header><p>{material.scope_note}</p>{material.parts.map((part, index) => <SourceMaterial key={`${part.title}-${index}`} material={part} nested />)}</section>;
}

function RecordForm({ record, kind, draft, setDraft, elapsed, disabled, onSubmit, pending, error, directVerification = false }) {
  const numeric = record.response_mode === "numeric";
  const ready = formReadiness(record, draft, kind);
  const title = kind === "entry" ? "第一步 · 先独立作答" : kind === "probe" ? "第二步 · 最小探查" : directVerification ? "第二步 · 独立验证" : "第三步 · 无提示迁移";
  const action = kind === "entry" ? "提交首答" : kind === "probe" ? "提交探查作答" : directVerification ? "提交独立验证" : "提交独立迁移";
  return <section className="adaptive-question" aria-labelledby="adaptive-question-heading">
    <header className="adaptive-question-meta"><div><span>{title}</span><strong>{record.title}</strong></div><span><Clock size={14} /> {elapsedCopy(elapsed)}</span></header>
    <SourceMaterial material={record.source_material} />
    <h1 id="adaptive-question-heading">{record.prompt}</h1>
    <fieldset disabled={disabled}>
      <legend>{numeric ? "填写你的答案" : "选择一个答案"}</legend>
      {numeric ? <input className="adaptive-number-input" inputMode="decimal" value={draft.selectedResponse} onChange={(event) => setDraft((value) => ({ ...value, selectedResponse: event.target.value }))} placeholder="例如：39" aria-label="填写数字答案" /> : <div className="adaptive-options">
        {record.options.map((option) => <label key={option.label} className={draft.selectedResponse === option.label ? "selected" : ""}>
          <input type="radio" name={`adaptive-${kind}-${record.record_id}`} value={option.label} checked={draft.selectedResponse === option.label} onChange={() => setDraft((value) => ({ ...value, selectedResponse: option.label }))} />
          <span>{option.label}</span><strong>{option.text}</strong>
        </label>)}
      </div>}
    </fieldset>
    <fieldset className="adaptive-confidence" disabled={disabled}><legend>此刻的把握程度</legend><div>{CONFIDENCE.map(([value, label]) => <label key={value} className={draft.confidence === value ? "selected" : ""}><input type="radio" name={`adaptive-confidence-${kind}`} value={value} checked={draft.confidence === value} onChange={() => setDraft((current) => ({ ...current, confidence: value }))} />{label}</label>)}</div></fieldset>
    {kind === "entry" && <details className="adaptive-rationale"><summary>补充你的判断过程（可选）</summary><textarea value={draft.rationale} maxLength={1200} onChange={(event) => setDraft((value) => ({ ...value, rationale: event.target.value }))} placeholder="例如：我先比较了相邻项的变化……" /><small>{draft.rationale.length} / 1200</small></details>}
    {error && <div className="adaptive-error" role="alert"><WarningCircle size={16} /><span>{error}</span></div>}
    <footer><p>{kind === "transfer" ? "本题没有提示；只有独立作答才有资格进入状态收据。" : "答案、信心和用时会写入本机可回放记录。"}</p><button className="button primary" type="button" disabled={!ready || disabled} onClick={onSubmit}>{pending ? "正在保存…" : action}</button></footer>
  </section>;
}

function Completion({ session }) {
  if (!session || !["completed", "completed_no_error"].includes(session.stage)) return null;
  if (session.stage === "completed_no_error") return <section className="adaptive-completion"><CheckCircle size={22} weight="fill" /><div><h1>本题首答正确</h1><p>没有依据这一题推断错因或提高掌握状态。可在之后完成另一轮独立练习。</p></div></section>;
  const committed = session.state_update.eligible;
  const reason = {
    unseen_unassisted_transfer_passed: "未见、无提示的迁移题已通过，允许记录一条有限的掌握证据。",
    independent_transfer_not_passed: "独立迁移尚未通过，本次不提高掌握状态。",
    transfer_was_assisted: "迁移过程使用了帮助，本次不作为独立掌握证据。",
  }[session.state_update.reason] || "本次状态变化仅依据可回放的独立迁移证据。";
  return <section className="adaptive-completion" aria-labelledby="adaptive-receipt-heading"><SealCheck size={22} weight="fill" /><div><small>本机状态收据</small><h1 id="adaptive-receipt-heading">{committed ? "已记录一条独立迁移证据" : "学习状态保持不变"}</h1><p>{reason}</p><dl><div><dt>后续任务</dt><dd>{session.review_task.kind === "delayed_retention" ? "延迟复习" : "独立重试"} · {session.review_task.due_on}</dd></div><div><dt>成功标准</dt><dd>{session.review_task.success_criterion}</dd></div><div><dt>跳过后果</dt><dd>{session.review_task.skip_consequence}</dd></div></dl></div></section>;
}

export function XingceAdaptiveWorkspace({ subtypeId, displayTitle = undefined, onServiceReachable = undefined }) {
  const [workspace, setWorkspace] = useState({ phase: "loading", data: null, error: null });
  const [session, setSession] = useState(null);
  const [draft, setDraft] = useState(EMPTY_DRAFT);
  const [startedAt, setStartedAt] = useState(null);
  const [elapsed, setElapsed] = useState(0);
  const [submission, setSubmission] = useState({ inFlight: false, kind: null, commandId: null, error: null });

  const reportServiceReachable = useCallback(() => { void onServiceReachable?.(); }, [onServiceReachable]);
  const reload = useCallback(async () => {
    setWorkspace({ phase: "loading", data: null, error: null });
    setSession(null); setDraft(EMPTY_DRAFT); setSubmission({ inFlight: false, kind: null, commandId: null, error: null });
    try {
      const data = await fetchXingceAdaptiveWorkspace(subtypeId);
      reportServiceReachable();
      setWorkspace({ phase: "ready", data, error: null }); setStartedAt(Date.now()); setElapsed(0);
    } catch (error) { setWorkspace({ phase: "error", data: null, error }); }
  }, [reportServiceReachable, subtypeId]);

  useEffect(() => { void reload(); }, [reload]);
  useEffect(() => {
    if (!startedAt || submission.inFlight || !currentRecord(workspace.data, session)) return undefined;
    const timer = window.setInterval(() => setElapsed(elapsedSeconds(startedAt)), 1000);
    return () => window.clearInterval(timer);
  }, [session, startedAt, submission.inFlight, workspace.data]);

  const record = useMemo(() => currentRecord(workspace.data, session), [session, workspace.data]);
  const kind = currentKind(session);
  const stage = session?.stage || "entry";
  const directVerification = (session?.stage === "awaiting_transfer" && session?.entry?.correct === true && !session?.probe)
    || session?.learning_route === "direct_verification";
  const submit = useCallback(async () => {
    if (!record || !kind || !formReadiness(record, draft, kind) || submission.inFlight) return;
    const commandId = submission.kind === kind && submission.commandId ? submission.commandId : createCommandId(`xingce-${kind}`);
    setSubmission({ inFlight: true, kind, commandId, error: null });
    const shared = { subtypeId, selectedResponse: draft.selectedResponse.trim(), confidence: draft.confidence, elapsedSeconds: elapsed, commandId };
    try {
      const result = kind === "entry"
        ? await startXingceAdaptiveSession({ ...shared, entryRecordId: record.record_id, rationale: draft.rationale })
        : kind === "probe"
          ? await answerXingceAdaptiveProbe({ ...shared, session })
          : await answerXingceAdaptiveTransfer({ ...shared, session });
      reportServiceReachable(); setSession(result); setDraft(EMPTY_DRAFT); setStartedAt(Date.now()); setElapsed(0); setSubmission({ inFlight: false, kind: null, commandId: null, error: null });
    } catch (error) { setSubmission({ inFlight: false, kind, commandId, error: error?.message || "本机服务没有接受这次作答。" }); }
  }, [draft, elapsed, kind, record, reportServiceReachable, session, submission, subtypeId]);

  if (workspace.phase === "loading") return <section className="adaptive-workspace-state" aria-live="polite"><ArrowClockwise size={18} />正在读取本机题型工作台…</section>;
  if (workspace.phase === "error") return <section className="adaptive-workspace-state error" role="alert"><WarningCircle size={18} /><div><strong>无法读取本机题型工作台</strong><p>{workspace.error?.message || "请检查本机服务后重试。"}</p><button className="button secondary compact" type="button" onClick={reload}>重新读取</button></div></section>;

  return <section className="adaptive-workspace">
    <header className="adaptive-heading"><div><small>行测 · 已审核题型</small><h1>{displayTitle || workspace.data.pack.subtype_id.replace(/^xingce\./, "")}</h1><p>本轮以本机题包完成首答、探查、针对性帮助、无提示迁移和可回放收据。</p></div><button className="button secondary compact" type="button" onClick={reload} disabled={submission.inFlight}>重新读取</button></header>
    <div className="adaptive-layout"><StageRail stage={stage} pack={workspace.data.pack} title={displayTitle} directVerification={directVerification} /><main className="adaptive-main"><CandidatePanel session={session} /><ProbeEvidence session={session} /><DirectVerificationPanel session={session} /><TeachingPanel teaching={session?.stage === "awaiting_transfer" ? session.teaching : null} />{record && <RecordForm record={record} kind={kind} draft={draft} setDraft={setDraft} elapsed={elapsed} disabled={submission.inFlight} onSubmit={submit} pending={submission.inFlight} error={submission.error} directVerification={directVerification} />}{<Completion session={session} />}</main></div>
  </section>;
}
