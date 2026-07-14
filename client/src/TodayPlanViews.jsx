import { useMemo, useState } from "react";
import {
  ArrowRight,
  CalendarBlank,
  CaretRight,
  CheckCircle,
  Clock,
  Info,
  ListChecks,
  Play,
} from "@phosphor-icons/react";
import { evidenceDisplayLabel } from "./evidencePresentation.js";
import { localDateString, resolveClientNow } from "./todayPlanAdapter.js";

const TASK_KIND_COPY = {
  cause_probe: "错因候选探查",
  independent_retry: "独立重试",
  delayed_retention: "延迟保持复核",
};

const TASK_STATE_COPY = {
  scheduled: "待确认",
  accepted: "已接受",
  completed: "已标记处理",
  postponed: "已推迟",
  skipped: "已跳过",
};

const EMPTY_COPY = {
  no_recorded_evidence: ["尚无可排程的学习证据", "完成一次真实的首答、探查、教学与独立验证后，复习安排才可能出现。"],
  no_pending_review_tasks: ["当前没有待处理复习", "已有真实学习证据对应的 ReviewSchedule 任务均已处理完成。"],
  no_task_due_today: ["今天没有到期任务", "已有复习安排，但没有任务在今天到期。"],
  task_due_after_exam: ["任务到期日晚于考试日", "固定工程窗口没有在考试日前形成可执行任务。"],
  activity_unavailable: ["对应练习当前不可用", "计划没有把不可启动的活动排进今天。"],
  no_task_within_guardrail: ["今天没有符合约束的任务", "当前预算与固定工作量约束下没有可选任务。"],
};

function tomorrowString(today) {
  const [year, month, day] = today.split("-").map(Number);
  const value = new Date(year, month - 1, day + 1, 12, 0, 0);
  return localDateString(value);
}

export function planStateCopy(planning) {
  if (planning.phase === "loading") return ["正在读取今日计划", "操作暂不可用。"];
  if (planning.phase === "not-created") return ["今天尚未生成计划", "可在“任务”页用本机当天日期显式创建。"];
  if (planning.phase === "offline") return ["本机计划不可用", "恢复本机服务后再读取或创建；不会显示缓存演示计划。"];
  if (planning.phase === "error") return ["计划响应异常", "当前数据没有通过客户端合同校验，所有计划操作已关闭。"];
  if (planning.plan?.status === "empty") return EMPTY_COPY[planning.plan.emptyReason] || ["今天没有任务", "本机计划为空。"];
  return ["今日计划已读取", `${planning.plan?.tasks.length || 0} 项任务`];
}

export function TodayPlanOverview({ planning, setPage }) {
  const [title, detail] = planStateCopy(planning);
  const tasks = planning.phase === "connected" ? planning.plan?.tasks || [] : [];
  return (
    <section className="assignments-section" data-testid="today-plan-overview" data-state={planning.phase} data-error-code={planning.error?.code || ""}>
      <div className="section-title row-between">
        <h2>今日安排</h2>
        <div className="section-actions"><button className="text-link" onClick={() => setPage("practice")}>查看任务状态</button></div>
      </div>
      <div className="table-shell" role="table" aria-label="今日安排">
        <div className="table-row table-head" role="row"><span>任务</span><span>类型</span><span>预计时间</span><span>状态</span></div>
        {tasks.length > 0 ? tasks.map((task) => (
          <button className="table-row" role="row" key={task.id} onClick={() => setPage("practice")}>
            <span>{task.reason}</span>
            <span>{TASK_KIND_COPY[task.taskKind]}</span>
            <span>{task.expectedDurationMinutes} 分钟</span>
            <span className={`status ${task.state}`}>{TASK_STATE_COPY[task.state]}</span>
          </button>
        )) : (
          <div className="table-empty-row plan-empty-row" role="row"><span><strong>{title}</strong><small>{detail}</small></span></div>
        )}
      </div>
    </section>
  );
}

