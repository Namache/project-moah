import { DndContext, DragOverlay, KeyboardSensor, PointerSensor, closestCorners, useDroppable, useSensor, useSensors, type DragEndEvent, type DragStartEvent } from "@dnd-kit/core";
import { SortableContext, sortableKeyboardCoordinates, useSortable, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { ChevronLeft, ChevronRight, MoreHorizontal, Plus } from "lucide-react";
import { taskStatusStyle } from "../../lib/tones";
import { toneClasses } from "../ui";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { TaskStatus, TaskSummary } from "../../types/task";
import { boardColumns } from "../../types/task";
import { FocusMark, TaskMeta } from "./TaskBits";
import { msg, t, tp } from "../../lib/i18n";

const DRAG_HINT = msg("Drag to another column, or press Space to pick up, arrow keys to move, Space to drop, and Escape to cancel.");

function CardBody({ task }: { task: TaskSummary }) {
  return (
    <>
      <div className="flex min-h-5 flex-wrap items-center gap-1.5 pr-6"><span className="break-all text-xs font-medium tabular-nums text-ink-subtle">{task.human_id}</span>{task.is_focus && <FocusMark compact />}</div>
      <p className="mt-1 break-words text-sm font-semibold leading-5 text-ink">{task.title}</p>
      <TaskMeta task={task} />
    </>
  );
}

function Card({ task, onOpen, onMove, selected, readOnly }: { task: TaskSummary; onOpen: (task: TaskSummary) => void; onMove: (id: string, status: TaskStatus, index: number) => void; selected: boolean; readOnly: boolean }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: task.id, data: { status: task.status }, disabled: readOnly });
  const [menuOpen, setMenuOpen] = useState(false);
  const menuButton = useRef<HTMLButtonElement>(null);
  return (
    <li ref={setNodeRef} style={{ transform: CSS.Transform.toString(transform), transition }}
      onBlur={(event) => { if (menuOpen && !event.currentTarget.contains(event.relatedTarget as Node | null)) setMenuOpen(false); }}
      onKeyDown={(event) => { if (event.key === "Escape" && menuOpen) { event.stopPropagation(); setMenuOpen(false); menuButton.current?.focus(); } }}
      className={`group relative rounded-lg border bg-surface shadow-card transition-shadow hover:shadow-card-hover ${selected ? "border-forest ring-1 ring-forest" : "border-line"} ${isDragging ? "opacity-40" : ""}`}>
      {/* The task button is the drag handle; the move menu has independent keyboard and pointer behavior. */}
      <button type="button" {...attributes} {...listeners} onClick={() => onOpen(task)} aria-label={`${task.human_id} ${task.title}`} aria-pressed={selected} title={readOnly ? undefined : t(DRAG_HINT)}
        className={`block w-full rounded-lg p-3 text-left focus-visible:outline-2 focus-visible:outline-forest ${readOnly ? "cursor-pointer" : "cursor-grab"}`}>
        <CardBody task={task} />
      </button>
      {!readOnly && <>
        <button ref={menuButton} type="button" aria-label={t("Move {id} to another status", { id: task.human_id })} title={t("Move to…")} aria-expanded={menuOpen}
          onClick={() => setMenuOpen((open) => !open)}
          className={`absolute right-1.5 top-1.5 inline-flex h-7 w-7 items-center justify-center rounded-md text-ink-subtle hover:bg-neutral-soft hover:text-ink focus-visible:outline-2 focus-visible:outline-forest ${menuOpen ? "bg-neutral-soft text-ink" : ""}`}>
          <MoreHorizontal size={16} aria-hidden="true" />
        </button>
        {menuOpen && <div role="group" aria-label={t("Move {id} to status", { id: task.human_id })} className="border-t border-line px-2 pb-2 pt-1.5">
          <p className="px-1 pb-1 text-xs font-semibold uppercase tracking-wide text-ink-subtle" aria-hidden="true">{t("Move to")}</p>
          <div className="flex flex-wrap gap-1">
            {boardColumns.filter((column) => column.status !== task.status).map((column) =>
              <button key={column.status} type="button" onClick={() => { setMenuOpen(false); onMove(task.id, column.status, Number.MAX_SAFE_INTEGER); }}
                className="rounded-md border border-line px-2 py-1 text-xs font-medium text-ink hover:border-forest hover:bg-sage-pale focus-visible:outline-2 focus-visible:outline-forest">
                {column.label}
              </button>
            )}
          </div>
        </div>}
      </>}
    </li>
  );
}

