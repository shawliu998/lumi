const MAX_SHORTCUT_OPTIONS = 4;

const DIRECT_OPTION_INDEX = new Map([
  ["a", 0],
  ["1", 0],
  ["b", 1],
  ["2", 1],
  ["c", 2],
  ["3", 2],
  ["d", 3],
  ["4", 3],
]);

const NON_TEXT_INPUT_TYPES = new Set([
  "button",
  "checkbox",
  "color",
  "file",
  "hidden",
  "image",
  "radio",
  "range",
  "reset",
  "submit",
]);
const ENTER_OWNING_TAGS = new Set(["A", "BUTTON", "DETAILS", "SUMMARY"]);

function targetTagName(target) {
  return typeof target?.tagName === "string" ? target.tagName.toUpperCase() : "";
}

function hasModifiedKey(event) {
  return Boolean(
    event?.altKey
      || event?.ctrlKey
      || event?.metaKey
      || event?.shiftKey
      || event?.isComposing
      || event?.repeat,
  );
}

function isEditableElement(element) {
  if (!element) return false;
  const tagName = targetTagName(element);
  if (tagName === "TEXTAREA" || tagName === "SELECT" || element.isContentEditable === true) return true;
  if (tagName !== "INPUT") return false;
  const inputType = typeof element.type === "string" ? element.type.toLowerCase() : "text";
  return !NON_TEXT_INPUT_TYPES.has(inputType);
}

function isEditableTarget(target) {
  if (!target) return false;
  if (isEditableElement(target)) return true;
  if (typeof target.closest !== "function") return false;
  return isEditableElement(target.closest("input, textarea, select, [contenteditable='true']"));
}

function isInsideDetails(target) {
  const tagName = targetTagName(target);
  if (tagName === "DETAILS" || tagName === "SUMMARY") return true;
  return typeof target?.closest === "function" && Boolean(target.closest("details"));
}

function ownsEnterKey(target) {
  if (isEditableTarget(target) || isInsideDetails(target)) return true;
  const tagName = targetTagName(target);
  if (ENTER_OWNING_TAGS.has(tagName)) return true;
  return typeof target?.closest === "function" && Boolean(target.closest("a, button"));
}

function shortcutOptionIds(options) {
  if (!Array.isArray(options)) return [];
  return options
    .slice(0, MAX_SHORTCUT_OPTIONS)
    .map((option) => {
      const value = option && typeof option === "object" ? option.id : option;
      return value === null || value === undefined ? "" : String(value).trim();
    })
    .filter(Boolean);
}

/**
 * Resolves a plain keyboard event to one of the first four option IDs.
 *
 * A-D and 1-4 select by position. Arrow keys move relative to the current
 * option and wrap at either end. The function never mutates the event or the
 * options and returns null when the page should keep ownership of the key.
 */
export function resolvePracticeOptionShortcut(event, options, currentOptionId = null) {
  if (!event || event.defaultPrevented || hasModifiedKey(event) || isEditableTarget(event.target)) {
    return null;
  }

  const optionIds = shortcutOptionIds(options);
  if (optionIds.length === 0) return null;

  const key = typeof event.key === "string" ? event.key : "";
  const directIndex = DIRECT_OPTION_INDEX.get(key.toLowerCase());
  if (directIndex !== undefined) return optionIds[directIndex] ?? null;

  if (key !== "ArrowUp" && key !== "ArrowDown") return null;
  const currentIndex = optionIds.indexOf(String(currentOptionId ?? ""));
  if (currentIndex === -1) {
    return key === "ArrowDown" ? optionIds[0] : optionIds[optionIds.length - 1];
  }

  const offset = key === "ArrowDown" ? 1 : -1;
  return optionIds[(currentIndex + offset + optionIds.length) % optionIds.length];
}

/**
 * Returns the action owned by a plain Enter key in the active practice phase.
 * Interactive controls, text entry, and disclosure content retain their
 * native Enter behavior.
 */
export function resolvePracticeEnterAction(event, phase) {
  if (
    !event
      || event.key !== "Enter"
      || event.defaultPrevented
      || hasModifiedKey(event)
      || ownsEnterKey(event.target)
  ) {
    return null;
  }
  if (phase === "question") return "submit";
  if (phase === "feedback") return "continue";
  return null;
}

export function shouldConfirmPracticeExit(phase, answeredCount) {
  return phase !== "complete" && Number.isInteger(answeredCount) && answeredCount > 0;
}
