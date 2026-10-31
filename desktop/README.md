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

## Build installers

```bash
cd desktop
npm install
npm run dist        # AppImage (Linux), dmg (macOS), or nsis (Windows)
```

`electron-builder` bundles the `reverseai/` Python sources into the app as
resources. The user still needs a Python 3.11+ runtime available; packaging a
full Python runtime is a later step (PyInstaller sidecar).

## How it works

- `main.js` finds a free port, spawns `python -m reverseai serve` there, waits
  until it answers, then opens the window on that URL. On quit it stops the
  backend. External links open in the real browser; a single instance is
  enforced.
- `preload.js` exposes only `window.reverseaiDesktop` (a desktop flag + backend
  info) with context isolation on.

## Not yet (honest scope)

System tray + background daemon, a global quick-launch hotkey, and a bundled
Python runtime are planned but not built here. This shell is the foundation they
hang off.
