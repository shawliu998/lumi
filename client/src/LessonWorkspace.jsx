import { useEffect, useId, useMemo, useRef, useState } from "react";
import {
  ArrowRight,
  CheckCircle,
  Clock,
  Info,
  Lightbulb,
  LockKey,
  X,
} from "@phosphor-icons/react";
import { continueAttempt, submitAttempt } from "./hermesApi";
import {
  normalizeLessonPolicy,
  recordInitialAnswer,
  recordVerification,
} from "./lessonProgress";
import "./lesson.css";

const CONFIDENCE_VALUES = { low: 0.35, medium: 0.65, high: 0.9 };

function createRunId() {
  const suffix = globalThis.crypto?.randomUUID?.()
    || `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
  return `lesson-${suffix}`;
}

function normalizeItems(lesson) {
  const rawItems = Array.isArray(lesson?.practice_items)
    ? lesson.practice_items
    : Array.isArray(lesson?.practice_fixtures)
      ? lesson.practice_fixtures
      : [];
  return rawItems.map((item) => ({
    fixture_id: item?.fixture_id,
    prompt: item?.prompt || item?.task?.prompt || "",
    response_mode: item?.response_mode || item?.task?.response_mode || "short_text",
    options: item?.options || item?.task?.options || {},
  })).filter((item) => item.fixture_id && item.prompt);
}

function optionEntries(value) {
  return value && typeof value === "object" && !Array.isArray(value)
    ? Object.entries(value)
    : [];
}

function ConfidenceField({ value, onChange, disabled = false }) {
  return (
    <label className="lesson-confidence">
      <span>作答信心</span>
      <select value={value} onChange={(event) => onChange(event.target.value)} disabled={disabled}>
        <option value="">请选择</option>
        <option value="low">不太确定</option>
        <option value="medium">基本确定</option>
        <option value="high">非常确定</option>
      </select>
    </label>
  );
}

function AnswerField({ answer, setAnswer, options, responseMode, name, disabled = false }) {
  const entries = optionEntries(options);
  if (entries.length > 0) {
    return (
      <fieldset className="lesson-options" disabled={disabled}>
        <legend>请选择一个答案</legend>
        {entries.map(([key, value]) => (
          <label className={answer === key ? "selected" : ""} key={key}>
            <input
              type="radio"
              name={name}
              value={key}
              checked={answer === key}
              onChange={(event) => setAnswer(event.target.value)}
            />
            <strong>{key}</strong>
            <span>{value}</span>
          </label>
        ))}
      </fieldset>
    );
  }
  return (
    <label className="lesson-answer-field">
      <span>你的回答</span>
      <textarea
        value={answer}
        onChange={(event) => setAnswer(event.target.value)}
        placeholder={responseMode === "spoken_text" ? "输入口述回答文本" : "写下答案或关键依据"}
        rows={3}
        disabled={disabled}
      />
    </label>
  );
}

export function LessonWorkspace({ lesson, onClose, onCompleted, onRefreshSkills }) {
  const titleId = useId();
  const answerName = useId();
  const workspaceRef = useRef(null);
  const closeRef = useRef(null);
  const completionAnnounced = useRef(false);
  const items = useMemo(() => normalizeItems(lesson), [lesson]);
  const policy = lesson?.completion_policy || {};
  const { minimumQuestions, requiredTransfers } = normalizeLessonPolicy(policy, items.length);

  const [view, setView] = useState("learn");
  const [exampleDraft, setExampleDraft] = useState("");
  const [exampleRevealed, setExampleRevealed] = useState(false);
  const [visibleHintCount, setVisibleHintCount] = useState(0);
  const [itemIndex, setItemIndex] = useState(0);
  const [phase, setPhase] = useState("question");
  const [resumePhase, setResumePhase] = useState("question");
  const [answer, setAnswer] = useState("");
  const [confidence, setConfidence] = useState("");
  const [startedAt, setStartedAt] = useState(Date.now());
  const [runId, setRunId] = useState(createRunId);
  const [session, setSession] = useState(null);
  const [answeredCount, setAnsweredCount] = useState(0);
  const [verifiedStreak, setVerifiedStreak] = useState(0);
  const [mistakeCount, setMistakeCount] = useState(0);
  const [teachingVisible, setTeachingVisible] = useState(false);
  const [roundResult, setRoundResult] = useState(null);
  const [error, setError] = useState(null);

  const method = lesson?.method_card || {};
  const example = lesson?.worked_example || {};
  const hints = Array.isArray(example?.hint_ladder) ? example.hint_ladder : [];
  const steps = Array.isArray(example?.steps) ? example.steps : [];
  const currentItem = items[itemIndex] || null;

  useEffect(() => {
    setView("learn");
    setExampleDraft("");
    setExampleRevealed(false);
    setVisibleHintCount(0);
    setItemIndex(0);
    setPhase("question");
    setResumePhase("question");
    setAnswer("");
    setConfidence("");
    setStartedAt(Date.now());
    setRunId(createRunId());
    setSession(null);
    setAnsweredCount(0);
    setVerifiedStreak(0);
    setMistakeCount(0);
    setTeachingVisible(false);
    setRoundResult(null);
    setError(null);
    completionAnnounced.current = false;
  }, [lesson?.lesson_id]);

  useEffect(() => {
    if (!lesson) return undefined;
    const previousFocus = document.activeElement;
    closeRef.current?.focus();
    const handleKeyDown = (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose?.();
        return;
      }
      if (event.key !== "Tab" || !workspaceRef.current) return;
      const focusable = [...workspaceRef.current.querySelectorAll(
        "button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex='-1'])",
      )];
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      previousFocus?.focus?.();
    };
  }, [lesson, onClose]);

  if (!lesson) return null;

  const resetAnswer = () => {
    setAnswer("");
    setConfidence("");
    setStartedAt(Date.now());
  };

  const fail = (nextError, retryPhase) => {
    setError(nextError);
    setResumePhase(retryPhase);
    setPhase("error");
  };

  const submitInitial = async () => {
    setPhase("submitting");
    setError(null);
    try {
      const result = await submitAttempt({
        fixtureId: currentItem.fixture_id,
        response: answer,
        confidence: CONFIDENCE_VALUES[confidence],
        responseTimeSeconds: (Date.now() - startedAt) / 1000,
        runId,
      });
      setSession(result);
      const nextProgress = recordInitialAnswer(
        { answeredCount, verifiedStreak, mistakeCount },
        result.attempt.score.passed,
      );
      setAnsweredCount(nextProgress.answeredCount);
      setMistakeCount(nextProgress.mistakeCount);
      resetAnswer();
      setPhase("key_step");
    } catch (nextError) {
      fail(nextError, "question");
    }
  };

  const submitKeyStep = async () => {
    setPhase("submitting");
    setError(null);
    try {
      const result = await continueAttempt({
        session: session?.attempt,
        phase: "probe",
        response: answer,
        confidence: CONFIDENCE_VALUES[confidence],
        responseTimeSeconds: (Date.now() - startedAt) / 1000,
      });
      setSession((current) => ({ ...current, ...result }));
      setTeachingVisible(false);
      resetAnswer();
      setPhase("verification");
    } catch (nextError) {
      fail(nextError, "key_step");
    }
  };

  const submitVerification = async () => {
    setPhase("submitting");
    setError(null);
    try {
      const result = await continueAttempt({
        session: session?.continuation,
        phase: "verification",
        response: answer,
        confidence: CONFIDENCE_VALUES[confidence],
        responseTimeSeconds: (Date.now() - startedAt) / 1000,
      });
      const merged = { ...session, ...result };
      const effective = result.continuation?.verification?.effective === true;
      const nextProgress = recordVerification(
        { answeredCount, verifiedStreak, mistakeCount },
        effective,
        { minimumQuestions, requiredTransfers },
      );
      setSession(merged);
      setAnsweredCount(nextProgress.answeredCount);
      setVerifiedStreak(nextProgress.verifiedStreak);
      setMistakeCount(nextProgress.mistakeCount);
      setRoundResult({
        complete: nextProgress.complete,
        effective,
        answeredCount: nextProgress.answeredCount,
        verifiedStreak: nextProgress.verifiedStreak,
        revealTeaching: nextProgress.revealTeaching,
      });
      resetAnswer();
      setPhase("round_result");
      Promise.resolve(onRefreshSkills?.()).catch(() => {});
      if (nextProgress.complete && !completionAnnounced.current) {
        completionAnnounced.current = true;
        onCompleted?.(lesson.lesson_id);
      }
    } catch (nextError) {
      fail(nextError, "verification");
    }
  };

  const submitActive = (event) => {
    event.preventDefault();
    if (!answer.trim() || !confidence || phase === "submitting") return;
    if (phase === "question") submitInitial();
    else if (phase === "key_step") submitKeyStep();
    else if (phase === "verification") submitVerification();
  };

  const continueAfterResult = () => {
    if (roundResult?.complete) {
      setView("complete");
      return;
    }
    setItemIndex((value) => (value + 1) % Math.max(1, items.length));
    setPhase("question");
    setResumePhase("question");
    setSession(null);
    setRoundResult(null);
    setTeachingVisible(false);
    setRunId(createRunId());
    resetAnswer();
  };

  const activePrompt = phase === "key_step"
    ? session?.attempt?.probe?.prompt
    : phase === "verification"
      ? session?.continuation?.verification?.prompt
      : currentItem?.prompt;
  const activeOptions = phase === "verification"
    ? session?.continuation?.verification?.options
    : phase === "question"
      ? currentItem?.options
      : {};
  const activeResponseMode = phase === "verification"
    ? session?.continuation?.verification?.response_mode
    : currentItem?.response_mode;
  const canSubmit = Boolean(answer.trim() && confidence);
  const conflict = error?.status === 409;
  const questionLabel = answeredCount < minimumQuestions ? `第 ${answeredCount + 1} 题` : "加练题";

  return (
    <div className="lesson-workspace-layer">
      <section ref={workspaceRef} className="lesson-workspace" role="dialog" aria-modal="true" aria-labelledby={titleId}>
        <header className="lesson-workspace-header">
          <div>
            <small>{lesson.module || "行测微教程"}</small>
            <h2 id={titleId}>{lesson.title || "学习教程"}</h2>
          </div>
          <span className="lesson-duration"><Clock size={12} />约 {lesson.estimated_minutes || 8} 分钟</span>
          <button ref={closeRef} type="button" className="icon-button lesson-close" onClick={onClose} aria-label="关闭教程"><X size={16} /></button>
        </header>

        {view === "learn" && (
          <div className="lesson-scroll lesson-learn-view">
            <div className="lesson-trust-row"><span><LockKey size={12} />内容与练习在本机处理</span><span><Info size={12} />阅读本身不会改变掌握度</span></div>
            <div className="lesson-learn-grid">
              <section className="lesson-method-card" aria-labelledby="method-card-title">
                <span>方法卡</span>
                <h3 id="method-card-title">先找比较起点</h3>
                <p>{method.definition}</p>
                <div className="lesson-formula"><small>公式</small><strong>{method.formula}</strong></div>
                {Array.isArray(method.applicability) && method.applicability.length > 0 && (
                  <div className="lesson-conditions"><small>什么时候能用</small><ul>{method.applicability.map((item) => <li key={item}>{item}</li>)}</ul></div>
                )}
                {method.common_mistake && (
                  <div className="lesson-trap"><small>一个易错点 · {method.common_mistake.label}</small><p>{method.common_mistake.explanation}</p></div>
                )}
              </section>

              <section className="lesson-example" aria-labelledby="worked-example-title">
                <span>先试一遍</span>
                <h3 id="worked-example-title">原创例题</h3>
                <p className="lesson-example-prompt">{example.prompt}</p>
                {!exampleRevealed ? (
                  <>
                    <label className="lesson-answer-field lesson-example-answer"><span>你的计算或答案</span><textarea value={exampleDraft} onChange={(event) => setExampleDraft(event.target.value)} rows={3} placeholder="先写下自己的思路；这里不会计入掌握度" /></label>
                    {hints.length > 0 && (
                      <div className="lesson-hint-stack" aria-live="polite">
                        {hints.slice(0, visibleHintCount).map((hint) => <div key={`${hint.level}-${hint.prompt}`}><small><Lightbulb size={12} />{hint.label || `第 ${hint.level} 级提示`}</small><p>{hint.prompt}</p></div>)}
                        <button type="button" className="lesson-text-button" disabled={visibleHintCount >= hints.length} onClick={() => setVisibleHintCount((value) => Math.min(hints.length, value + 1))}>{visibleHintCount === 0 ? "我需要一点提示" : visibleHintCount < hints.length ? "再给一级提示" : "提示已全部展开"}</button>
                      </div>
                    )}
                    <div className="lesson-example-actions">
                      <button type="button" className="button secondary compact" onClick={() => setExampleRevealed(true)}>暂时不会，直接看步骤</button>
                      <button type="button" className="button primary compact" disabled={!exampleDraft.trim()} onClick={() => setExampleRevealed(true)}>核对步骤</button>
                    </div>
                  </>
                ) : (
                  <div className="lesson-solution" aria-live="polite">
                    {steps.map((step, index) => <div key={step.step_id || `${step.instruction}-${index}`}><span>{index + 1}</span><p><strong>{step.instruction}</strong>{step.content}</p></div>)}
                  </div>
                )}
              </section>
            </div>
            <footer className="lesson-learn-footer">
              <p>练习会保存真实作答、验证结果与可回放轨迹；教程阅读不会写入 mastery。</p>
              <button type="button" className="button primary" disabled={items.length === 0} onClick={() => { setView("practice"); setStartedAt(Date.now()); }}>开始做题 <ArrowRight size={13} /></button>
            </footer>
          </div>
        )}

        {view === "practice" && (
          <div className="lesson-scroll lesson-practice-view">
            <div className="lesson-practice-progress" aria-label="学习进度">
              <span><strong>{Math.min(answeredCount, minimumQuestions)} / {minimumQuestions}</strong> 已作答</span>
              <span><strong>{verifiedStreak} / {requiredTransfers}</strong> 连续迁移</span>
            </div>

            {items.length === 0 && <div className="lesson-state"><Info size={25} /><h3>教程还没有可用练习</h3><p>内容未补齐前不会生成学习记录。</p><button type="button" className="button secondary" onClick={onClose}>关闭</button></div>}

            {phase === "submitting" && <div className="lesson-state" role="status"><span className="practice-spinner" /><h3>正在核对并保存</h3><p>本次作答只写入此 Mac。</p></div>}

            {["question", "key_step", "verification"].includes(phase) && currentItem && (
              <form className="lesson-problem" onSubmit={submitActive}>
                <div className="lesson-problem-heading">
                  <span>{phase === "key_step" ? "关键一步" : questionLabel}</span>
                  <small>{phase === "verification" ? "换一道新题，独立完成" : phase === "key_step" ? "写下依据，不展示错因标签" : `练习 ${itemIndex + 1} / ${items.length}`}</small>
                </div>

                {phase === "key_step" && (
                  <div className={session?.attempt?.score?.passed ? "lesson-feedback correct" : "lesson-feedback"}>
                    <CheckCircle size={15} weight={session?.attempt?.score?.passed ? "fill" : "regular"} />
                    <span><strong>{session?.attempt?.score?.passed ? "首答判断正确" : "首答暂未通过"}</strong><small>先完成这一关键步，再决定需要哪种讲解。</small></span>
                  </div>
                )}

                {phase === "verification" && session?.continuation?.teaching?.prompt && (
                  <div className="lesson-on-demand">
                    <button type="button" className="lesson-text-button" aria-expanded={teachingVisible} onClick={() => setTeachingVisible((value) => !value)}><Lightbulb size={12} />{teachingVisible ? "收起方法提示" : "需要时查看方法提示"}</button>
                    {teachingVisible && <p>{session.continuation.teaching.prompt}</p>}
                  </div>
                )}

                <section className="lesson-question"><small>{phase === "key_step" ? "请写出判断依据" : "题目"}</small><p>{activePrompt}</p></section>
                <AnswerField answer={answer} setAnswer={setAnswer} options={activeOptions} responseMode={activeResponseMode} name={`${answerName}-${phase}-${itemIndex}`} />
                <ConfidenceField value={confidence} onChange={setConfidence} />
                <button type="submit" className="button primary lesson-submit" disabled={!canSubmit}>{phase === "verification" ? "提交这道新题" : phase === "key_step" ? "提交关键一步" : "提交答案"} <ArrowRight size={13} /></button>
                <p className="lesson-evidence-note"><LockKey size={12} />只有已评分作答和无提示迁移会影响技能证据；内部诊断不会作为事实展示。</p>
              </form>
            )}

            {phase === "round_result" && roundResult && (
              <div className={roundResult.effective ? "lesson-round-result verified" : "lesson-round-result"} role="status">
                <CheckCircle size={29} weight={roundResult.effective ? "fill" : "regular"} />
                <h3>{roundResult.effective ? "这次迁移通过了" : "这次迁移还没通过"}</h3>
                <p>{roundResult.effective ? `已连续通过 ${roundResult.verifiedStreak} 次新题验证。` : "连续记录已重置，下一题会继续验证同一个方法。"}</p>
                {roundResult.revealTeaching && session?.continuation?.teaching?.prompt && <div className="lesson-full-explanation"><small>两次错误后展开微教程</small><p>{session.continuation.teaching.prompt}</p></div>}
                <dl><div><dt>累计作答</dt><dd>{roundResult.answeredCount} 题</dd></div><div><dt>当前连续迁移</dt><dd>{roundResult.verifiedStreak} 次</dd></div></dl>
                <button type="button" className="button primary" onClick={continueAfterResult}>{roundResult.complete ? "查看完成结果" : "下一题"} <ArrowRight size={13} /></button>
              </div>
            )}

            {phase === "error" && (
              <div className="lesson-state lesson-error" role="alert">
                <Info size={25} />
                <h3>{conflict ? "这一步已被其他操作处理" : "这次作答还没有确认保存"}</h3>
                <p>{conflict ? "为避免重复写入，请关闭教程后重新进入；已确认的轨迹不会丢失。" : error?.message || "本机服务暂时无法处理本次作答。"}</p>
                {conflict ? <button type="button" className="button secondary" onClick={onClose}>关闭并重新进入</button> : <button type="button" className="button primary" onClick={() => { setError(null); setPhase(resumePhase); }}>返回重试</button>}
              </div>
            )}
          </div>
        )}

        {view === "complete" && (
          <div className="lesson-complete" role="status">
            <CheckCircle size={36} weight="fill" />
            <span>本课完成</span>
            <h3>你已经用新题验证了增长率方法</h3>
            <p>至少 {minimumQuestions} 道真实作答、连续 {requiredTransfers} 次无提示迁移已经写入本机轨迹。阅读内容没有被计作掌握。</p>
            <dl><div><dt>计分作答</dt><dd>{answeredCount}</dd></div><div><dt>连续迁移</dt><dd>{verifiedStreak}</dd></div><div><dt>云端调用</dt><dd>0</dd></div></dl>
            <button type="button" className="button primary" onClick={onClose}>返回行测练习</button>
          </div>
        )}
      </section>
    </div>
  );
}
