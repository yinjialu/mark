// Paint saved ranges without wrapping or changing React-owned text nodes.
function __codexMarksUnderlineController(win, read) {
  const doc = win.document, name = 'codex-marks-saved';
  const selector = '[data-response-annotation-conversation][data-response-annotation-target]';
  const key = item => JSON.stringify([item.thread_id, item.message_id]);
  const sheet = new win.CSSStyleSheet();
  sheet.replaceSync(`::highlight(${name}) { text-decoration-line: underline; text-decoration-style: solid; text-decoration-color: #d39620; text-decoration-thickness: 2px; text-underline-position: under; text-underline-offset: 3px; }`);
  doc.adoptedStyleSheets = [...doc.adoptedStyleSheets, sheet];
  let cache = [], scope = '', lastRead = 0, timer, busy = false, dirty = false, forceRead = false, revision = 0, stopped = false;
  const textOf = body => { const range = doc.createRange(); range.selectNodeContents(body); return range.toString(); };
  const hashes = new WeakMap();
  async function hash(body, text) {
    const prior = hashes.get(body);
    if (prior?.text === text) return prior.hash;
    const bytes = await win.crypto.subtle.digest('SHA-256', new win.TextEncoder().encode(text));
    const value = Array.from(new Uint8Array(bytes), byte => byte.toString(16).padStart(2, '0')).join('');
    hashes.set(body, {text, hash: value}); return value;
  }
  function rangeAt(body, start, end) {
    if (!Number.isSafeInteger(start) || !Number.isSafeInteger(end) || start < 0 || end <= start) return null;
    const walker = doc.createTreeWalker(body, win.NodeFilter.SHOW_TEXT), range = doc.createRange();
    let node, offset = 0, began = false;
    while ((node = walker.nextNode())) {
      const next = offset + node.length;
      if (!began && start < next) { range.setStart(node, start - offset); began = true; }
      if (began && end <= next) { range.setEnd(node, end - offset); return range; }
      offset = next;
    }
    return null;
  }
  function roots() {
    return Array.from(doc.querySelectorAll(selector)).map(root => ({root,
      thread_id: root.getAttribute('data-response-annotation-conversation'),
      message_id: root.getAttribute('data-response-annotation-target')})).filter(item =>
      /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(item.thread_id)
      && item.message_id && item.message_id.length <= 200);
  }
  async function update() {
    if (busy || stopped) return;
    busy = true; dirty = false;
    const generation = revision, requested = roots();
    const messages = Array.from(new Map(requested.map(({thread_id, message_id}) =>
      [key({thread_id, message_id}), {thread_id, message_id}])).values()).sort((a, b) => key(a).localeCompare(key(b)));
    const nextScope = JSON.stringify(messages);
    const refresh = forceRead || scope !== nextScope || Date.now() - lastRead >= 10000;
    forceRead = false;
    try {
      if (refresh) {
        const found = [];
        for (let i = 0; i < messages.length; i += 100) {
          const result = await read(messages.slice(i, i + 100));
          if (result?.ok !== true || !Array.isArray(result.marks)) throw new Error('Position read failed');
          found.push(...result.marks);
        }
        if (stopped || generation !== revision) { forceRead = true; return; }
        cache = found; scope = nextScope; lastRead = Date.now();
      }
      const highlight = new win.Highlight();
      for (const item of requested) {
        const marks = cache.filter(mark => !mark.block_kind && key(mark) === key(item));
        if (!marks.length) continue;
        // Capture can use the response body or the root for a selection outside it.
        const candidate = item.root.querySelector('[data-selected-text-overlay-target]');
        for (const body of candidate ? [candidate, item.root] : [item.root]) {
          const text = textOf(body);
          if (!text || text.length > 1000000) continue;
          const digest = await hash(body, text);
          if (stopped || generation !== revision || !body.isConnected || textOf(body) !== text) return;
          for (const mark of marks) {
            if (mark.text_sha256 !== digest || mark.end_utf16 > text.length) continue;
            const range = rangeAt(body, mark.start_utf16, mark.end_utf16);
            if (range) highlight.add(range);
          }
          if (candidate && textOf(item.root) === text) break;
        }
      }
      if (!stopped && generation === revision) win.CSS.highlights.set(name, highlight);
    } catch (_) {
      // Storage/DOM failures cannot affect the host or mark's successful save state.
      // Retry on the next focus, mutation, or bounded periodic refresh.
      lastRead = 0;
    } finally {
      busy = false;
      if (dirty && !stopped) schedule();
    }
  }
  function schedule(force = false) {
    if (stopped) return;
    dirty = true; forceRead ||= force;
    if (timer === undefined) timer = win.setTimeout(() => { timer = undefined; void update(); }, 120);
  }
  const observer = new win.MutationObserver(records => {
    if (!records.some(record => {
      const element = record.target.nodeType === 1 ? record.target : record.target.parentElement;
      return record.type === 'attributes' || element?.closest(selector) || (record.type === 'childList' && [...record.addedNodes, ...record.removedNodes].some(node =>
        node.nodeType === 1 && (node.matches(selector) || node.querySelector(selector))));
    })) return;
    revision++;
    // Live Ranges can shift when React edits a node: remove before recomputing.
    win.CSS.highlights.delete(name); schedule();
  });
  observer.observe(doc.documentElement, {subtree: true, childList: true, characterData: true,
    attributes: true, attributeFilter: ['data-response-annotation-conversation', 'data-response-annotation-target', 'data-selected-text-overlay-target']});
  const refresh = () => { revision++; schedule(true); };
  win.addEventListener('focus', refresh);
  win.addEventListener('codex-marks-changed', refresh);
  doc.addEventListener('visibilitychange', refresh);
  const interval = win.setInterval(() => { if (!doc.hidden && doc.hasFocus()) schedule(true); }, 10000);
  schedule(true);
  return {refresh, stop() {
    stopped = true; observer.disconnect(); win.clearTimeout(timer); win.clearInterval(interval);
    win.removeEventListener('focus', refresh); doc.removeEventListener('visibilitychange', refresh);
    win.removeEventListener('codex-marks-changed', refresh);
    win.CSS.highlights.delete(name); doc.adoptedStyleSheets = doc.adoptedStyleSheets.filter(item => item !== sheet);
  }};
}
var __codexMarksUnderlines;
function __codexMarksStartUnderlines() {
  if (__codexMarksUnderlines || !window.codexMarks?.listUnderlines || !window.CSS?.highlights || !window.Highlight || !window.crypto?.subtle) return;
  try { __codexMarksUnderlines = __codexMarksUnderlineController(window, messages => window.codexMarks.listUnderlines(messages)); } catch (_) {}
}
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', __codexMarksStartUnderlines, {once: true});
else setTimeout(__codexMarksStartUnderlines, 0);
