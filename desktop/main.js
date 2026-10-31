// ReverseAI desktop shell.
//
// A thin, honest native wrapper: it launches the real ReverseAI server
// (`python -m reverseai serve`) as a child process on a free local port, waits
// until it answers, then loads the existing web UI in a native window. No
// re-implementation of the product - the desktop app IS the product, framed.
"use strict";

const { app, BrowserWindow, Menu, shell, dialog, ipcMain } = require("electron");
const { spawn } = require("child_process");
const http = require("http");
const net = require("net");
const path = require("path");
const fs = require("fs");

const HOST = "127.0.0.1";
let serverProc = null;
let serverPort = 0;
let mainWindow = null;
let serverLog = [];

// In a packaged build the Python sources are shipped under resources/app-python;
// in development they live one level up from this folder.
function projectRoot() {
  const packaged = path.join(process.resourcesPath || "", "app-python");
  if (fs.existsSync(path.join(packaged, "reverseai"))) return packaged;
  return path.join(__dirname, "..");
}

function pythonCandidates() {
  const fromEnv = process.env.REVERSEAI_PYTHON;
  const list = fromEnv ? [fromEnv] : [];
  return list.concat(process.platform === "win32"
    ? ["python", "python3", "py"]
    : ["python3", "python"]);
}

function freePort() {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.unref();
    srv.on("error", reject);
    srv.listen(0, HOST, () => {
      const port = srv.address().port;
      srv.close(() => resolve(port));
    });
  });
}

function waitForServer(port, timeoutMs = 40000) {
  const deadline = Date.now() + timeoutMs;
  return new Promise((resolve, reject) => {
    const tick = () => {
      const req = http.get({ host: HOST, port, path: "/", timeout: 1500 }, (res) => {
        res.resume();
        resolve();
      });
      req.on("error", () => {
        if (Date.now() > deadline) return reject(new Error("server did not start in time"));
        setTimeout(tick, 400);
      });
      req.on("timeout", () => { req.destroy(); });
    };
    tick();
  });
}

function startServer() {
  return new Promise(async (resolve, reject) => {
    let port;
    try {
      port = await freePort();
    } catch (e) {
      return reject(e);
    }
    serverPort = port;
    const root = projectRoot();
    const store = path.join(app.getPath("userData"), "jobs");
    try { fs.mkdirSync(store, { recursive: true }); } catch (_) {}

    const args = ["-m", "reverseai", "serve", "--host", HOST,
                  "--port", String(port), "--store", store];
    const env = Object.assign({}, process.env, {
      PYTHONUNBUFFERED: "1",
      REVERSEAI_STORE: process.env.REVERSEAI_STORE || store,
    });

    let lastErr = null;
    for (const exe of pythonCandidates()) {
      try {
        const proc = spawn(exe, args, { cwd: root, env });
        let spawnFailed = false;
        proc.on("error", (err) => { spawnFailed = true; lastErr = err; });
        proc.stdout.on("data", (d) => pushLog(d));
        proc.stderr.on("data", (d) => pushLog(d));
        // Give the spawn a moment to fail on a bad interpreter.
        await new Promise((r) => setTimeout(r, 250));
        if (spawnFailed) continue;
        serverProc = proc;
        proc.on("exit", (code, sig) => {
          serverProc = null;
          if (!app.isQuitting && mainWindow) {
            dialog.showErrorBox("ReverseAI server stopped",
              `The backend exited (code ${code}, signal ${sig}).\n\n` +
              tailLog());
          }
        });
        try {
          await waitForServer(port);
          return resolve(port);
        } catch (e) {
          lastErr = e;
          try { proc.kill("SIGTERM"); } catch (_) {}
          serverProc = null;
          continue;
        }
      } catch (e) {
        lastErr = e;
      }
    }
    reject(lastErr || new Error("could not launch the Python backend"));
  });
}

function pushLog(buf) {
  const s = buf.toString();
  serverLog.push(s);
  if (serverLog.length > 400) serverLog = serverLog.slice(-400);
}

function tailLog() {
  return serverLog.join("").split("\n").slice(-25).join("\n");
}

