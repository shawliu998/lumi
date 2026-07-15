import assert from "node:assert/strict";
import test from "node:test";

import {
  resolvePracticeEnterAction,
  resolvePracticeOptionShortcut,
  shouldConfirmPracticeExit,
} from "../src/practiceKeyboard.js";

const options = [
  { id: "alpha", text: "选项 A" },
  { id: "beta", text: "选项 B" },
  { id: "gamma", text: "选项 C" },
  { id: "delta", text: "选项 D" },
  { id: "epsilon", text: "不应有快捷键的第五项" },
];

test("letter and number shortcuts map to no more than the first four options", () => {
  assert.equal(resolvePracticeOptionShortcut({ key: "a" }, options), "alpha");
  assert.equal(resolvePracticeOptionShortcut({ key: "A" }, options), "alpha");
  assert.equal(resolvePracticeOptionShortcut({ key: "b" }, options), "beta");
  assert.equal(resolvePracticeOptionShortcut({ key: "C" }, options), "gamma");
  assert.equal(resolvePracticeOptionShortcut({ key: "d" }, options), "delta");
  assert.equal(resolvePracticeOptionShortcut({ key: "1" }, options), "alpha");
  assert.equal(resolvePracticeOptionShortcut({ key: "2" }, options), "beta");
  assert.equal(resolvePracticeOptionShortcut({ key: "3" }, options), "gamma");
  assert.equal(resolvePracticeOptionShortcut({ key: "4" }, options), "delta");
  assert.equal(resolvePracticeOptionShortcut({ key: "e" }, options), null);
  assert.equal(resolvePracticeOptionShortcut({ key: "5" }, options), null);
  assert.equal(resolvePracticeOptionShortcut({ key: "D" }, options.slice(0, 3)), null);
});

test("arrow shortcuts cycle relative to the current option and wrap", () => {
  assert.equal(resolvePracticeOptionShortcut({ key: "ArrowDown" }, options, "alpha"), "beta");
  assert.equal(resolvePracticeOptionShortcut({ key: "ArrowDown" }, options, "delta"), "alpha");
  assert.equal(resolvePracticeOptionShortcut({ key: "ArrowUp" }, options, "delta"), "gamma");
  assert.equal(resolvePracticeOptionShortcut({ key: "ArrowUp" }, options, "alpha"), "delta");
  assert.equal(resolvePracticeOptionShortcut({ key: "ArrowDown" }, options), "alpha");
  assert.equal(resolvePracticeOptionShortcut({ key: "ArrowUp" }, options), "delta");
  assert.equal(resolvePracticeOptionShortcut({ key: "ArrowDown" }, [{ id: "only" }], "only"), "only");
});

test("option shortcuts leave editable targets, modified keys, and invalid input alone", () => {
  assert.equal(resolvePracticeOptionShortcut({ key: "a", target: { tagName: "INPUT", type: "text" } }, options), null);
  assert.equal(resolvePracticeOptionShortcut({ key: "a", target: { tagName: "INPUT", type: "search" } }, options), null);
  assert.equal(resolvePracticeOptionShortcut({ key: "a", target: { tagName: "TEXTAREA" } }, options), null);
  assert.equal(resolvePracticeOptionShortcut({ key: "a", target: { tagName: "SELECT" } }, options), null);
  assert.equal(resolvePracticeOptionShortcut({ key: "b", target: { tagName: "INPUT", type: "radio" } }, options), "beta");
  assert.equal(resolvePracticeOptionShortcut({ key: "a", target: { tagName: "SPAN", isContentEditable: true } }, options), null);
  assert.equal(resolvePracticeOptionShortcut({ key: "a", metaKey: true }, options), null);
  assert.equal(resolvePracticeOptionShortcut({ key: "a", ctrlKey: true }, options), null);
  assert.equal(resolvePracticeOptionShortcut({ key: "a", altKey: true }, options), null);
  assert.equal(resolvePracticeOptionShortcut({ key: "A", shiftKey: true }, options), null);
  assert.equal(resolvePracticeOptionShortcut({ key: "ArrowDown", repeat: true }, options, "alpha"), null);
  assert.equal(resolvePracticeOptionShortcut({ key: "Process", isComposing: true }, options), null);
  assert.equal(resolvePracticeOptionShortcut({ key: "Escape" }, options), null);
  assert.equal(resolvePracticeOptionShortcut({ key: "a" }, []), null);
  assert.equal(resolvePracticeOptionShortcut({ key: "a" }, null), null);
  assert.equal(resolvePracticeOptionShortcut(null, options), null);
});

test("plain Enter resolves to submit for questions and continue for feedback", () => {
  assert.equal(resolvePracticeEnterAction({ key: "Enter" }, "question"), "submit");
  assert.equal(resolvePracticeEnterAction({ key: "Enter" }, "feedback"), "continue");
  for (const phase of ["starting", "submitting", "complete", "error", undefined]) {
    assert.equal(resolvePracticeEnterAction({ key: "Enter" }, phase), null);
  }
  assert.equal(resolvePracticeEnterAction({ key: "Space" }, "question"), null);
});

test("Enter preserves text entry, disclosure, control, composition, and modifier behavior", () => {
  assert.equal(resolvePracticeEnterAction({ key: "Enter", target: { tagName: "TEXTAREA" } }, "question"), null);
  assert.equal(resolvePracticeEnterAction({ key: "Enter", target: { tagName: "INPUT", type: "text" } }, "question"), null);
  assert.equal(resolvePracticeEnterAction({ key: "Enter", target: { tagName: "INPUT", type: "radio" } }, "question"), "submit");
  assert.equal(resolvePracticeEnterAction({ key: "Enter", target: { tagName: "DETAILS" } }, "feedback"), null);
  assert.equal(resolvePracticeEnterAction({ key: "Enter", target: { tagName: "SUMMARY" } }, "feedback"), null);
  assert.equal(resolvePracticeEnterAction({
    key: "Enter",
    target: { tagName: "SPAN", closest: (selector) => selector === "details" ? {} : null },
  }, "feedback"), null);
  assert.equal(resolvePracticeEnterAction({ key: "Enter", target: { tagName: "BUTTON" } }, "feedback"), null);
  assert.equal(resolvePracticeEnterAction({ key: "Enter", metaKey: true }, "question"), null);
  assert.equal(resolvePracticeEnterAction({ key: "Enter", ctrlKey: true }, "question"), null);
  assert.equal(resolvePracticeEnterAction({ key: "Enter", altKey: true }, "question"), null);
  assert.equal(resolvePracticeEnterAction({ key: "Enter", shiftKey: true }, "question"), null);
  assert.equal(resolvePracticeEnterAction({ key: "Enter", isComposing: true }, "question"), null);
  assert.equal(resolvePracticeEnterAction({ key: "Enter", repeat: true }, "question"), null);
  assert.equal(resolvePracticeEnterAction({ key: "Enter", defaultPrevented: true }, "question"), null);
  assert.equal(resolvePracticeEnterAction(null, "question"), null);
});

test("an explicit confirmation protects in-progress answered groups", () => {
  assert.equal(shouldConfirmPracticeExit("feedback", 1), true);
  assert.equal(shouldConfirmPracticeExit("question", 3), true);
  assert.equal(shouldConfirmPracticeExit("error", 7), true);
  assert.equal(shouldConfirmPracticeExit("question", 0), false);
  assert.equal(shouldConfirmPracticeExit("starting", 0), false);
  assert.equal(shouldConfirmPracticeExit("complete", 8), false);
  assert.equal(shouldConfirmPracticeExit("question", null), false);
});
