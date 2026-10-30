// @vitest-environment node
import ts from "typescript";
import { describe, expect, it } from "vitest";
import { ru } from "./locales/ru";

/**
 * Keeps the app translatable: every text the interface shows goes through t(), tp(), tx() or msg(),
 * and every one of them has a Russian entry with the same {placeholders} and <tags>.
 */
const files = import.meta.glob(["./**/*.{ts,tsx}", "!./**/*.test.{ts,tsx}", "!./test/**", "!./locales/**"], { query: "?raw", import: "default", eager: true }) as Record<string, string>;

/** Text attributes a person reads or a screen reader speaks. */
const SPOKEN = new Set(["aria-label", "title", "label", "placeholder", "alt", "linkLabel", "hint", "description", "confirmLabel"]);
/** Names that stay the same in every language. */
const NAMES = new Set(["Claude Code", "Codex", "Claude", "Git", "Project Moah", "MCP", "Ctrl K", "⌘K", "Esc"]);

interface Found { keys: Set<string>; untranslated: string[] }

function scan(): Found {
  const keys = new Set<string>();
  const untranslated: string[] = [];
  for (const [file, text] of Object.entries(files)) {
    const source = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, file.endsWith("x") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
    const where = (node: ts.Node) => `${file}:${source.getLineAndCharacterOfPosition(node.getStart()).line + 1}`;
    const literal = (node: ts.Node | undefined) => (node && (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) ? node.text : null);
    const visit = (node: ts.Node) => {
      if (ts.isCallExpression(node) && ts.isIdentifier(node.expression)) {
        const name = node.expression.text;
        const args = node.arguments;
        if (name === "t" || name === "tx" || name === "msg") { const key = literal(args[0]); if (key !== null) keys.add(key); }
        if (name === "tp") { const other = literal(args[2]); if (other !== null) keys.add(other); }
      }
      if (ts.isJsxText(node)) {
        const words = node.getText().replace(/\s+/g, " ").trim();
        if (/\p{L}/u.test(words) && !NAMES.has(words)) untranslated.push(`${where(node)} text "${words}"`);
      }
      if (ts.isJsxAttribute(node) && SPOKEN.has(node.name.getText()) && node.initializer) {
        const value = ts.isStringLiteral(node.initializer) ? node.initializer.text
          : ts.isJsxExpression(node.initializer) && node.initializer.expression ? literal(node.initializer.expression) : null;
        if (value && /\p{L}/u.test(value) && !NAMES.has(value)) untranslated.push(`${where(node)} ${node.name.getText()}="${value}"`);
      }
      ts.forEachChild(node, visit);
    };
    visit(source);
  }
  return { keys, untranslated };
}

const found = scan();
const placeholders = (text: string) => [...text.matchAll(/\{(\w+)\}|<(\w+)>/g)].map((m) => m[0]).sort().join(" ");

describe("translation", () => {
  it("reads the app's source files", () => {
    expect(Object.keys(files).length).toBeGreaterThan(50);
  });

  it("shows no interface text outside t(), tp(), tx() or msg()", () => {
    expect(found.untranslated).toEqual([]);
  });

  it("has a Russian entry for every text", () => {
    expect([...found.keys].filter((key) => !(key in ru)).sort()).toEqual([]);
  });

  it("has no Russian entries the app no longer uses", () => {
    expect(Object.keys(ru).filter((key) => !found.keys.has(key)).sort()).toEqual([]);
  });

  it("keeps the same placeholders and tags in Russian", () => {
    const wrong = Object.entries(ru).flatMap(([key, value]) => (typeof value === "string" ? [value] : [...value])
      .filter((form) => placeholders(form).replace(/\{count\}/g, "") !== placeholders(key).replace(/\{count\}/g, ""))
      .map((form) => `${key} → ${form}`));
    expect(wrong).toEqual([]);
  });
});