export function ReviewScheduleSummary({ planning, onOpenReport }) {
  const schedule = planning.schedule;
  const available = Boolean(schedule);
  const next = useMemo(() => schedule?.items
    .filter((item) => item.state !== "completed")
    .sort((left, right) => left.dueOn.localeCompare(right.dueOn))[0] || null, [schedule]);
  return (
    <aside className="daily-panel review-summary" data-testid="review-schedule-summary" data-source={available ? "sidecar" : "unavailable"}>
      <div className="row-between"><strong>复习安排</strong><span>{available ? "独立排程" : "不可用"}</span></div>
      <p className="daily-source-copy">{available ? "来自 ReviewSchedule；任务操作不写入学习轨迹或 KT。" : "未读取到真实 ReviewSchedule；不根据技能报告推算。"}</p>
      <dl>
        <div><dt>全部任务</dt><dd>{available ? `${schedule.count} 项` : "—"}</dd></div>
        <div><dt>下次到期</dt><dd>{next?.dueOn || "暂无"}</dd></div>
      </dl>
      <hr />
      <strong>今日计划</strong>
      <p>{planStateCopy(planning)[0]}</p>
      <button className="text-link" onClick={onOpenReport}>查看排程证据 <ArrowRight size={12} /></button>
    </aside>
  );
}

function PlanningNotice({ notice }) {
  if (!notice) return null;
  return (
    <div className={`planning-notice ${notice.kind}`} role={notice.kind === "error" || notice.kind === "conflict" ? "alert" : "status"} data-testid="planning-notice" data-state={notice.kind} data-code={notice.code || undefined}>
      <Info size={14} />
      <div><strong>{notice.title}</strong><p>{notice.message}</p></div>
    </div>
  );
}

function CreatePlanForm({ onCreate, processing, disabled }) {
  const today = localDateString(resolveClientNow());
  const [examDate, setExamDate] = useState("");
  const [budget, setBudget] = useState("60");
  const validBudget = Number.isInteger(Number(budget)) && Number(budget) >= 5 && Number(budget) <= 240;
  return (
    <form className="create-plan-form" onSubmit={(event) => {
      event.preventDefault();
      if (!disabled && validBudget) onCreate({ examDate: examDate || undefined, dailyBudgetMinutes: Number(budget) });
    }}>
      <div className="form-row-grid">
        <label><span>计划日期</span><input value={today} readOnly /></label>
        <label><span>考试日期（可选）</span><input type="date" min={today} value={examDate} onChange={(event) => setExamDate(event.target.value)} /></label>
        <label><span>今日可用时间</span><span className="number-input"><input type="number" min="5" max="240" step="1" value={budget} onChange={(event) => setBudget(event.target.value)} /><em>分钟</em></span></label>
      </div>
      <p className="form-contract-note"><Info size={13} />计划日期只取这台 Mac 的客户端本地当天；预计时长均为未校准工程估算。</p>
      <button className="button primary" type="submit" disabled={disabled || processing || !validBudget}>{processing ? "正在创建今日计划" : "创建今日计划"}</button>
    </form>
  );
}

function EvidenceRows({ refs }) {
  return (
    <div className="task-evidence-list">
      {refs.map((ref) => (
        <div key={ref.ref}>
          <strong className="evidence-label">{evidenceDisplayLabel(ref)}</strong>
          {ref.kind === "candidate_cause" && <span className="evidence-boundary">候选 / 未确认</span>}
          <details className="evidence-details">
            <summary>查看证据详情</summary>
            <dl>
              <div><dt>运行编号</dt><dd><code>{ref.runId}</code></dd></div>
              <div><dt>事件序号</dt><dd>{ref.eventSeq}</dd></div>
              <div><dt>事件类型</dt><dd><code>{ref.eventKind}</code></dd></div>
              <div><dt>证据哈希</dt><dd><code>{ref.eventHash}</code></dd></div>
              <div><dt>JSON 指针</dt><dd><code>{ref.jsonPointer}</code></dd></div>
            </dl>
          </details>
        </div>
      ))}
    </div>
  );
}

