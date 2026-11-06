/**
 * Which field dictation writes into: any text field the person clicked, anywhere in the app.
 * Fields are React-controlled, so text goes in through the browser's own value setter plus an
 * input event; each field's onChange then runs exactly as if the person had typed.
 */
export type TextField = HTMLInputElement | HTMLTextAreaElement;

const TEXT_INPUT_TYPES = new Set(["text", "search", "url", "email", ""]);

export function isDictatable(element: Element | null): element is TextField {
  if (element instanceof HTMLTextAreaElement) return !element.disabled && !element.readOnly;
  if (element instanceof HTMLInputElement) return TEXT_INPUT_TYPES.has(element.type) && !element.disabled && !element.readOnly;
  return false;
}

export function setFieldValue(field: TextField, value: string) {
  const limited = field.maxLength > 0 ? value.slice(0, field.maxLength) : value;
  const prototype = field instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(prototype, "value")?.set?.call(field, limited);
  field.dispatchEvent(new Event("input", { bubbles: true }));
}

/** The name a person sees for a field: its label, its accessible name, or its placeholder. */
export function fieldName(field: TextField): string {
  // A label's own words, without the extras inside it such as "*" or "Optional".
  const labelNode = field.labels?.[0];
  const label = labelNode ? [...labelNode.childNodes].filter((node) => node.nodeType === Node.TEXT_NODE).map((node) => node.textContent).join(" ").replace(/\*/g, "").replace(/\s+/g, " ").trim() : "";
  const labelledBy = field.getAttribute("aria-labelledby");
  const fromId = labelledBy ? document.getElementById(labelledBy)?.textContent?.trim() : "";
  return label || field.getAttribute("aria-label") || fromId || field.placeholder || "";
}
