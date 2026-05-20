# UI Redesign — Design Spec

**Date:** 2026-05-20
**Status:** Approved (brainstorm complete)
**Scope:** Full frontend redesign of the Second Brain web app — `frontend/` only. Backend, routing semantics, and business logic are untouched.

## Goals

- Migrate from ad-hoc custom CSS to a token-driven design system built on **Shadcn/ui + Tailwind CSS**.
- Adopt a **Linear/Vercel-style** flat dark aesthetic: near-black background, 1px hairlines, single indigo accent, no gradients, rigid 4px spacing grid.
- Replace the current `TopBar + WikiSidebar + ChatPanel` layout with a **Linear-style icon rail + secondary sidebar + main + persistent chat panel** four-zone shell.
- Preserve all existing business logic, API hooks, and state stores. Presentation is fully swapped; logic is not.

## Non-Goals

- Backend changes (API, agents, DB).
- iOS app changes.
- Light theme (dark-only at launch; light is a stretch).
- New features beyond a command palette and help overlay; this is a redesign, not a feature push.

---

## Design System Foundation

### Library stack

- **Tailwind CSS** with CSS-variable theme tokens
- **Shadcn/ui** primitives copied into `frontend/src/components/ui/`
- **Radix** (via Shadcn) for accessibility primitives
- **lucide-react** for icons
- **cmdk** (via Shadcn `<Command>`) for the command palette
- **sonner** (via Shadcn) for toasts
- Existing libs retained: `@tanstack/react-query`, `react-router-dom`, `react-resizable-panels`, `@uiw/react-codemirror`, `react-markdown`, `remark-*`, `rehype-katex`

### Color tokens (dark-first)

Defined as CSS variables in `globals.css`, consumed via Tailwind:

| Token | Value | Usage |
|---|---|---|
| `--background` | `#0a0a0a` (zinc-950) | App background |
| `--foreground` | `#fafafa` (zinc-50) | Primary text |
| `--card` | `#0f0f0f` | Panels, cards |
| `--popover` | `#141414` | Menus, popovers |
| `--muted` | `#171717` (zinc-900) | Subdued surfaces, hover |
| `--muted-foreground` | `#a1a1aa` (zinc-400) | Secondary text |
| `--border` | `#27272a` (zinc-800) | 1px hairlines (workhorse) |
| `--input` | `#27272a` | Form borders |
| `--primary` | `#6366f1` (indigo-500) | Single accent — links, focus, primary buttons |
| `--primary-foreground` | `#fafafa` | Text on primary |
| `--destructive` | `#ef4444` (red-500) | Delete, error |
| `--ring` | `#6366f1` | Focus ring |

**Rules:** No gradients. No secondary accent. One accent — indigo-500. All color use goes through tokens.

### Typography

- `Inter` (variable) — sans, default. `font-feature-settings: "cv11", "ss01"` for Linear-style digits.
- `JetBrains Mono` — code blocks and inline code.
- Type scale: `text-xs` (11px) → `text-sm` (13px, **body default**) → `text-base` (14px) → `text-lg` (16px headings) → `text-2xl` (page titles). No oversized headers.

### Spacing & radius

- 4px base grid. Allowed Tailwind spacing units: `0, 1, 2, 3, 4, 6, 8, 12, 16`. No arbitrary `px-[13px]` style values.
- Radius scale: `rounded-md` (6px) default, `rounded-lg` (8px) for panels/cards, `rounded-full` for avatars/pills only.
- Shadows reserved for popovers/dialogs (`shadow-lg`); no shadows on flat surfaces.

---

## Shell Layout

Four zones, left to right:

```
┌──┬───────────────┬──────────────────────────┬──────────────┐
│  │  WIKI         │  ‹ Wiki › Note title  ⋯  │   Chat       │
│ 📚│ ─────────     ├──────────────────────────┤              │
│ 📁│ 📄 Page 1     │                          │   message    │
│ 🤖│ 📁 Folder     │      Main content        │   message    │
│ 🌐│   └ Sub-pg    │                          │              │
│ 💬│ 📄 Page 2     │                          │   ┌──────┐   │
│ ⚙│ + New page   │                          │   │ ask…│   │
└──┴───────────────┴──────────────────────────┴──────────────┘
 56px    240px              flex                  360px
 fixed   resizable          flex-1                resizable
```

