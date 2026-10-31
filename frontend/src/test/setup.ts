import { configure } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

// Slower machines, Windows above all, need more than the default second for a screen to settle.
configure({ asyncUtilTimeout: 10000 });

// jsdom has <dialog> but not its modal methods; mirror the open attribute so dialogs render in tests.
if (typeof HTMLDialogElement !== "undefined" && !HTMLDialogElement.prototype.showModal) {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.show = function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
}
