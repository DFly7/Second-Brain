# UI Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate `frontend/` from ad-hoc custom CSS to a Shadcn/ui + Tailwind design system with a Linear-style four-zone shell (icon rail / secondary sidebar / main / persistent chat panel), in five phased PRs.

**Architecture:** All business logic (`src/api/`, `src/hooks/`, `src/state/`, `auth.ts`, routing) is preserved. Presentation layer is fully replaced. Shadcn primitives are copied into `src/components/ui/`. CSS variables drive theming. `react-resizable-panels` powers the three resizable zones. New surfaces (command palette `⌘K`, help overlay `⌘?`) are added in Phase 4.

**Tech Stack:** React 18, Vite, TypeScript, Tailwind CSS, Shadcn/ui (Radix), `lucide-react`, `cmdk`, `sonner`, `@tanstack/react-query`, `react-router-dom`, `react-resizable-panels`, `@fontsource/inter`, `@fontsource/jetbrains-mono`.

**Spec:** `.agents/superpowers/plans/2026-05-20-ui-redesign-design.md`

**Testing approach:** This is a presentation-layer rewrite. Traditional unit-test TDD doesn't fit visual/structural changes well. We use:
- **Smoke tests** for new pure logic (command palette filter, theme provider state, keyboard shortcut dispatcher)
- **Manual smoke-test checklist** after each phase (auth, wiki render, file upload, ingest, chat SSE, automation run, browser-chat) — defined in the spec
- **Type-check + build** gates: every task ends with `tsc --noEmit` and (where it changes runtime behaviour) `npm run build` clean
- **Visual verification** in the dev server before marking a phase done

---

## File Structure

**New directories:**
- `frontend/src/components/ui/` — Shadcn primitives (one file per primitive, auto-scaffolded)
- `frontend/src/components/shell/` — `AppShell.tsx`, `IconRail.tsx`, `ContextBar.tsx`
- `frontend/src/components/secondary-sidebar/` — `SecondarySidebar.tsx`, `WikiTree.tsx`, `FilesTree.tsx`, `AutomationsList.tsx`, `BrowserSessionsList.tsx`, `SessionsList.tsx`
- `frontend/src/components/command-palette/` — `CommandPalette.tsx`, `commands.ts`
- `frontend/src/components/help/` — `HelpOverlay.tsx`, `shortcuts.ts`
- `frontend/src/components/theme/` — `ThemeProvider.tsx`
- `frontend/src/lib/` — `utils.ts` (Shadcn `cn()` helper), `keyboard.ts` (shortcut dispatcher)
- `frontend/src/styles/` — `globals.css`

**New config files:**
- `frontend/tailwind.config.ts`
- `frontend/postcss.config.js`
- `frontend/components.json` (Shadcn CLI config)

**Modified files:**
- `frontend/package.json` (deps)
- `frontend/tsconfig.json` (path alias `@/*`)
- `frontend/vite.config.ts` (path alias `@/*`)
- `frontend/index.html` (drop inline styles, add globals.css import via main.tsx)
- `frontend/src/main.tsx` (import globals.css, wrap with `ThemeProvider`)
- `frontend/src/App.tsx` (use `AppShell` instead of `Layout`; mount `CommandPalette`, `HelpOverlay`, `Toaster`)

**Replaced (deleted after migration):**
- `frontend/src/components/Layout.tsx` → `shell/AppShell.tsx`
- `frontend/src/components/TopBar.tsx` → `shell/ContextBar.tsx`
- `frontend/src/components/WikiSidebar.tsx` → `secondary-sidebar/WikiTree.tsx`

**Restyled in place (logic preserved):**
- `ChatPanel.tsx`, `ChatConversation.tsx`, `WikiContent.tsx`, `FilesView.tsx`, `FilesList.tsx`, `FileViewer.tsx`, `AutomationsPage.tsx`, `BrowserChatPage.tsx`, `IngestModal.tsx`, `SessionDrawer.tsx`, `SourceMetaModal.tsx`, `ActivityLog.tsx`

**Removed dependencies:** `github-markdown-css`

---

# Phase 0 — Foundation

No visible UI change. Establishes Tailwind, Shadcn, tokens, fonts, theme provider, path alias.

---

### Task 0.1: Install Tailwind, PostCSS, autoprefixer

**Files:**
- Modify: `frontend/package.json`

- [ ] **Step 1: Install Tailwind toolchain**

Run from `frontend/`:
```bash
npm install -D tailwindcss@^3.4.0 postcss@^8.4.0 autoprefixer@^10.4.0 @tailwindcss/typography@^0.5.0
```

- [ ] **Step 2: Verify install**

Run: `npx tailwindcss --help`
Expected: usage output, no error.

- [ ] **Step 3: Commit**

```bash
git add frontend/package.json frontend/package-lock.json
git commit -m "chore(frontend): add tailwind, postcss, typography plugin"
```

---

### Task 0.2: Configure path alias `@/*`

**Files:**
- Modify: `frontend/tsconfig.json`
- Modify: `frontend/vite.config.ts`
- Create: `frontend/src/lib/utils.ts`

- [ ] **Step 1: Add path alias to tsconfig**

Edit `frontend/tsconfig.json`, add inside `compilerOptions`:
```json
"baseUrl": ".",
"paths": { "@/*": ["./src/*"] }
```

- [ ] **Step 2: Add path alias to vite config**

Edit `frontend/vite.config.ts`. Add `import path from 'path'` at top. Add to `defineConfig`:
```ts
resolve: { alias: { '@': path.resolve(__dirname, './src') } },
```

- [ ] **Step 3: Install `clsx` and `tailwind-merge`**

Run from `frontend/`:
```bash
npm install clsx tailwind-merge
```

- [ ] **Step 4: Create the `cn()` helper**

Write `frontend/src/lib/utils.ts`:
```ts
import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
```

- [ ] **Step 5: Verify with a smoke import**

In a scratch place (or temporarily in `main.tsx`), add `import { cn } from '@/lib/utils'` and `console.log(cn('a', 'b'))`. Run `npm run build`. Expected: builds clean, console logs `"a b"` on dev.
Then remove the smoke import.

- [ ] **Step 6: Commit**

```bash
git add frontend/tsconfig.json frontend/vite.config.ts frontend/src/lib/utils.ts frontend/package.json frontend/package-lock.json
git commit -m "chore(frontend): add @/* path alias and cn() helper"
```

---

### Task 0.3: Tailwind config with token CSS variables

**Files:**
- Create: `frontend/tailwind.config.ts`
- Create: `frontend/postcss.config.js`
- Create: `frontend/src/styles/globals.css`
- Modify: `frontend/src/main.tsx`
- Modify: `frontend/index.html`

- [ ] **Step 1: Write `frontend/postcss.config.js`**

```js
export default {
  plugins: { tailwindcss: {}, autoprefixer: {} },
}
```

- [ ] **Step 2: Write `frontend/tailwind.config.ts`**

```ts
import type { Config } from 'tailwindcss'
import typography from '@tailwindcss/typography'

export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    container: { center: true, padding: '2rem', screens: { '2xl': '1400px' } },
    extend: {
      colors: {
        background: 'hsl(var(--background))',
        foreground: 'hsl(var(--foreground))',
        card: { DEFAULT: 'hsl(var(--card))', foreground: 'hsl(var(--card-foreground))' },
        popover: { DEFAULT: 'hsl(var(--popover))', foreground: 'hsl(var(--popover-foreground))' },
        muted: { DEFAULT: 'hsl(var(--muted))', foreground: 'hsl(var(--muted-foreground))' },
        primary: { DEFAULT: 'hsl(var(--primary))', foreground: 'hsl(var(--primary-foreground))' },
        destructive: { DEFAULT: 'hsl(var(--destructive))', foreground: 'hsl(var(--destructive-foreground))' },
        border: 'hsl(var(--border))',
        input: 'hsl(var(--input))',
        ring: 'hsl(var(--ring))',
      },
      borderRadius: { lg: '8px', md: '6px', sm: '4px' },
      fontFamily: {
        sans: ['Inter Variable', 'Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono Variable', 'JetBrains Mono', 'ui-monospace', 'monospace'],
      },
    },
  },
  plugins: [typography],
} satisfies Config
```

