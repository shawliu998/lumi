import { useEffect, useMemo, useState } from "react";
import { ArrowRight, Info } from "@phosphor-icons/react";
import {
  endSmartPracticeSession,
  fetchPracticeOverview,
  startSmartPracticeSession,
  submitSmartPracticeAnswer,
  submitSmartPracticeProbe,
} from "./hermesApi";
import {
  DEFAULT_SMART_PRACTICE_SCOPE_ID,
  getSmartPracticeScope,
  SMART_PRACTICE_SCOPES,
} from "./practiceScopes";
import { SmartPracticeWorkspace } from "./SmartPracticeWorkspace";
import { PageHeader } from "./AppShell";

function practiceReadError(error) {
  if (error?.status === 404) return "当前本机服务版本尚未提供学习概览。";
  if (error?.kind === "contract") return "学习概览格式暂不兼容，未展示替代数据。";
  return "暂时无法读取学习概览；刷题功能仍可正常使用。";
}

export function PracticeScreen({
  sidecar,
  onRetrySidecar,
  onRefreshSkills,
  initialScopeId = DEFAULT_SMART_PRACTICE_SCOPE_ID,
  launchRequest = 0,
  onLaunchHandled,
  onOpenRecords,
}) {
  const [workspaceOpen, setWorkspaceOpen] = useState(false);
  const [closingWorkspace, setClosingWorkspace] = useState(false);
  const [closeError, setCloseError] = useState("");
  const [selectedScopeId, setSelectedScopeId] = useState(() => getSmartPracticeScope(initialScopeId).scopeId);
  const [overviewState, setOverviewState] = useState({ phase: "idle", data: null, error: "" });
  const moduleScopes = useMemo(() => SMART_PRACTICE_SCOPES.filter((scope) => !scope.mixed), []);
  const mixedScope = useMemo(() => SMART_PRACTICE_SCOPES.find((scope) => scope.mixed), []);
  const selectedScope = getSmartPracticeScope(selectedScopeId);
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
        error: practiceReadError(error),
      }));
    return () => { active = false; };
  }, [sidecar.phase]);

  useEffect(() => {
    if (activeSession?.scopeId) setSelectedScopeId(activeSession.scopeId);
  }, [activeSession?.scopeId]);

  useEffect(() => {
    if (!activeSession?.scopeId && initialScopeId) {
      setSelectedScopeId(getSmartPracticeScope(initialScopeId).scopeId);
    }
  }, [activeSession?.scopeId, initialScopeId]);

  useEffect(() => {
    if (launchRequest > 0 && sidecar.phase === "connected" && !closingWorkspace) {
      setCloseError("");
      setWorkspaceOpen(true);
      onLaunchHandled?.();
    }
  }, [closingWorkspace, launchRequest, onLaunchHandled, sidecar.phase]);

  const refreshPracticeOverview = async () => {
    try {
      const data = await fetchPracticeOverview();
      setOverviewState({ phase: "ready", data, error: "" });
      return data;
    } catch (error) {
      setOverviewState({ phase: "error", data: null, error: practiceReadError(error) });
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
    if (closingWorkspace) return;
    setClosingWorkspace(true);
    setWorkspaceOpen(false);
    setCloseError("");
    try {
      if (sessionId && reason !== "completed") {
        await endSmartPracticeSession({ sessionId, reason: "learner_ended_early" });
      }
    } catch (error) {
      setCloseError(error?.message || "本组退出状态暂未保存；重新打开后会尝试恢复。");
    } finally {
      try {
        await onRefreshSkills?.();
        await refreshPracticeOverview();
      } finally {
        setClosingWorkspace(false);
      }
    }
  };

  if (sidecar.phase !== "connected") {
    return (
      <div className="lumi-page practice-page-v2">
        <PageHeader title="选择本组范围" description="每组固定八题，答案是唯一必填项。" />
        <div className="practice-v2-unavailable" role={sidecar.phase === "checking" ? "status" : "alert"}>
          {sidecar.phase === "checking" ? <span className="lumi-status-spinner" /> : <Info size={25} />}
          <div>
            <h2>{sidecar.phase === "checking" ? "正在准备本机题库" : "本机题库暂时不可用"}</h2>
            <p>{sidecar.phase === "checking" ? "读取完成后会自动显示练习范围。" : "重新连接后可以继续未完成的一组；已有作答不会被清空。"}</p>
          </div>
          {sidecar.phase !== "checking" && <button type="button" className="lumi-button is-primary" onClick={onRetrySidecar}>重新连接</button>}
        </div>
      </div>
    );
  }

  const recommendedScopeId = overviewState.phase === "ready"
    ? overviewState.data.recommendedScopeId
    : "";
  const orderedScopes = mixedScope ? [mixedScope, ...moduleScopes] : moduleScopes;

  return (
    <div className="lumi-page practice-page-v2">
      <PageHeader
        eyebrow="行测 · Core-320"
        title="选择本组范围"
        description="选择后立即进入固定八题；系统只在重复错误形成证据时增加教学介入。"
        action={typeof onOpenRecords === "function" ? (
          <button type="button" className="lumi-text-button" onClick={onOpenRecords}>查看学习记录</button>
        ) : null}
      />

      <div className="practice-v2-layout">
        <fieldset className="practice-v2-scope-list" disabled={Boolean(activeSession)}>
          <legend>练习范围</legend>
          {orderedScopes.map((scope) => {
            const selected = selectedScopeId === scope.scopeId;
            const recommended = !activeSession && recommendedScopeId === scope.scopeId;
            return (
              <label className={selected ? "is-selected" : ""} key={scope.scopeId}>
                <input
                  className="sr-only"
                  type="radio"
                  name="smart-practice-scope"
                  value={scope.scopeId}
                  checked={selected}
                  onChange={(event) => setSelectedScopeId(event.target.value)}
                />
                <span className="practice-v2-scope-mark" aria-hidden="true" />
                <span className="practice-v2-scope-copy">
                  <span><strong>{scope.mixed ? "智能刷题" : scope.label}</strong>{recommended && <em>建议</em>}</span>
                  <small>{scope.focus}</small>
                </span>
                <span className="practice-v2-scope-count">{scope.mixed ? "四模块" : `${scope.poolSize} 题`}</span>
              </label>
            );
          })}
          {activeSession && <p>已有一组未完成练习，完成或结束后才能切换范围。</p>}
        </fieldset>

        <section className="practice-v2-start" aria-labelledby="practice-v2-start-title">
          <span>{activeSession ? `未完成 · ${activeSession.answeredCount} / ${activeSession.targetCount}` : "本组安排"}</span>
          <h2 id="practice-v2-start-title">{activeSession ? `继续${entryScope.label}` : `${entryScope.mixed ? "智能刷题" : entryScope.label} · 8 题`}</h2>
          <p>{entryScope.description}</p>
          <dl>
            <div><dt>需要填写</dt><dd>只选答案</dd></div>
            <div><dt>完整解析</dt><dd>按需展开</dd></div>
            <div><dt>预计用时</dt><dd>{activeSession ? `剩 ${activeSession.targetCount - activeSession.answeredCount} 个题位` : "6–8 分钟"}</dd></div>
          </dl>
          <button
            type="button"
            className="lumi-button is-primary practice-v2-start-button"
            disabled={closingWorkspace}
            onClick={() => { setCloseError(""); setWorkspaceOpen(true); }}
          >
            {closingWorkspace ? "正在结束上一组" : activeSession ? "继续本组" : "开始作答"}<ArrowRight size={16} />
          </button>
          <small>正确时快速前进；首次错误只显示最短必要纠偏。</small>
        </section>
      </div>

      {overviewState.phase === "error" && (
        <p className="practice-v2-inline-status" role="status"><Info size={15} />{overviewState.error}</p>
      )}
      {closingWorkspace && <p className="practice-v2-inline-status" role="status"><span className="lumi-status-spinner" />正在确认本组退出状态</p>}
      {closeError && <p className="practice-v2-inline-status is-error" role="alert"><Info size={15} />{closeError}</p>}

      {workspaceOpen && (
        <SmartPracticeWorkspace
          startSession={startContinuousSession}
          submitAnswer={submitSmartPracticeAnswer}
          submitProbe={submitSmartPracticeProbe}
          close={closeSmartPractice}
        />
      )}
    </div>
  );
}