function Column({ status, label, tasks, onOpen, onMove, onAdd, selectedId, readOnly }: { status: TaskStatus; label: string; tasks: TaskSummary[]; onOpen: (task: TaskSummary) => void; onMove: (id: string, status: TaskStatus, index: number) => void; onAdd?: (status: TaskStatus) => void; selectedId: string | null; readOnly: boolean }) {
  const { setNodeRef, isOver } = useDroppable({ id: status, data: { status }, disabled: readOnly });
  const { tone, icon: Icon } = taskStatusStyle[status];
  return (
    <section aria-label={tp(tasks.length, "{column}, {count} task", "{column}, {count} tasks", { column: label })} className="flex min-w-0 flex-col rounded-xl bg-neutral-soft/60 p-2">
      <h2 className={`flex items-center gap-1.5 px-1.5 pb-1.5 pt-1 text-sm font-semibold ${toneClasses[tone].text}`}><Icon size={15} aria-hidden="true" /><span className="truncate">{label}</span><span className="text-xs font-medium tabular-nums text-ink-subtle">{tasks.length}</span></h2>
      {onAdd && !readOnly && <button type="button" onClick={() => onAdd(status)} className="mb-1.5 flex items-center gap-1.5 rounded-md px-1.5 py-1 text-left text-xs font-medium text-ink-subtle hover:bg-hover hover:text-forest focus-visible:outline-2 focus-visible:outline-forest"><Plus size={14} aria-hidden="true" />{t("Add task")}<span className="sr-only"> {t("to {column}", { column: label })}</span></button>}
      <SortableContext items={tasks.map((t) => t.id)} strategy={verticalListSortingStrategy}>
        <ul ref={setNodeRef} className={`min-h-24 flex-1 space-y-2 rounded-lg p-0.5 transition-colors ${isOver ? "bg-sage-pale" : ""}`}>
          {tasks.map((task) => <Card key={task.id} task={task} onOpen={onOpen} onMove={onMove} selected={task.id === selectedId} readOnly={readOnly} />)}
          {tasks.length === 0 && <li className="rounded-lg border border-dashed border-line-strong px-2 py-5 text-center text-xs text-ink-subtle">{readOnly ? t("No tasks") : t("Drop a task here")}</li>}
        </ul>
      </SortableContext>
    </section>
  );
}

/** Tracks whether a horizontally scrolling element has more content to either side. */
function useScrollEdges() {
  const ref = useRef<HTMLDivElement>(null);
  const [edges, setEdges] = useState({ left: false, right: false });
  const update = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    const left = el.scrollLeft > 1;
    const right = el.scrollLeft + el.clientWidth < el.scrollWidth - 1;
    setEdges((current) => (current.left === left && current.right === right ? current : { left, right }));
  }, []);
  useEffect(() => {
    update();
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(update);
    observer.observe(el);
    return () => observer.disconnect();
  }, [update]);
  return { ref, edges, update };
}