- [ ] **Step 3: Write `frontend/src/styles/globals.css`**

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

@layer base {
  :root {
    --background: 0 0% 4%;
    --foreground: 0 0% 98%;
    --card: 0 0% 6%;
    --card-foreground: 0 0% 98%;
    --popover: 0 0% 8%;
    --popover-foreground: 0 0% 98%;
    --muted: 0 0% 9%;
    --muted-foreground: 240 5% 65%;
    --primary: 239 84% 67%;
    --primary-foreground: 0 0% 98%;
    --destructive: 0 84% 60%;
    --destructive-foreground: 0 0% 98%;
    --border: 240 4% 16%;
    --input: 240 4% 16%;
    --ring: 239 84% 67%;
  }

  html, body, #root { height: 100%; }
  body {
    @apply bg-background text-foreground antialiased;
    font-feature-settings: "cv11", "ss01";
    font-size: 13px;
  }
  *, *::before, *::after { box-sizing: border-box; }
}
```

- [ ] **Step 4: Import `globals.css` in `main.tsx`**

Add at top of `frontend/src/main.tsx`:
```ts
import '@/styles/globals.css'
```

- [ ] **Step 5: Remove inline `<style>` from `index.html`**

Edit `frontend/index.html`. Delete the entire `<style>...</style>` block in `<head>`.

- [ ] **Step 6: Verify dev server**

Run from `frontend/`: `npm run dev`
Expected: app loads, background is near-black (`hsl(0 0% 4%)`), no console errors. Existing components are unstyled or partially styled — that's fine, they'll be migrated in later phases.

- [ ] **Step 7: Commit**

```bash
git add frontend/tailwind.config.ts frontend/postcss.config.js frontend/src/styles/globals.css frontend/src/main.tsx frontend/index.html
git commit -m "feat(frontend): wire tailwind with linear-style dark tokens"
```

---

### Task 0.4: Add Inter and JetBrains Mono fonts

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/src/main.tsx`

- [ ] **Step 1: Install fontsource packages**

Run from `frontend/`:
```bash
npm install @fontsource-variable/inter @fontsource-variable/jetbrains-mono
```

- [ ] **Step 2: Import fonts in `main.tsx`**

Add at top of `frontend/src/main.tsx` (after `globals.css` import):
```ts
import '@fontsource-variable/inter'
import '@fontsource-variable/jetbrains-mono'
```

- [ ] **Step 3: Verify**

