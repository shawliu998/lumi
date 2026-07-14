import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowClockwise,
  CaretLeft,
  CaretRight,
  CheckCircle,
  Database,
  MagnifyingGlass,
  ShieldCheck,
  WarningCircle,
  XCircle,
} from "@phosphor-icons/react";

import {
  fetchQuestionBankQuestion,
  fetchQuestionBankStatus,
  searchQuestionBank,
  submitQuestionBankAttempt,
} from "./questionBankApi.js";
import { createCommandId } from "./publicLearningId.js";

const EMPTY_LIST = { items: [], pagination: { page: 1, page_size: 20, total_items: 0, total_pages: 0 } };

function countText(value) {
  return new Intl.NumberFormat("zh-CN").format(Number(value) || 0);
}

function errorCopy(error, fallback) {
  if (error?.code === "question_bank_unavailable") return "本机尚未安装经过校验的题库导出。";
  if (error?.kind === "unavailable") return "本机服务未连接，题库不会读取缓存或演示数据。";
  return error?.message || fallback;
}

function QuestionList({ state, activeId, onSelect }) {
  if (state.phase === "loading") return <div className="bank-list-state"><span className="bank-loading-dot" />正在读取本机索引</div>;
  if (state.phase === "error") return <div className="bank-list-state error"><WarningCircle size={17} />{errorCopy(state.error, "题目列表读取失败。")}</div>;
  if (state.data.items.length === 0) return <div className="bank-list-state"><MagnifyingGlass size={17} />没有符合条件的题目</div>;
  return (
    <div className="bank-question-list" role="list" aria-label="题目列表">
      {state.data.items.map((item) => (
        <button
          key={item.question_id}
          type="button"
          role="listitem"
          className={activeId === item.question_id ? "bank-question-row active" : "bank-question-row"}
          onClick={() => onSelect(item.question_id)}
          aria-current={activeId === item.question_id ? "true" : undefined}
        >
          <span className="bank-question-meta"><strong>{item.subtype_name}</strong><small>{item.year || "年份未知"} · {item.region || "地区未知"}</small></span>
          <span className="bank-question-preview">{item.stem_preview}</span>
          <span className="bank-question-source">{item.paper_title}{item.question_number ? ` · 第 ${item.question_number} 题` : ""}</span>
        </button>
      ))}
    </div>
  );
}

