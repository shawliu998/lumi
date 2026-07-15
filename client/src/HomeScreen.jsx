import { useEffect, useMemo, useState } from "react";
import {
  ArrowRight,
  ChartBar,
  CheckCircle,
  Clock,
  Info,
  ListChecks,
  NotePencil,
  Target,
} from "@phosphor-icons/react";
import { fetchPracticeOverview } from "./hermesApi";
import { PageHeader } from "./AppShell";
import { getSmartPracticeScope, SMART_PRACTICE_SCOPES } from "./practiceScopes";

const MODULE_ICONS = {
  verbal: NotePencil,
  judgment: ListChecks,
  quantitative: Target,
  "data-analysis": ChartBar,
};

function recommendationReason(overview) {
  if (!overview) return "完成第一组后，Lumi 会依据真实作答给出下一步建议。";
  if (overview.activeSession) return `上次停在第 ${overview.activeSession.answeredCount + 1} 题，继续即可，不会新建一组。`;
  if (overview.profile.overall.scored_attempt_count === 0) return "还没有足够证据，先从四模块混合练习建立第一组基线。";
  const reasons = overview.recommendation?.decision?.reason_codes || [];
  if (reasons.some((reason) => !reason.startsWith("no_") && reason.includes("supported_weakness"))) {
    return "最近跨场次、跨题族的独立作答证据集中在这个范围。";
  }
  return "当前证据不足以改变方向，继续这个范围最稳妥。";
}

function recentSessionCopy(session) {
  if (!session) return null;
  const scope = getSmartPracticeScope(session.scopeId);
  const answered = session.answeredCount;
  const questionAttempts = session.questionAttemptCount;
  const correct = session.correctCount;
  return {
    title: session.status === "active" ? `${scope.label} · 未完成` : `${scope.label} · 最近一组`,
    meta: Number.isInteger(questionAttempts) && questionAttempts > 0 && Number.isInteger(correct)
      ? `普通题答对 ${correct} / ${questionAttempts}`
      : `完成 ${answered} / 8 个题位`,
    scopeId: scope.scopeId,
  };
}

export function HomeScreen({ sidecar, onStartPractice, onOpenRecords, onRetrySidecar }) {
  const [overviewState, setOverviewState] = useState({ phase: "idle", data: null, error: "" });
  const moduleScopes = useMemo(() => SMART_PRACTICE_SCOPES.filter((scope) => !scope.mixed), []);

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
        error: error?.message || "暂时无法读取本机学习记录。",
      }));
    return () => { active = false; };
  }, [sidecar.phase]);

  const overview = overviewState.data;
  const recommendedScope = getSmartPracticeScope(
    overview?.activeSession?.scopeId || overview?.recommendedScopeId || "xingce.mixed.core",
  );
  const recent = recentSessionCopy(overview?.recentSessions?.[0]);
  const primaryLabel = overview?.activeSession
    ? `继续本组 ${overview.activeSession.answeredCount} / ${overview.activeSession.targetCount}`
    : "开始一组";

  if (sidecar.phase !== "connected") {
    const checking = sidecar.phase === "checking";
    return (
      <div className="lumi-page home-page">
        <PageHeader title="今天，从一道题开始" description="Lumi 会把练习、最小反馈和后续验证组织在同一个八题节奏里。" />
        <section className="home-unavailable" role={checking ? "status" : "alert"}>
          {checking ? <span className="lumi-status-spinner" /> : <Info size={24} />}
          <div>
            <h2>{checking ? "正在准备本机题库" : "本机题库暂时不可用"}</h2>
            <p>{checking ? "读取完成后即可直接开始，不需要登录。" : "重新连接不会清空已有作答和未完成会话。"}</p>
          </div>
          {!checking && <button type="button" className="lumi-button is-primary" onClick={onRetrySidecar}>重新连接</button>}
        </section>
      </div>
    );
  }

  return (
    <div className="lumi-page home-page">
      <PageHeader
        eyebrow="Lumi · 行测"
        title="今天，从一道题开始"
        description="专注完成一组；需要时才展开讲解。"
      />

      <section className="home-recommendation" aria-labelledby="home-recommendation-title">
        <div className="home-recommendation-kicker">
          <span aria-hidden="true">01</span>
          <span>今天建议</span>
        </div>
        <div className="home-recommendation-copy">
          <h2 id="home-recommendation-title">{recommendedScope.label} · 固定 8 题</h2>
          <p>{recommendationReason(overview)}</p>
          <div className="home-recommendation-meta">
            <span><CheckCircle size={15} />答案是唯一必填项</span>
            <span><Clock size={15} />约 6–8 分钟</span>
          </div>
        </div>
        <button
          type="button"
          className="lumi-button is-primary home-primary-action"
          onClick={() => onStartPractice(recommendedScope.scopeId)}
        >
          {primaryLabel}<ArrowRight size={17} />
        </button>
      </section>

      {overviewState.phase === "loading" && (
        <p className="home-read-status" role="status"><span className="lumi-status-spinner" />正在整理本机练习建议</p>
      )}
      {overviewState.phase === "error" && (
        <p className="home-read-status is-error" role="status"><Info size={15} />学习建议暂未更新，仍可直接刷题。</p>
      )}

      <section className="home-modules" aria-labelledby="home-modules-title">
        <div className="lumi-section-heading">
          <div><span>快速选择</span><h2 id="home-modules-title">按模块开始</h2></div>
          <button type="button" className="lumi-text-button" onClick={() => onStartPractice("xingce.mixed.core")}>混合练习</button>
        </div>
        <div className="home-module-list">
          {moduleScopes.map((scope) => {
            const Icon = MODULE_ICONS[scope.key] || Target;
            return (
              <button type="button" key={scope.scopeId} onClick={() => onStartPractice(scope.scopeId)}>
                <span className={`home-module-icon is-${scope.key}`}><Icon size={20} /></span>
                <span><strong>{scope.label}</strong><small>{scope.focus}</small></span>
                <ArrowRight size={15} />
              </button>
            );
          })}
        </div>
      </section>

      <section className="home-recent" aria-labelledby="home-recent-title">
        <div className="lumi-section-heading">
          <div><span>学习记录</span><h2 id="home-recent-title">最近一组</h2></div>
          <button type="button" className="lumi-text-button" onClick={onOpenRecords}>查看记录</button>
        </div>
        {recent ? (
          <button type="button" className="home-recent-row" onClick={() => onStartPractice(recent.scopeId)}>
            <span><strong>{recent.title}</strong><small>{recent.meta}</small></span>
            <span>继续这个范围<ArrowRight size={15} /></span>
          </button>
        ) : (
          <div className="home-recent-empty">
            <p>还没有练习记录。完成第一组后，这里只保留一条简短结果。</p>
          </div>
        )}
      </section>
    </div>
  );
}
