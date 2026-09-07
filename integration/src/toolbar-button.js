// Runs as a React child of Codex's existing selectedTextOverlay component.
// xlr, g3 and zH are the React, JSX and button bindings in the pinned app build.
function __codexMarksNativeButton({selectedText, selectionSource}) {
  const [state, setState] = xlr.useState("ready");
  const [failure, setFailure] = xlr.useState("");
  xlr.useEffect(() => { setState("ready"); setFailure(""); }, [selectedText, selectionSource?.thread_id,
    selectionSource?.message_id, selectionSource?.start_utf16, selectionSource?.end_utf16]);
  if (!window.codexMarks || typeof selectedText !== "string" || !selectedText.trim()) return null;
  const save = async () => {
    if (state === "saving" || state === "saved") return;
    setState("saving");
    try {
      if (!selectionSource) throw new Error("无法读取这处原文的位置，请重新划词");
      const result = await window.codexMarks.saveSelectedText(selectedText, selectionSource);
      if (!result || result.ok !== true) throw new Error(result?.error || "保存失败，请重试");
      setState("saved");
      if (window.Event && window.dispatchEvent) window.dispatchEvent(new window.Event('codex-marks-changed'));
      if (typeof __codexMarksUnderlines !== "undefined") __codexMarksUnderlines?.refresh();
    } catch (error) {
      setFailure(error?.message || "保存失败，请再次点击 mark 重试");
      setState("error");
    }
  };
  const label = state === "saving" ? "mark…" : state === "saved" ? "✓ mark" : "mark";
  return (0, g3.jsx)(zH, {
    onClick: save,
    disabled: state === "saving" || state === "saved",
    title: failure || "保存选中文字到 mark 收藏库",
    "aria-label": failure || "mark",
    children: label
  });
}
