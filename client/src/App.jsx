import { useCallback, useEffect, useId, useRef, useState } from "react";
import { CheckCircle, HardDrive, ShieldCheck, X } from "@phosphor-icons/react";
import { AppShell } from "./AppShell";
import { HomeScreen } from "./HomeScreen";
import { LearningRecordsScreen } from "./LearningRecordsScreen";
import { PracticeScreen } from "./PracticeScreen";
import { fetchCapabilities, fetchHealth } from "./hermesApi";
import { DEFAULT_SMART_PRACTICE_SCOPE_ID } from "./practiceScopes";

const INITIAL_SIDECAR_STATE = {
  phase: "checking",
  health: null,
  capabilities: null,
  error: null,
};

function SettingsDialog({ open, onClose, sidecar }) {
  const dialogRef = useRef(null);
  const closeRef = useRef(null);
  const titleId = useId();

  useEffect(() => {
    if (!open) return undefined;
    const previousFocus = document.activeElement;
    const frame = window.requestAnimationFrame(() => closeRef.current?.focus());
    return () => {
      window.cancelAnimationFrame(frame);
      previousFocus?.focus?.();
    };
  }, [open]);

  if (!open) return null;

  const handleKeyDown = (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      onClose();
      return;
    }
    if (event.key !== "Tab" || !dialogRef.current) return;
    const focusable = [...dialogRef.current.querySelectorAll("button:not([disabled]), [href], input:not([disabled])")];
    if (!focusable.length) return;
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

  const connected = sidecar.phase === "connected";
  return (
    <div className="lumi-settings-scrim" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section
        ref={dialogRef}
        className="lumi-settings-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onKeyDown={handleKeyDown}
      >
        <header>
          <div>
            <span>应用设置</span>
            <h2 id={titleId}>本机学习空间</h2>
          </div>
          <button ref={closeRef} type="button" className="lumi-icon-button" onClick={onClose} aria-label="关闭设置">
            <X size={18} />
          </button>
        </header>
        <div className="lumi-settings-body">
          <section>
            <HardDrive size={21} aria-hidden="true" />
            <div>
              <strong>记录保存在此 Mac</strong>
              <p>练习会话、作答证据和后续验证安排默认由本机服务保存。</p>
            </div>
            <span className={connected ? "is-ready" : "is-unavailable"}>
              {connected ? <CheckCircle size={15} weight="fill" /> : null}
              {connected ? "已就绪" : "暂不可用"}
            </span>
          </section>
          <section>
            <ShieldCheck size={21} aria-hidden="true" />
            <div>
              <strong>不要求云端账号</strong>
              <p>当前核心刷题、学习状态和轨迹检查不依赖登录。</p>
            </div>
          </section>
        </div>
        <footer><kbd>⌘ ,</kbd><span>随时打开设置</span></footer>
      </section>
    </div>
  );
}

export function App() {
  const [page, setPage] = useState("overview");
  const [practiceScopeId, setPracticeScopeId] = useState(DEFAULT_SMART_PRACTICE_SCOPE_ID);
  const [practiceLaunchRequest, setPracticeLaunchRequest] = useState(0);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [sidecar, setSidecar] = useState(INITIAL_SIDECAR_STATE);

  const refreshSidecar = useCallback(async () => {
    setSidecar((current) => ({ ...current, phase: "checking", error: null }));
    try {
      const [health, capabilities] = await Promise.all([fetchHealth(), fetchCapabilities()]);
      setSidecar({ phase: "connected", health, capabilities, error: null });
    } catch (error) {
      setSidecar({
        phase: error?.kind === "unavailable" ? "offline" : "error",
        health: null,
        capabilities: null,
        error,
      });
    }
  }, []);

  const refreshHealth = useCallback(async () => {
    try {
      const health = await fetchHealth();
      setSidecar((current) => ({ ...current, phase: "connected", health, error: null }));
      return health;
    } catch (error) {
      setSidecar((current) => ({
        ...current,
        phase: error?.kind === "unavailable" ? "offline" : "error",
        health: null,
        error,
      }));
      return null;
    }
  }, []);

  useEffect(() => {
    refreshSidecar();
  }, [refreshSidecar]);

  const openPractice = useCallback((scopeId) => {
    if (typeof scopeId === "string" && scopeId) setPracticeScopeId(scopeId);
    setPracticeLaunchRequest((value) => value + 1);
    setPage("practice");
  }, []);

  const navigate = useCallback((nextPage) => {
    setPracticeLaunchRequest(0);
    setPage(nextPage);
  }, []);

  return (
    <>
      <AppShell
        page={page}
        onNavigate={navigate}
        sidecar={sidecar}
        onRetrySidecar={refreshSidecar}
        onOpenSettings={() => setSettingsOpen(true)}
      >
        {page === "overview" && (
          <HomeScreen
            sidecar={sidecar}
            onStartPractice={openPractice}
            onOpenRecords={() => setPage("reports")}
            onRetrySidecar={refreshSidecar}
          />
        )}
        {page === "practice" && (
          <PracticeScreen
            sidecar={sidecar}
            onRetrySidecar={refreshSidecar}
            onRefreshSkills={refreshHealth}
            initialScopeId={practiceScopeId}
            launchRequest={practiceLaunchRequest}
            onLaunchHandled={() => setPracticeLaunchRequest(0)}
            onOpenRecords={() => setPage("reports")}
          />
        )}
        {page === "reports" && (
          <LearningRecordsScreen
            sidecar={sidecar}
            onStartPractice={openPractice}
            onRetrySidecar={refreshSidecar}
          />
        )}
      </AppShell>
      <SettingsDialog open={settingsOpen} onClose={() => setSettingsOpen(false)} sidecar={sidecar} />
    </>
  );
}
