import { useEffect, useId, useReducer, useRef, useState } from "react";
import {
  ArrowRight,
  CheckCircle,
  Info,
  Lightbulb,
  X,
  XCircle,
} from "@phosphor-icons/react";
import {
  createSmartPracticeState,
  SMART_PRACTICE_TARGET,
  smartPracticeReducer,
} from "./smartPracticeState";
import {
  resolvePracticeEnterAction,
  resolvePracticeOptionShortcut,
  shouldConfirmPracticeExit,
} from "./practiceKeyboard";

function AnswerField({ question, answer, onChange, disabled, name }) {
  if (question.options.length > 0) {
    return (
      <fieldset className="smart-practice-options" disabled={disabled}>
        <legend>请选择一个答案</legend>
        {question.options.map((option, index) => (
          <label className={answer === option.id ? "selected" : ""} key={option.id}>
            <input
              type="radio"
              name={name}
              value={option.id}
              checked={answer === option.id}
              onChange={(event) => onChange(event.target.value)}
              aria-keyshortcuts={index < 4 ? `${String.fromCharCode(65 + index)} ${index + 1}` : undefined}
            />
            <strong>{option.id}</strong>
            <span>{option.text}</span>
          </label>
        ))}
      </fieldset>
    );
  }
  return (
    <label className="smart-practice-text-answer">
      <span>你的答案</span>
      <textarea
        rows={4}
        value={answer}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        placeholder="写下答案"
      />
    </label>
  );
}

function FeedbackView({
  state,
  probeName,
  onProbeAnswer,
  onProbeSubmit,
  onProbeSkip,
  onContinue,
}) {
  const { feedback } = state;
  const finalQuestion = state.answeredCount >= state.targetCount
    || (Boolean(feedback.probe) && state.answeredCount + 1 >= state.targetCount);
  const tone = feedback.correct === true ? "correct" : feedback.correct === false ? "incorrect" : "neutral";
  const FeedbackIcon = feedback.correct === true ? CheckCircle : feedback.correct === false ? XCircle : Info;
  const probe = feedback.probe;

  return (
    <section className="smart-practice-feedback" aria-labelledby="smart-practice-feedback-title">
      <div className={`smart-practice-verdict ${tone}`} role="status" aria-live="polite">
        <FeedbackIcon size={24} weight={feedback.correct === true ? "fill" : "regular"} />
        <div>
          <h3 id="smart-practice-feedback-title">{feedback.title}</h3>
          {feedback.correctOption && feedback.correct === false && (
            <small>正确答案 {feedback.correctOption}</small>
          )}
          {feedback.keyPrinciple && <p>{feedback.keyPrinciple}</p>}
        </div>
      </div>

      {feedback.explanation && (
        <details className="smart-practice-explanation">
          <summary>展开完整解析</summary>
          <div>
            {feedback.explanation.split(/\n{2,}/u).map((paragraph, index) => (
              <p key={`${index}-${paragraph.slice(0, 16)}`}>{paragraph}</p>
            ))}
          </div>
        </details>
      )}

      {feedback.microtutorial && (
        <aside className="smart-practice-tutorial" aria-labelledby="smart-practice-tutorial-title">
          <span><Lightbulb size={14} />Lumi 提示</span>
          <h4 id="smart-practice-tutorial-title">{feedback.microtutorial.title}</h4>
          {feedback.microtutorial.body && <p>{feedback.microtutorial.body}</p>}
          {feedback.microtutorial.points.length > 0 && (
            <ul>{feedback.microtutorial.points.map((point) => <li key={point}>{point}</li>)}</ul>
          )}
        </aside>
      )}

      {probe ? (
        <section className="smart-practice-probe" aria-labelledby="smart-practice-probe-title">
          <div>
            <span>可选探查</span>
            <small>使用下一题位，可直接跳过</small>
          </div>
          <h4 id="smart-practice-probe-title">{probe.prompt}</h4>
          <fieldset disabled={state.probeStatus === "submitting"}>
            <legend className="sr-only">请选择探查答案</legend>
            {probe.options.map((option) => (
              <label className={state.probeAnswer === option.id ? "selected" : ""} key={option.id}>
                <input
                  type="radio"
                  name={probeName}
                  value={option.id}
                  checked={state.probeAnswer === option.id}
                  onChange={(event) => onProbeAnswer(event.target.value)}
                />
                <span>{option.text}</span>
              </label>
            ))}
          </fieldset>
          {state.probeError && <p className="smart-practice-probe-error" role="alert">{state.probeError}</p>}
          <div className="smart-practice-probe-actions">
            <button
              type="button"
              className="button secondary compact"
              disabled={state.probeStatus === "submitting"}
              onClick={onProbeSkip}
            >
              跳过，{finalQuestion ? "查看总结" : "继续下一题"}
            </button>
            <button
              type="button"
              className="button primary compact"
              disabled={!state.probeAnswer.trim() || state.probeStatus === "submitting"}
              onClick={onProbeSubmit}
            >
              {state.probeStatus === "submitting" ? "正在保存" : "提交探查"}
            </button>
          </div>
        </section>
      ) : (
        <button type="button" className="button primary smart-practice-next" onClick={onContinue}>
          {finalQuestion ? "查看本组总结" : "下一题"}<ArrowRight size={14} />
        </button>
      )}
    </section>
  );
}

