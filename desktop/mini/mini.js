"use strict";

// Draws the timer the main process reports. The ring empties as the time runs out.
const RADIUS = 10.5;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;
const button = document.getElementById("timer");
const time = document.getElementById("time");
const count = document.getElementById("count");
const arc = button.querySelector(".arc");
let current = null;
let skew = 0;

function format(ms) {
  const seconds = Math.max(0, Math.ceil(ms / 1000));
  return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}

function draw() {
  if (!current) return;
  const { timer, labels, review } = current;
  const left = timer.running ? Math.max(0, timer.endsAt - (Date.now() + skew)) : timer.remainingMs;
  const share = timer.totalMs > 0 ? Math.min(1, left / timer.totalMs) : 0;
  arc.setAttribute("stroke-dasharray", `${CIRCUMFERENCE * share} ${CIRCUMFERENCE}`);
  button.classList.toggle("break", timer.phase === "break");
  button.classList.toggle("focus", timer.phase !== "break");
  button.classList.toggle("paused", !timer.running);
  const text = format(left);
  if (time.textContent !== text) time.textContent = text;
  const waiting = review > 99 ? "99+" : String(review);
  count.hidden = !(review > 0);
  if (count.textContent !== waiting) count.textContent = waiting;
  const phase = !timer.running ? labels.paused : timer.phase === "break" ? labels.break : labels.focus;
  const parts = [phase, labels.left.replace("{time}", text)];
  if (review > 0) parts.push(labels.review.replace("{count}", String(review)));
  const label = `${parts.join(". ")}. ${labels.open}`;
  if (button.getAttribute("aria-label") !== label) {
    button.setAttribute("aria-label", label);
    button.title = label;
  }
}

window.moahTimer.onState((state) => {
  current = state;
  // The main process's clock and this window's are the same computer's, but allow for a tiny gap.
  skew = state.now - Date.now();
  if (Math.abs(skew) < 2000) skew = 0;
  draw();
});
button.addEventListener("click", () => window.moahTimer.open());
setInterval(draw, 250);