function QuestionDetail({ state, answer, setAnswer, confidence, setConfidence, onSubmit, onNext }) {
  if (state.phase === "idle") return <div className="bank-detail-empty"><Database size={24} /><strong>从左侧选择一道题</strong><p>题目与评分均来自本机只读索引。</p></div>;
  if (state.phase === "loading") return <div className="bank-detail-empty"><span className="bank-loading-dot" /><strong>正在核对题目签名</strong></div>;
  if (state.phase === "error") return <div className="bank-detail-empty error"><WarningCircle size={22} /><strong>题目未载入</strong><p>{errorCopy(state.error, "题目内容未通过校验。")}</p></div>;

  const question = state.data.question;
  const attempt = state.data.attempt;
  const result = state.result;
  const multiple = ["multiple", "multi", "multiple_choice"].includes(question.question_type);
  const selected = new Set(answer ? answer.split("|") : []);
  const toggle = (label) => {
    if (!multiple) return setAnswer(label);
    if (selected.has(label)) selected.delete(label);
    else selected.add(label);
    setAnswer([...selected].sort().join("|"));
  };

  return (
    <article className="bank-question-detail" aria-labelledby="bank-question-title">
      <header className="bank-detail-header">
        <div><span>{question.module || "模块未标注"} · {question.subtype_name}</span><h2 id="bank-question-title">{question.paper_title}</h2></div>
        <small>{question.year || "年份未知"} · {question.region || "地区未知"}{question.question_number ? ` · 第 ${question.question_number} 题` : ""}</small>
      </header>
      <div className="bank-detail-scroll">
        {question.material && <section className="bank-material"><small>材料</small><p>{question.material}</p></section>}
        {question.stem && <section className="bank-stem"><small>题目</small><p>{question.stem}</p></section>}
        {question.has_assets && <div className="bank-asset-notice"><WarningCircle size={14} /><span>本题依赖尚未打包的图像或公式资源；Lumi 不会隐式联网，也不会在题目不完整时评分。</span></div>}
        <fieldset className="bank-options" disabled={!attempt.allowed || Boolean(result) || state.submitting}>
          <legend className="sr-only">选择答案</legend>
          {question.options.map((option) => (
            <label key={option.label} className={selected.has(option.label) ? "selected" : ""}>
              <input type={multiple ? "checkbox" : "radio"} name="bank-answer" checked={selected.has(option.label)} onChange={() => toggle(option.label)} />
              <span>{option.label}</span><p>{option.text}</p>
            </label>
          ))}
        </fieldset>
        {!result && attempt.allowed && (
          <label className="bank-confidence"><span>作答信心</span><select value={confidence} onChange={(event) => setConfidence(event.target.value)}><option value="">请选择</option><option value="high">高</option><option value="medium">中</option><option value="low">低</option></select></label>
        )}
        {state.errorAfterSubmit && <p className="bank-attempt-error" role="alert">{errorCopy(state.errorAfterSubmit, "答案未提交，可安全重试。")}</p>}
        {result && (
          <section className={result.correct ? "bank-result correct" : "bank-result incorrect"} aria-live="polite">
            <header>{result.correct ? <CheckCircle size={18} weight="fill" /> : <XCircle size={18} weight="fill" />}<strong>{result.correct ? "回答正确" : "这次没有答对"}</strong><span>正确答案 {result.answer}</span></header>
            <p>{result.explanation || "本题暂无额外解析。"}</p>
            <div><ShieldCheck size={14} /><span>本次仅记录普通练习结果；不会直接更新 KT，也不会把一次答错解释成已确认错因。</span></div>
          </section>
        )}
      </div>
      <footer className="bank-detail-actions">
        {result ? <button type="button" className="button primary" onClick={onNext}>下一题<CaretRight size={13} /></button> : attempt.allowed ? <button type="button" className="button primary" disabled={!answer || !confidence || state.submitting} onClick={onSubmit}>{state.submitting ? "正在本机评分" : "提交答案"}</button> : <button type="button" className="button secondary" disabled>等待离线资源包</button>}
      </footer>
    </article>
  );
}

