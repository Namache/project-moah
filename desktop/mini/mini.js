"use strict";

// Draws the timer the main process reports. The ring empties as the time runs out.
// Left mouse button: a press on the ring starts or pauses, a press on the time opens Moah, and
// holding the button down and moving drags the timer anywhere on the screen.
const RADIUS = 10.5;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;
// How far the pointer has to move (in pixels) before a press becomes a drag, so a slightly shaky click still clicks.
const DRAG_AFTER = 4;
const oval = document.getElementById("timer");
const toggle = document.getElementById("toggle");
const open = document.getElementById("open");
const time = document.getElementById("time");
const count = document.getElementById("count");
const arc = oval.querySelector(".arc");
let current = null;
let skew = 0;

function format(ms) {
  const seconds = Math.max(0, Math.ceil(ms / 1000));
  return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}

function setLabel(element, label) {
  if (element.getAttribute("aria-label") === label) return;
  element.setAttribute("aria-label", label);
  element.title = label;
}

function draw() {
  if (!current) return;
  const { timer, labels, review } = current;
  const left = timer.running ? Math.max(0, timer.endsAt - (Date.now() + skew)) : timer.remainingMs;
  const share = timer.totalMs > 0 ? Math.min(1, left / timer.totalMs) : 0;
  arc.setAttribute("stroke-dasharray", `${CIRCUMFERENCE * share} ${CIRCUMFERENCE}`);
  oval.classList.toggle("break", timer.phase === "break");
  oval.classList.toggle("focus", timer.phase !== "break");
  oval.classList.toggle("paused", !timer.running);
  oval.classList.toggle("waiting", Boolean(timer.waiting));
  oval.classList.toggle("idle", timer.phase === "idle");
  const text = format(left);
  if (time.textContent !== text) time.textContent = text;
  const waiting = review > 99 ? "99+" : String(review);
  count.hidden = !(review > 0);
  if (count.textContent !== waiting) count.textContent = waiting;

  const isBreak = timer.phase === "break";
  let phase;
  if (timer.phase === "idle") phase = labels.ready;
  else if (timer.waiting) phase = isBreak ? labels.breakReady : labels.focusReady;
  else if (!timer.running) phase = labels.paused;
  else phase = isBreak ? labels.break : labels.focus;
  const parts = [phase, labels.left.replace("{time}", text)];
  if (review > 0) parts.push(labels.review.replace("{count}", String(review)));
  setLabel(open, `${parts.join(". ")}. ${labels.open}`);
  let action;
  if (timer.running) action = labels.pause;
  else if (timer.phase === "idle") action = labels.start;
  else if (timer.waiting) action = isBreak ? labels.startBreak : labels.startFocus;
  else action = labels.resume;
  setLabel(toggle, action);
}

window.moahTimer.onState((state) => {
  current = state;
  // The main process's clock and this window's are the same computer's, but allow for a tiny gap.
  skew = state.now - Date.now();
  if (Math.abs(skew) < 2000) skew = 0;
  draw();
});

// One press of the left button: where it started, and whether it has become a drag.
let press = null;

oval.addEventListener("pointerdown", (event) => {
  if (event.button !== 0 || !event.isPrimary) return;
  event.preventDefault();
  press = { x: event.screenX, y: event.screenY, onToggle: toggle.contains(event.target), dragging: false };
  window.moahTimer.drag("start");
});

// The page keeps getting moves while the button is held, even when the pointer runs ahead of the window.
window.addEventListener("pointermove", (event) => {
  if (!press) return;
  if (!press.dragging && Math.hypot(event.screenX - press.x, event.screenY - press.y) < DRAG_AFTER) return;
  press.dragging = true;
  oval.classList.add("dragging");
  window.moahTimer.drag("move");
});

window.addEventListener("pointerup", (event) => {
  if (!press || event.button !== 0) return;
  const done = press;
  press = null;
  oval.classList.remove("dragging");
  if (done.dragging) {
    window.moahTimer.drag("end");
    return;
  }
  window.moahTimer.drag("cancel");
  if (done.onToggle) window.moahTimer.toggle();
  else window.moahTimer.open();
});

window.addEventListener("pointercancel", () => {
  if (!press) return;
  if (press.dragging) window.moahTimer.drag("end");
  else window.moahTimer.drag("cancel");
  press = null;
  oval.classList.remove("dragging");
});
// The buttons act on pointerup above, so a drag that ends on them never counts as a click.
oval.addEventListener("click", (event) => event.preventDefault());
setInterval(draw, 250);
