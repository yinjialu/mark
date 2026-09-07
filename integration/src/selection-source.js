// Capture only the selected response, while its DOM Range is still available.
function __codexMarksSelectionSource(target, range, selectedText, annotation) {
  try {
    const root = target.closest('[data-response-annotation-conversation][data-response-annotation-target]');
    if (!root || !range || !root.contains(range.startContainer) || !root.contains(range.endContainer)) return null;
    const candidate = root.querySelector('[data-selected-text-overlay-target]');
    const body = candidate && candidate.contains(range.startContainer) && candidate.contains(range.endContainer) ? candidate : root;
    const whole = body.ownerDocument.createRange(); whole.selectNodeContents(body);
    const text = whole.toString();
    if (!text || text.length > 1000000) return null;
    const prefix = whole.cloneRange(); prefix.setEnd(range.startContainer, range.startOffset);
    const through = whole.cloneRange(); through.setEnd(range.endContainer, range.endOffset);
    let start = prefix.toString().length, end = through.toString().length;
    const exact = text.slice(start, end);
    // The host may trim the browser selection before displaying its toolbar.
    if (exact !== selectedText && exact.trim() === selectedText) {
      start += exact.length - exact.trimStart().length;
      end -= exact.length - exact.trimEnd().length;
    }
    if (text.slice(start, end) !== selectedText || end <= start) return null;
    const threadId = root.getAttribute('data-response-annotation-conversation') || '';
    const messageId = annotation?.source?.messageId || annotation?.anchor?.messageId || root.getAttribute('data-response-annotation-target');
    if (!messageId) return null;
    return {thread_id: threadId, message_id: messageId, text, start_utf16: start, end_utf16: end};
  } catch (_) { return null; }
}
