// A single purpose bridge; never expose ipcRenderer or filesystem APIs.
(() => {
  // Some desktop runtimes omit Electron's optional process.isMainFrame field.
  // The browser's top-window check still excludes every child frame.
  if (process.isMainFrame === false || window.top !== window) return;
  const {contextBridge, ipcRenderer} = require("electron");
  contextBridge.exposeInMainWorld("codexMarks", Object.freeze({
    updates(request) {
      if (request?.op === "install" && !navigator.userActivation?.isActive) return Promise.reject(new Error("请点击安装并重启"));
      return ipcRenderer.invoke("local.codex-marks:updates:v1", request);
    },
    library(request) {
      if (!['search', 'get'].includes(request?.op) && !navigator.userActivation?.isActive) return Promise.reject(new Error('请点击按钮更新收藏'));
      return ipcRenderer.invoke('local.codex-marks:library:v1', request);
    },
    beginBlockMark(source) {
      if (!navigator.userActivation?.isActive) return Promise.reject(new Error('请点击 mark 保存'));
      return ipcRenderer.invoke('local.codex-marks:begin-block:v1', source);
    },
    saveBlock(token, content) {
      if (typeof token !== 'string' || typeof content !== 'string' || content.length > 34000000) return Promise.reject(new Error('图片或表格过大'));
      return ipcRenderer.invoke('local.codex-marks:save-block:v1', {token, content});
    },
    listUnderlines(messages) {
      return ipcRenderer.invoke("local.codex-marks:list-underlines:v1", {messages});
    },
    saveSelectedText(quote, source) {
      if (!navigator.userActivation?.isActive) return Promise.reject(new Error("请点击 mark 保存"));
      if (typeof quote !== "string" || !quote.trim() || quote.length > 100000) {
        return Promise.reject(new Error("选区无效或过长"));
      }
      return ipcRenderer.invoke("local.codex-marks:save-selection:v1", source === undefined ? {quote} : {quote, source});
    }
  }));
})();