Run `npm run dev`, open devtools, inspect body — `font-family` should resolve to Inter Variable. No console errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/src/main.tsx
git commit -m "feat(frontend): load inter and jetbrains mono fonts"
```

---

### Task 0.5: Initialize Shadcn CLI and scaffold primitives

**Files:**
- Create: `frontend/components.json`
- Create: `frontend/src/components/ui/*` (one file per primitive)

- [ ] **Step 1: Write `frontend/components.json` manually**

(Avoid the interactive `init` — write the config directly.)
```json
{
  "$schema": "https://ui.shadcn.com/schema.json",
  "style": "default",
  "rsc": false,
  "tsx": true,
  "tailwind": {
    "config": "tailwind.config.ts",
    "css": "src/styles/globals.css",
    "baseColor": "zinc",
    "cssVariables": true
  },
  "aliases": {
    "components": "@/components",
    "utils": "@/lib/utils",
    "ui": "@/components/ui",
    "lib": "@/lib",
    "hooks": "@/hooks"
  }
}
```

- [ ] **Step 2: Add primitives**

Run from `frontend/`:
```bash
npx shadcn@latest add button input textarea dialog sheet dropdown-menu command tooltip separator scroll-area table tabs popover sonner avatar badge skeleton resizable card
```

When prompted about overwrites: choose "yes".

- [ ] **Step 3: Verify each primitive exists**

Run from `frontend/`:
```bash
ls src/components/ui/ | sort
```
Expected lines (one per file, plus possibly `index.ts`):
`avatar.tsx badge.tsx button.tsx card.tsx command.tsx dialog.tsx dropdown-menu.tsx input.tsx popover.tsx resizable.tsx scroll-area.tsx separator.tsx sheet.tsx skeleton.tsx sonner.tsx table.tsx tabs.tsx textarea.tsx tooltip.tsx`

- [ ] **Step 4: Smoke-test build**

Run: `npm run build`
Expected: build succeeds. No type errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/components.json frontend/src/components/ui frontend/package.json frontend/package-lock.json
git commit -m "feat(frontend): scaffold shadcn/ui primitives"
```

---

### Task 0.6: ThemeProvider (dark-only)

**Files:**
- Create: `frontend/src/components/theme/ThemeProvider.tsx`
- Modify: `frontend/src/main.tsx`

- [ ] **Step 1: Write `ThemeProvider.tsx`**

```tsx
import { useEffect, type ReactNode } from 'react'

export function ThemeProvider({ children }: { children: ReactNode }) {
  useEffect(() => {
    const root = document.documentElement
    root.classList.add('dark')
    root.style.colorScheme = 'dark'
  }, [])
  return <>{children}</>
}
```

- [ ] **Step 2: Wrap app root**

Edit `frontend/src/main.tsx`. Wrap the existing render tree's outermost component in `<ThemeProvider>`:
```tsx
import { ThemeProvider } from '@/components/theme/ThemeProvider'
// inside the render call:
//   <ThemeProvider>
//     <App />  // or whatever the current root is
//   </ThemeProvider>
```

- [ ] **Step 3: Verify**

Run `npm run dev`. Devtools: `<html>` should have `class="dark"` and `style="color-scheme: dark"`. App background is `--background`.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/theme/ThemeProvider.tsx frontend/src/main.tsx
git commit -m "feat(frontend): add ThemeProvider (dark default)"
```

---

### Task 0.7: Phase 0 verification

- [ ] **Step 1: Type-check**

Run from `frontend/`: `npx tsc --noEmit`
Expected: zero errors.

- [ ] **Step 2: Production build**

Run from `frontend/`: `npm run build`
Expected: succeeds, no errors.

- [ ] **Step 3: Smoke-test**

Run `npm run dev`. Verify in browser:
- App loads
- Background is near-black
- Inter font is loaded (devtools → Network → Fonts)
- No console errors

- [ ] **Step 4: Tag completion**

```bash
git tag phase-0-complete
```

---

# Phase 1 — Shell

Build the new four-zone shell. Replace `Layout.tsx`, `TopBar.tsx`, `WikiSidebar.tsx`. Wire `react-resizable-panels` for the three resizable zones.

---

### Task 1.1: Install icon library

**Files:**
- Modify: `frontend/package.json`

- [ ] **Step 1: Install lucide-react**

Run from `frontend/`:
```bash
npm install lucide-react
```

- [ ] **Step 2: Verify import**

Open `frontend/src/main.tsx`, temporarily add `import { BookOpen } from 'lucide-react'; console.log(BookOpen)`. Run `npm run dev` — no error. Then remove the smoke import.

- [ ] **Step 3: Commit**

```bash
git add frontend/package.json frontend/package-lock.json
git commit -m "chore(frontend): add lucide-react icons"
```

---

### Task 1.2: Build `IconRail`

**Files:**
- Create: `frontend/src/components/shell/IconRail.tsx`

- [ ] **Step 1: Write the component**

Read `frontend/src/App.tsx` first to confirm route paths (`/wiki`, `/files`, `/automations`, `/browser`, `/sessions` or whatever they actually are). Adjust the `sections` array below to match the real paths.

```tsx
import { NavLink } from 'react-router-dom'
import { BookOpen, FolderOpen, Bot, Globe, MessageSquare, Settings, HelpCircle } from 'lucide-react'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'

const sections = [
  { to: '/wiki',        icon: BookOpen,      label: 'Wiki' },
  { to: '/files',       icon: FolderOpen,    label: 'Files' },
  { to: '/automations', icon: Bot,           label: 'Automations' },
  { to: '/browser',     icon: Globe,         label: 'Browser' },
  { to: '/sessions',    icon: MessageSquare, label: 'Sessions' },
]

export function IconRail() {
  return (
    <TooltipProvider delayDuration={300}>
      <nav className="flex h-full w-14 flex-col items-center border-r border-border bg-background py-3">
        <div className="flex flex-1 flex-col gap-1">
          {sections.map(({ to, icon: Icon, label }) => (
            <Tooltip key={to}>
              <TooltipTrigger asChild>
                <NavLink
                  to={to}
                  className={({ isActive }) =>
                    cn(
                      'relative flex h-9 w-9 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground',
                      isActive && 'bg-muted text-foreground before:absolute before:left-[-10px] before:top-1/2 before:h-5 before:w-0.5 before:-translate-y-1/2 before:rounded-r before:bg-primary'
                    )
                  }
                >
                  <Icon className="h-4 w-4" />
                </NavLink>
              </TooltipTrigger>
              <TooltipContent side="right">{label}</TooltipContent>
            </Tooltip>
          ))}
        </div>
        <div className="flex flex-col gap-1">
          <Tooltip>
            <TooltipTrigger asChild>
              <button className="flex h-9 w-9 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground" aria-label="Help">
                <HelpCircle className="h-4 w-4" />
              </button>
            </TooltipTrigger>
            <TooltipContent side="right">Help (?)</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <NavLink to="/settings" className="flex h-9 w-9 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground">
                <Settings className="h-4 w-4" />
              </NavLink>
            </TooltipTrigger>
            <TooltipContent side="right">Settings</TooltipContent>
          </Tooltip>
        </div>
      </nav>
    </TooltipProvider>
  )
}
```

- [ ] **Step 2: Type-check**

Run: `npx tsc --noEmit`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/shell/IconRail.tsx
git commit -m "feat(frontend): add IconRail with section navigation"
```

---

### Task 1.3: Build `ContextBar`

**Files:**
- Create: `frontend/src/components/shell/ContextBar.tsx`

- [ ] **Step 1: Write the component**

```tsx
import { type ReactNode } from 'react'
import { Search } from 'lucide-react'
import { Button } from '@/components/ui/button'

type Crumb = { label: string; href?: string }

export function ContextBar({
  breadcrumbs = [],
  actions,
  onOpenPalette,
}: {
  breadcrumbs?: Crumb[]
  actions?: ReactNode
  onOpenPalette?: () => void
}) {
  return (
    <header className="flex h-10 shrink-0 items-center justify-between gap-2 border-b border-border bg-background px-4">
      <nav className="flex items-center gap-1 text-sm text-muted-foreground">
        {breadcrumbs.map((c, i) => (
          <span key={i} className="flex items-center gap-1">
            {i > 0 && <span className="text-muted-foreground/50">/</span>}
            {c.href ? (
              <a href={c.href} className="hover:text-foreground">{c.label}</a>
            ) : (
              <span className={i === breadcrumbs.length - 1 ? 'text-foreground' : ''}>{c.label}</span>
            )}
          </span>
        ))}
      </nav>
      <div className="flex items-center gap-1">
        {actions}
        <Button variant="ghost" size="sm" className="h-7 gap-2 text-xs text-muted-foreground" onClick={onOpenPalette}>
          <Search className="h-3.5 w-3.5" />
          <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px]">⌘K</span>
        </Button>
      </div>
    </header>
  )
}
```

- [ ] **Step 2: Type-check**

Run: `npx tsc --noEmit`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/shell/ContextBar.tsx
git commit -m "feat(frontend): add ContextBar with breadcrumbs and palette button"
```

---

### Task 1.4: Build `SecondarySidebar` container

**Files:**
- Create: `frontend/src/components/secondary-sidebar/SecondarySidebar.tsx`

- [ ] **Step 1: Write the container**

```tsx
import { type ReactNode } from 'react'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Plus, Search } from 'lucide-react'

export function SecondarySidebar({
  title,
  primaryAction,
  onPrimaryAction,
  search,
  onSearchChange,
  children,
}: {
  title: string
  primaryAction?: string
  onPrimaryAction?: () => void
  search?: string
  onSearchChange?: (v: string) => void
  children: ReactNode
}) {
  return (
    <aside className="flex h-full flex-col border-r border-border bg-background">
      <div className="flex h-10 shrink-0 items-center justify-between border-b border-border px-3">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{title}</h2>
        {primaryAction && (
          <Button variant="ghost" size="sm" className="h-6 gap-1 px-2 text-xs" onClick={onPrimaryAction}>
            <Plus className="h-3 w-3" />
            {primaryAction}
          </Button>
        )}
      </div>
      {onSearchChange && (
        <div className="border-b border-border p-2">
          <div className="relative">
            <Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={search ?? ''}
              onChange={(e) => onSearchChange(e.target.value)}
              placeholder="Filter…"
              className="h-7 pl-7 text-xs"
            />
          </div>
        </div>
      )}
      <div className="flex-1 overflow-y-auto">{children}</div>
    </aside>
  )
}
```

- [ ] **Step 2: Type-check**

Run: `npx tsc --noEmit`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/secondary-sidebar/SecondarySidebar.tsx
git commit -m "feat(frontend): add SecondarySidebar container"
```

---

### Task 1.5: Port WikiSidebar logic into `WikiTree`

**Files:**
- Read first: `frontend/src/components/WikiSidebar.tsx`
- Create: `frontend/src/components/secondary-sidebar/WikiTree.tsx`

- [ ] **Step 1: Read the existing component**

Read `frontend/src/components/WikiSidebar.tsx` end-to-end. Identify: data source (query hook), tree shape, click handlers, new-page action.

- [ ] **Step 2: Write `WikiTree.tsx`**

Replicate the same data fetching and event handlers, but render rows with new styling. Reference template:

```tsx
import { useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { ChevronRight, FileText } from 'lucide-react'
import { cn } from '@/lib/utils'
import { SecondarySidebar } from './SecondarySidebar'
// import the same query hook WikiSidebar.tsx uses, e.g.:
// import { useWikiPages } from '@/hooks/useWikiPages'

type Node = { id: string; title: string; children?: Node[]; href: string }

function TreeRow({ node, depth, activeHref }: { node: Node; depth: number; activeHref: string }) {
  const [open, setOpen] = useState(true)
  const hasChildren = node.children && node.children.length > 0
  const isActive = node.href === activeHref
  return (
    <div>
      <Link
        to={node.href}
        className={cn(
          'group flex h-7 items-center gap-1 rounded-sm px-2 text-[13px] text-muted-foreground hover:bg-muted hover:text-foreground',
          isActive && 'bg-muted text-foreground before:mr-1 before:h-4 before:w-0.5 before:rounded-r before:bg-primary'
        )}
        style={{ paddingLeft: 8 + depth * 12 }}
      >
        {hasChildren ? (
          <button onClick={(e) => { e.preventDefault(); setOpen(!open) }} className="text-muted-foreground/60">
            <ChevronRight className={cn('h-3 w-3 transition-transform', open && 'rotate-90')} />
          </button>
        ) : (
          <FileText className="h-3 w-3 text-muted-foreground/60" />
        )}
        <span className="truncate">{node.title}</span>
      </Link>
      {hasChildren && open && node.children!.map((c) => (
        <TreeRow key={c.id} node={c} depth={depth + 1} activeHref={activeHref} />
      ))}
    </div>
  )
}

export function WikiTree() {
  const [filter, setFilter] = useState('')
  const { pathname } = useLocation()
  // const { data: tree } = useWikiPages() — use the exact hook from WikiSidebar.tsx
  const tree: Node[] = [] // REPLACE with real data

  const filtered = filter
    ? tree.filter((n) => n.title.toLowerCase().includes(filter.toLowerCase()))
    : tree

  return (
    <SecondarySidebar
      title="Wiki"
      primaryAction="New"
      onPrimaryAction={() => { /* trigger new-page modal/route — match WikiSidebar.tsx behaviour */ }}
      search={filter}
      onSearchChange={setFilter}
    >
      <div className="p-1">
        {filtered.map((n) => <TreeRow key={n.id} node={n} depth={0} activeHref={pathname} />)}
      </div>
    </SecondarySidebar>
  )
}
```

Replace the placeholder data and handlers with the real ones from `WikiSidebar.tsx`.

- [ ] **Step 3: Type-check**

Run: `npx tsc --noEmit`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/secondary-sidebar/WikiTree.tsx
git commit -m "feat(frontend): port wiki tree into SecondarySidebar/WikiTree"
```

