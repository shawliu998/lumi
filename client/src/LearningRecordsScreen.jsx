import { useEffect, useId, useState } from "react";
import {
  ArrowRight,
  ChartBar,
  CheckCircle,
  ClipboardText,
  Clock,
  Info,
  ListChecks,
} from "@phosphor-icons/react";
import {
  fetchPracticeHistory,
  fetchPracticeProfile,
  fetchPracticeSessionReport,
  fetchWrongQuestionBook,
} from "./hermesApi";

const TABS = [
  { id: "recent", label: "最近练习", icon: Clock },
  { id: "evidence", label: "模块证据", icon: ChartBar },
  { id: "wrong", label: "错题", icon: ClipboardText },
];

const EVIDENCE_STATUS_LABELS = {
  no_evidence: "暂无独立证据",
  insufficient: "证据不足",
  needs_attention: "需要关注",
  developing: "证据仍在积累",
  consistent: "近期表现较一致",
};

const SESSION_STATUS_LABELS = {
  active: "进行中",
  completed: "已完成",
  ended_early: "提前结束",
};

const HYPOTHESIS_STATUS_LABELS = {
  evidence_insufficient: "证据不足",
  repeated_error_observed: "观察到重复",
  awaiting_disambiguation: "待辨析",
  supported_hypothesis: "有支持，仍是假设",
  awaiting_transfer_validation: "待迁移验证",
  weakened_by_transfer: "后续证据已减弱",
  persistent_or_recurrent: "重复出现",
  resolved_after_validation: "验证后已解除",
  hypothesis_withdrawn: "已撤回",
  voided: "已作废",
};

const CLOSED_HYPOTHESIS_STATES = new Set([
  "resolved_after_validation",
  "hypothesis_withdrawn",
  "voided",
]);

function createResourceState(phase = "idle") {
  return { phase, data: null, error: "" };
}

function createRecordsState(phase = "idle") {
  return {
    history: createResourceState(phase),
    profile: createResourceState(phase),
    wrong: createResourceState(phase),
  };
}

function readError(error, label) {
  if (error?.kind === "contract") return `${label}数据格式与当前客户端不兼容。`;
  if (error?.status === 404) return `当前本机服务版本尚未提供${label}。`;
  return `暂时无法读取${label}；已保存的学习记录不会受影响。`;
}

function formatAccuracy(value) {
  return typeof value === "number" && Number.isFinite(value)
    ? `${Math.round(value * 100)}%`
    : "暂无证据";
}

function formatDuration(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "暂无记录";
  if (value < 60) return `${Math.round(value)} 秒`;
  const minutes = Math.floor(value / 60);
  const seconds = Math.round(value % 60);
  return seconds > 0 ? `${minutes} 分 ${seconds} 秒` : `${minutes} 分钟`;
}

function formatCount(value, unit) {
  return Number.isInteger(value) && value >= 0 ? `${value} ${unit}` : "未记录";
}