export function TaskBoard({ tasks, selectedId, onOpen, onMove, onAdd, readOnly = false }: { tasks: TaskSummary[]; selectedId: string | null; onOpen: (task: TaskSummary) => void; onMove: (id: string, status: TaskStatus, index: number) => void; onAdd?: (status: TaskStatus) => void; readOnly?: boolean }) {
  const [activeId, setActiveId] = useState<string | null>(null);
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }), useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates, keyboardCodes: { start: ["Space"], cancel: ["Escape"], end: ["Space"] } }));
  const columns = useMemo(() => boardColumns.map((c) => ({ ...c, tasks: tasks.filter((t) => t.status === c.status).sort((a, b) => a.sort_order - b.sort_order) })), [tasks]);
  const active = tasks.find((t) => t.id === activeId) ?? null;
  const scroll = useScrollEdges();

  function handleEnd(event: DragEndEvent) {
    setActiveId(null);
    const { active: dragged, over } = event;
    if (!over) return;
    const overStatus = (over.data.current?.status as TaskStatus | undefined) ?? (over.id as TaskStatus);
    const column = columns.find((c) => c.status === overStatus);
    const moving = tasks.find((t) => t.id === dragged.id);
    if (!column || !moving) return;
    const others = column.tasks.filter((t) => t.id !== moving.id);
    const overIndex = others.findIndex((t) => t.id === over.id);
    let index = overIndex === -1 ? others.length : overIndex;
    // Dropping lower in the same column lands after the card it was dropped on.
    if (moving.status === overStatus && overIndex !== -1 && column.tasks.findIndex((t) => t.id === moving.id) < column.tasks.findIndex((t) => t.id === over.id)) index = overIndex + 1;
    if (moving.status === overStatus && index === column.tasks.findIndex((t) => t.id === moving.id)) return;
    onMove(moving.id, overStatus, index);
  }

  return (
    <DndContext accessibility={{ screenReaderInstructions: { draggable: t(DRAG_HINT) } }} sensors={readOnly ? [] : sensors} collisionDetection={closestCorners} onDragStart={(e: DragStartEvent) => setActiveId(String(e.active.id))} onDragCancel={() => setActiveId(null)} onDragEnd={handleEnd}>
      {!readOnly && <p className="sr-only">{t("Drag cards to move them, or use the more button on a card. With a keyboard, focus a card and press Space, then the arrow keys.")}</p>}
      <div className="relative">
        {/* Six columns share the width down to a 148px minimum; below that the board scrolls, with fades marking the hidden side. */}
        <div ref={scroll.ref} onScroll={scroll.update} className="board-scroll grid auto-cols-[minmax(148px,1fr)] grid-flow-col gap-2 overflow-x-auto pb-2" role="group" aria-label={t("Task board")}>
          {columns.map((c) => <Column key={c.status} status={c.status} label={c.label} tasks={c.tasks} onOpen={onOpen} onMove={onMove} onAdd={onAdd} selectedId={selectedId} readOnly={readOnly} />)}
        </div>
        {scroll.edges.left && <div className="pointer-events-none absolute inset-y-0 left-0 flex w-12 items-start bg-gradient-to-r from-canvas to-transparent pt-1.5">
          <button type="button" tabIndex={-1} aria-hidden="true" title={t("Scroll left")} onClick={() => scroll.ref.current?.scrollBy({ left: -320, behavior: "smooth" })} className="pointer-events-auto inline-flex h-7 w-7 items-center justify-center rounded-full border border-line bg-surface text-ink-muted shadow-sm hover:text-forest"><ChevronLeft size={16} /></button>
        </div>}
        {scroll.edges.right && <div className="pointer-events-none absolute inset-y-0 right-0 flex w-12 items-start justify-end bg-gradient-to-l from-canvas to-transparent pt-1.5">
          <button type="button" tabIndex={-1} aria-hidden="true" title={t("Scroll right for more columns")} onClick={() => scroll.ref.current?.scrollBy({ left: 320, behavior: "smooth" })} className="pointer-events-auto inline-flex h-7 w-7 items-center justify-center rounded-full border border-line bg-surface text-ink-muted shadow-sm hover:text-forest"><ChevronRight size={16} /></button>
        </div>}
      </div>
      <DragOverlay dropAnimation={null}>{active && <div className="w-[220px] rotate-1 rounded-lg border border-forest bg-surface p-3 shadow-dialog"><CardBody task={active} /></div>}</DragOverlay>
    </DndContext>
  );
}