function SummaryView({ summary, onNextGroup }) {
  const normalQuestionTotal = Number.isInteger(summary.scoredCount) ? summary.scoredCount : null;
  const score = !summary.scoreBreakdownComplete || summary.correctCount === null || normalQuestionTotal === null
    ? "—"
    : `${summary.correctCount} / ${normalQuestionTotal}`;
  const weakness = summary.primaryWeakness;
  return (
    <section className="smart-practice-summary" aria-labelledby="smart-practice-summary-title">
      <span>本组已完成</span>
      <h3 id="smart-practice-summary-title">{summary.title}</h3>
      <p>{summary.message}</p>

      <div className="smart-practice-summary-result" aria-label="本组普通题结果">
        <strong>{score}</strong>
        <span>
          普通题答对
          <small>{!summary.scoreBreakdownComplete || summary.correctCount === null ? "恢复前的普通题判分明细不完整" : `本组共占用 ${summary.totalCount} / 8 个题位`}</small>
        </span>
      </div>

      <div className="smart-practice-summary-insights">
        <section aria-labelledby="smart-practice-weakness-title">
          <small id="smart-practice-weakness-title">最重要的错误模式</small>
          <strong>{weakness?.title || "证据不足，暂不形成判断"}</strong>
          <p>{weakness?.evidence || "目前没有跨独立题族重复的错误线索。"}</p>
        </section>
        <section>
          <small>仍待确认</small>
          <strong>{weakness ? "这个模式能否在新材料中再次出现" : "是否存在稳定的错误模式"}</strong>
          <p>后续只用无提示、独立作答继续验证。</p>
        </section>
        <section>
          <small>下一组准备验证</small>
          <strong>{weakness ? `换题面检查「${weakness.title}」` : "继续积累跨题族证据"}</strong>
          <p>不会增加额外学习任务。</p>
        </section>
      </div>

      <section className="smart-practice-wrong-list" aria-labelledby="smart-practice-wrong-title">
        <div>
          <h4 id="smart-practice-wrong-title">本组错题</h4>
          <span>{summary.wrongQuestions.length} 道</span>
        </div>
        {!summary.wrongQuestionsComplete && (
          <p className="smart-practice-partial-note">
            本组从中断处恢复；这里只列出恢复后本窗口读取到的错题，完整记录可在错题本查看。
          </p>
        )}
        {summary.wrongQuestions.length > 0 ? (
          <div className="smart-practice-wrong-items">
            {summary.wrongQuestions.map((item) => (
              <details key={`${item.id}-${item.ordinal}`}>
                <summary>
                  <span>第 {item.ordinal} 题</span>
                  <strong>你的答案 {item.selectedOption || "未记录"}</strong>
                </summary>
                <div>
                  <p>{item.prompt}</p>
                  {item.correctOption && <small>正确答案：{item.correctOption}</small>}
                  {item.keyPrinciple && <p><strong>关键点：</strong>{item.keyPrinciple}</p>}
                  {item.explanation && <p><strong>解析：</strong>{item.explanation}</p>}
                </div>
              </details>
            ))}
          </div>
        ) : (
          <p className="smart-practice-wrong-empty">本组已判分题目中没有错题。</p>
        )}
      </section>

      <button type="button" className="button primary smart-practice-finish" onClick={onNextGroup}>
        开始下一组 <ArrowRight size={15} />
      </button>
    </section>
  );
}