---

### Task 1.6: Stub secondary sidebars for other sections

Create minimal placeholders. They'll be filled in Phase 3.

**Files:**
- Create: `frontend/src/components/secondary-sidebar/FilesTree.tsx`
- Create: `frontend/src/components/secondary-sidebar/AutomationsList.tsx`
- Create: `frontend/src/components/secondary-sidebar/BrowserSessionsList.tsx`
- Create: `frontend/src/components/secondary-sidebar/SessionsList.tsx`

- [ ] **Step 1: Write all four stubs**

Each file follows this pattern (substitute title):

```tsx
import { SecondarySidebar } from './SecondarySidebar'

export function FilesTree() {
  return (
    <SecondarySidebar title="Files">
      <div className="p-4 text-xs text-muted-foreground">Coming in Phase 3</div>
    </SecondarySidebar>
  )
}
```

Replicate for `AutomationsList` (title "Automations"), `BrowserSessionsList` (title "Browser"), `SessionsList` (title "Sessions").

- [ ] **Step 2: Type-check**

Run: `npx tsc --noEmit`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/secondary-sidebar/
git commit -m "feat(frontend): stub secondary sidebars for non-wiki sections"
```

---

### Task 1.7: Build `AppShell` with three resizable zones

**Files:**
- Create: `frontend/src/components/shell/AppShell.tsx`

- [ ] **Step 1: Inspect `Layout.tsx`**

Read `frontend/src/components/Layout.tsx` to confirm: how the existing chat panel is mounted, how the resizable behaviour works (likely `react-resizable-panels`), how routing is composed (e.g., `<Outlet />`).

- [ ] **Step 2: Write `AppShell.tsx`**

```tsx
import { useLocation, Outlet } from 'react-router-dom'
import { ResizablePanelGroup, ResizablePanel, ResizableHandle } from '@/components/ui/resizable'
import { IconRail } from './IconRail'
import { WikiTree } from '@/components/secondary-sidebar/WikiTree'
import { FilesTree } from '@/components/secondary-sidebar/FilesTree'
import { AutomationsList } from '@/components/secondary-sidebar/AutomationsList'
import { BrowserSessionsList } from '@/components/secondary-sidebar/BrowserSessionsList'
import { SessionsList } from '@/components/secondary-sidebar/SessionsList'
import { ChatPanel } from '@/components/ChatPanel'

function SecondaryForRoute() {
  const { pathname } = useLocation()
  if (pathname.startsWith('/wiki'))        return <WikiTree />
  if (pathname.startsWith('/files'))       return <FilesTree />
  if (pathname.startsWith('/automations')) return <AutomationsList />
  if (pathname.startsWith('/browser'))     return <BrowserSessionsList />
  if (pathname.startsWith('/sessions'))    return <SessionsList />
  return null
}

export function AppShell() {
  return (
    <div className="flex h-screen w-screen overflow-hidden bg-background text-foreground">
      <IconRail />
      <ResizablePanelGroup direction="horizontal" className="flex-1">
        <ResizablePanel defaultSize={18} minSize={14} maxSize={30} collapsible collapsedSize={0}>
          <SecondaryForRoute />
        </ResizablePanel>
        <ResizableHandle />
        <ResizablePanel defaultSize={56} minSize={30}>
          <main className="flex h-full flex-col">
            <Outlet />
          </main>
        </ResizablePanel>
        <ResizableHandle />
        <ResizablePanel defaultSize={26} minSize={20} maxSize={45} collapsible collapsedSize={0}>
          <ChatPanel />
        </ResizablePanel>
      </ResizablePanelGroup>
    </div>
  )
}
```

**Note:** If `ChatPanel` currently takes props (session id, etc.), pass them through here matching the old `Layout.tsx` exactly. Read `Layout.tsx` to verify.

- [ ] **Step 3: Type-check**

Run: `npx tsc --noEmit`
Expected: clean (may error if ChatPanel signature differs — fix the props passing).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/shell/AppShell.tsx
git commit -m "feat(frontend): add AppShell with three resizable zones"
```

---

### Task 1.8: Mount `AppShell` in `App.tsx`

**Files:**
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Read current `App.tsx`**

Identify where `<Layout>` (or whatever the current shell is) wraps the routes.

- [ ] **Step 2: Replace `<Layout>` with `<AppShell>`**

In the routes config, swap the wrapping component. `AppShell` renders an `<Outlet />`, so child routes work as before:

```tsx
import { AppShell } from '@/components/shell/AppShell'

// in the router:
//   <Route element={<AppShell />}>
//     <Route path="/wiki/*" element={<WikiContent />} />
//     ... existing child routes
//   </Route>
```

If the current app uses a non-`Outlet` pattern (e.g., `<Layout>{children}</Layout>` inside each page), instead just substitute `<AppShell>` for `<Layout>` in the same place — and adapt `AppShell` to accept `children` instead of using `<Outlet />`.

- [ ] **Step 3: Type-check**

Run: `npx tsc --noEmit`
Expected: clean.

- [ ] **Step 4: Visual smoke-test**

Run `npm run dev`. Open the app. Verify:
- Icon rail is on the left, 56px wide
- Secondary sidebar appears with Wiki tree (when on `/wiki` route)
- Main content area renders the active route's content
- Chat panel is on the right
- All three middle zones are resizable (drag the handles)
- No console errors

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.tsx
git commit -m "feat(frontend): mount AppShell as root layout"
```

---

### Task 1.9: Delete old `Layout.tsx`, `TopBar.tsx`, `WikiSidebar.tsx`

**Files:**
- Delete: `frontend/src/components/Layout.tsx`
- Delete: `frontend/src/components/TopBar.tsx`
- Delete: `frontend/src/components/WikiSidebar.tsx`

- [ ] **Step 1: Grep for residual imports**

Run from repo root:
```bash
grep -r "from.*components/Layout" frontend/src
grep -r "from.*components/TopBar" frontend/src
grep -r "from.*components/WikiSidebar" frontend/src
```
Expected: no results (only files were `App.tsx` and self-references).

- [ ] **Step 2: Delete the three files**

```bash
rm frontend/src/components/Layout.tsx frontend/src/components/TopBar.tsx frontend/src/components/WikiSidebar.tsx
```

- [ ] **Step 3: Type-check + build**

Run: `npx tsc --noEmit && npm run build`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/
git commit -m "refactor(frontend): remove legacy Layout, TopBar, WikiSidebar"
```

---

### Task 1.10: Phase 1 verification

- [ ] **Step 1: Type-check + build**

Run: `npx tsc --noEmit && npm run build`
Expected: clean.

- [ ] **Step 2: Manual smoke-test (from spec checklist)**

`npm run dev`. Verify each by hand:
- Authentik login flow completes
- Wiki page renders (markdown still displays even if unstyled)
- File upload works (existing modal still opens — may look unstyled)
- Ingest flow runs
- Chat send works, SSE streams a reply
- Automations page loads
- Browser-chat page loads

No console errors throughout.

- [ ] **Step 3: Tag**

```bash
git tag phase-1-complete
```

---

# Phase 2 — Atomic components

Migrate buttons, inputs, modals, drawers to Shadcn primitives. Add Toaster.

---

### Task 2.1: Mount global `<Toaster>` and wire utility

**Files:**
- Modify: `frontend/src/App.tsx`
- Create: `frontend/src/lib/toast.ts`

- [ ] **Step 1: Mount Toaster**

In `frontend/src/App.tsx`, import and render at app root (outside routes):
```tsx
import { Toaster } from '@/components/ui/sonner'
// inside the top-level return:
//   <Toaster position="bottom-right" theme="dark" />
```

- [ ] **Step 2: Create `frontend/src/lib/toast.ts`**

```ts
import { toast as sonner } from 'sonner'

export const toast = {
  success: (msg: string) => sonner.success(msg),
  error: (msg: string) => sonner.error(msg),
  info: (msg: string) => sonner.info(msg),
}
```

- [ ] **Step 3: Type-check**

