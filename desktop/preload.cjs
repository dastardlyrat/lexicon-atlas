const {contextBridge} = require("electron");

contextBridge.exposeInMainWorld("lexiconAtlasDesktop", Object.freeze({
  offline: true,
  runtime: "electron",
  protocol: "loopback-static",
}));
