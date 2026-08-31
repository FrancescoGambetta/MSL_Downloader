# MSL Image Downloader

A local web app to catalog, search and download NASA Mars Science Laboratory
(Curiosity rover) imagery. It talks directly to the public NASA Mars Photos
API from the browser — there is no backend server, and everything you save
is stored locally in your browser.

## Prerequisites

- Node.js 18+ and npm

## Run Locally

```bash
npm install
npm run dev
```

Open the local URL printed by Vite (usually `http://localhost:5173`).

## Build

```bash
npm run build
```

The production build is written to `./dist` and can be served with any
static file host:

```bash
npm run preview
```

## Checks

```bash
npm run lint
npm run typecheck
```

## Configuration

Open **Settings** in the app (top right) to set your own NASA API key (get one
free at https://api.nasa.gov), your preferred output folder label, the
interface language, colour palette and font. Without a personal key the app
uses NASA's shared `DEMO_KEY`, which has a very low rate limit — a handful of
searches per hour, after which the log reports "rate limit reached".

Every preference, along with the image archive itself, is stored in this
browser's localStorage.