Run: `npx tsc --noEmit`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/App.tsx frontend/src/lib/toast.ts
git commit -m "feat(frontend): mount sonner toaster"
```

---

### Task 2.2: Migrate `IngestModal` to `<Dialog>`

**Files:**
- Modify: `frontend/src/components/IngestModal.tsx`

- [ ] **Step 1: Read existing modal**

Read `frontend/src/components/IngestModal.tsx` to understand props (likely `open`, `onClose`, ingestion handlers) and the existing markup.

- [ ] **Step 2: Replace outer modal markup with Shadcn `<Dialog>`**

Wrap content in `<Dialog open={open} onOpenChange={(o) => !o && onClose()}>` with `<DialogContent>`, `<DialogHeader>`, `<DialogTitle>`, `<DialogFooter>` from `@/components/ui/dialog`. Replace any raw `<button>` with `<Button>` from `@/components/ui/button`. Replace `<input>` with `<Input>`. Replace `<textarea>` with `<Textarea>`.

Reference shape:
```tsx
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
// ...
return (
  <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
    <DialogContent className="max-w-lg">
      <DialogHeader><DialogTitle>Ingest source</DialogTitle></DialogHeader>
      {/* existing body, with <Input>, <Textarea>, <Button> swaps */}
      <DialogFooter>
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button onClick={handleSubmit}>Ingest</Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
)
```

Strip all inline styles. Strip any custom backdrop logic — Dialog handles it.

- [ ] **Step 3: Replace inline error/success messages with `toast`**

Wherever the old code rendered an inline error or success banner, call `toast.error(msg)` or `toast.success(msg)` from `@/lib/toast` instead.

- [ ] **Step 4: Type-check + visual test**

Run: `npx tsc --noEmit`
Then `npm run dev`, open the Ingest modal, submit a valid and invalid case. Verify toast appears.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/IngestModal.tsx
git commit -m "feat(frontend): migrate IngestModal to shadcn Dialog"
```

---

### Task 2.3: Migrate `SourceMetaModal` to `<Dialog>`

**Files:**
- Modify: `frontend/src/components/SourceMetaModal.tsx`

- [ ] **Step 1: Read existing component**

Read `frontend/src/components/SourceMetaModal.tsx`.

- [ ] **Step 2: Apply the same migration pattern as Task 2.2**

Wrap in `<Dialog>` / `<DialogContent>`. Swap all primitives. Route error/success through `toast`.

- [ ] **Step 3: Type-check + visual test**

Run: `npx tsc --noEmit`. Then in dev, open the source meta modal and verify.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/SourceMetaModal.tsx
git commit -m "feat(frontend): migrate SourceMetaModal to shadcn Dialog"
```

---

### Task 2.4: Migrate `SessionDrawer` to `<Sheet>`

**Files:**
- Modify: `frontend/src/components/SessionDrawer.tsx`

- [ ] **Step 1: Read existing component**

Read `frontend/src/components/SessionDrawer.tsx` to find props (open/close, session list).

- [ ] **Step 2: Replace with Shadcn `<Sheet>` (right side)**

```tsx
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet'

return (
  <Sheet open={open} onOpenChange={(o) => !o && onClose()}>
    <SheetContent side="right" className="w-96">
      <SheetHeader><SheetTitle>Sessions</SheetTitle></SheetHeader>
      {/* existing body, with Shadcn primitive swaps */}
    </SheetContent>
  </Sheet>
)
```

- [ ] **Step 3: Type-check + visual test**

Run: `npx tsc --noEmit`. Open the session drawer in dev.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/SessionDrawer.tsx
git commit -m "feat(frontend): migrate SessionDrawer to shadcn Sheet"
```

---

### Task 2.5: Migrate `ActivityLog` to `<Sheet>`

**Files:**
- Modify: `frontend/src/components/ActivityLog.tsx`

- [ ] **Step 1: Read existing component**

Read `frontend/src/components/ActivityLog.tsx`.

- [ ] **Step 2: Apply Sheet migration**

Same pattern as Task 2.4 — wrap in `<Sheet>` (right side, width `w-[28rem]`).

- [ ] **Step 3: Type-check + visual test**

Run: `npx tsc --noEmit`. Open the activity log in dev.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/ActivityLog.tsx
git commit -m "feat(frontend): migrate ActivityLog to shadcn Sheet"
```

---

### Task 2.6: Sweep remaining raw inputs/buttons

**Files:** all files under `frontend/src/components/` not in `ui/`.

- [ ] **Step 1: Find raw `<button>` elements**

Run from repo root:
```bash
grep -rn "<button" frontend/src/components | grep -v "components/ui/"
```

For each match (excluding ones inside icon rails where we already control styling): swap `<button>` for the Shadcn `<Button>` component with the appropriate `variant` (`default`, `ghost`, `outline`, `destructive`) and `size` (`default`, `sm`, `icon`).

- [ ] **Step 2: Find raw `<input>` elements**

```bash
grep -rn "<input" frontend/src/components | grep -v "components/ui/"
```

Swap for `<Input>` from `@/components/ui/input`. For text-area-like usage, swap for `<Textarea>`.

- [ ] **Step 3: Find raw `<select>` elements**

```bash
grep -rn "<select" frontend/src/components | grep -v "components/ui/"
```

Swap for Shadcn `<DropdownMenu>` (for actions) or — if you need a true select — install `select` primitive first:
```bash
cd frontend && npx shadcn@latest add select
```
Then use `<Select>`, `<SelectTrigger>`, `<SelectContent>`, `<SelectItem>`.

- [ ] **Step 4: Type-check + visual test**

Run: `npx tsc --noEmit && npm run build`. Then `npm run dev`, click through every page making sure buttons and inputs all render and work.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/
git commit -m "refactor(frontend): replace remaining raw inputs/buttons with shadcn primitives"
```

---

### Task 2.7: Phase 2 verification

- [ ] **Step 1: Verify no raw primitives remain**

Run:
```bash
grep -rn "<button\|<input \|<select " frontend/src/components | grep -v "components/ui/" | grep -v "// "
```
Expected: no results, or only intentional cases (document them inline).

- [ ] **Step 2: Smoke-test (full checklist)**

Auth → wiki render → file upload → ingest → chat SSE → automation run → browser-chat. All work, no console errors.

- [ ] **Step 3: Tag**

```bash
git tag phase-2-complete
```

---

# Phase 3 — Page views

Restyle the page-level views: tables, markdown rendering, chat conversation, browser-chat. Fill in the secondary-sidebar stubs.

---

### Task 3.1: Restyle `WikiContent` with Tailwind Typography

**Files:**
- Modify: `frontend/src/components/WikiContent.tsx`
- Modify: `frontend/package.json` (remove `github-markdown-css`)

- [ ] **Step 1: Read current implementation**

Read `frontend/src/components/WikiContent.tsx`. Find the import `import 'github-markdown-css/...'` and the class wrappers (`markdown-body`).

- [ ] **Step 2: Replace wrapper class with Tailwind Typography**

Remove the `import 'github-markdown-css/...'` line. Change the rendering wrapper:

```tsx
<article className="prose prose-invert prose-zinc max-w-none px-8 py-6">
  <ReactMarkdown
    remarkPlugins={[remarkGfm, remarkMath]}
    rehypePlugins={[rehypeKatex]}
  >
    {content}
  </ReactMarkdown>
</article>
```

- [ ] **Step 3: Verify code blocks and KaTeX render**

`npm run dev`. Open a wiki page with: a heading, a list, a code block, a table, and an inline math expression (`$x^2$`). All four should render correctly.

- [ ] **Step 4: Uninstall `github-markdown-css`**

Run from `frontend/`:
```bash
npm uninstall github-markdown-css
```

- [ ] **Step 5: Type-check + build**

