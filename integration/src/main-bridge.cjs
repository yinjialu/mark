"use strict";
const path = require("node:path");
const {pathToFileURL} = require("node:url");
const {spawn} = require("node:child_process");
const CHANNEL = "local.codex-marks:save-selection:v1";

function trustedSender(event, appPath) {
  if (!event.senderFrame || event.senderFrame !== event.sender.mainFrame) return false;
  try {
    const url = new URL(event.senderFrame.url);
    if (url.username || url.password || url.port) return false;
    if (url.protocol === "app:" && url.hostname === "-") return true;
    url.hash = ""; url.search = "";
    return url.href === pathToFileURL(path.join(appPath, "webview/index.html")).href;
  } catch (_) { return false; }
}

function validPayload(payload) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)
    || Object.keys(payload).some(key => !["quote", "source"].includes(key))
    || typeof payload.quote !== "string" || !payload.quote.trim() || payload.quote.length > 100000) return false;
  if (!("source" in payload)) return true;
  const s = payload.source;
  return !!s && typeof s === "object" && !Array.isArray(s) && Object.keys(s).length === 5
    && Object.keys(s).every(key => ["thread_id", "message_id", "text", "start_utf16", "end_utf16"].includes(key))
    && typeof s.thread_id === "string" && /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(s.thread_id)
    && typeof s.message_id === "string" && s.message_id.length > 0 && s.message_id.length <= 200
    && typeof s.text === "string" && s.text.length <= 1000000
    && Number.isSafeInteger(s.start_utf16) && Number.isSafeInteger(s.end_utf16)
    && s.start_utf16 >= 0 && s.end_utf16 > s.start_utf16 && s.end_utf16 <= s.text.length
    && s.text.slice(s.start_utf16, s.end_utf16) === payload.quote;
}

function validUnderlineRequest(payload) {
  return !!payload && typeof payload === "object" && !Array.isArray(payload)
    && Object.keys(payload).length === 1 && Array.isArray(payload.messages)
    && payload.messages.length > 0 && payload.messages.length <= 100
    && payload.messages.every(item => item && typeof item === "object" && !Array.isArray(item)
      && Object.keys(item).length === 2 && typeof item.thread_id === "string"
      && /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(item.thread_id)
      && typeof item.message_id === "string" && item.message_id.length > 0 && item.message_id.length <= 200);
}

function validBlockSource(s) {
  return !!s && typeof s === 'object' && !Array.isArray(s) && Object.keys(s).length === 7
    && ['image', 'mermaid', 'table'].includes(s.kind)
    && validUnderlineRequest({messages: [{thread_id: s.thread_id, message_id: s.message_id}]})
    && Number.isSafeInteger(s.block_index) && s.block_index >= 0 && s.block_index <= 10000
    && typeof s.source_hash === 'string' && /^[0-9a-f]{64}$/.test(s.source_hash)
    && typeof s.source_text === 'string' && s.source_text.length <= 100000
    && typeof s.caption === 'string' && s.caption.length <= 200;
}

function runBackend(payload, resourcesPath, run, listing, block = false) {
  return new Promise(resolve => {
    let done = false, stdout = "", bytes = 0;
    const child = run("/usr/bin/python3", ["-B", path.join(resourcesPath, listing ? "codex-marks/list-underlines.py" : block ? "codex-marks/capture-block.py" : "codex-marks/capture.py")],
      {stdio: ["pipe", "pipe", "pipe"], shell: false, windowsHide: true});
    const finish = value => { if (!done) { done = true; clearTimeout(timer); resolve(value); } };
    const timer = setTimeout(() => { child.kill(); finish({ok: false, error: "保存超时，请重试"}); }, 30000);
    child.on("error", () => finish({ok: false, error: "无法启动本地收藏存储"}));
    child.stdin.on("error", () => finish({ok: false, error: "无法写入选区"}));
    child.stdout.on("data", chunk => {
      bytes += chunk.length;
      if (bytes > (listing ? 524288 : 16384)) { child.kill(); finish({ok: false, error: "存储响应过长"}); }
      else stdout += chunk.toString("utf8");
    });
    child.stderr.resume(); // Never log selected text or Python diagnostics into Codex telemetry.
    child.on("close", code => {
      if (code !== 0) return finish({ok: false, error: "保存失败，请重试"});
      try {
        const result = JSON.parse(stdout);
        if (listing) {
          const requested = new Set(payload.messages.map(item => JSON.stringify([item.thread_id, item.message_id])));
          if (result.ok !== true || !Array.isArray(result.marks) || result.marks.length > 1000) throw new Error();
          const marks = result.marks.map(mark => {
            if (requested.has(JSON.stringify([mark.thread_id, mark.message_id])) && typeof mark.mark_id === 'string'
                && mark.mark_id.length <= 100 && ['image', 'mermaid', 'table'].includes(mark.block_kind)
                && Number.isSafeInteger(mark.block_index) && mark.block_index >= 0 && mark.block_index <= 10000
                && typeof mark.block_source_hash === 'string' && /^[0-9a-f]{64}$/.test(mark.block_source_hash)) {
              return {mark_id: mark.mark_id, thread_id: mark.thread_id, message_id: mark.message_id,
                block_kind: mark.block_kind, block_index: mark.block_index, block_source_hash: mark.block_source_hash};
            }
            if (!requested.has(JSON.stringify([mark.thread_id, mark.message_id]))
              || typeof mark.mark_id !== "string" || mark.mark_id.length > 100
              || typeof mark.text_sha256 !== "string" || !/^[0-9a-f]{64}$/.test(mark.text_sha256)
              || !Number.isSafeInteger(mark.start_utf16) || !Number.isSafeInteger(mark.end_utf16)
              || mark.start_utf16 < 0 || mark.end_utf16 <= mark.start_utf16 || mark.end_utf16 > 1000000) throw new Error();
            return {mark_id: mark.mark_id, thread_id: mark.thread_id, message_id: mark.message_id,
              text_sha256: mark.text_sha256, start_utf16: mark.start_utf16, end_utf16: mark.end_utf16};
          });
          return finish({ok: true, marks});
        }
        if (result.ok !== true || typeof result.mark_id !== "string") throw new Error();
        finish({ok: true, created: result.created === true, mark_id: result.mark_id});
      } catch (_) { finish({ok: false, error: "存储响应无效"}); }
    });
    child.stdin.end(JSON.stringify(payload));
  });
}