export function QuestionBankWorkspace() {
  const [status, setStatus] = useState({ phase: "loading", data: null, error: null });
  const [list, setList] = useState({ phase: "idle", data: EMPTY_LIST, error: null });
  const [detail, setDetail] = useState({ phase: "idle", data: null, result: null, submitting: false, error: null, errorAfterSubmit: null });
  const [queryDraft, setQueryDraft] = useState("");
  const [query, setQuery] = useState("");
  const [subtypeId, setSubtypeId] = useState("");
  const [page, setPage] = useState(1);
  const [answer, setAnswer] = useState("");
  const [confidence, setConfidence] = useState("");
  const [startedAt, setStartedAt] = useState(Date.now());
  const commandId = useRef(createCommandId());

  const loadStatus = useCallback(async () => {
    setStatus({ phase: "loading", data: null, error: null });
    try {
      const data = await fetchQuestionBankStatus();
      setStatus({ phase: data.available ? "available" : "unavailable", data, error: null });
    } catch (error) {
      setStatus({ phase: "error", data: null, error });
    }
  }, []);

  useEffect(() => { loadStatus(); }, [loadStatus]);

  useEffect(() => {
    if (status.phase !== "available") return;
    let active = true;
    setList((current) => ({ ...current, phase: "loading", error: null }));
    searchQuestionBank({ subtypeId, query, page, pageSize: 20 })
      .then((data) => active && setList({ phase: "ready", data, error: null }))
      .catch((error) => active && setList({ phase: "error", data: EMPTY_LIST, error }));
    return () => { active = false; };
  }, [page, query, status.phase, subtypeId]);

  const selectQuestion = useCallback(async (questionId) => {
    setDetail({ phase: "loading", data: null, result: null, submitting: false, error: null, errorAfterSubmit: null });
    setAnswer("");
    setConfidence("");
    setStartedAt(Date.now());
    commandId.current = createCommandId();
    try {
      const data = await fetchQuestionBankQuestion(questionId);
      setDetail({ phase: "ready", data, result: null, submitting: false, error: null, errorAfterSubmit: null });
    } catch (error) {
      setDetail({ phase: "error", data: null, result: null, submitting: false, error, errorAfterSubmit: null });
    }
  }, []);

  const submit = useCallback(async () => {
    const questionId = detail.data?.question?.question_id;
    if (!questionId) return;
    setDetail((current) => ({ ...current, submitting: true, errorAfterSubmit: null }));
    try {
      const result = await submitQuestionBankAttempt({
        questionId,
        selectedResponse: answer,
        confidence,
        elapsedSeconds: Math.min(7200, Math.max(0, (Date.now() - startedAt) / 1000)),
        commandId: commandId.current,
      });
      setDetail((current) => ({ ...current, result, submitting: false, errorAfterSubmit: null }));
    } catch (error) {
      setDetail((current) => ({ ...current, submitting: false, errorAfterSubmit: error }));
    }
  }, [answer, confidence, detail.data, startedAt]);

  const activeId = detail.data?.question?.question_id || "";
  const activeIndex = useMemo(() => list.data.items.findIndex((item) => item.question_id === activeId), [activeId, list.data.items]);
  const next = useCallback(() => {
    const candidate = list.data.items[activeIndex + 1] || list.data.items[0];
    if (candidate) selectQuestion(candidate.question_id);
  }, [activeIndex, list.data.items, selectQuestion]);

  if (status.phase === "loading") return <div className="bank-shell bank-centered"><span className="bank-loading-dot" /><strong>正在核对本地题库</strong></div>;
  if (status.phase === "error" || status.phase === "unavailable") {
    return <div className="bank-shell bank-centered"><Database size={27} /><strong>完整题库尚未连接</strong><p>{status.phase === "error" ? errorCopy(status.error, "题库状态读取失败。") : "请先安装经过校验的版本化本地导出。Lumi 不会读取可变工作文件。"}</p><button type="button" className="button secondary" onClick={loadStatus}><ArrowClockwise size={13} />重新检查</button></div>;
  }

  const bank = status.data.export;
  return (
    <div className="bank-shell">
      <header className="bank-page-header">
        <div><small>本机只读资源</small><h1>完整行测题库</h1><p>{countText(bank.access_counts.direct_practice_ready)} 道可直接练习 · {countText(bank.access_counts.asset_gated)} 道等待离线资源 · {countText(bank.counts.needs_review)} 道隔离待复核</p></div>
        <span><Database size={14} />{bank.export_version}</span>
      </header>
      <section className="bank-controls" aria-label="题库筛选">
        <form onSubmit={(event) => { event.preventDefault(); setPage(1); setQuery(queryDraft.trim()); }}>
          <MagnifyingGlass size={14} /><input value={queryDraft} onChange={(event) => setQueryDraft(event.target.value)} placeholder="搜索题干或试卷" maxLength={100} /><button type="submit">搜索</button>
        </form>
        <label><span className="sr-only">题型</span><select value={subtypeId} onChange={(event) => { setSubtypeId(event.target.value); setPage(1); }}><option value="">全部题型</option>{bank.subtypes.map((row) => <option key={row.subtype_id} value={row.subtype_id}>{row.name}（{countText(row.ready_count)}）</option>)}</select></label>
      </section>
      <div className="bank-workspace">
        <aside className="bank-browser">
          <QuestionList state={list} activeId={activeId} onSelect={selectQuestion} />
          <footer className="bank-pagination"><button type="button" aria-label="上一页" disabled={page <= 1 || list.phase !== "ready"} onClick={() => setPage((value) => value - 1)}><CaretLeft size={13} /></button><span>{list.data.pagination.page} / {Math.max(1, list.data.pagination.total_pages)}</span><button type="button" aria-label="下一页" disabled={page >= list.data.pagination.total_pages || list.phase !== "ready"} onClick={() => setPage((value) => value + 1)}><CaretRight size={13} /></button></footer>
        </aside>
        <QuestionDetail state={detail} answer={answer} setAnswer={setAnswer} confidence={confidence} setConfidence={setConfidence} onSubmit={submit} onNext={next} />
      </div>
    </div>
  );
}