`npx tsc --noEmit && npm run build`. Clean.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/WikiContent.tsx frontend/package.json frontend/package-lock.json
git commit -m "feat(frontend): restyle WikiContent with tailwind typography, drop github-markdown-css"
```

---

### Task 3.2: Restyle `ChatPanel` and `ChatConversation`

**Files:**
- Modify: `frontend/src/components/ChatPanel.tsx`
- Modify: `frontend/src/components/ChatConversation.tsx`

- [ ] **Step 1: Read both files end-to-end**

Identify: the SSE handling, message rendering, composer logic, model picker. **Do not touch any of that logic.**

- [ ] **Step 2: Restyle `ChatPanel` container**

Wrap with:
```tsx
<div className="flex h-full flex-col border-l border-border bg-background">
  <div className="flex h-10 shrink-0 items-center justify-between border-b border-border px-3">
    {/* session switcher button (existing logic) */}
  </div>
  <div className="flex-1 overflow-y-auto">
    <ChatConversation … />
  </div>
  <div className="border-t border-border p-3">
    {/* composer (existing logic) — use <Textarea> and <Button> */}
  </div>
</div>
```

- [ ] **Step 3: Restyle `ChatConversation` messages**

User messages: plain row, `text-sm`, `py-2 px-3`.
Assistant messages: wrap in `<Card>` from `@/components/ui/card`:
```tsx
import { Card } from '@/components/ui/card'

{messages.map((m) =>
  m.role === 'user' ? (
    <div key={m.id} className="px-3 py-2 text-sm text-foreground">
      {m.content}
    </div>
  ) : (
    <Card key={m.id} className="mx-3 my-2 border-border bg-card p-3 text-sm">
      {/* existing markdown rendering */}
    </Card>
  )
)}
```

Tool-call indicators, streaming spinners — keep their behaviour, restyle wrappers with Tailwind only.

- [ ] **Step 4: Type-check + smoke-test**

`npx tsc --noEmit`. Then `npm run dev`. Send a message, watch SSE stream in. Verify session switching still works.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ChatPanel.tsx frontend/src/components/ChatConversation.tsx
git commit -m "feat(frontend): restyle ChatPanel and ChatConversation"
```

---

### Task 3.3: Migrate `FilesView` / `FilesList` to `<Table>`

**Files:**
- Modify: `frontend/src/components/FilesView.tsx`
- Modify: `frontend/src/components/FilesList.tsx`

- [ ] **Step 1: Read both files**

Identify what each row exposes (name, size, type, actions).

- [ ] **Step 2: Replace list markup with Shadcn `<Table>`**

```tsx
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '@/components/ui/table'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Button } from '@/components/ui/button'
import { MoreHorizontal } from 'lucide-react'

return (
  <Table>
    <TableHeader>
      <TableRow>
        <TableHead>Name</TableHead>
        <TableHead>Size</TableHead>
        <TableHead>Type</TableHead>
        <TableHead className="w-10"></TableHead>
      </TableRow>
    </TableHeader>
    <TableBody>
      {files.map((f) => (
        <TableRow key={f.id}>
          <TableCell>{f.name}</TableCell>
          <TableCell>{f.size}</TableCell>
          <TableCell>{f.type}</TableCell>
          <TableCell>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="icon" className="h-7 w-7"><MoreHorizontal className="h-4 w-4" /></Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                {/* existing row actions */}
              </DropdownMenuContent>
            </DropdownMenu>
          </TableCell>
        </TableRow>
      ))}
    </TableBody>
  </Table>
)
```

- [ ] **Step 3: Type-check + smoke-test**

`npx tsc --noEmit`. Then `npm run dev`, upload a file, verify it lists, verify row actions work.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/FilesView.tsx frontend/src/components/FilesList.tsx
git commit -m "feat(frontend): migrate Files view to shadcn Table"
```

---

### Task 3.4: Migrate `FileViewer` to `<Dialog>`

**Files:**
- Modify: `frontend/src/components/FileViewer.tsx`

- [ ] **Step 1: Read current implementation**

- [ ] **Step 2: Apply same Dialog wrapping pattern as Task 2.2**

`<DialogContent className="max-w-4xl h-[80vh]">` to give room for previews.

- [ ] **Step 3: Type-check + smoke-test**

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/FileViewer.tsx
git commit -m "feat(frontend): migrate FileViewer to shadcn Dialog"
```

---

### Task 3.5: Restyle `AutomationsPage` with `<Table>` + `<Dialog>`

**Files:**
- Modify: `frontend/src/components/AutomationsPage.tsx`

- [ ] **Step 1: Read current implementation**

- [ ] **Step 2: Replace list with `<Table>`**

Same shape as Task 3.3.

- [ ] **Step 3: Wrap create/edit forms in `<Dialog>`**

Same pattern as Task 2.2.

- [ ] **Step 4: Type-check + smoke-test**

`npx tsc --noEmit`. Then `npm run dev`, view automations, create one, edit one, run one.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/AutomationsPage.tsx
git commit -m "feat(frontend): restyle AutomationsPage with Table and Dialog"
```

---

### Task 3.6: Restyle `BrowserChatPage`

**Files:**
- Modify: `frontend/src/components/BrowserChatPage.tsx`

- [ ] **Step 1: Read current implementation**

- [ ] **Step 2: Restyle**

Strip inline styles, apply Tailwind classes consistent with new tokens. Same chat-pattern as `ChatPanel`: assistant in `<Card>`, user plain, composer at bottom.

- [ ] **Step 3: Type-check + smoke-test**

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/BrowserChatPage.tsx
git commit -m "feat(frontend): restyle BrowserChatPage with new tokens"
```

---

### Task 3.7: Fill in secondary-sidebar stubs

**Files:**
- Modify: `frontend/src/components/secondary-sidebar/FilesTree.tsx`
- Modify: `frontend/src/components/secondary-sidebar/AutomationsList.tsx`
- Modify: `frontend/src/components/secondary-sidebar/BrowserSessionsList.tsx`
- Modify: `frontend/src/components/secondary-sidebar/SessionsList.tsx`

- [ ] **Step 1: For each stub, find the data hook**

In `FilesView.tsx`, `AutomationsPage.tsx`, etc., locate the existing query hook (e.g., `useFiles()`, `useAutomations()`).

- [ ] **Step 2: Render a list of items in each sidebar**

Template (apply per sidebar):
```tsx
import { useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { cn } from '@/lib/utils'
import { SecondarySidebar } from './SecondarySidebar'

export function FilesTree() {
  const [filter, setFilter] = useState('')
  const { pathname } = useLocation()
  // const { data: items = [] } = useFiles()
  const items: { id: string; name: string; href: string }[] = []
  const filtered = filter ? items.filter((i) => i.name.toLowerCase().includes(filter.toLowerCase())) : items

  return (
    <SecondarySidebar title="Files" search={filter} onSearchChange={setFilter}>
      <div className="p-1">
        {filtered.map((i) => (
          <Link
            key={i.id}
            to={i.href}
            className={cn(
              'flex h-7 items-center rounded-sm px-2 text-[13px] text-muted-foreground hover:bg-muted hover:text-foreground',
              pathname === i.href && 'bg-muted text-foreground'
            )}
          >
            <span className="truncate">{i.name}</span>
          </Link>
        ))}
      </div>
    </SecondarySidebar>
  )
}
```

Replace placeholder data and types with the real hook output per sidebar. For `SessionsList`, group by date with subheaders.

- [ ] **Step 3: Type-check + smoke-test**

`npx tsc --noEmit`. Then `npm run dev`, click through each section in the icon rail. Each shows its data in the secondary sidebar.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/secondary-sidebar/
git commit -m "feat(frontend): fill in FilesTree, AutomationsList, BrowserSessionsList, SessionsList"
```

---

### Task 3.8: Phase 3 verification

- [ ] **Step 1: Search for legacy styling residue**

```bash
grep -rn "style={{" frontend/src/components | grep -v "components/ui/" | grep -v "paddingLeft.*depth"
grep -rn "github-markdown" frontend/src
```
Each match should be inspected; flag any that's not a one-off for tree-indentation or similar narrow case. Replace with Tailwind classes where possible.

- [ ] **Step 2: Type-check + build**

`npx tsc --noEmit && npm run build`. Clean.

- [ ] **Step 3: Smoke-test (full checklist)**

Auth, wiki, file upload, ingest, chat SSE, automation run, browser-chat. No console errors.

- [ ] **Step 4: Tag**

```bash
git tag phase-3-complete
```

---

# Phase 4 — Power features & polish

Command palette, keyboard shortcuts, help overlay, empty states, accessibility.

---

### Task 4.1: Keyboard shortcut dispatcher

**Files:**
- Create: `frontend/src/lib/keyboard.ts`
- Create: `frontend/src/components/help/shortcuts.ts`

- [ ] **Step 1: Write the shortcuts registry**

`frontend/src/components/help/shortcuts.ts`:
```ts
export type Shortcut = {
  id: string
  keys: string          // human label, e.g. "⌘ K"
  match: (e: KeyboardEvent) => boolean
  description: string
  group: 'Navigation' | 'Chat' | 'Wiki'
}