function TaskActions({ task, plan, processing, onCommand, onLaunch }) {
  const [postponeOpen, setPostponeOpen] = useState(false);
  const [postponeUntil, setPostponeUntil] = useState(tomorrowString(plan.planDate));
  const busy = processing === task.id;
  if (task.state === "completed") {
    return <div className="task-terminal-state"><CheckCircle size={14} weight="fill" /><span>仅标记已处理；这不是学习效果证据，也没有更新 KT。</span></div>;
  }
  if (task.state === "postponed" || task.state === "skipped") {
    return <div className="task-terminal-state neutral"><CalendarBlank size={14} /><span>{task.state === "postponed" ? `已推迟；${task.dueOn} 是最早恢复到期日/进入轮候日。实际展示仍受预算、公平轮转与已接受承诺影响。` : `已跳过；任务保留在 ReviewSchedule，并按后续学习日公平轮候。当前进入轮候日 ${task.dueOn}；不承诺当天展示。`}</span></div>;
  }
  return (
    <div className="task-actions" data-processing={busy ? "true" : "false"}>
      {task.state === "scheduled" && <button className="button primary" disabled={busy} onClick={() => onCommand(task, "accept")}>{busy ? "正在处理" : "接受任务"}</button>}
      {task.state === "accepted" && (
        <>
          <button className="button primary" disabled={busy || !task.launchable} onClick={() => onLaunch(task)}><Play size={12} weight="fill" />{task.launchable ? "开始练习" : "练习不可用"}</button>
          <button className="button secondary complete-action" disabled={busy} onClick={() => onCommand(task, "complete")}>仅标记已处理</button>
          <small className="completion-warning">“已处理”不是学习效果证据，也不更新 KT。</small>
        </>
      )}
      <button className="button secondary" disabled={busy} onClick={() => setPostponeOpen((open) => !open)}>推迟</button>
      <button className="button text-button" disabled={busy} onClick={() => onCommand(task, "skip")}>跳过</button>
      {postponeOpen && (
        <label className="postpone-control"><span>最早恢复到期日 / 进入轮候日</span><input type="date" min={tomorrowString(plan.planDate)} value={postponeUntil} onChange={(event) => setPostponeUntil(event.target.value)} /><small>实际展示仍受预算、公平轮转与已接受承诺影响。</small><button className="button secondary" disabled={busy} onClick={() => onCommand(task, "postpone", postponeUntil)}>确认推迟</button></label>
      )}
    </div>
  );
}

function TaskItem({ task, plan, processing, onCommand, onLaunch }) {
  return (
    <article className="today-task" data-testid="today-task" data-task-id={task.id} data-state={task.state}>
      <header>
        <div><span>任务 {task.ordinal}</span><h2>{TASK_KIND_COPY[task.taskKind]}</h2></div>
        <strong className={`task-state ${task.state}`}>{TASK_STATE_COPY[task.state]}</strong>
      </header>
      <p className="task-reason">{task.reason}</p>
      {task.causeStatusCopy && <p className="candidate-boundary"><Info size={13} /><span><strong>{task.causeStatusCopy}</strong> · {task.causeLabel}</span></p>}
      <dl className="task-definition-grid">
        <div><dt>预计时长</dt><dd>{task.expectedDurationMinutes} 分钟 <small>未校准工程估算</small></dd></div>
        <div><dt>当前到期日</dt><dd>{task.dueOn}</dd></div>
        <div><dt>任务类型</dt><dd><code>{task.taskKind}</code></dd></div>
        <div><dt>活动</dt><dd>{task.activityRef.availability === "launchable" ? "可启动" : "不可用"} · <code>{task.activityRef.fixtureId}</code></dd></div>
        <div className="wide"><dt>题目新颖性</dt><dd><strong>同题组独立复测</strong> · 不构成未见平行题上的迁移验证</dd></div>
        <div><dt>固定窗口</dt><dd>+{task.policyOffsetDays} 天 <small>未校准工程规则</small></dd></div>
        <div><dt>窗口日期</dt><dd>基准 {task.baseDueOn}<br />首次排入 {task.initialDueOn}</dd></div>
        <div className="wide"><dt>成功标准</dt><dd>{task.successCriterion}</dd></div>
        <div className="wide"><dt>跳过后果</dt><dd>{task.skipConsequence}</dd></div>
      </dl>
      <p className={`schedule-truth ${task.schedulingAdjustment}`}><CalendarBlank size={13} /><span>{task.scheduleTruthCopy}</span></p>
      <section className="task-evidence"><div className="task-evidence-heading"><strong>结构化证据引用</strong><span>{task.evidenceRefs.length} 条</span></div><EvidenceRows refs={task.evidenceRefs} /></section>
      {task.activityRef.availability !== "launchable" || !task.launchable ? <p className="activity-boundary"><Info size={13} />只有 availability=launchable 且绑定当前增长率 fixture 的任务可以开始练习。</p> : null}
      <TaskActions task={task} plan={plan} processing={processing} onCommand={onCommand} onLaunch={onLaunch} />
    </article>
  );
}