function capture(payload, resourcesPath, run = spawn) { return runBackend(payload, resourcesPath, run, false); }
function listUnderlines(payload, resourcesPath, run = spawn) { return runBackend(payload, resourcesPath, run, true); }
function captureBlock(payload, resourcesPath, run = spawn) { return runBackend(payload, resourcesPath, run, false, true); }

function register() {
  const {app, ipcMain, nativeImage} = require("electron");
  require('./codex-marks-library.cjs').registerLibrary({app, ipcMain}, trustedSender);
  const {randomUUID} = require('node:crypto');
  const tickets = new Map();
  const pending = new Set();
  const reading = new Set();
  ipcMain.handle('local.codex-marks:begin-block:v1', (event, source) => {
    if (!trustedSender(event, app.getAppPath()) || !validBlockSource(source)) return {ok: false};
    for (const [token, item] of tickets) if (item.expires < Date.now() || item.sender === event.sender.id) tickets.delete(token);
    if (tickets.size >= 64) return {ok: false};
    const token = randomUUID();
    tickets.set(token, {sender: event.sender.id, source, expires: Date.now() + 120000});
    return {ok: true, token};
  });
  ipcMain.handle('local.codex-marks:save-block:v1', async (event, payload) => {
    if (!trustedSender(event, app.getAppPath()) || !payload || typeof payload.token !== 'string') return {ok: false};
    const ticket = tickets.get(payload.token);
    if (!ticket || ticket.sender !== event.sender.id || ticket.expires < Date.now()) return {ok: false, error: '请重新点击 mark'};
    tickets.delete(payload.token);
    if (Object.keys(payload).length !== 2 || typeof payload.content !== 'string' || payload.content.length > 34000000) return {ok: false};
    if (pending.has(event.sender.id)) return {ok: false, error: '正在保存，请稍候'};
    pending.add(event.sender.id);
    try {
      if (ticket.source.kind === 'image') {
        if (!payload.content.startsWith('data:image/png;base64,')) throw new Error();
        const decoded = nativeImage.createFromDataURL(payload.content), size = decoded.getSize();
        if (decoded.isEmpty() || size.width * size.height > 40000000) throw new Error();
      }
      return await captureBlock({source: ticket.source, content: payload.content}, process.resourcesPath);
    } catch (_) { return {ok: false, error: '无法保存这份内容，请重试'}; }
    finally { pending.delete(event.sender.id); }
  });
  ipcMain.handle("local.codex-marks:list-underlines:v1", async (event, payload) => {
    if (!trustedSender(event, app.getAppPath()) || !validUnderlineRequest(payload)) return {ok: false, error: "不允许的位置请求"};
    if (reading.has(event.sender.id)) return {ok: false, error: "正在读取标记位置"};
    reading.add(event.sender.id);
    try { return await listUnderlines(payload, process.resourcesPath); }
    catch (_) { return {ok: false, error: "无法读取标记位置"}; }
    finally { reading.delete(event.sender.id); }
  });
  ipcMain.handle(CHANNEL, async (event, payload) => {
    if (!trustedSender(event, app.getAppPath()) || !validPayload(payload)) {
      return {ok: false, error: "不允许的收藏请求"};
    }
    if (pending.has(event.sender.id)) return {ok: false, error: "正在保存，请稍候"};
    pending.add(event.sender.id);
    try { return await capture(payload, process.resourcesPath); }
    catch (_) { return {ok: false, error: "保存失败，请重试"}; }
    finally { pending.delete(event.sender.id); }
  });
}
module.exports = {register, trustedSender, validPayload, validUnderlineRequest, validBlockSource, capture, listUnderlines, captureBlock};
