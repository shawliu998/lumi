const ALPHABET = "ABCDEFGHIJKLMNOP";
const RUN_ID = /^r_[A-P]{40}$/;
const COMMAND_ID = /^c_[A-P]{40}$/;

function createId(prefix) {
  if (typeof globalThis.crypto?.getRandomValues !== "function") {
    throw new TypeError("Web Crypto getRandomValues is required for persistent learning ids");
  }
  const bytes = globalThis.crypto.getRandomValues(new Uint8Array(20));
  const encoded = Array.from(bytes, (byte) => `${ALPHABET[byte >> 4]}${ALPHABET[byte & 15]}`).join("");
  return `${prefix}_${encoded}`;
}

export function createRunId() {
  return createId("r");
}

export function createCommandId() {
  return createId("c");
}

export function isRunId(value) {
  return typeof value === "string" && RUN_ID.test(value);
}

export function isCommandId(value) {
  return typeof value === "string" && COMMAND_ID.test(value);
}