### Icon rail (`w-14`, 56px, fixed)
- Icon-only navigation. Tooltips on hover via `<Tooltip>`.
- Sections (top): Wiki, Files, Automations, Browser, Sessions.
- Bottom-pinned: Help (`?`), Settings, user avatar/menu.
- Active item: 2px indigo left-edge accent bar + `bg-muted` background.

### Secondary sidebar (`react-resizable-panels`, default 240px, min 180px, collapsible via `⌘B`)
- Content varies per active rail section:
  - **Wiki** → page tree (current `WikiSidebar` logic, restyled)
  - **Files** → folder tree / sources list
  - **Automations** → automations list + filters
  - **Browser** → browser-chat sessions list
  - **Sessions** → flat session list grouped by date
- Header: section title + primary action button (e.g., "+ New page").
- Filter input below header.
- Tree: 13px text, 28px row height, indented children, hover `bg-muted`, active `bg-muted` + indigo left bar.

### Context bar (top of main, `h-10`, 40px)
- Breadcrumb on the left (`‹ Wiki › Note title`).
- Page actions on the right (icon buttons + a `⌘K` button opening the command palette).
- 1px bottom border, no shadow. Replaces the current fat `TopBar`.

### Main content (flex-1, scrollable)
- `max-w-4xl` centered for reading views (Wiki). `w-full` for app views (Files, Automations).
- Default padding `px-8 py-6`.

### Right chat panel (`react-resizable-panels`, default 360px, min 280px, max 600px, collapsible via `⌘J`)
- Persistent. Collapses to a 0px state with a floating reopen affordance.
- Session switcher pinned top (opens a `<Sheet>` listing all chat sessions).
- Messages list (scrollable). Assistant messages rendered as subtle `<Card>`; user as plain row.
- Composer pinned bottom with model picker + send.

### Command palette (`⌘K`)
- Shadcn `<Command>` (cmdk) at root of `App.tsx`.
- Scope: jump to wiki page, switch chat session, run automation, toggle chat/sidebar, change theme.

### Help / Shortcuts overlay (`⌘?` or `?`)
- Shadcn `<Dialog>` triggered by `⌘?` (or `?` when no input is focused).
- Sections:
  - **Navigation** — `⌘K` palette, `⌘B` toggle sidebar, `⌘J` toggle chat, `g w/f/a/b/s` jump to section
  - **Chat** — `⌘Enter` send, `⌘↑` edit last, `⌘N` new session
  - **Wiki** — `⌘E` edit, `⌘S` save, `/` focus search
- Layout: two-column grid; keys as `<Badge variant="outline">` styled like `<kbd>`, description right.
- Discoverability: `?` icon in the icon rail (above Settings); first-run toast pointing to it (localStorage flag).

---

## Component Migration Map

| Current | New | Notes |
|---|---|---|
| `Layout.tsx` | `AppShell.tsx` (new) | 4-zone grid |
| `TopBar.tsx` | `ContextBar.tsx` (40px) | Slimmer; breadcrumb + actions |
| `WikiSidebar.tsx` | `SecondarySidebar/WikiTree.tsx` | Generalized per section |
| `SessionDrawer.tsx` | Shadcn `<Sheet>` (right) | — |
| `IngestModal.tsx` | Shadcn `<Dialog>` | — |
| `SourceMetaModal.tsx` | Shadcn `<Dialog>` | — |
| `ActivityLog.tsx` | Shadcn `<Sheet>` | — |
| `ChatPanel.tsx` | Rewritten with Shadcn primitives | Same logic |
| `ChatConversation.tsx` | Restyled | Assistant as `<Card>`, user plain |
| `WikiContent.tsx` | Tailwind Typography (`prose prose-invert prose-zinc`) | Drop `github-markdown-css` |
| `FilesView.tsx` / `FilesList.tsx` | Shadcn `<Table>` + `<DropdownMenu>` | — |
| `FileViewer.tsx` | Shadcn `<Dialog>` | — |
| `AutomationsPage.tsx` | `<Table>` + `<Dialog>` create/edit | — |
| `BrowserChatPage.tsx` | Restyled with new tokens | — |
| — (new) | `CommandPalette.tsx` (`cmdk`/Shadcn `<Command>`) | Global ⌘K |
| — (new) | `HelpOverlay.tsx` (Shadcn `<Dialog>`) | ⌘? |
| — (new) | `ThemeProvider.tsx` | CSS-var-driven, dark default |

**Shadcn primitives to install:** `button, input, textarea, dialog, sheet, dropdown-menu, command, tooltip, separator, scroll-area, table, tabs, popover, sonner, avatar, badge, skeleton, resizable, kbd, card`.