function formatDateTime(value) {
  if (!value) return "时间未记录";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "时间未记录";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "long",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function RecordsLoading({ label }) {
  return (
    <div className="records-state" role="status">
      <span className="records-spinner" aria-hidden="true" />
      <strong>正在读取{label}</strong>
      <p>读取过程不会追加作答或改变学习状态。</p>
    </div>
  );
}

function RecordsError({ message, onRetry }) {
  return (
    <div className="records-state records-state-error" role="alert">
      <Info size={24} />
      <strong>记录暂未显示</strong>
      <p>{message}</p>
      <button type="button" className="records-secondary-action" onClick={onRetry}>重新读取</button>
    </div>
  );
}

function RecordsEmpty({ title, description, onStartPractice }) {
  return (
    <div className="records-state records-state-empty">
      <ListChecks size={25} />
      <strong>{title}</strong>
      <p>{description}</p>
      {typeof onStartPractice === "function" && (
        <button type="button" className="records-primary-action" onClick={() => onStartPractice()}>
          开始一组 8 题 <ArrowRight size={15} />
        </button>
      )}
    </div>
  );
}

function HypothesisList({ items, compact = false }) {
  const hypotheses = Array.isArray(items) ? items : [];
  if (!hypotheses.length) return null;
  return (
    <div className={compact ? "records-hypothesis-list is-compact" : "records-hypothesis-list"}>
      {hypotheses.map((item) => {
        const candidate = Array.isArray(item.cause_candidates) ? item.cause_candidates[0] : null;
        const closed = CLOSED_HYPOTHESIS_STATES.has(item.status);
        return (
          <article key={item.hypothesis_id || `${item.signature_label}-${item.status}`}>
            <div>
              <strong>{item.signature_label || "观察到的错误选项模式"}</strong>
              <small>{candidate?.label
                ? `${closed ? "原假设" : "可能原因"}：${candidate.label}`
                : closed ? "该假设已结束" : "可能原因仍待继续验证"}</small>
            </div>
            <span className={closed ? "is-closed" : ""}>
              {HYPOTHESIS_STATUS_LABELS[item.status] || "状态待确认"}
            </span>
          </article>
        );
      })}
    </div>
  );
}

function SessionEvidence({ sessionId }) {
  const [resource, setResource] = useState(createResourceState());

  const load = () => {
    if (resource.phase === "loading" || resource.phase === "ready") return;
    setResource(createResourceState("loading"));
    fetchPracticeSessionReport(sessionId)
      .then((data) => setResource({ phase: "ready", data, error: "" }))
      .catch((error) => setResource({
        phase: "error",
        data: null,
        error: readError(error, "本组证据链"),
      }));
  };

  const report = resource.data;
  const verified = report?.audit?.trace_verified === true
    && report?.audit?.semantic_replay_verified === true;
  return (
    <details className="records-session-evidence" onToggle={(event) => event.currentTarget.open && load()}>
      <summary>查看本组证据链</summary>
      <div>
        {resource.phase === "idle" || resource.phase === "loading" ? (
          <p role="status"><span className="records-spinner" aria-hidden="true" />正在核对本组轨迹</p>
        ) : resource.phase === "error" ? (
          <div className="records-session-evidence-error" role="alert">
            <p>{resource.error}</p>
            <button type="button" className="records-secondary-action" onClick={load}>重新读取</button>
          </div>
        ) : (
          <>
            <div className="records-session-evidence-status">
              {verified ? <CheckCircle size={17} weight="fill" /> : <Info size={17} />}
              <span>
                <strong>{verified ? "轨迹与语义回放已验证" : "证据验证状态不完整"}</strong>
                <small>{report.audit?.rebuildable ? "本组结果可从追加式本机轨迹重建。" : "当前报告未声明可重建。"}</small>
              </span>
            </div>
            {report.error_hypotheses?.length > 0 ? (
              <HypothesisList items={report.error_hypotheses} compact />
            ) : (
              <p className="records-hypothesis-empty">本组没有形成可展示的错误原因假设。</p>
            )}
          </>
        )}
      </div>
    </details>
  );
}

function RecentPractice({ resource, onRetry, onStartPractice }) {
  if (resource.phase === "loading" || resource.phase === "idle") return <RecordsLoading label="最近练习" />;
  if (resource.phase === "error") return <RecordsError message={resource.error} onRetry={onRetry} />;

  const items = resource.data?.items || [];
  if (items.length === 0) {
    return (
      <RecordsEmpty
        title="还没有练习记录"
        description="完成或提前结束一组练习后，这里会显示由本机轨迹重建的事实记录。"
        onStartPractice={onStartPractice}
      />
    );
  }

  return (
    <>
      <div className="records-session-list">
        {items.map((session) => (
          <article className="records-session-row" key={session.session_id}>
          <header className="records-session-heading">
            <div>
              <small>{formatDateTime(session.started_at)}</small>
              <h3>{session.title || session.module_label || "行测练习"}</h3>
            </div>
            <span className={`records-session-status records-session-status-${session.status || "unknown"}`}>
              {SESSION_STATUS_LABELS[session.status] || "状态未记录"}
            </span>
          </header>
          <dl className="records-session-facts">
            <div><dt>普通题作答</dt><dd>{formatCount(session.question_attempt_count, "题")}</dd></div>
            <div><dt>正确</dt><dd>{formatCount(session.correct_count, "题")}</dd></div>
            <div><dt>正确率</dt><dd>{formatAccuracy(session.accuracy)}</dd></div>
            <div><dt>探查或跳过</dt><dd>{formatCount(session.probe_or_skip_count, "个题位")}</dd></div>
          </dl>
          <p className="records-session-note">
            {Number.isInteger(session.answered_count) && Number.isInteger(session.target_count)
              ? `本组占用 ${session.answered_count} / ${session.target_count} 个题位；普通题与可选探查分开统计。`
              : "本组题位记录不完整；普通题与可选探查仍保持分开统计。"}
          </p>
          <SessionEvidence sessionId={session.session_id} />
          </article>
        ))}
      </div>
      {resource.data.total > items.length && (
        <p className="records-truncation-note">当前显示最近 {items.length} 组；更早记录仍保存在本机。</p>
      )}
    </>
  );
}

function ModuleEvidence({ resource, onRetry, onStartPractice }) {
  if (resource.phase === "loading" || resource.phase === "idle") return <RecordsLoading label="模块证据" />;
  if (resource.phase === "error") return <RecordsError message={resource.error} onRetry={onRetry} />;

  const profile = resource.data;
  const overall = profile?.overall;
  const modules = profile?.modules || [];
  if (!overall || overall.scored_attempt_count === 0) {
    return (
      <RecordsEmpty
        title="暂无可汇总的作答证据"
        description="这里不会用示例数据或空值补出掌握度。完成第一组真实练习后再回来查看。"
        onStartPractice={onStartPractice}
      />
    );
  }

  return (
    <div className="records-evidence-document">
      <section className="records-overall" aria-labelledby="records-overall-title">
        <header>
          <div>
            <small>截至 {formatDateTime(profile.as_of)}</small>
            <h3 id="records-overall-title">全部已记录作答</h3>
          </div>
          <span>{overall.scored_attempt_count} 次已判分作答</span>
        </header>
        <dl className="records-overall-facts">
          <div><dt>已完成练习</dt><dd>{overall.completed_session_count} 组</dd></div>
          <div><dt>作答正确率</dt><dd>{formatAccuracy(overall.accuracy)}</dd></div>
          <div><dt>独立证据</dt><dd>{overall.independent_attempt_count} 次</dd></div>
          <div><dt>平均作答时间</dt><dd>{formatDuration(overall.average_response_time_seconds)}</dd></div>
        </dl>
        <p className="records-policy-note">
          {profile.evidence_policy?.note || "正确率是作答事实，不代表掌握度；模块判断只使用符合条件的独立证据。"}
        </p>
      </section>

      <section className="records-module-section" aria-labelledby="records-module-title">
        <header className="records-section-heading">
          <h3 id="records-module-title">四模块证据</h3>
          <p>空值保持为“暂无证据”，不按 0% 展示。</p>
        </header>
        <div className="records-module-list">
          {modules.map((module) => (
            <article className="records-module-row" key={module.module_id}>
              <div className="records-module-name">
                <h4>{module.module_label}</h4>
                <span>{EVIDENCE_STATUS_LABELS[module.evidence_status] || "证据状态未记录"}</span>
              </div>
              <dl className="records-module-facts">
                <div><dt>全部作答</dt><dd>{module.facts.attempt_count} 次</dd></div>
                <div><dt>作答正确率</dt><dd>{formatAccuracy(module.facts.accuracy)}</dd></div>
                <div><dt>独立作答</dt><dd>{module.independent_evidence.attempt_count} 次</dd></div>
                <div><dt>独立题族</dt><dd>{module.independent_evidence.distinct_family_count} 个</dd></div>
              </dl>
            </article>
          ))}
        </div>
      </section>

      <section className="records-hypothesis-section" aria-labelledby="records-hypothesis-title">
        <header className="records-section-heading">
          <div>
            <h3 id="records-hypothesis-title">待验证错误模式</h3>
            <p>错误原因始终是可撤销假设，不是对学习者心理的定论。</p>
          </div>
        </header>
        {profile.error_hypotheses.length > 0 ? (
          <HypothesisList items={profile.error_hypotheses} />
        ) : (
          <p className="records-hypothesis-empty">当前没有形成可展示的跨题错误模式。</p>
        )}
      </section>
    </div>
  );
}

function WrongQuestions({ resource, onRetry, onStartPractice }) {
  if (resource.phase === "loading" || resource.phase === "idle") return <RecordsLoading label="错题" />;
  if (resource.phase === "error") return <RecordsError message={resource.error} onRetry={onRetry} />;

  const items = resource.data?.items || [];
  if (items.length === 0) {
    return (
      <RecordsEmpty
        title="暂无待复习错题"
        description="只有真实答错且最近一次仍未解决的题目会显示在这里。"
        onStartPractice={onStartPractice}
      />
    );
  }

  return (
    <>
      <div className="records-wrong-list">
        {items.map((item) => (
          <details className="records-wrong-row" key={`${item.id}-${item.questionVersionId}`}>
          <summary>
            <span className="records-wrong-summary">
              <small>{item.moduleLabel}</small>
              <strong>{item.prompt}</strong>
            </span>
            <span className="records-wrong-count">{item.wrongAttempts} 次答错</span>
          </summary>
          <div className="records-wrong-detail">
            <dl>
              <div><dt>最近答案</dt><dd>{item.lastSelectedOption || "未记录"}</dd></div>
              <div><dt>正确答案</dt><dd>{item.correctOption || "未记录"}</dd></div>
              <div><dt>独立答错</dt><dd>{item.independentWrongAttempts} 次</dd></div>
            </dl>
            {item.keyPrinciple && <p><strong>关键点：</strong>{item.keyPrinciple}</p>}
            {item.explanation && (
              <details className="records-wrong-explanation">
                <summary>展开完整解析</summary>
                <p>{item.explanation}</p>
              </details>
            )}
            {item.diagnosisHypotheses.length > 0 && (
              <section className="records-wrong-hypotheses" aria-label="与这道题相关的可撤销假设">
                <strong>与这道题相关的可撤销假设</strong>
                <HypothesisList items={item.diagnosisHypotheses} compact />
              </section>
            )}
            <small>题目版本：{item.questionVersionId}</small>
          </div>
          </details>
        ))}
      </div>
      {resource.data.total > items.length && (
        <p className="records-truncation-note">当前显示最近 {items.length} 道待复习错题；其余记录仍保存在本机。</p>
      )}
    </>
  );
}

export function LearningRecordsScreen({ sidecar, onStartPractice, onRetrySidecar }) {
  const [activeTab, setActiveTab] = useState("recent");
  const [reloadKey, setReloadKey] = useState(0);
  const [records, setRecords] = useState(() => createRecordsState());
  const tabPrefix = useId();

  useEffect(() => {
    if (sidecar?.phase !== "connected") {
      setRecords(createRecordsState());
      return undefined;
    }

    let active = true;
    setRecords(createRecordsState("loading"));
    Promise.allSettled([
      fetchPracticeHistory({ limit: 100 }),
      fetchPracticeProfile(),
      fetchWrongQuestionBook({ limit: 100, state: "needs_review" }),
    ]).then(([historyResult, profileResult, wrongResult]) => {
      if (!active) return;
      const toResource = (result, label) => result.status === "fulfilled"
        ? { phase: "ready", data: result.value, error: "" }
        : { phase: "error", data: null, error: readError(result.reason, label) };
      setRecords({
        history: toResource(historyResult, "最近练习"),
        profile: toResource(profileResult, "模块证据"),
        wrong: toResource(wrongResult, "错题"),
      });
    });

    return () => { active = false; };
  }, [sidecar?.phase, reloadKey]);

  const retryRecords = () => setReloadKey((value) => value + 1);
  const moveTabFocus = (event, currentId) => {
    const currentIndex = TABS.findIndex((tab) => tab.id === currentId);
    let nextIndex = currentIndex;
    if (event.key === "ArrowRight") nextIndex = (currentIndex + 1) % TABS.length;
    else if (event.key === "ArrowLeft") nextIndex = (currentIndex - 1 + TABS.length) % TABS.length;
    else if (event.key === "Home") nextIndex = 0;
    else if (event.key === "End") nextIndex = TABS.length - 1;
    else return;
    event.preventDefault();
    const nextId = TABS[nextIndex].id;
    setActiveTab(nextId);
    window.requestAnimationFrame(() => document.getElementById(`${tabPrefix}-${nextId}-tab`)?.focus());
  };
  const activeResource = activeTab === "recent"
    ? records.history
    : activeTab === "evidence"
      ? records.profile
      : records.wrong;

  if (sidecar?.phase !== "connected") {
    const checking = sidecar?.phase === "checking";
    return (
      <section className="records-screen" aria-labelledby={`${tabPrefix}-title`}>
        <header className="records-page-heading">
          <div><span>行测 · 本机学习记录</span><h1 id={`${tabPrefix}-title`}>学习记录</h1></div>
        </header>
        <div className="records-state records-state-offline" role={checking ? "status" : "alert"}>
          <Info size={26} />
          <strong>{checking ? "正在连接本机记录" : "本机记录服务未连接"}</strong>
          <p>{checking ? "首次启动通常只需片刻。" : "连接恢复后会重新读取真实记录，不会填充示例数据。"}</p>
          {!checking && typeof onRetrySidecar === "function" && (
            <button type="button" className="records-primary-action" onClick={onRetrySidecar}>重新连接</button>
          )}
        </div>
      </section>
    );
  }

  return (
    <section className="records-screen" aria-labelledby={`${tabPrefix}-title`}>
      <header className="records-page-heading">
        <div>
          <span>行测 · 本机学习记录</span>
          <h1 id={`${tabPrefix}-title`}>学习记录</h1>
          <p>所有结果都来自已接受的本机作答轨迹；事实、独立证据与可撤销假设分开记录。</p>
        </div>
        {typeof onStartPractice === "function" && (
          <button type="button" className="records-primary-action" onClick={() => onStartPractice()}>
            继续刷题 <ArrowRight size={15} />
          </button>
        )}
      </header>

      <div className="records-tabs" role="tablist" aria-label="学习记录类型">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button
            type="button"
            id={`${tabPrefix}-${id}-tab`}
            className={activeTab === id ? "records-tab records-tab-active" : "records-tab"}
            role="tab"
            aria-selected={activeTab === id}
            aria-controls={`${tabPrefix}-${id}-panel`}
            tabIndex={activeTab === id ? 0 : -1}
            onClick={() => setActiveTab(id)}
            onKeyDown={(event) => moveTabFocus(event, id)}
            key={id}
          >
            <Icon size={16} />{label}
          </button>
        ))}
      </div>

      <div
        className="records-tab-panel"
        id={`${tabPrefix}-${activeTab}-panel`}
        role="tabpanel"
        aria-labelledby={`${tabPrefix}-${activeTab}-tab`}
        aria-busy={activeResource.phase === "loading"}
      >
        {activeTab === "recent" && (
          <RecentPractice resource={records.history} onRetry={retryRecords} onStartPractice={onStartPractice} />
        )}
        {activeTab === "evidence" && (
          <ModuleEvidence resource={records.profile} onRetry={retryRecords} onStartPractice={onStartPractice} />
        )}
        {activeTab === "wrong" && (
          <WrongQuestions resource={records.wrong} onRetry={retryRecords} onStartPractice={onStartPractice} />
        )}
      </div>

      <footer className="records-footer-note">
        <CheckCircle size={14} />
        <span>读取记录不会追加作答、改变证据状态或创建新的学习任务。</span>
      </footer>
    </section>
  );
}
