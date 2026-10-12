"use strict";
/**
 * Electron shell for Local ERP.
 *  - starts the local FastAPI server (packaged erp-server, or `python -m uvicorn` in development)
 *  - keeps user data in the per-user app-data folder (never in the install directory, so upgrades/uninstall don't touch it)
 *  - hardened per Electron's security checklist: contextIsolation, sandbox, no nodeIntegration, CSP, blocked navigation
 */
const { app, BrowserWindow, dialog, shell, session } = require("electron");
const { spawn } = require("child_process");
const path = require("path");
const http = require("http");
const fs = require("fs");

const PORT = process.env.ERP_PORT || "8765"; // not 8000, to avoid clashing with a dev server
const URL = `http://127.0.0.1:${PORT}`;
let server = null;
let win = null;

function serverCommand() {
  const env = { ...process.env, ERP_PORT: PORT, ERP_HOST: "127.0.0.1", ERP_DATA_DIR: path.join(app.getPath("userData"), "data") };
  if (app.isPackaged) {
    const exe = path.join(process.resourcesPath, "server", process.platform === "win32" ? "erp-server.exe" : "erp-server");
    return { cmd: exe, args: [], opts: { env, cwd: path.dirname(exe), windowsHide: true } };
  }
  const root = path.join(__dirname, "..");
  const py = process.env.PYTHON || (process.platform === "win32" ? "python" : path.join(root, ".venv", "bin", "python"));
  return { cmd: fs.existsSync(py) ? py : "python3", args: ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", PORT],
           opts: { env, cwd: path.join(root, "backend"), windowsHide: true } };
}

function startServer() {
  const { cmd, args, opts } = serverCommand();
  fs.mkdirSync(opts.env.ERP_DATA_DIR, { recursive: true });
  const log = fs.createWriteStream(path.join(opts.env.ERP_DATA_DIR, "server.log"), { flags: "a" });
  server = spawn(cmd, args, opts);
  server.stdout.pipe(log);
  server.stderr.pipe(log);
  server.on("exit", (code) => { if (!app.isQuitting) dialog.showErrorBox("Local ERP", `The ERP service stopped unexpectedly (code ${code}). See server.log in ${opts.env.ERP_DATA_DIR}.`); });
}

function waitForServer(timeoutMs = 60000) {
  const t0 = Date.now();
  return new Promise((resolve, reject) => {
    const tick = () => {
      http.get(`${URL}/api/health`, (res) => { res.resume(); res.statusCode === 200 ? resolve() : retry(); }).on("error", retry);
    };
    const retry = () => (Date.now() - t0 > timeoutMs ? reject(new Error("Server did not start in time")) : setTimeout(tick, 400));
    tick();
  });
}

function createWindow() {
  win = new BrowserWindow({
    width: 1366, height: 820, minWidth: 1024, minHeight: 640, title: "Local ERP", show: false,
    webPreferences: { preload: path.join(__dirname, "preload.js"), contextIsolation: true, sandbox: true, nodeIntegration: false, webSecurity: true },
  });
  win.setMenuBarVisibility(false);
  win.once("ready-to-show", () => win.show());
  // only our own origin may be shown in the window; everything else opens in the system browser (or is refused)
  win.webContents.on("will-navigate", (e, url) => { if (!url.startsWith(URL)) { e.preventDefault(); } });
  win.webContents.setWindowOpenHandler(({ url }) => { if (/^https:\/\//.test(url)) shell.openExternal(url); return { action: "deny" }; });
  win.loadURL(URL);
}

app.whenReady().then(async () => {
  session.defaultSession.webRequest.onHeadersReceived((details, cb) => {
    cb({ responseHeaders: { ...details.responseHeaders,
      "Content-Security-Policy": ["default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"] } });
  });
  session.defaultSession.setPermissionRequestHandler((_wc, _perm, cb) => cb(false));
  if (!app.requestSingleInstanceLock()) return app.quit();
  startServer();
  try { await waitForServer(); } catch (e) { dialog.showErrorBox("Local ERP", e.message); return app.quit(); }
  createWindow();
});
app.on("second-instance", () => { if (win) { if (win.isMinimized()) win.restore(); win.focus(); } });
app.on("before-quit", () => { app.isQuitting = true; if (server) server.kill(); });
app.on("window-all-closed", () => app.quit());