**Removed:** inline `<style>` in `index.html`, `github-markdown-css`, all ad-hoc component CSS.

**Untouched:** `src/api/`, `src/hooks/`, `src/state/`, `auth.ts`, routing in `App.tsx` (route paths preserved), CodeMirror editor logic.

---

## Phased Roadmap

Each phase is an independent PR. Entry/exit criteria gate the next.

### Phase 0 — Foundation (no visible change)
- Install Tailwind, configure `tailwind.config.ts` with the token variables and the typography plugin
- Install Shadcn CLI, scaffold `components/ui/` with the 20-ish primitives listed above
- Add `Inter` + `JetBrains Mono` via `@fontsource`
- Create `ThemeProvider` (dark only) and put CSS variables in `globals.css`
- **Exit:** app builds, looks identical, Tailwind verified in a smoke-test component.

### Phase 1 — Shell
- Build `AppShell.tsx`, `IconRail.tsx`, `ContextBar.tsx`, `SecondarySidebar/` (with `WikiTree` first)
- Wire `react-resizable-panels` for secondary sidebar + main + chat
- Replace `Layout.tsx` + `TopBar.tsx` + `WikiSidebar.tsx`
- **Exit:** every existing route renders inside the new shell; no business-logic regressions.

### Phase 2 — Atomic components
- Migrate all buttons, inputs, textareas, selects to Shadcn primitives
- Migrate modals → `<Dialog>`; drawers → `<Sheet>`
- Add `<Toaster>` (sonner); route existing error/success messages through it
- **Exit:** no raw `<button>`/`<input>`/inline-styled modal remains.

### Phase 3 — Page views
- `FilesView`/`FilesList` → `<Table>` + `<DropdownMenu>`
- `AutomationsPage` → `<Table>` + Dialog flows
- `WikiContent` → Tailwind Typography; drop `github-markdown-css`
- `BrowserChatPage` → restyled
- `ChatPanel` + `ChatConversation` → rewritten styling, same logic
- **Exit:** no page still has legacy styles.

### Phase 4 — Power features & polish
- Command palette (`⌘K`)
- Keyboard shortcuts: `⌘B`, `⌘J`, `⌘?`, `g w/f/a/b/s`, `⌘Enter`, etc.
- Help / Shortcuts overlay (`⌘?`)
- Empty states, skeletons, loading audit
- Accessibility pass: focus rings, ARIA labels, tab order
- First-run help toast
- **Exit:** keyboard-driven flow works end-to-end.

### Effort estimate
Phase 0 ~½ day · Phase 1 ~1–2 days · Phase 2 ~1 day · Phase 3 ~2 days · Phase 4 ~1 day. Total ~6–7 dev-days.

---

## Risk Assessment & Safeguards

### Risks
- **Layout breakage on smaller viewports** — the four-zone shell is wide. Below ~1100px we need to auto-collapse the secondary sidebar; below ~900px also collapse the chat panel.
- **Markdown rendering regressions** when swapping `github-markdown-css` → Tailwind Typography. Code blocks, KaTeX, GFM tables need spot-checks.
- **CodeMirror theming** — needs explicit dark theme to match new tokens; default may clash.
- **Tightly-coupled presentation+logic** in `ChatPanel.tsx` and `ChatConversation.tsx` — restyle without touching SSE handling, optimistic updates, or session state.
- **Tailwind purge** — make sure `content` glob covers all `.tsx` paths including dynamically-classnamed components.

### Per-phase smoke-test checklist
After each phase, manually verify:
- Auth flow (Authentik login + redirect)
- Wiki page render (markdown, code, math)
- File upload + ingest
- Chat send + SSE streaming
- Automation run
- Browser-chat session

Plus: `tsc --noEmit` clean, `npm run build` clean, no console errors on a fresh load.

### Rollback
- Each phase is a discrete PR. Revert that PR.
- No backend/DB changes, so rollback is purely frontend.
- No feature flag needed unless a phase ships partially merged — keep PRs atomic and this isn't required.

---

## Out of scope (explicit)

- Light theme (deferred to a follow-up)
- Mobile/tablet layouts beyond "the shell collapses sensibly" (no native mobile UX redesign here)
- Reworking the iOS app
- Backend, agent, or DB changes
- Renaming routes or restructuring URLs

---

## Open questions

None at design-approval time. Implementation-level decisions (exact icon choices per section, exact `prose` class tuning, etc.) are deferred to the implementation plan.
