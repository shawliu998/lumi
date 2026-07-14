import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("./QuestionBankWorkspace.jsx", import.meta.url), "utf8");
const appSource = readFileSync(new URL("./App.jsx", import.meta.url), "utf8");

test("full question bank is a first-class local workspace", () => {
  assert.match(appSource, /id: "question-bank", label: "完整题库"/);
  assert.match(appSource, /page === "question-bank" && <QuestionBankWorkspace/);
  assert.match(source, /完整行测题库/);
  assert.match(source, /本机只读资源/);
  assert.match(source, /隔离待复核/);
});

test("unanswered question UI does not render an answer or explanation field", () => {
  assert.match(source, /result\.answer/);
  assert.match(source, /result\.explanation/);
  assert.doesNotMatch(source, /question\.answer/);
  assert.doesNotMatch(source, /question\.explanation/);
  assert.match(source, /不会直接更新 KT/);
  assert.match(source, /不会把一次答错解释成已确认错因/);
});

test("question bank handles offline assets and narrow layouts honestly", () => {
  assert.match(source, /不会隐式联网，也不会在题目不完整时评分/);
  assert.match(source, /function QuestionAssets/);
  assert.match(source, /questionBankAssetUrl\(asset\)/);
  assert.match(source, /题目材料图/);
  assert.match(source, /作答要求图/);
  assert.match(source, /选项 \$\{option\.label\} 配图/);
  assert.match(source, /解析中的图片尚未在答后视图展示/);
  assert.doesNotMatch(source, /asset\.source_path/);
  assert.doesNotMatch(source, /asset\.source_url/);
  assert.match(source, /onError=\{\(\) => onAssetError\(asset\.asset_id\)\}/);
  assert.match(source, /assetRenderFailed/);
  assert.match(source, /本机图片未能完整载入，本题已停止作答/);
  assert.match(source, /重新核对离线资源/);
  assert.match(source, /resultRef\.current\.scrollIntoView/);
  assert.match(source, /htmlFor="question-bank-search"/);
  assert.match(source, /等待离线资源/);
  assert.match(source, /请先安装经过校验的版本化本地导出/);
  assert.match(source, /question_bank_unavailable/);
});
