import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

test("responsive icon-only navigation buttons retain explicit accessible names", () => {
  const app = readFileSync(new URL("./App.jsx", import.meta.url), "utf8");
  const css = readFileSync(new URL("./styles.css", import.meta.url), "utf8");
  const mobileCss = css.slice(css.indexOf("@media (max-width: 650px)"));

  assert.match(mobileCss, /\.nav-item span,[\s\S]*?display:\s*none/);
  assert.match(mobileCss, /\.profile-row > span:not\(\.avatar\),[\s\S]*?display:\s*none/);
  assert.match(mobileCss, /\.global-search span\s*\{[^}]*display:\s*none/);
  assert.match(app, /NAV_ITEMS\.map[\s\S]*aria-label=\{label\}/);
  for (const label of ["设置", "意见反馈", "使用帮助"]) {
    assert.match(app, new RegExp(`className="nav-item"[^\n]*aria-label="${label}"`));
  }
  assert.match(app, /className="profile-row"[^\n]*aria-label="本机学习者"/);
  assert.match(app, /className="global-search"[^\n]*aria-label="打开全局搜索"/);
  assert.match(app, /className=\{`connection-status \$\{sidecar\.phase\}`\}[^\n]*aria-label=\{`\$\{connectionTitle\}，\$\{connectionDetail\}，点击重试`\}/);
});
