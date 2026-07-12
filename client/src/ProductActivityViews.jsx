import { Clock, Info } from "@phosphor-icons/react";

const CONFIDENCE_OPTIONS = [
  ["low", "不太确定"],
  ["medium", "基本确定"],
  ["high", "非常确定"],
];

function formatElapsed(seconds) {
  const value = Math.max(0, Math.floor(Number(seconds) || 0));
  const minutes = Math.floor(value / 60);
  const remainder = String(value % 60).padStart(2, "0");
  return `${minutes}:${remainder}`;
}

export function ProductActivityQuestion({
  activity,
  answer,
  onAnswer,
  confidence,
  onConfidence,
  workNotes,
  onWorkNotes,
  elapsedSeconds,
  stepLabel,
  independentCopy,
  submitLabel,
  onSubmit,
}) {
  const source = activity.source;
  return (
    <form className="product-activity" data-testid="product-activity" data-activity-id={activity.activityId} data-content-signature={activity.contentSignature} onSubmit={(event) => { event.preventDefault(); onSubmit(); }}>
      <header className="activity-meta">
        <div><span>{stepLabel}</span><strong>资料分析</strong></div>
        <span className="activity-timer" aria-label={`本题已用时 ${formatElapsed(elapsedSeconds)}`}><Clock size={13} />{formatElapsed(elapsedSeconds)}</span>
      </header>

      <p className="activity-source">{source.year} · {source.paperTitle} · 第 {source.questionNo} 题</p>
      <section className="activity-material" aria-labelledby={`${activity.activityId}-material`}>
        <h3 id={`${activity.activityId}-material`}>材料</h3>
        <p>{activity.materialText}</p>
      </section>
      <fieldset className="activity-question">
        <legend>{activity.stemText}</legend>
        <div className="activity-options">
          {activity.options.map((option) => (
            <label key={option.label} className={answer === option.label ? "activity-option selected" : "activity-option"}>
              <input type="radio" name={`${activity.activityId}-answer`} value={option.label} checked={answer === option.label} onChange={() => onAnswer(option.label)} />
              <span>{option.label}</span>
              <strong>{option.text}</strong>
            </label>
          ))}
        </div>
      </fieldset>

      <div className="independent-boundary"><Info size={13} /><span>{independentCopy}</span></div>

      <fieldset className="confidence-field">
        <legend>作答信心</legend>
        <div>
          {CONFIDENCE_OPTIONS.map(([value, label]) => (
            <label key={value} className={confidence === value ? "selected" : ""}>
              <input type="radio" name={`${activity.activityId}-confidence`} value={value} checked={confidence === value} onChange={() => onConfidence(value)} />
              <span>{label}</span>
            </label>
          ))}
        </div>
      </fieldset>

      <details className="work-notes">
        <summary>补充作答过程（可选）</summary>
        <label><span>你的公式、定位或排除依据</span><textarea value={workNotes} onChange={(event) => onWorkNotes(event.target.value)} maxLength={1000} placeholder="例如：先找现期量和增长率，再还原基期量" /></label>
        <small>本版只用于你整理思路，不参与评分，也不作为错因证据。</small>
      </details>

      <button className="button primary panel-primary" type="submit" disabled={!answer || !confidence}>{submitLabel}</button>
    </form>
  );
}

export function ProductActivityLoadState({ phase, error, onRetry }) {
  if (phase === "loading") {
    return <div className="run-waiting" role="status"><strong>正在读取本机真题</strong><p>核对题目版本与安全投影，请稍候。</p></div>;
  }
  return (
    <div className="run-error activity-load-error" role="alert" data-testid="product-activity-error">
      <Info size={18} />
      <h3>真题活动暂不可用</h3>
      <p>{error?.message || "本机题目投影不完整；为避免泄露答案或错配评分，本轮不会回退到演示题。"}</p>
      <button className="button secondary" type="button" onClick={onRetry}>重新读取真题</button>
    </div>
  );
}
