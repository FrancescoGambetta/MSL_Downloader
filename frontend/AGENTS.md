# AGENTS.md

## Project Context

This is a standalone, fully local frontend application (no backend server).
Treat it as user-owned application code, keep changes focused on the user's
request, and preserve existing project conventions.

Start with `README.md` for local setup and build instructions.

## Key Files

- `src/pages/Home.jsx`: the whole app shell and layout — header, sidebar, and the two content grids.
- `src/components/ui/panel.jsx`: the shared card (header / body / footer / empty state) every surface is built from.
- `src/components/ui/modal.jsx`: `Modal` and `Sheet` overlays — portalled, Escape-dismissable, scroll-locking.
- `src/lib/useDownloader.js`: search + download state machine driving the log, progress and gallery.
- `src/lib/localAuth.js`: local, single-user "auth" stand-in (no server, no real security).
- `src/lib/localDb.js`: localStorage-backed entity storage used in place of a remote database.
- `src/lib/nasaApi.js`: direct client for the public NASA Mars Photos API.
- `src/lib/AppSettingsContext.jsx`: language, palette, font, output folder and API key, persisted to localStorage.
- `vite.config.js`: Vite config (React plugin + `@` → `src` alias).

## Conventions

- Only `src/components/ui/` holds shadcn-style primitives; add new ones there and keep
  the file name matching the primitive. `toggle-chip.jsx` is a project-specific control,
  deliberately not named `toggle` so it can't collide with the shadcn naming scheme.
- Panels compose `Panel`/`PanelHeader`/`PanelTitle`/`PanelBody`/`PanelFooter` rather than
  re-declaring the card markup, and accept a `className` so the page owns their grid placement.
- Every user-visible string goes through `t()` and must be added to all five languages in
  `src/lib/translations.js`.
- The sidebar is a drawer below `lg` and a docked sticky column at `lg` and up; overlay
  behaviour (Escape, scroll lock) comes from `src/hooks/use-dismissable.js`.

## Working Notes

- `npm run dev` starts the frontend dev server — that's the only thing needed to run the app locally.
- There is no backend, no auth server, and no remote database. Anything the app "saves" lives in the browser's localStorage.
- Run the relevant checks from `package.json` (`npm run lint`, `npm run typecheck`) before finishing code changes.
