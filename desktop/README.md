# ReverseAI Desktop

The native desktop app. It is a thin Electron shell that launches the real
ReverseAI backend (`python -m reverseai serve`) on a private local port and
loads the existing UI in a native window - so the desktop app *is* the product,
not a re-implementation of it.

## Prerequisites

- **Python 3.11+** with the `reverseai` package importable (i.e. this repo), and
  your `.env` configured (e.g. `DEEPSEEK_API_KEY`). The same thing you run with
  `python3 -m reverseai serve`.
- **Node.js 18+** and npm (only to run or build the shell).

## Run it

```bash
cd desktop
npm install        # first time only: fetches Electron
npm start
```

The window shows a splash while the engine starts, then loads ReverseAI. Jobs
are stored under the OS app-data folder (File -> Open job store folder).

If your Python is not `python3` on the PATH, point the shell at it:

```bash
REVERSEAI_PYTHON=/path/to/python npm start
```

## Build installers (bundled Python - users need nothing pre-installed)

The backend is frozen into a standalone executable with PyInstaller, then
packaged into the app, so the installed app runs with **no separate Python**.

Build locally (produces an installer for the OS you run it on):

```bash
cd desktop
pip install pyinstaller        # build-time only
npm install
npm run build:backend          # freeze reverseai -> backend/dist/reverseai-server
npm run dist                   # AppImage+deb (Linux), dmg+zip (macOS), nsis (Windows)
```

### All three platforms at once (recommended)

Installers for macOS, Windows, and Linux are built in CI: the
**Build desktop installers** GitHub Actions workflow freezes the backend and
runs electron-builder on each OS and uploads the installers. PyInstaller can't
cross-compile, so each OS is built on its own runner - CI is how you ship to all
devices.

The workflow is staged at `docs/github-workflows/desktop-release.yml` (the repo
convention, since pushing to `.github/workflows/` needs a token with the
`workflow` scope). Copy it to `.github/workflows/` to activate it, then trigger
it from the Actions tab or by pushing a `v*` tag.

If the bundled backend is missing (a dev checkout without `npm run build:backend`),
the app falls back to a system `python3` running the source.

## How it works

- `main.js` finds a free port, spawns `python -m reverseai serve` there, waits
  until it answers, then opens the window on that URL. On quit it stops the
  backend. External links open in the real browser; a single instance is
  enforced.
- `preload.js` exposes only `window.reverseaiDesktop` (a desktop flag + backend
  info) with context isolation on.

## Not yet (honest scope)

System tray + background daemon, a global quick-launch hotkey, and code-signed/
notarized builds (CI currently produces unsigned installers) are planned but not
built here.
