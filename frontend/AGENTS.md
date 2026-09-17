# AGENTS.md

## Project Context

React frontend for MSL Downloader. It is the UI for a local, single user
desktop style web app: the real work (catalog search, downloads, Catalog
Manager jobs) is done by the FastAPI backend in `../webapi/`, not in the
browser. Treat it as user owned application code, keep changes focused on
the user's request, and preserve existing project conventions.

Start with `README.md` for local setup and run instructions (the backend
must be running too).

## Key Files

- `src/App.jsx`: routes — `/` Landing, `/download` Home (the downloader),
  `/catalog-manager` CatalogManager, plus NotFound.
- `src/pages/Home.jsx`: the MSL Downloader page (search, download, results,
  metadata).
- `src/pages/CatalogManager.jsx`: the Catalog Manager page (tabs under
  `components/catalog/tabs/`: Overview, Updates, Personalize, Composition,
  Verify).
- `src/components/layout/`: shared shell (`AppHeader.jsx`, `AppSidebar.jsx`,
  `AppSwitch.jsx`, `PageIntro.jsx`).
- `src/components/ui/panel.jsx`: the shared card (header/body/footer/empty
  state) every surface is built from.
- `src/components/ui/modal.jsx`: `Modal` and `Sheet` overlays, portalled,
  Escape dismissable, scroll locking.
- `src/lib/mslApi.js`: the real backend client for catalog search, download
  jobs, files and metadata (`webapi/main.py`).
- `src/lib/catalogManagerApi.js`: backend client for Catalog Manager jobs
  (`webapi/catalog_manager_routes.py`).
- `src/lib/sessionApi.js` and `src/lib/AuthContext.jsx`: session/auth against
  `webapi/session_routes.py`.
- `src/lib/AppSettingsContext.jsx`: language, palette, font and default
  download folder, persisted to localStorage (UI preferences only, not app
  data).
- `src/lib/localDb.js`: small localStorage backed store for UI only saved
  records; not the source of truth for catalogs or downloads.
- `vite.config.js`: Vite config (React plugin + `@` → `src` alias).

Two files are left over from the project's very first, backend less mockup
and are no longer part of the live data flow: `src/lib/nasaApi.js` and
`src/lib/catalogData.js`. Worth a follow up cleanup pass to remove them.

## Conventions

- Only `src/components/ui/` holds shadcn style primitives; add new ones
  there and keep the file name matching the primitive. `toggle-chip.jsx` is a
  project specific control, deliberately not named `toggle` so it can't
  collide with the shadcn naming scheme.
- Panels compose `Panel`/`PanelHeader`/`PanelTitle`/`PanelBody`/`PanelFooter`
  rather than re declaring the card markup, and accept a `className` so the
  page owns their grid placement.
- Every user visible string goes through `t()` and must be added to all five
  languages in `src/lib/translations.js`.
- The sidebar is a drawer below `lg` and a docked sticky column at `lg` and
  up; overlay behaviour (Escape, scroll lock) comes from
  `src/hooks/use-dismissable.js`.

## Working Notes

- Backend and frontend must both be running:
  `uvicorn webapi.main:app --port 8000` and `npm run dev` (or use
  `../launchers/Avvia_MSL_App.bat` / `.sh`).
- Catalog search, downloads, job status/logs and Catalog Manager operations
  are all served by the backend; nothing about them lives only in the
  browser.
- `AppSettingsContext` (language, theme, font, default folder) and
  `localDb.js` (small saved record convenience store) are the only things
  kept client side.
- Run the relevant checks from `package.json` (`npm run lint`,
  `npm run typecheck`) before finishing code changes.