/**
 * Low-interruption, fixed-eight practice workspace.
 *
 * Required callbacks:
 * - startSession({ nextGroup }) -> { session, question }
 * - submitAnswer({ sessionId, questionId, questionVersionId, answer, ordinal,
 *                  responseTimeSeconds }) -> { result, question?, summary? }
 * - close({ reason, sessionId, answeredCount, targetCount })
 *
 * Optional callback:
 * - submitProbe({ sessionId, hypothesisId, answer })
 */
export function SmartPracticeWorkspace({ startSession, submitAnswer, submitProbe, close }) {
  const [state, dispatch] = useReducer(smartPracticeReducer, undefined, createSmartPracticeState);
  const [exitPrompt, setExitPrompt] = useState(false);
  const titleId = useId();
  const answerName = useId();
  const probeName = useId();
  const workspaceRef = useRef(null);
  const closeRef = useRef(null);
  const exitContinueRef = useRef(null);
  const exitPromptRef = useRef(false);
  const startPromiseRef = useRef(null);
  const startLockRef = useRef(false);
  const submitLockRef = useRef(false);
  const questionStartedAtRef = useRef(Date.now());
  const stateRef = useRef(state);
  const closeCallbackRef = useRef(close);
  stateRef.current = state;
  exitPromptRef.current = exitPrompt;
  closeCallbackRef.current = close;

  const closeWorkspace = (reason, { confirmed = false } = {}) => {
    const current = stateRef.current;
    if (startLockRef.current || current.phase === "submitting" || current.probeStatus === "submitting") return;
    if (!confirmed && shouldConfirmPracticeExit(current.phase, current.answeredCount)) {
      setExitPrompt(true);
      return;
    }
    closeCallbackRef.current?.({
      reason: reason || (current.phase === "complete" ? "completed" : "ended_early"),
      sessionId: current.sessionId,
      answeredCount: current.answeredCount,
      targetCount: SMART_PRACTICE_TARGET,
    });
  };

  const requestSession = ({ force = false, nextGroup = false } = {}) => {
    dispatch({ type: "START_REQUESTED" });
    if (force || !startPromiseRef.current) {
      startPromiseRef.current = typeof startSession === "function"
        ? Promise.resolve().then(() => startSession({ nextGroup }))
        : Promise.reject(new Error("缺少开始练习的回调。"));
    }
    return startPromiseRef.current;
  };

  const beginSession = ({ force = false, nextGroup = false } = {}) => {
    if (startLockRef.current) {
      return !force && startPromiseRef.current ? startPromiseRef.current : null;
    }
    startLockRef.current = true;
    const pending = requestSession({ force, nextGroup });
    pending.then(
      () => { startLockRef.current = false; },
      () => { startLockRef.current = false; },
    );
    return pending;
  };

  useEffect(() => {
    let active = true;
    beginSession()
      .then((payload) => {
        if (!active) return;
        questionStartedAtRef.current = Date.now();
        dispatch({ type: "START_SUCCEEDED", payload });
      })
      .catch((error) => active && dispatch({ type: "START_FAILED", error }));
    return () => { active = false; };
  }, []); // The session callback is intentionally captured once for this workspace run.

  useEffect(() => {
    const previousFocus = document.activeElement;
    workspaceRef.current?.focus();
    const handleKeyDown = (event) => {
      if (event.defaultPrevented) return;
      if (event.key === "Escape") {
        event.preventDefault();
        if (exitPromptRef.current) {
          setExitPrompt(false);
          closeRef.current?.focus();
          return;
        }
        closeWorkspace();
        return;
      }
      if (exitPromptRef.current && event.key !== "Tab") return;

      const current = stateRef.current;
      if (current.phase === "question" && current.currentQuestion?.options?.length) {
        const optionId = resolvePracticeOptionShortcut(
          event,
          current.currentQuestion.options,
          current.answer,
        );
        if (optionId) {
          event.preventDefault();
          dispatch({ type: "ANSWER_CHANGED", value: optionId });
          window.requestAnimationFrame(() => {
            const radios = [...(workspaceRef.current?.querySelectorAll(".smart-practice-options input[type='radio']") || [])];
            radios.find((radio) => radio.value === optionId)?.focus();
          });
          return;
        }
      }

      const enterAction = resolvePracticeEnterAction(event, current.phase);
      if (enterAction === "submit" && current.answer.trim()) {
        event.preventDefault();
        workspaceRef.current?.querySelector(".smart-practice-question-card")?.requestSubmit?.();
        return;
      }
      if (enterAction === "continue" && !current.feedback?.probe) {
        event.preventDefault();
        if (current.answeredCount < current.targetCount) questionStartedAtRef.current = Date.now();
        dispatch({ type: "CONTINUE" });
        return;
      }

      if (event.key !== "Tab" || !workspaceRef.current) return;
      const focusable = [...workspaceRef.current.querySelectorAll(
        "button:not([disabled]), input:not([disabled]), textarea:not([disabled]), details > summary, [tabindex]:not([tabindex='-1'])",
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
  }, []);

  useEffect(() => {
    if (!exitPrompt) return undefined;
    const frame = window.requestAnimationFrame(() => exitContinueRef.current?.focus());
    return () => window.cancelAnimationFrame(frame);
  }, [exitPrompt]);

  const resumeFromExitPrompt = () => {
    setExitPrompt(false);
    window.requestAnimationFrame(() => workspaceRef.current?.focus());
  };

  const retryStart = () => {
    const pending = beginSession({ force: true });
    if (!pending) return;
    pending
      .then((payload) => {
        questionStartedAtRef.current = Date.now();
        dispatch({ type: "START_SUCCEEDED", payload });
      })
      .catch((error) => dispatch({ type: "START_FAILED", error }));
  };

  const startNextGroup = () => {
    if (stateRef.current.phase !== "complete") return;
    const pending = beginSession({ force: true, nextGroup: true });
    if (!pending) return;
    pending
      .then((payload) => {
        questionStartedAtRef.current = Date.now();
        dispatch({ type: "START_SUCCEEDED", payload });
      })
      .catch((error) => dispatch({ type: "START_FAILED", error }));
  };

  const submitCurrentAnswer = async (event) => {
    event.preventDefault();
    if (!state.answer.trim() || state.phase !== "question" || submitLockRef.current) return;
    submitLockRef.current = true;
    dispatch({ type: "SUBMIT_REQUESTED" });
    try {
      if (typeof submitAnswer !== "function") throw new Error("缺少保存答案的回调。");
      const payload = await submitAnswer({
        sessionId: state.sessionId,
        questionId: state.currentQuestion.questionId,
        questionVersionId: state.currentQuestion.questionVersionId,
        answer: state.answer.trim(),
        ordinal: state.currentQuestion.ordinal || state.answeredCount + 1,
        responseTimeSeconds: Math.max(0, (Date.now() - questionStartedAtRef.current) / 1000),
      });
      dispatch({ type: "SUBMIT_SUCCEEDED", payload });
    } catch (error) {
      dispatch({ type: "SUBMIT_FAILED", error });
    } finally {
      submitLockRef.current = false;
    }
  };

  const continuePractice = () => {
    if (state.answeredCount < state.targetCount) questionStartedAtRef.current = Date.now();
    dispatch({ type: "CONTINUE" });
  };

  const resolveOptionalProbe = async ({ answer, continueAfter = false }) => {
    const probe = state.feedback?.probe;
    if (!probe || !String(answer || "").trim() || state.probeStatus === "submitting") return;
    dispatch({ type: "PROBE_SUBMIT_REQUESTED", allowSkip: answer === "__skip__" });
    try {
      if (typeof submitProbe !== "function") throw new Error("缺少保存探查结果的回调。");
      const payload = await submitProbe({
        sessionId: state.sessionId,
        hypothesisId: probe.hypothesisId,
        answer: String(answer).trim(),
      });
      dispatch({ type: "PROBE_SUBMIT_SUCCEEDED", payload });
      if (continueAfter) {
        questionStartedAtRef.current = Date.now();
        dispatch({ type: "CONTINUE" });
      }
    } catch (error) {
      dispatch({ type: "PROBE_SUBMIT_FAILED", error });
    }
  };

  const submitOptionalProbe = () => resolveOptionalProbe({ answer: state.probeAnswer });
  const skipOptionalProbe = () => resolveOptionalProbe({ answer: "__skip__", continueAfter: true });

  const retrySubmit = () => dispatch({ type: "RETRY_SUBMIT" });
  const question = state.currentQuestion;
  const submitting = state.phase === "submitting";
  const saving = state.phase === "starting" || submitting || state.probeStatus === "submitting";

  return (
    <div className="smart-practice-layer">
      <section
        ref={workspaceRef}
        className="smart-practice-workspace"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
      >
        <header className="smart-practice-header">
          <div>
            <small>{state.moduleLabel}</small>
            <h2 id={titleId}>{state.title}</h2>
          </div>
          <div className="smart-practice-progress" aria-live="polite">
            <progress value={state.answeredCount} max={state.targetCount} aria-label={`已完成 ${state.answeredCount} 题，共 8 题`} />
            <span>{state.phase === "question" || state.phase === "submitting"
              ? <>第 <strong>{Math.min(state.targetCount, state.answeredCount + 1)}</strong> / {state.targetCount} 题</>
              : <>已完成 <strong>{state.answeredCount}</strong> / {state.targetCount}</>}</span>
          </div>
          <button
            ref={closeRef}
            type="button"
            className="lumi-icon-button smart-practice-close"
            onClick={() => closeWorkspace()}
            disabled={saving}
            aria-label={saving ? "正在保存作答" : state.phase === "complete" ? "关闭练习" : "提前结束练习"}
          >
            <X size={17} />
          </button>
        </header>

        <div
          className="smart-practice-scroll"
          aria-busy={state.phase === "starting" || submitting}
        >
          {exitPrompt ? (
            <section className="smart-practice-state smart-practice-exit-confirm" role="alertdialog" aria-labelledby="smart-practice-exit-title">
              <Info size={27} />
              <h3 id="smart-practice-exit-title">结束本组？</h3>
              <p>已完成 {state.answeredCount} / 8 个题位。主动结束后，本组会标记为“提前结束”，不会保留为可继续会话。</p>
              <div>
                <button ref={exitContinueRef} type="button" className="button primary" onClick={resumeFromExitPrompt}>继续作答</button>
                <button type="button" className="button secondary" onClick={() => closeWorkspace("ended_early", { confirmed: true })}>结束本组</button>
              </div>
            </section>
          ) : state.phase === "starting" && (
            <div className="smart-practice-state" role="status">
              <span className="practice-spinner" />
              <h3>正在准备 8 道题</h3>
              <p>准备完成后会直接进入第 1 题。</p>
            </div>
          )}

          {!exitPrompt && (state.phase === "question" || submitting) && question && (
            <form className="smart-practice-question-card" onSubmit={submitCurrentAnswer}>
              <div className="smart-practice-question-heading">
                <span>{question.eyebrow || "连续刷题"}</span>
                <small>只需提交答案</small>
              </div>
              <div className="smart-practice-question-layout">
                <div className="smart-practice-question-pane">
                  <section className="smart-practice-prompt" aria-labelledby="smart-practice-question-title">
                    <small>题目</small>
                    <p id="smart-practice-question-title">{question.prompt}</p>
                  </section>
                  <AnswerField
                    question={question}
                    answer={state.answer}
                    onChange={(value) => dispatch({ type: "ANSWER_CHANGED", value })}
                    disabled={submitting}
                    name={answerName}
                  />
                </div>
              </div>
              <div className="smart-practice-actions">
                <button
                  type="submit"
                  className="button primary smart-practice-submit"
                  disabled={!state.answer.trim() || submitting}
                >
                  {submitting ? "正在核对" : "提交答案"}<ArrowRight size={14} />
                </button>
                <p className="smart-practice-evidence-note">
                  A–D 或 1–4 选择 · Enter 提交
                </p>
              </div>
            </form>
          )}

          {!exitPrompt && state.phase === "feedback" && state.feedback && (
            <FeedbackView
              state={state}
              probeName={probeName}
              onProbeAnswer={(value) => dispatch({ type: "PROBE_ANSWER_CHANGED", value })}
              onProbeSubmit={submitOptionalProbe}
              onProbeSkip={skipOptionalProbe}
              onContinue={continuePractice}
            />
          )}

          {!exitPrompt && state.phase === "complete" && state.summary && (
            <SummaryView summary={state.summary} onNextGroup={startNextGroup} />
          )}

          {!exitPrompt && state.phase === "error" && (
            <div className="smart-practice-state smart-practice-error" role="alert">
              <Info size={26} />
              <h3>{state.retryKind === "start" ? "暂时无法开始练习" : "这次操作还没有完成"}</h3>
              <p>{state.error}</p>
              <div>
                {state.retryKind === "start" && <button type="button" className="button primary" onClick={retryStart}>重新开始</button>}
                {state.retryKind === "submit" && <button type="button" className="button primary" onClick={retrySubmit}>返回本题重试</button>}
                {state.retryKind === "continue" && <button type="button" className="button primary" onClick={retryStart}>重新读取下一题</button>}
                <button type="button" className="button secondary" onClick={() => closeWorkspace("interrupted", { confirmed: true })}>结束本组</button>
              </div>
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