function stopServer() {
  if (!serverProc) return;
  const proc = serverProc;
  serverProc = null;
  try {
    if (process.platform === "win32") {
      spawn("taskkill", ["/pid", String(proc.pid), "/f", "/t"]);
    } else {
      proc.kill("SIGTERM");
      setTimeout(() => { try { proc.kill("SIGKILL"); } catch (_) {} }, 2500);
    }
  } catch (_) {}
}

function buildMenu() {
  const isMac = process.platform === "darwin";
  const template = [
    ...(isMac ? [{ role: "appMenu" }] : []),
    {
      label: "File",
      submenu: [
        {
          label: "Open job store folder",
          click: () => shell.openPath(path.join(app.getPath("userData"), "jobs")),
        },
        { type: "separator" },
        isMac ? { role: "close" } : { role: "quit" },
      ],
    },
    { label: "Edit", role: "editMenu" },
    {
      label: "View",
      submenu: [
        { label: "Reload", accelerator: "CmdOrCtrl+R",
          click: () => mainWindow && mainWindow.reload() },
        { role: "toggleDevTools" },
        { type: "separator" },
        { role: "resetZoom" }, { role: "zoomIn" }, { role: "zoomOut" },
        { type: "separator" }, { role: "togglefullscreen" },
      ],
    },
    {
      label: "Help",
      submenu: [
        {
          label: "About ReverseAI",
          click: () => dialog.showMessageBox(mainWindow, {
            type: "info", title: "ReverseAI",
            message: "ReverseAI", detail:
              "Understand. Modify. Rebuild.\n\nDesktop shell v" + app.getVersion() +
              "\nBackend: " + (serverPort ? "http://" + HOST + ":" + serverPort : "not running"),
          }),
        },
      ],
    },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

function createWindow(port) {
  mainWindow = new BrowserWindow({
    width: 1280, height: 860, minWidth: 720, minHeight: 540,
    backgroundColor: "#0e1526", show: false, autoHideMenuBar: true,
    title: "ReverseAI",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      spellcheck: true,
    },
  });
  mainWindow.once("ready-to-show", () => mainWindow.show());
  mainWindow.loadURL(`http://${HOST}:${port}/`);

  // Open external links (anything off the local backend) in the real browser.
  const isLocal = (u) => { try { return new URL(u).host === `${HOST}:${port}`; } catch (_) { return false; } };
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (!isLocal(url)) { shell.openExternal(url); return { action: "deny" }; }
    return { action: "allow" };
  });
  mainWindow.webContents.on("will-navigate", (e, url) => {
    if (!isLocal(url)) { e.preventDefault(); shell.openExternal(url); }
  });
  mainWindow.on("closed", () => { mainWindow = null; });
}

async function boot() {
  const splash = new BrowserWindow({
    width: 420, height: 300, frame: false, resizable: false,
    backgroundColor: "#0e1526", show: true, center: true,
  });
  splash.loadFile(path.join(__dirname, "loading.html"));
  try {
    const port = await startServer();
    createWindow(port);
    if (mainWindow) mainWindow.once("ready-to-show", () => { try { splash.close(); } catch (_) {} });
  } catch (e) {
    try { splash.close(); } catch (_) {}
    dialog.showErrorBox("ReverseAI could not start",
      "The Python backend failed to launch.\n\n" +
      "Make sure Python 3.11+ is installed and the 'reverseai' package is " +
      "importable (run from the project, or set REVERSEAI_PYTHON).\n\n" +
      String(e && e.message || e) + "\n\n" + tailLog());
    app.quit();
  }
}

// One running instance; focus the existing window on a second launch.
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (mainWindow) { if (mainWindow.isMinimized()) mainWindow.restore(); mainWindow.focus(); }
  });
  ipcMain.handle("reverseai:info", () => ({ port: serverPort, version: app.getVersion() }));
  app.whenReady().then(() => { buildMenu(); boot(); });
  app.on("activate", () => { if (!mainWindow && serverPort) createWindow(serverPort); });
}

app.on("before-quit", () => { app.isQuitting = true; });
app.on("will-quit", stopServer);
app.on("window-all-closed", () => { if (process.platform !== "darwin") app.quit(); });
process.on("exit", stopServer);
