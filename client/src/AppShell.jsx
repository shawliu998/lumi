import { useEffect, useId, useRef, useState } from "react";
import {
  CaretLeft,
  CaretRight,
  ChartBar,
  CheckCircle,
  Gear,
  House,
  Info,
  ListChecks,
  MagnifyingGlass,
} from "@phosphor-icons/react";
import lumiMark from "./assets/lumi-mark.png";

const NAV_ITEMS = [
  { id: "overview", label: "首页", icon: House },
  { id: "practice", label: "刷题", icon: ListChecks },
  { id: "reports", label: "学习记录", icon: ChartBar },
];

const PAGE_CONTEXT = {
  overview: ["首页", "今天从哪里开始"],
  practice: ["刷题", "选择范围并开始固定八题"],
  reports: ["学习记录", "查看真实作答留下的证据"],
};

function connectionCopy(phase) {
  if (phase === "connected") return ["本机已就绪", "connected"];
  if (phase === "checking") return ["正在准备", "checking"];
  if (phase === "error") return ["服务异常", "error"];
  return ["本机离线", "offline"];
}

function CommandPalette({ open, onClose, onNavigate, onOpenSettings }) {
  const [query, setQuery] = useState("");
  const inputRef = useRef(null);
  const dialogRef = useRef(null);
  const titleId = useId();

  useEffect(() => {
    if (!open) {
      setQuery("");
      return undefined;
    }
    const previousFocus = document.activeElement;
    const frame = window.requestAnimationFrame(() => inputRef.current?.focus());
    return () => {
      window.cancelAnimationFrame(frame);
      previousFocus?.focus?.();
    };
  }, [open]);

  if (!open) return null;

  const actions = [
    ...NAV_ITEMS.map((item) => ({
      id: item.id,
      label: `前往${item.label}`,
      detail: PAGE_CONTEXT[item.id][1],
      run: () => onNavigate(item.id),
    })),
    { id: "settings", label: "打开设置", detail: "本机数据与应用选项", run: onOpenSettings },
  ];
  const normalized = query.trim().toLocaleLowerCase("zh-CN");
  const visible = actions.filter((action) => (
    !normalized || `${action.label}${action.detail}`.toLocaleLowerCase("zh-CN").includes(normalized)
  ));

  const handleKeyDown = (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      onClose();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = [...dialogRef.current.querySelectorAll("button:not([disabled]), input:not([disabled])")];
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

  return (
    <div className="lumi-command-scrim" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section
        ref={dialogRef}
        className="lumi-command"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onKeyDown={handleKeyDown}
      >
        <h2 className="sr-only" id={titleId}>快速前往</h2>
        <label className="lumi-command-input">
          <MagnifyingGlass size={18} aria-hidden="true" />
          <input
            ref={inputRef}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索页面或操作"
            aria-label="搜索页面或操作"
          />
          <kbd>Esc</kbd>
        </label>
        <div className="lumi-command-results">
          {visible.map((action) => (
            <button
              type="button"
              key={action.id}
              onClick={() => {
                action.run();
                onClose();
              }}
            >
              <span><strong>{action.label}</strong><small>{action.detail}</small></span>
              <span className="lumi-command-enter">↵</span>
            </button>
          ))}
          {!visible.length && <p>没有匹配的页面或操作。</p>}
        </div>
      </section>
    </div>
  );
}

export function PageHeader({ eyebrow, title, description, action }) {
  return (
    <header className="lumi-page-header">
      <div>
        {eyebrow && <span>{eyebrow}</span>}
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      {action && <div className="lumi-page-action">{action}</div>}
    </header>
  );
}

export function AppShell({ page, onNavigate, sidecar, onRetrySidecar, onOpenSettings, children }) {
  const [collapsed, setCollapsed] = useState(false);
  const [commandOpen, setCommandOpen] = useState(false);
  const [connectionTitle, connectionState] = connectionCopy(sidecar.phase);
  const pageContext = PAGE_CONTEXT[page] || PAGE_CONTEXT.overview;

  useEffect(() => {
    const handleGlobalKeyDown = (event) => {
      if (event.defaultPrevented || document.querySelector("[aria-modal='true']")) return;
      if ((event.metaKey || event.ctrlKey) && event.key.toLocaleLowerCase() === "k") {
        event.preventDefault();
        setCommandOpen(true);
      }
      if (event.metaKey && event.key === ",") {
        event.preventDefault();
        onOpenSettings();
      }
    };
    document.addEventListener("keydown", handleGlobalKeyDown);
    return () => document.removeEventListener("keydown", handleGlobalKeyDown);
  }, [onOpenSettings]);

  return (
    <div className={collapsed ? "lumi-shell is-collapsed" : "lumi-shell"}>
      <aside className="lumi-sidebar" aria-label="应用侧栏">
        <div className="lumi-brand-row">
          <button
            type="button"
            className="lumi-brand"
            onClick={() => onNavigate("overview")}
            aria-label="前往 Lumi 首页"
          >
            <img src={lumiMark} alt="" />
            {!collapsed && <strong>Lumi</strong>}
          </button>
          {!collapsed && (
            <button type="button" className="lumi-icon-button" onClick={() => setCollapsed(true)} aria-label="收起侧栏">
              <CaretLeft size={17} />
            </button>
          )}
        </div>

        <nav className="lumi-primary-nav" aria-label="主导航">
          {NAV_ITEMS.map(({ id, label, icon: Icon }) => (
            <button
              type="button"
              key={id}
              className={page === id ? "is-active" : ""}
              onClick={() => onNavigate(id)}
              aria-current={page === id ? "page" : undefined}
              aria-label={collapsed ? label : undefined}
              title={collapsed ? label : undefined}
            >
              <Icon size={19} weight={page === id ? "fill" : "regular"} />
              {!collapsed && <span>{label}</span>}
            </button>
          ))}
        </nav>

        <div className="lumi-sidebar-spacer" />

        {sidecar.phase === "offline" || sidecar.phase === "error" ? (
          <button
            type="button"
            className={`lumi-local-state is-${connectionState}`}
            onClick={onRetrySidecar}
            title={collapsed ? `${connectionTitle}，点击重试` : undefined}
            aria-label={collapsed ? `${connectionTitle}，点击重试` : undefined}
            data-testid="sidecar-status"
            data-state={sidecar.phase}
          >
            <Info size={16} />
            {!collapsed && <span><strong>{connectionTitle}</strong><small>点击重新连接</small></span>}
          </button>
        ) : (
          <div
            className={`lumi-local-state is-${connectionState}`}
            title={collapsed ? connectionTitle : undefined}
            data-testid="sidecar-status"
            data-state={sidecar.phase}
          >
            {sidecar.phase === "connected" ? <CheckCircle size={16} weight="fill" /> : <span className="lumi-status-spinner" />}
            {!collapsed && <span><strong>{connectionTitle}</strong><small>记录保存在此 Mac</small></span>}
          </div>
        )}

        <button
          type="button"
          className="lumi-settings-button"
          onClick={onOpenSettings}
          title={collapsed ? "设置" : undefined}
          aria-label={collapsed ? "设置" : undefined}
        >
          <Gear size={19} />
          {!collapsed && <span>设置</span>}
        </button>
      </aside>

      <section className="lumi-app-main">
        <header className="lumi-toolbar">
          {collapsed && (
            <button type="button" className="lumi-icon-button" onClick={() => setCollapsed(false)} aria-label="展开侧栏">
              <CaretRight size={17} />
            </button>
          )}
          <div className="lumi-toolbar-context">
            <strong>{pageContext[0]}</strong>
            <span>{pageContext[1]}</span>
          </div>
          <button type="button" className="lumi-command-trigger" onClick={() => setCommandOpen(true)}>
            <MagnifyingGlass size={15} />
            <span>快速前往</span>
            <kbd>⌘ K</kbd>
          </button>
        </header>
        <main className="lumi-content">{children}</main>
      </section>

      <CommandPalette
        open={commandOpen}
        onClose={() => setCommandOpen(false)}
        onNavigate={onNavigate}
        onOpenSettings={onOpenSettings}
      />
    </div>
  );
}
