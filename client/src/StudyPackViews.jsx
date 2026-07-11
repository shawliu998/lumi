import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  BookOpenText,
  CaretRight,
  CheckCircle,
  FilePdf,
  FileText,
  Info,
  LinkSimple,
  ListChecks,
  Plus,
  ShieldWarning,
  SpinnerGap,
  WarningCircle,
  X,
  XCircle,
} from "@phosphor-icons/react";
import {
  attemptStudyPackItem,
  commandStudyPack,
  createStudyPack,
  fetchStudyPack,
  fetchStudyPackCitation,
  fetchStudyPackList,
  launchStudyPackItem,
} from "./hermesApi.js";
import { createCommandId } from "./publicLearningId.js";
import {
  createActivePracticeProjection,
  pdfFileToSource,
  STUDY_PACK_LIFECYCLE_COPY,
  studyPackErrorCopy,
  studyPackWriteRecovery,
  summarizePracticeResults,
} from "./studyPackAdapter.js";

const INITIAL_COLLECTION = { phase: "loading", items: [], error: null, partialErrorCount: 0 };

function useHeadingFocus(key) {
  const ref = useRef(null);
  useEffect(() => { ref.current?.focus(); }, [key]);
  return ref;
}

function formatUpdated(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "更新时间不可用";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function sourceCopy(kind) {
  return kind === "text_pdf" ? "PDF 文档" : "粘贴文本";
}

function locatorCopy(kind, index) {
  return kind === "page" ? `第 ${index} 页` : `第 ${index} 节`;
}

function LifecycleBadge({ lifecycle, override }) {
  const state = override || lifecycle;
  return <span className={`pack-state ${state}`} data-state={state}>{STUDY_PACK_LIFECYCLE_COPY[state] || "状态不可用"}</span>;
}

function MaterialsState({ phase, error, onRetry }) {
  const copy = error ? studyPackErrorCopy(error) : null;
  if (phase === "loading") {
    return (
      <div className="materials-state loading" role="status" data-state="loading">
        <BookOpenText size={22} />
        <strong>正在读取学习资料</strong>
        <p>从本机服务核对学习包状态。</p>
      </div>
    );
  }
  return (
    <div className={`materials-state ${copy?.state || phase}`} role="alert" data-state={copy?.state || phase}>
      <WarningCircle size={22} />
      <strong>{copy?.title || "学习资料暂不可用"}</strong>
      <p>{copy?.message || "请稍后重试。"}</p>
      <button className="button secondary" type="button" onClick={onRetry}>重新读取</button>
    </div>
  );
}

function PackList({ items, onOpen, onImport }) {
  if (!items.length) {
    return (
      <div className="materials-state empty" data-state="empty">
        <BookOpenText size={22} />
        <strong>还没有学习包</strong>
        <p>导入一份自己的文字资料，形成带来源引用的短笔记和三道练习。</p>
        <button className="button primary" type="button" onClick={onImport}><Plus size={13} />导入资料</button>
      </div>
    );
  }
  return (
    <div className="pack-table-shell">
      <table className="pack-table">
        <caption className="sr-only">本机学习包</caption>
        <thead><tr><th>学习包</th><th>状态</th><th>来源</th><th>内容</th><th>更新</th><th><span className="sr-only">操作</span></th></tr></thead>
        <tbody>{items.map((pack) => (
          <tr key={pack.packId}>
            <td className="pack-title-cell"><strong>{pack.title}</strong><small>本机学习包</small></td>
            <td><LifecycleBadge lifecycle={pack.lifecycle} /></td>
            <td>{sourceCopy(pack.source.kind)}</td>
            <td>{pack.artifactCounts.total} 项</td>
            <td>{formatUpdated(pack.updatedAt)}</td>
            <td><button className="pack-row-action" type="button" onClick={() => onOpen(pack)} aria-label={`打开${pack.title}`}>打开<CaretRight size={12} /></button></td>
          </tr>
        ))}</tbody>
      </table>
    </div>
  );
}

function StudyPackImport({ onCancel, onCreated }) {
  const [kind, setKind] = useState("pasted_text");
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [file, setFile] = useState(null);
  const [state, setState] = useState({ phase: "ready", error: null, commandId: null });
  const headingRef = useHeadingFocus("import");
  const aliveRef = useRef(false);
  const operationRef = useRef(0);
  const inFlightRef = useRef(false);
  useEffect(() => {
    aliveRef.current = true;
    inFlightRef.current = false;
    return () => {
      aliveRef.current = false;
      inFlightRef.current = false;
      operationRef.current += 1;
    };
  }, []);

  const changeInput = (updater) => {
    updater();
    setState({ phase: "ready", error: null, commandId: null });
  };

  const submit = async (event) => {
    event.preventDefault();
    if (inFlightRef.current) return;
    inFlightRef.current = true;
    const operation = ++operationRef.current;
    const commandId = state.commandId || createCommandId();
    setState({ phase: "submitting", error: null, commandId });
    try {
      const source = kind === "pasted_text"
        ? { kind: "pasted_text", text }
        : await pdfFileToSource(file);
      const created = await createStudyPack({ title, source, commandId });
      if (!aliveRef.current || operation !== operationRef.current) return;
      inFlightRef.current = false;
      onCreated(created);
    } catch (error) {
      if (!aliveRef.current || operation !== operationRef.current) return;
      inFlightRef.current = false;
      const recovery = studyPackWriteRecovery(error);
      setState({ phase: "error", error, commandId: recovery.retainCommandId ? commandId : null });
    }
  };
  const errorCopy = state.error ? studyPackErrorCopy(state.error) : null;
  const canSubmit = title.trim() && (kind === "pasted_text" ? text.trim() : file) && state.phase !== "submitting";

  return (
    <div className="study-pack-import">
      <button className="back-link" type="button" onClick={onCancel} disabled={state.phase === "submitting"}><ArrowLeft size={13} />返回学习资料</button>
      <div className="page-heading materials-detail-heading">
        <h1 ref={headingRef} tabIndex={-1}>导入学习资料</h1>
        <p>资料只交给这台 Mac 上的 Lumi 服务处理。</p>
      </div>
      <form className="pack-import-form" onSubmit={submit} noValidate>
        <label className="pack-field" htmlFor="pack-title">
          <span>标题 <em>必填</em></span>
          <input id="pack-title" value={title} maxLength={200} onChange={(event) => changeInput(() => setTitle(event.target.value))} placeholder="例如：资料分析方法整理" required aria-describedby="pack-title-note" />
          <small id="pack-title-note">标题用于本机列表，不会作为文件路径或学习技能。</small>
        </label>

        <fieldset className="source-kind-fieldset">
          <legend>资料来源</legend>
          <div className="source-kind-options">
            <label className={kind === "pasted_text" ? "selected" : ""}>
              <input type="radio" name="source-kind" value="pasted_text" checked={kind === "pasted_text"} onChange={() => changeInput(() => setKind("pasted_text"))} />
              <FileText size={17} /><span><strong>粘贴文本</strong><small>纯文本，最大 512 KB</small></span>
            </label>
            <label className={kind === "text_pdf" ? "selected" : ""}>
              <input type="radio" name="source-kind" value="text_pdf" checked={kind === "text_pdf"} onChange={() => changeInput(() => setKind("text_pdf"))} />
              <FilePdf size={17} /><span><strong>选择 PDF</strong><small>单个文件，最大 8 MB</small></span>
            </label>
          </div>
        </fieldset>

        {kind === "pasted_text" ? (
          <label className="pack-field" htmlFor="pack-source-text">
            <span>资料正文</span>
            <textarea id="pack-source-text" value={text} onChange={(event) => changeInput(() => setText(event.target.value))} placeholder="在这里粘贴需要整理和练习的文字资料" required aria-describedby="source-limit-note" />
          </label>
        ) : (
          <div className="pack-file-field">
            <span>PDF 文件</span>
            <input id="pack-pdf-file" type="file" accept="application/pdf,.pdf" onChange={(event) => changeInput(() => setFile(event.target.files?.[0] || null))} aria-describedby="source-limit-note" />
            <label className="file-picker" htmlFor="pack-pdf-file">
              <FilePdf size={17} />
              <span><strong>{file ? file.name : "选择一个 PDF"}</strong><small>{file ? `${(file.size / 1024 / 1024).toFixed(2)} MB` : "只读取你明确选择的文件，不接受本机路径"}</small></span>
            </label>
          </div>
        )}

        <div className="pack-limit-note" id="source-limit-note"><Info size={14} /><p>PDF 必须能直接选中文字，最多 120 页；不支持扫描件识别、加密文件、图片、网页或多文件合并。整理后的正文最多 25 万字。</p></div>
        {errorCopy && <div className="pack-inline-error" role="alert"><WarningCircle size={14} /><div><strong>{errorCopy.title}</strong><p>{errorCopy.message}</p></div></div>}
        <div className="pack-form-actions">
          <button className="button secondary" type="button" onClick={onCancel}>取消</button>
          <button className="button primary" type="submit" disabled={!canSubmit}>{state.phase === "submitting" ? "正在导入" : state.phase === "error" ? "重试导入" : "创建学习包"}</button>
        </div>
      </form>
    </div>
  );
}

function CitationButton({ packId, spanId, source, label = "查看来源", onResolve }) {
  const [phase, setPhase] = useState("ready");
  const inFlightRef = useRef(false);
  const resolve = async (event) => {
    if (inFlightRef.current) return;
    inFlightRef.current = true;
    const returnFocus = event.currentTarget;
    setPhase("loading");
    try {
      const citation = await fetchStudyPackCitation({ packId, spanId, source });
      inFlightRef.current = false;
      setPhase("ready");
      onResolve({ ...citation, returnFocus });
    } catch (error) {
      inFlightRef.current = false;
      setPhase("ready");
      onResolve({ error, spanId, returnFocus });
    }
  };
  return <button className="citation-button" type="button" onClick={resolve} disabled={phase === "loading"}><LinkSimple size={12} />{phase === "loading" ? "正在核验" : label}</button>;
}

function CitationPanel({ value, onClose }) {
  const panelRef = useRef(null);
  useEffect(() => { if (value) panelRef.current?.focus(); }, [value]);
  if (!value) return null;
  const close = () => {
    const returnFocus = value.returnFocus;
    onClose();
    globalThis.requestAnimationFrame?.(() => returnFocus?.focus());
  };
  if (value.error) {
    const copy = studyPackErrorCopy(value.error);
    return <div ref={panelRef} tabIndex={-1} className="citation-panel error" role="alert"><WarningCircle size={14} /><div><strong>{copy.title}</strong><p>{copy.message}</p></div><button type="button" className="icon-button" onClick={close} aria-label="关闭来源"><X size={13} /></button></div>;
  }
  return (
    <aside ref={panelRef} tabIndex={-1} className="citation-panel" aria-label="来源定位" role="status">
      <LinkSimple size={14} />
      <div><strong>已核验来源 · {locatorCopy(value.locatorKind, value.locatorIndex)}</strong><p>{value.excerpt}</p><small>字符位置 {value.startOffset}–{value.endOffset}</small></div>
      <button type="button" className="icon-button" onClick={close} aria-label="关闭来源"><X size={13} /></button>
    </aside>
  );
}

function PublishedArtifacts({ pack, onStartPractice }) {
  const [citation, setCitation] = useState(null);
  const note = pack.artifacts.find((item) => item.type === "study_pack.one_page_notes");
  const cards = pack.artifacts.filter((item) => item.type === "study_pack.knowledge_card");
  const reviewTask = pack.artifacts.find((item) => item.type === "study_pack.review_task");

  return (
    <div className="published-pack-content">
      <section className="pack-artifact-section note-section">
        <header><div><small>一页笔记</small><h2>{note.content.title}</h2></div><span>{note.content.claims.length} 条要点</span></header>
        <ol className="note-claims">
          {note.content.claims.map((claim, index) => {
            const ref = note.content.citations.find((item) => item.fieldPointer === `/claims/${index}`);
            return <li key={`${index}-${claim}`}><span>{claim}</span><CitationButton packId={pack.packId} spanId={ref.spanId} source={pack.source} onResolve={setCitation} /></li>;
          })}
        </ol>
      </section>

      <section className="pack-artifact-section cards-section">
        <header><div><small>知识卡</small><h2>{cards.length} 张卡片</h2></div><span>展开后查看答案</span></header>
        <div className="knowledge-card-list">
          {cards.map((card, index) => {
            const ref = card.content.citations.find((item) => item.fieldPointer === "/answer");
            return (
              <details key={card.artifactId}>
                <summary><span>{index + 1}</span><strong>{card.content.question}</strong><CaretRight size={13} /></summary>
                <div className="knowledge-card-answer"><p>{card.content.answer}</p><CitationButton packId={pack.packId} spanId={ref.spanId} source={pack.source} onResolve={setCitation} /></div>
              </details>
            );
          })}
        </div>
      </section>

      <section className="pack-artifact-section practice-entry">
        <div><small>练习</small><h2>3 道连续练习</h2><p>开始后，答题屏只显示当前题目；提交答案后才会显示正确答案、解释和引用原文。</p></div>
        <button className="button primary" type="button" onClick={onStartPractice}><ListChecks size={13} />开始练习</button>
      </section>

      <section className="pack-artifact-section review-task-section">
        <header><div><small>包内复习任务</small><h2>复述练习</h2></div><span>不写入复习安排</span></header>
        <p>{reviewTask.content.instruction}</p>
        <div className="pack-local-boundary"><Info size={13} />只属于这个学习包，不会改动今日计划、技能掌握或错因档案。</div>
        <CitationButton packId={pack.packId} spanId={reviewTask.content.citations[0].spanId} source={pack.source} onResolve={setCitation} />
      </section>

      <CitationPanel value={citation} onClose={() => setCitation(null)} />
    </div>
  );
}

function StudyPackDetail({ pack, viewState, onBack, onReload, onUpdated, onStartPractice }) {
  const [mutation, setMutation] = useState({ phase: "ready", error: null, commandId: null, action: null });
  const headingRef = useHeadingFocus(`detail-${pack.packId}-${pack.version}`);
  const inFlightRef = useRef(false);
  const operationRef = useRef(0);
  const aliveRef = useRef(false);
  useEffect(() => {
    aliveRef.current = true;
    inFlightRef.current = false;
    return () => {
      aliveRef.current = false;
      inFlightRef.current = false;
      operationRef.current += 1;
    };
  }, []);
  const stale = viewState.phase === "stale" || mutation.error?.code === "stale_version";
  useEffect(() => {
    setMutation((current) => ["submitting", "recovering"].includes(current.phase)
      ? current
      : { phase: "ready", error: null, commandId: null, action: null });
  }, [pack.version]);
  const mutate = async (action) => {
    if (inFlightRef.current || viewState.phase === "loading") return;
    inFlightRef.current = true;
    const operation = ++operationRef.current;
    const commandId = mutation.commandId && mutation.action === action ? mutation.commandId : createCommandId();
    setMutation({ phase: "submitting", error: null, commandId, action });
    try {
      const next = await commandStudyPack({ pack, action, commandId });
      if (!aliveRef.current || operation !== operationRef.current) return;
      inFlightRef.current = false;
      setMutation({ phase: "ready", error: null, commandId: null, action: null });
      onUpdated(next);
    } catch (error) {
      if (!aliveRef.current || operation !== operationRef.current) return;
      const recovery = studyPackWriteRecovery(error);
      if (recovery.refresh) {
        setMutation({ phase: "recovering", error, commandId: null, action });
        try {
          await onReload();
          if (!aliveRef.current || operation !== operationRef.current) return;
          inFlightRef.current = false;
          setMutation({ phase: "ready", error: null, commandId: null, action: null });
        } catch (refreshError) {
          if (!aliveRef.current || operation !== operationRef.current) return;
          inFlightRef.current = false;
          setMutation({ phase: "error", error: refreshError, commandId: null, action });
        }
        return;
      }
      inFlightRef.current = false;
      setMutation({ phase: "error", error, commandId: recovery.retainCommandId ? commandId : null, action });
    }
  };
  const visibleError = mutation.error || viewState.error;
  const errorCopy = visibleError ? studyPackErrorCopy(visibleError) : null;
  const reviewAccepted = pack.review.accepted && pack.review.decisionCount === pack.review.acceptedCount;
  const writeLocked = ["submitting", "recovering"].includes(mutation.phase) || viewState.phase === "loading";

  return (
    <div className="study-pack-detail" data-lifecycle={stale ? "stale" : pack.lifecycle}>
      <button className="back-link" type="button" onClick={onBack} disabled={writeLocked}><ArrowLeft size={13} />返回学习资料</button>
      <header className="pack-detail-header">
        <div><div className="pack-detail-kicker"><LifecycleBadge lifecycle={pack.lifecycle} override={stale ? "stale" : undefined} /><span>版本 {pack.version}</span></div><h1 ref={headingRef} tabIndex={-1}>{pack.title}</h1></div>
        <div className="pack-detail-actions">
          {stale && <button className="button secondary" type="button" onClick={() => { onReload().catch(() => {}); }} disabled={writeLocked}>读取最新版本</button>}
          {!stale && pack.lifecycle === "draft" && <button className="button primary" type="button" disabled={writeLocked} onClick={() => mutate("request_review")}>{mutation.phase === "submitting" ? "正在核验" : mutation.phase === "recovering" ? "正在读取最新状态" : "请求核验"}</button>}
          {!stale && pack.lifecycle === "review" && <button className="button primary" type="button" disabled={writeLocked || !reviewAccepted} onClick={() => mutate("publish")}>{mutation.phase === "submitting" ? "正在发布" : mutation.phase === "recovering" ? "正在读取最新状态" : "发布学习包"}</button>}
        </div>
      </header>

      <dl className="pack-source-summary">
        <div><dt>来源</dt><dd>{sourceCopy(pack.source.kind)}</dd></div>
        <div><dt>范围</dt><dd>{pack.source.kind === "text_pdf" ? `${pack.source.locatorCount} 页` : `${pack.source.locatorCount} 节`}</dd></div>
        <div><dt>内容</dt><dd>{pack.artifactCounts.total} 项学习内容</dd></div>
        <div><dt>更新</dt><dd>{formatUpdated(pack.updatedAt)}</dd></div>
      </dl>

      {errorCopy && <div className={`pack-inline-error ${errorCopy.state}`} role="alert"><WarningCircle size={14} /><div><strong>{errorCopy.title}</strong><p>{errorCopy.message}</p></div></div>}

      {pack.lifecycle === "draft" && (
        <section className="pack-lifecycle-panel" data-state="draft"><BookOpenText size={18} /><div><strong>草稿已生成</strong><p>笔记、卡片和三道练习仍需本机核验。核验前不能查看来源或开始练习。</p></div></section>
      )}
      {pack.lifecycle === "review" && (
        <section className="pack-lifecycle-panel" data-state="review">{reviewAccepted ? <CheckCircle size={18} /> : <WarningCircle size={18} />}<div><strong>{reviewAccepted ? "全部学习内容已通过核验" : "核验结果不完整"}</strong><p>{pack.review.acceptedCount} / {pack.review.decisionCount} 项通过。发布会冻结当前版本；候选技能仍保持未确认。</p></div></section>
      )}
      {pack.lifecycle === "quarantined" && (
        <section className="pack-lifecycle-panel quarantined" data-state="quarantined"><ShieldWarning size={18} /><div><strong>学习包已隔离</strong><p>{studyPackErrorCopy({ code: pack.quarantineReason }).message}</p><details><summary>查看核验说明</summary><p>{studyPackErrorCopy({ code: pack.quarantineReason }).title}</p></details></div></section>
      )}

      {pack.lifecycle !== "quarantined" && pack.candidateSkillLinks.length > 0 && (
        <details className="candidate-skills-disclosure">
          <summary>候选技能 · {pack.candidateSkillLinks.length} 项，均未确认<CaretRight size={13} /></summary>
          <div>{pack.candidateSkillLinks.map((link) => <p key={`${link.artifactId}-${link.label}`}><span>{link.label}</span><strong>候选 / 未确认</strong></p>)}</div>
        </details>
      )}

      {pack.lifecycle === "published" && <PublishedArtifacts pack={pack} onStartPractice={onStartPractice} />}
    </div>
  );
}

function PracticeError({ error, onRetry, onExit, exitLocked = false }) {
  const copy = studyPackErrorCopy(error);
  const fixture = error?.code === "evaluation_fixture_rejected";
  return (
    <div className={`practice-blocked ${fixture ? "fixture" : ""}`} role="alert" data-state={fixture ? "evaluation-fixture" : copy.state}>
      {fixture ? <ShieldWarning size={24} /> : <WarningCircle size={24} />}
      <strong>{copy.title}</strong><p>{copy.message}</p>
      <div>{!fixture && <button className="button secondary" type="button" onClick={onRetry}>重试当前步骤</button>}<button className="button text-button" type="button" onClick={onExit} disabled={exitLocked}>退出练习</button></div>
    </div>
  );
}

function practiceItemsFromPack(pack) {
  return pack.artifacts
    .filter((item) => item.type === "study_pack.practice_item")
    .map((item) => ({
      artifactId: item.artifactId,
      artifactVersion: item.artifactVersion,
      packId: item.packId,
      scorer: item.content.scorer,
    }));
}

function StudyPackPractice({ practiceItems, onExit, onRefreshPack, onPackRefreshed }) {
  const itemsRef = useRef(practiceItems);
  const aliveRef = useRef(false);
  const operationRef = useRef(0);
  const inFlightRef = useRef(false);
  const headingRef = useRef(null);
  const [state, setState] = useState({
    phase: "launching", index: 0, launch: null, answer: "", result: null,
    results: [], error: null, commandId: null,
  });

  const launchAt = useCallback(async (index, { answer = "" } = {}) => {
    const operation = ++operationRef.current;
    setState((current) => ({ ...current, phase: "launching", index, launch: null, answer: "", result: null, error: null, commandId: null }));
    try {
      const launch = await launchStudyPackItem(itemsRef.current[index]);
      createActivePracticeProjection(launch);
      if (!aliveRef.current || operation !== operationRef.current) return;
      setState((current) => ({ ...current, phase: "active", index, launch, answer, error: null }));
    } catch (error) {
      if (!aliveRef.current || operation !== operationRef.current) return;
      setState((current) => ({ ...current, phase: "error", error }));
    }
  }, []);

  useEffect(() => {
    aliveRef.current = true;
    inFlightRef.current = false;
    launchAt(0);
    return () => {
      aliveRef.current = false;
      inFlightRef.current = false;
      operationRef.current += 1;
    };
  }, [launchAt]);

  useEffect(() => {
    if (["active", "revealed", "completed"].includes(state.phase)) headingRef.current?.focus();
  }, [state.index, state.phase]);

  const submit = async (event) => {
    event?.preventDefault?.();
    if (inFlightRef.current || !state.answer.trim() || !state.launch) return;
    inFlightRef.current = true;
    const operation = ++operationRef.current;
    const commandId = state.commandId || createCommandId();
    setState((current) => ({ ...current, phase: "submitting", error: null, commandId }));
    try {
      const result = await attemptStudyPackItem({ launch: state.launch, learnerAnswer: state.answer, commandId });
      if (!aliveRef.current || operation !== operationRef.current) return;
      inFlightRef.current = false;
      if (result.refreshedPack) onPackRefreshed(result.refreshedPack);
      setState((current) => ({ ...current, phase: "revealed", result, results: [...current.results, result], commandId: null }));
    } catch (error) {
      if (!aliveRef.current || operation !== operationRef.current) return;
      const recovery = studyPackWriteRecovery(error);
      if (recovery.refresh) {
        setState((current) => ({ ...current, phase: "recovering", error, commandId: null }));
        try {
          const refreshedPack = await onRefreshPack();
          const refreshedItems = practiceItemsFromPack(refreshedPack);
          const expectedIds = itemsRef.current.map((item) => item.artifactId);
          if (
            refreshedItems.length !== 3
            || refreshedItems.some((item, index) => item.artifactId !== expectedIds[index])
          ) {
            const mismatch = new Error("最新学习包与当前三道练习不一致。");
            mismatch.kind = "contract";
            mismatch.code = "invalid_study_pack_contract";
            throw mismatch;
          }
          itemsRef.current = refreshedItems;
          const relaunched = await launchStudyPackItem(refreshedItems[state.index]);
          createActivePracticeProjection(relaunched);
          if (!aliveRef.current || operation !== operationRef.current) return;
          inFlightRef.current = false;
          setState((current) => ({ ...current, phase: "active", launch: relaunched, result: null, error: null, commandId: null }));
        } catch (refreshError) {
          if (!aliveRef.current || operation !== operationRef.current) return;
          inFlightRef.current = false;
          setState((current) => ({ ...current, phase: "error", error: refreshError, commandId: null }));
        }
        return;
      }
      inFlightRef.current = false;
      setState((current) => ({ ...current, phase: "error", error, commandId: recovery.retainCommandId ? commandId : null }));
    }
  };

  const next = () => {
    if (state.index === itemsRef.current.length - 1) setState((current) => ({ ...current, phase: "completed" }));
    else launchAt(state.index + 1);
  };
  const retry = () => {
    if (state.launch && state.answer) submit();
    else launchAt(state.index);
  };
  const writeLocked = ["submitting", "recovering"].includes(state.phase);
  const safeExit = () => { if (!writeLocked) onExit(); };

  if (state.phase === "error") return <div className="study-pack-practice"><PracticeError error={state.error} onRetry={retry} onExit={safeExit} exitLocked={writeLocked} /></div>;
  if (state.phase === "completed") {
    const expectedArtifactIds = itemsRef.current.map((item) => item.artifactId);
    const summary = summarizePracticeResults(state.results, expectedArtifactIds);
    return (
      <div className="study-pack-practice completed" data-state="completed">
        <div className="practice-complete-mark"><CheckCircle size={26} weight="fill" /></div>
        <h1 ref={headingRef} tabIndex={-1}>本轮练习已完成</h1>
        <p>完成 3 道题，答对 {summary.correct} 道。结果只保存在这个学习包中，不会更新技能掌握、错因档案或今日计划。</p>
        <ol className="practice-result-list">
          {state.results.map((result, index) => <li key={result.attemptId}><span>第 {index + 1} 题</span><strong>{result.correct ? "正确" : "需再看"}</strong><span>{result.score} / {result.maxScore}</span></li>)}
        </ol>
        <button className="button primary" type="button" onClick={safeExit}>返回学习包</button>
      </div>
    );
  }

  const projection = state.launch ? createActivePracticeProjection(state.launch) : null;
  return (
    <div className="study-pack-practice" data-state={state.phase === "revealed" ? "answered" : "active"}>
      <div className="sr-only" role="status" aria-live="polite" aria-atomic="true">{state.phase === "revealed" ? (state.result.correct ? "回答正确，答案和解释已显示。" : "回答已提交，答案和解释已显示。") : state.phase === "recovering" ? "学习包状态已变化，正在读取最新题目。" : ""}</div>
      <header className="practice-header"><button className="back-link" type="button" onClick={safeExit} disabled={writeLocked}><ArrowLeft size={13} />退出练习</button><span>第 {state.index + 1} / 3 题</span></header>
      {["launching", "recovering"].includes(state.phase) ? (
        <div className="practice-loading" role="status"><BookOpenText size={20} /><strong>正在读取当前题目</strong><p>题目核验完成前不显示资料内容。</p></div>
      ) : (
        <section className="practice-question-shell">
          <div className="practice-question-heading"><small>请根据刚才学习的资料独立作答</small><h1 ref={headingRef} tabIndex={-1}>{projection.prompt}</h1></div>
          {state.phase !== "revealed" ? (
            <form className="practice-answer-form" onSubmit={submit}>
              <label htmlFor="pack-practice-answer">你的答案</label>
              <textarea id="pack-practice-answer" value={state.answer} autoFocus disabled={state.phase === "submitting"} onChange={(event) => setState((current) => ({ ...current, answer: event.target.value, commandId: null }))} placeholder="请在这里输入答案" required />
              <div className="practice-submit-row"><span>提交前不显示答案、解释或来源原文。</span><button className="button primary" type="submit" disabled={!state.answer.trim() || state.phase === "submitting"}>{state.phase === "submitting" ? "正在提交" : "提交答案"}</button></div>
            </form>
          ) : (
            <section className="practice-reveal">
              <header className={state.result.correct ? "correct" : "incorrect"}>{state.result.correct ? <CheckCircle size={18} /> : <XCircle size={18} />}<div><strong>{state.result.correct ? "回答正确" : "这题需要再看"}</strong><span>得分 {state.result.score} / {state.result.maxScore}</span></div></header>
              <dl><div><dt>正确答案</dt><dd>{state.result.answer}</dd></div><div><dt>解释</dt><dd>{state.result.explanation}</dd></div></dl>
              <div className="practice-cited-context"><strong>引用原文</strong>{state.result.citedContext.map((citation) => <blockquote key={`${citation.spanId}-${citation.fieldPointer}`}><p>{citation.excerpt}</p><footer>{locatorCopy(citation.locatorKind, citation.locatorIndex)} · 字符位置 {citation.startOffset}–{citation.endOffset}</footer></blockquote>)}</div>
              <button className="button primary" type="button" onClick={next}>{state.index === 2 ? "查看练习总结" : "继续下一题"}<ArrowRight size={13} /></button>
            </section>
          )}
        </section>
      )}
    </div>
  );
}

export function StudyPackMaterials() {
  const [collection, setCollection] = useState(INITIAL_COLLECTION);
  const [mode, setMode] = useState("list");
  const [selected, setSelected] = useState(null);
  const [detailState, setDetailState] = useState({ phase: "ready", error: null });
  const listHeadingRef = useHeadingFocus(mode === "list" ? "materials-list" : mode);
  const refreshOperationRef = useRef(0);

  const refresh = useCallback(async () => {
    const operation = ++refreshOperationRef.current;
    setCollection((current) => ({ ...current, phase: "loading", error: null }));
    try {
      const listing = await fetchStudyPackList();
      const settled = await Promise.allSettled(listing.map((item) => fetchStudyPack(item.packId)));
      if (operation !== refreshOperationRef.current) return;
      const items = settled.filter((result) => result.status === "fulfilled").map((result) => result.value);
      const failures = settled.filter((result) => result.status === "rejected");
      if (listing.length > 0 && items.length === 0) throw failures[0].reason;
      items.sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
      setCollection({ phase: "connected", items, error: null, partialErrorCount: failures.length });
    } catch (error) {
      if (operation !== refreshOperationRef.current) return;
      setCollection({ phase: error?.kind === "unavailable" ? "offline" : "error", items: [], error, partialErrorCount: 0 });
    }
  }, []);

  useEffect(() => {
    refresh();
    return () => { refreshOperationRef.current += 1; };
  }, [refresh]);

  const open = (pack) => { setSelected(pack); setDetailState({ phase: "ready", error: null }); setMode("detail"); };
  const update = (pack) => {
    setSelected(pack);
    setCollection((current) => ({ ...current, items: current.items.map((item) => item.packId === pack.packId ? pack : item) }));
  };
  const reloadSelected = async () => {
    if (!selected) throw new Error("没有可刷新的学习包。");
    setDetailState({ phase: "loading", error: null });
    try {
      const pack = await fetchStudyPack(selected.packId);
      update(pack);
      setDetailState({ phase: "ready", error: null });
      return pack;
    } catch (error) {
      setDetailState({ phase: error?.code === "stale_version" ? "stale" : "error", error });
      throw error;
    }
  };
  const completeCreate = (pack) => {
    setCollection((current) => ({ phase: "connected", error: null, partialErrorCount: current.partialErrorCount, items: [pack, ...current.items.filter((item) => item.packId !== pack.packId)] }));
    setSelected(pack); setDetailState({ phase: "ready", error: null }); setMode("detail");
  };
  const exitPractice = async () => {
    setMode("detail");
    try { await reloadSelected(); } catch { /* Detail view presents the read error. */ }
  };

  if (mode === "practice" && selected) {
    const practiceItems = practiceItemsFromPack(selected);
    return <StudyPackPractice practiceItems={practiceItems} onExit={exitPractice} onRefreshPack={reloadSelected} onPackRefreshed={update} />;
  }

  const importAvailable = collection.phase === "connected";
  const showHeadingImport = importAvailable && collection.items.length > 0;
  const ConnectionIcon = collection.phase === "connected" ? CheckCircle : collection.phase === "loading" ? SpinnerGap : WarningCircle;

  return (
    <div className="screen materials-screen">
      {mode === "import" ? <StudyPackImport onCancel={() => setMode("list")} onCreated={completeCreate} /> : mode === "detail" && selected ? (
        <StudyPackDetail pack={selected} viewState={detailState} onBack={() => { setMode("list"); refresh(); }} onReload={reloadSelected} onUpdated={update} onStartPractice={() => setMode("practice")} />
      ) : (
        <>
          <div className="page-heading row-between materials-heading"><div><h1 ref={listHeadingRef} tabIndex={-1}>学习资料</h1><p>把自己的文字资料整理成可核验、可练习的本机学习包。</p></div>{showHeadingImport && <button className="button primary" type="button" onClick={() => setMode("import")}><Plus size={13} />导入资料</button>}</div>
          <div className="materials-connection" data-state={collection.phase}><ConnectionIcon size={14} weight={collection.phase === "connected" ? "fill" : "regular"} className={collection.phase === "loading" ? "status-spinner" : ""} /><strong>{collection.phase === "connected" ? "本机资料已连接" : collection.phase === "loading" ? "正在连接本机资料" : "本机资料不可用"}</strong>{collection.phase === "connected" && <small>{collection.items.length} 个学习包</small>}</div>
          {collection.partialErrorCount > 0 && <div className="materials-partial-warning" role="status"><WarningCircle size={14} /><span>{collection.partialErrorCount} 个学习包未通过本机核验，已隐藏；其他学习包仍可使用。</span></div>}
          {collection.phase === "connected" ? <PackList items={collection.items} onOpen={open} onImport={() => setMode("import")} /> : <MaterialsState phase={collection.phase} error={collection.error} onRetry={refresh} />}
        </>
      )}
    </div>
  );
}
