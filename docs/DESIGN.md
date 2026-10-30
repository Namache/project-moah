# Design rules

How Project Moah looks, behaves and talks. Follow these for every screen, so the app stays consistent when people and agents change it. The shared pieces live in `frontend/src/components/ui.tsx`; the tokens in `frontend/src/styles.css`.

## Principles

1. **Content first, minimal chrome.** Every control earns its place. If something is rarely needed, it goes behind a "⋯" menu, a collapsed panel or the command palette.
2. **Show, then tell.** Prefer an icon, a colour tone, a count or a progress bar over a sentence. Explanations go in a "?" tip or in Help, not under every heading.
3. **One way to do one thing.** The same action has the same name, icon, place and look everywhere.
4. **Nothing leaves the computer.** No web fonts, CDNs or remote images. Fonts and icons are bundled.

## Layout

- **Sidebar** (dark in both themes): logo, "+ New" (task, memory, project), search (Ctrl+K), daily pages, projects, then less-used pages, then Help and Settings at the bottom.
- **Page**: a title row (title on the left, at most one primary button on the right), then content. No breadcrumbs or back links: the sidebar is the way back.
- **Widgets and cards**: a small uppercase header with an icon, an optional "→" link to the full page, and the content. Cards never sit inside cards.
- Leave room for text about 30% longer than English (translations run long). Never give a button or tab a fixed width.

## Tokens

Use token classes only. Never raw Tailwind palette colours (`bg-red-100`) or hex values in components.

| Use | Classes |
|---|---|
| Page and card backgrounds | `bg-canvas`, `bg-surface`, `bg-hover` |
| Lines | `border-line`, `border-line-strong` |
| Text | `text-ink`, `text-ink-muted`, `text-ink-subtle` |
| Accent text, icons, focus | `text-forest`, `outline-forest` |
| Solid fill behind white text | `bg-primary` |
| Status tones | `neutral`, `info`, `success`, `warning`, `danger`, `special`: each has `bg-<tone>-soft` (tint), `text-<tone>-ink` (text on the tint) and `bg-<tone>` (dot, bar, solid) |
| Sidebar | `bg-side`, `text-side-ink`, `text-side-muted` |

**Tones by meaning.** Task status: backlog neutral, to do info, in progress warning, blocked danger, review special, done success. Memory type: decision success, rule special, fact info, idea warning, known issue danger, note neutral, warning warning. Colour is never the only signal: a tone always comes with a word or an icon.

**Sizes.** Text: `text-xs` (meta), `text-sm` (body, controls), `text-base` (card titles), `text-xl` (section), `text-2xl` (page title). No pixel sizes. Radii: `rounded-md` for small chips, `rounded-lg` for controls, `rounded-xl` for cards and widgets, `rounded-full` for pills and avatars.

## Components

| Need | Use | Not |
|---|---|---|
| Any button | `Button` (primary, secondary, quiet, danger) or `IconButton` (needs a label) | a raw `<button>` with its own classes |
| One main action per area | `variant="primary"` once | several green buttons in one view |
| Status or type label | `Badge` with a tone | hand-coloured spans |
| Switch between views or filters | `SegmentedControl` | a row of hand-made buttons |
| Rare actions on an item (edit, archive, delete) | `Menu` behind a "⋯" `IconButton` | a row of icon buttons |
| "Are you sure?" | `ConfirmDialog` | `window.confirm` |
| "It worked" / "It failed" | `notify()` (a short notice in the corner) | silent saves |
| Section on Home or a dashboard | `Widget` | a hand-built card |
| Nothing to show | `EmptyState` (icon, one line, one action) | a paragraph |

## Words

Sentence case everywhere ("Known issues", "AI context", "New task"), never Title Case. One word per thing:

| Say | Not |
|---|---|
| **memory** (one memory, two memories) | record, entry, memory item |
| **Inbox**: suggestions waiting for your decision. The sidebar Inbox shows every project, a project's Inbox tab shows that project | Review (for a page or tab) |
| **Review**: only the task status (the board column where finished work waits for a check) | |
| **Suggestion**: a change an agent proposes for you to accept or dismiss | proposal (in the interface) |
| **Delete**: gone forever, always confirmed | |
| **Remove**: take something off an item (an image, a link, a shelf) | delete |
| **Archive**: hide but keep, can be restored | |
| **Dismiss**: say no to a suggestion | skip, reject |
| **Context pack**, **Checkpoint**, **Handoff**, **Shelf** | |

Messages say what happened and what to do next: "Couldn't save. Check that Project Moah is still running, then try again."

An item on a shelf or in a suggestion can be a memory, a task or a file: call those **items**.

## Languages

The app speaks English and Russian (*Settings > General > Language*; System follows the computer). Everything is bundled; nothing is fetched.

- English text is the key. Interface text goes through `t()` (a sentence or label), `tp()` (a count, three Russian forms), `tx()` (a sentence with a link or bold inside, marked `<tag>…</tag>`) or `msg()` (text in a constant, translated where it is shown). See `frontend/src/lib/i18n.ts`.
- Whole sentences with `{placeholders}`, never glued pieces. Dates and numbers use `locale()`.
- Every key needs Russian in `frontend/src/locales/ru.ts`, with the same placeholders and tags. `src/i18n.test.ts` fails on untranslated text, missing or unused Russian, and placeholder mismatches.
- Help articles: English in `content/help/`, Russian with the same file name in `content/help/ru/`, same links, snippets and sections (checked by `help.test.tsx`).
- Text agents read stays English: context packs, MCP replies, brain suggestion `message`s. The app words suggestions itself from their `kind` and `args`.
- The diagnostic report stays English so anyone can read it.

Russian glossary (lowercase «вы», «ёлочки» quotes):

| English | Russian |
|---|---|
| memory / Memory (section) | запись, записи / Память |
| task, project, item | задача, проект, элемент |
| Inbox, Suggestion | Входящие, предложение |
| Review (task status) | На проверке |
| Delete, Remove, Archive, Restore, Dismiss | Удалить, Убрать, В архив, Восстановить, Отклонить |
| Lock / Locked, Pin / Pinned | Защитить / Защищена, Закрепить / Закреплена |
| Context pack, Checkpoint, Handoff, Shelf, Link | пакет контекста, контрольная точка, передача, полка, связь |
| Brain, Brain health, Global rules | Мозг, Здоровье мозга, Общие правила |
| Known issue, Milestone, Requirement | Известная проблема, Этап, Требование |
| AI context, AI visibility | Контекст для ИИ, Видимость для ИИ |
| Usage, Activity, Settings, Help | Расход, Активность, Настройки, Справка |
| Findable, Used lately, Learning | Достижимость, Использование, Обучение |
| Backlog, To do, In progress, Blocked, Done | Бэклог, К выполнению, В работе, Заблокировано, Готово |
| Active, Paused, Completed, Archived (statuses) | Активно, На паузе, Завершено, В архиве |

## Keyboard

Ctrl+K (⌘K on a Mac) or "/" opens the command palette. Escape closes any dialog, menu or panel. Every control is reachable with Tab and shows a focus ring.