const mod = (e: KeyboardEvent) => e.metaKey || e.ctrlKey

export const shortcuts: Shortcut[] = [
  { id: 'palette',     keys: '⌘ K',     group: 'Navigation', description: 'Open command palette',   match: (e) => mod(e) && e.key.toLowerCase() === 'k' },
  { id: 'sidebar',     keys: '⌘ B',     group: 'Navigation', description: 'Toggle secondary sidebar', match: (e) => mod(e) && e.key.toLowerCase() === 'b' },
  { id: 'chat',        keys: '⌘ J',     group: 'Navigation', description: 'Toggle chat panel',       match: (e) => mod(e) && e.key.toLowerCase() === 'j' },
  { id: 'help',        keys: '?',       group: 'Navigation', description: 'Show keyboard shortcuts', match: (e) => e.key === '?' && !mod(e) },
  { id: 'wikiSend',    keys: '⌘ Enter', group: 'Chat',       description: 'Send message',            match: (e) => mod(e) && e.key === 'Enter' },
  { id: 'newSession',  keys: '⌘ N',     group: 'Chat',       description: 'New chat session',         match: (e) => mod(e) && e.key.toLowerCase() === 'n' },
  { id: 'wikiEdit',    keys: '⌘ E',     group: 'Wiki',       description: 'Edit current page',       match: (e) => mod(e) && e.key.toLowerCase() === 'e' },
  { id: 'wikiSave',    keys: '⌘ S',     group: 'Wiki',       description: 'Save current page',       match: (e) => mod(e) && e.key.toLowerCase() === 's' },
]
```

- [ ] **Step 2: Write the dispatcher hook**

`frontend/src/lib/keyboard.ts`:
```ts
import { useEffect } from 'react'

export type ShortcutHandler = (id: string, e: KeyboardEvent) => void

export function useShortcuts(
  shortcuts: { id: string; match: (e: KeyboardEvent) => boolean }[],
  handler: ShortcutHandler,
) {
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const target = e.target as HTMLElement
      const isTyping = target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable
      for (const s of shortcuts) {
        if (s.match(e)) {
          // Allow ⌘-key shortcuts even when typing, but block bare-key shortcuts (like '?')
          if (isTyping && !(e.metaKey || e.ctrlKey)) continue
          e.preventDefault()
          handler(s.id, e)
          return
        }
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [shortcuts, handler])
}
```

- [ ] **Step 3: Type-check**

`npx tsc --noEmit`. Clean.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/keyboard.ts frontend/src/components/help/shortcuts.ts
git commit -m "feat(frontend): add keyboard shortcut dispatcher and registry"
```

---

### Task 4.2: Build `CommandPalette`

**Files:**
- Create: `frontend/src/components/command-palette/CommandPalette.tsx`
- Create: `frontend/src/components/command-palette/commands.ts`

- [ ] **Step 1: Write the commands list**

`commands.ts`:
```ts
import { type ReactNode } from 'react'
import { BookOpen, FolderOpen, Bot, Globe, MessageSquare, Plus } from 'lucide-react'

export type Command = {
  id: string
  label: string
  group: 'Navigate' | 'Actions'
  icon: ReactNode
  perform: (nav: (to: string) => void) => void
}

export const commands: Command[] = [
  { id: 'go-wiki',        label: 'Go to Wiki',        group: 'Navigate', icon: <BookOpen className="h-4 w-4" />,       perform: (n) => n('/wiki') },
  { id: 'go-files',       label: 'Go to Files',       group: 'Navigate', icon: <FolderOpen className="h-4 w-4" />,     perform: (n) => n('/files') },
  { id: 'go-automations', label: 'Go to Automations', group: 'Navigate', icon: <Bot className="h-4 w-4" />,            perform: (n) => n('/automations') },
  { id: 'go-browser',     label: 'Go to Browser',     group: 'Navigate', icon: <Globe className="h-4 w-4" />,          perform: (n) => n('/browser') },
  { id: 'go-sessions',    label: 'Go to Sessions',    group: 'Navigate', icon: <MessageSquare className="h-4 w-4" />,  perform: (n) => n('/sessions') },
  { id: 'new-page',       label: 'New wiki page',     group: 'Actions',  icon: <Plus className="h-4 w-4" />,           perform: (n) => n('/wiki/new') },
]
```

- [ ] **Step 2: Write the palette component**

`CommandPalette.tsx`:
```tsx
import { useNavigate } from 'react-router-dom'
import { CommandDialog, CommandInput, CommandList, CommandEmpty, CommandGroup, CommandItem } from '@/components/ui/command'
import { commands } from './commands'

export function CommandPalette({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const navigate = useNavigate()
  const groups = Array.from(new Set(commands.map((c) => c.group)))
  return (
    <CommandDialog open={open} onOpenChange={onOpenChange}>
      <CommandInput placeholder="Type a command or search…" />
      <CommandList>
        <CommandEmpty>No results found.</CommandEmpty>
        {groups.map((g) => (
          <CommandGroup key={g} heading={g}>
            {commands.filter((c) => c.group === g).map((c) => (
              <CommandItem
                key={c.id}
                onSelect={() => {
                  onOpenChange(false)
                  c.perform(navigate)
                }}
              >
                {c.icon}
                <span className="ml-2">{c.label}</span>
              </CommandItem>
            ))}
          </CommandGroup>
        ))}
      </CommandList>
    </CommandDialog>
  )
}
```

- [ ] **Step 3: Type-check**

`npx tsc --noEmit`. Clean.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/command-palette/
git commit -m "feat(frontend): add command palette"
```

---

### Task 4.3: Build `HelpOverlay`

**Files:**
- Create: `frontend/src/components/help/HelpOverlay.tsx`

- [ ] **Step 1: Write the component**

```tsx
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Badge } from '@/components/ui/badge'
import { shortcuts } from './shortcuts'