export function TodayPracticeScreen({ planning, onCreate, onCommand, onLaunchTask }) {
  const [title, detail] = planStateCopy(planning);
  const plan = planning.plan;
  const createDisabled = !["not-created"].includes(planning.phase);
  return (
    <div className="screen today-practice-screen" data-testid="today-practice" data-state={planning.phase}>
      <div className="page-heading row-between"><div><h1>今日任务</h1><p>计划与复习安排彼此独立于学习轨迹和 KT。</p></div>{plan && <span className="plan-version">计划 v{plan.version}</span>}</div>
      <PlanningNotice notice={planning.notice} />
      {planning.phase === "loading" && <div className="planning-state"><Clock size={20} /><strong>{title}</strong><p>{detail}</p></div>}
      {planning.phase === "not-created" && <><div className="practice-intro"><ListChecks size={18} /><div><strong>{title}</strong><p>{detail}</p></div></div><CreatePlanForm onCreate={onCreate} processing={planning.processing === "create"} disabled={createDisabled} /></>}
      {(planning.phase === "offline" || planning.phase === "error") && <div className="planning-state error"><Info size={20} /><strong>{title}</strong><p>{detail}</p></div>}
      {planning.phase === "connected" && plan?.status === "empty" && <div className="planning-state empty"><CalendarBlank size={20} /><strong>{title}</strong><p>{detail}</p><small>ReviewSchedule 当前共 {planning.schedule?.count ?? "—"} 项；计划为空不代表任何掌握结论。</small></div>}
      {planning.phase === "connected" && plan?.tasks.length > 0 && (
        <><p className="today-display-boundary">今日计划中，已接受任务全部优先展示且不计入此上限；剩余预算最多再排 {plan.basis.workloadGuardrail.maxNonAcceptedTasks} 项尚未接受的任务。候选任务会完整持久进入 ReviewSchedule，当前排程共 {planning.schedule?.count ?? "—"} 项。</p><div className="today-task-list">{plan.tasks.map((task) => <TaskItem key={task.id} task={task} plan={plan} processing={planning.processing} onCommand={onCommand} onLaunch={onLaunchTask} />)}</div></>
      )}
    </div>
  );
}

export function ReviewScheduleReport({ planning }) {
  const schedule = planning.schedule;
  if (!schedule) {
    return <div className="empty-state report-empty" data-testid="review-schedule-report" data-source="unavailable"><strong>复习安排不可用</strong><p>当前不会根据技能报告或客户端缓存推算任务。</p></div>;
  }
  if (schedule.items.length === 0) {
    return <div className="empty-state report-empty" data-testid="review-schedule-report" data-source="sidecar"><strong>还没有复习任务</strong><p>只有完成的真实学习轨迹才能生成 ReviewSchedule 证据。</p></div>;
  }
  return (
    <div className="review-report" data-testid="review-schedule-report" data-source="sidecar">
      <p className="report-note">独立 ReviewSchedule 投影 · {schedule.count} 项。接受、标记处理、推迟与跳过都不写入学习轨迹或 KT。</p>
      <div className="review-report-table">
        <div className="review-report-row head"><span>任务</span><span>到期</span><span>状态</span><span>证据</span></div>
        {schedule.items.map((task) => (
          <div className="review-report-entry" key={task.id}>
            <div className="review-report-row"><span><strong>{TASK_KIND_COPY[task.taskKind]}</strong><small>{task.reason}</small><em>{task.scheduleTruthCopy}</em><em>同题组独立复测；不构成未见平行题上的迁移验证。</em></span><span>{task.dueOn}</span><span>{TASK_STATE_COPY[task.state]}</span><span>{task.evidenceRefs.length} 条</span></div>
            <div className="review-report-evidence"><EvidenceRows refs={task.evidenceRefs} /></div>
          </div>
        ))}
      </div>
    </div>
  );
}

export { TASK_KIND_COPY, TASK_STATE_COPY };
