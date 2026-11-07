const {app, BrowserWindow} = require("electron");
const http = require("node:http");
const fs = require("node:fs");
const path = require("node:path");
const {URL} = require("node:url");

const STATIC_ROOT = path.resolve(__dirname, "..", "dist");
const MIME_TYPES = Object.freeze({
  ".css": "text/css; charset=utf-8",
  ".gz": "application/gzip",
  ".html": "text/html; charset=utf-8",
  ".ico": "image/x-icon",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".map": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
});

let server;

function safeStaticPath(requestUrl) {
  const parsed = new URL(requestUrl, "http://127.0.0.1");
  const relative = decodeURIComponent(parsed.pathname).replace(/^\/+/, "") || "index.html";
  const candidate = path.resolve(STATIC_ROOT, relative);
  const rootWithSeparator = `${STATIC_ROOT}${path.sep}`;
  if (candidate !== STATIC_ROOT && !candidate.startsWith(rootWithSeparator)) return null;
  return candidate;
}

function startStaticServer() {
  server = http.createServer((request, response) => {
    if (request.method !== "GET" && request.method !== "HEAD") {
      response.writeHead(405, {Allow: "GET, HEAD"});
      response.end();
      return;
    }
    let filePath;
    try {
      filePath = safeStaticPath(request.url || "/");
    } catch (_) {
      filePath = null;
    }
    if (!filePath) {
      response.writeHead(403);
      response.end();
      return;
    }
    fs.stat(filePath, (error, stats) => {
      if (error || !stats.isFile()) {
        response.writeHead(404);
        response.end();
        return;
      }
      const contentType = MIME_TYPES[path.extname(filePath).toLocaleLowerCase()];
      if (!contentType) {
        response.writeHead(415);
        response.end();
        return;
      }
      response.writeHead(200, {
        "Cache-Control": "no-store",
        "Content-Length": stats.size,
        "Content-Type": contentType,
        "X-Lexicon-Atlas-Offline": "true",
      });
      if (request.method === "HEAD") {
        response.end();
        return;
      }
      fs.createReadStream(filePath).pipe(response);
    });
  });
  return new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => resolve(server.address().port));
  });
}

async function createWindow() {
  const port = await startStaticServer();
  const window = new BrowserWindow({
    width: 1440,
    height: 960,
    minWidth: 900,
    minHeight: 640,
    backgroundColor: "#07111f",
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      preload: path.join(__dirname, "preload.cjs"),
    },
  });
  await window.loadURL(`http://127.0.0.1:${port}/index.html#word=language&view=sense`);
  window.on("closed", () => {
    if (server) server.close();
    server = null;
  });
}

app.whenReady().then(createWindow).catch((error) => {
  console.error("Lexicon Atlas failed to start:", error);
  app.quit();
});

app.on("window-all-closed", () => app.quit());