export function HelpOverlay({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const groups = Array.from(new Set(shortcuts.map((s) => s.group)))
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl">
        <DialogHeader><DialogTitle>Keyboard shortcuts</DialogTitle></DialogHeader>
        <div className="space-y-6">
          {groups.map((g) => (
            <section key={g}>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">{g}</h3>
              <div className="space-y-1">
                {shortcuts.filter((s) => s.group === g).map((s) => (
                  <div key={s.id} className="flex items-center justify-between text-sm">
                    <span>{s.description}</span>
                    <Badge variant="outline" className="font-mono">{s.keys}</Badge>
                  </div>
                ))}
              </div>
            </section>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  )
}
```

- [ ] **Step 2: Type-check**

`npx tsc --noEmit`. Clean.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/help/HelpOverlay.tsx
git commit -m "feat(frontend): add help overlay listing keyboard shortcuts"
```

---

### Task 4.4: Wire palette, overlay, and shortcuts into `AppShell`

**Files:**
- Modify: `frontend/src/components/shell/AppShell.tsx`
- Modify: `frontend/src/components/shell/IconRail.tsx`

- [ ] **Step 1: Add open-state for palette + overlay, and toggles for panels**

In `AppShell.tsx`:
```tsx
import { useState, useRef } from 'react'
import { useShortcuts } from '@/lib/keyboard'
import { shortcuts as shortcutsRegistry } from '@/components/help/shortcuts'
import { CommandPalette } from '@/components/command-palette/CommandPalette'
import { HelpOverlay } from '@/components/help/HelpOverlay'
import { type ImperativePanelHandle } from 'react-resizable-panels'

// inside AppShell():
const [paletteOpen, setPaletteOpen] = useState(false)
const [helpOpen, setHelpOpen] = useState(false)
const sidebarRef = useRef<ImperativePanelHandle>(null)
const chatRef = useRef<ImperativePanelHandle>(null)

useShortcuts(shortcutsRegistry, (id) => {
  if (id === 'palette') setPaletteOpen(true)
  else if (id === 'help') setHelpOpen(true)
  else if (id === 'sidebar') {
    const p = sidebarRef.current
    if (p) (p.getCollapsed() ? p.expand() : p.collapse())
  } else if (id === 'chat') {
    const p = chatRef.current
    if (p) (p.getCollapsed() ? p.expand() : p.collapse())
  }
})

// attach refs to the resizable panels:
//   <ResizablePanel ref={sidebarRef} … >
//   <ResizablePanel ref={chatRef} … >

// at the end of the return, alongside the layout:
//   <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} />
//   <HelpOverlay open={helpOpen} onOpenChange={setHelpOpen} />
```

- [ ] **Step 2: Wire the help-icon button in `IconRail`**

The help button in `IconRail.tsx` currently does nothing. Lift its click handler up by accepting an `onOpenHelp` prop:

```tsx
export function IconRail({ onOpenHelp }: { onOpenHelp: () => void }) {
  // …
  <button onClick={onOpenHelp} … >
```

Pass it from `AppShell`:
```tsx
<IconRail onOpenHelp={() => setHelpOpen(true)} />
```

- [ ] **Step 3: Wire the `⌘K` button in `ContextBar`**

The `ContextBar` already accepts `onOpenPalette`. Pass it from wherever ContextBar is mounted (likely page views in Phase 3 — verify and pass `() => setPaletteOpen(true)`).

If `ContextBar` isn't yet centralized, expose `setPaletteOpen` via React context. Create `frontend/src/components/shell/ShellContext.tsx`:
```tsx
import { createContext, useContext } from 'react'
export const ShellContext = createContext<{ openPalette: () => void; openHelp: () => void }>({ openPalette: () => {}, openHelp: () => {} })
export const useShell = () => useContext(ShellContext)
```
Wrap `<Outlet />` in `AppShell`:
```tsx
<ShellContext.Provider value={{ openPalette: () => setPaletteOpen(true), openHelp: () => setHelpOpen(true) }}>
  <Outlet />
</ShellContext.Provider>
```
Then in `ContextBar`, call `useShell().openPalette` for the ⌘K button.

- [ ] **Step 4: Smoke-test all shortcuts**

`npm run dev`. Test: `⌘K` opens palette, `⌘B` collapses/expands sidebar, `⌘J` collapses/expands chat, `?` (no focused input) opens help.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/shell/ frontend/src/components/secondary-sidebar/ 2>/dev/null; true
git add frontend/src/components/shell/AppShell.tsx frontend/src/components/shell/IconRail.tsx frontend/src/components/shell/ShellContext.tsx
git commit -m "feat(frontend): wire command palette, help overlay, and shortcut dispatcher"
```

---

### Task 4.5: First-run help hint

**Files:**
- Modify: `frontend/src/components/shell/AppShell.tsx`

- [ ] **Step 1: Add localStorage-gated toast**

In `AppShell.tsx`, after the `useShortcuts` call:
```tsx
import { useEffect } from 'react'
import { toast } from '@/lib/toast'

useEffect(() => {
  if (localStorage.getItem('sb.helpHintShown') === '1') return
  const t = setTimeout(() => {
    toast.info('Press ? for keyboard shortcuts')
    localStorage.setItem('sb.helpHintShown', '1')
  }, 2000)
  return () => clearTimeout(t)
}, [])
```

- [ ] **Step 2: Smoke-test**

In dev, run `localStorage.removeItem('sb.helpHintShown')` in devtools, reload — toast appears after 2s. Reload again — toast does not appear.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/shell/AppShell.tsx
git commit -m "feat(frontend): show first-run help hint toast"
```

---

### Task 4.6: Empty states and skeletons audit

**Files:** any page that fetches data — `FilesView.tsx`, `AutomationsPage.tsx`, `SessionsList.tsx`, `ChatPanel.tsx`, etc.

- [ ] **Step 1: Find loading states**

```bash
grep -rn "isLoading\|isPending" frontend/src/components | grep -v "components/ui/"
```

For each, ensure the loading state renders a `<Skeleton>` placeholder rather than nothing or a generic spinner.

```tsx
import { Skeleton } from '@/components/ui/skeleton'

if (isLoading) return (
  <div className="space-y-2 p-3">
    <Skeleton className="h-7 w-full" />
    <Skeleton className="h-7 w-full" />
    <Skeleton className="h-7 w-3/4" />
  </div>
)
```

- [ ] **Step 2: Find empty states**

```bash
grep -rn "length === 0\|length == 0" frontend/src/components | grep -v "components/ui/"
```

For each, render a centered muted message:
```tsx
<div className="flex h-full flex-col items-center justify-center gap-2 p-8 text-center">
  <p className="text-sm font-medium">No {thing} yet</p>
  <p className="text-xs text-muted-foreground">{guidance}</p>
</div>
```

- [ ] **Step 3: Type-check + smoke-test**

`npx tsc --noEmit`. Then run dev with a fresh database (or empty filters) to see each empty state.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/
git commit -m "feat(frontend): add skeletons and empty states across pages"
```

---

### Task 4.7: Accessibility pass

**Files:** all interactive components.

- [ ] **Step 1: Verify icon-only buttons have `aria-label`**

```bash
grep -rn "<Button variant=\"icon\"\|<Button size=\"icon\"" frontend/src/components | head -40
```

For each, confirm there's an `aria-label` attribute. If not, add one matching the icon's purpose (e.g., `aria-label="Open menu"`).

- [ ] **Step 2: Verify icon rail `NavLink` items have accessible names**

In `IconRail.tsx`, ensure `<NavLink>` items either have `aria-label` matching the section label, or the existing `<Tooltip>` content satisfies AT. Add `aria-label={label}` on each `NavLink` to be safe.

- [ ] **Step 3: Verify focus rings render**

In dev, tab through the app — every interactive element should show an indigo focus ring (`ring` token).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/
git commit -m "feat(frontend): a11y pass — aria labels and focus rings"
```

---

### Task 4.8: Phase 4 verification

- [ ] **Step 1: Type-check + build**

`npx tsc --noEmit && npm run build`. Clean.

- [ ] **Step 2: End-to-end smoke-test**

Run dev. Manually verify:
- Auth flow
- ⌘K opens palette, selecting an item navigates correctly
- ⌘B collapses/expands secondary sidebar
- ⌘J collapses/expands chat panel
- ? opens help overlay with all shortcuts listed
- All previous flows still work (wiki, files, ingest, chat SSE, automations, browser-chat)
- No console errors

- [ ] **Step 3: Tag**

```bash
git tag phase-4-complete
```

---

## Self-Review

**Spec coverage:**
- Foundation tokens, fonts, spacing → Phase 0 ✓
- Shell (icon rail / secondary sidebar / context bar / main / chat) → Phase 1 ✓
- Command palette, help overlay, shortcuts → Phase 4 ✓
- Component migration map (modals → Dialog, drawers → Sheet, tables, etc.) → Phases 2-3 ✓
- Removed deps (`github-markdown-css`, inline styles) → Phase 3 Task 3.1 + Phase 0 Task 0.3 ✓
- Risk safeguards (per-phase smoke-test, type-check gates, atomic PRs) → embedded in every verification task ✓

**Placeholder scan:** No `TBD`, no "implement later", every code-changing step has code shown. Placeholders in `WikiTree`/`FilesTree`/etc. are explicitly flagged with "REPLACE with real data" comments and the engineer is told to read the matching source file to find the actual hook.

**Type consistency:** `Shortcut`, `Command`, `Crumb`, `Node`, `ShellContext` types are defined where used, signatures are stable across tasks.

**Gaps fixed inline:** Added a path-alias smoke-test (Task 0.2 Step 5), added `ShellContext` for cross-tree state in Task 4.4, called out that primitive `select` may need a separate `npx shadcn add` in Task 2.6.

---

**Plan complete and saved to `.agents/superpowers/plans/2026-05-20-ui-redesign.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
