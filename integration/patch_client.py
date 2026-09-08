#!/usr/bin/env python3
"""Prepare a version-pinned Codex toolbar patch; never modify an installed app."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import plistlib
import shutil
import struct

ROOT = Path(__file__).resolve().parent
VERSION = "26.901.51231"
HEADER_HASH = "e2ab6e5985856e148ff78e79658e1241e9ab258d82453d201326bdd2e6779717"
ASSET = "webview/assets/app-primary-6cd7b8b3f5e3.js"
PRELOAD = ".vite/build/preload.js"
BOOTSTRAP = ".vite/build/early-bootstrap.js"
BRIDGE = ".vite/build/codex-marks-main.cjs"
INITIAL = "webview/assets/app-initial-cadb12d4a15e.js"
MERMAID = "webview/assets/mermaid-diagram-e0f2bd6686a8.js"
BLOCKS = "webview/assets/codex-marks-blocks.js"
RAIL = "webview/assets/thread-user-message-navigation-rail-app-555e91d9ccfc.js"
LIBRARY = "webview/assets/codex-marks-library.js"
LIBRARY_BRIDGE = ".vite/build/codex-marks-library.cjs"
UPDATE_BRIDGE = ".vite/build/codex-marks-update.cjs"
SIDEBAR = "webview/assets/codex-marks-sidebar.js"


def digest(data):
    return hashlib.sha256(data).hexdigest()


class Archive:
    def __init__(self, path):
        self.path = Path(path)
        with self.path.open("rb") as f:
            tag, header_size, payload_size, string_size = struct.unpack("<4I", f.read(16))
            if tag != 4 or header_size != payload_size + 4 or string_size > payload_size - 4:
                raise ValueError("Unexpected ASAR header")
            self.raw_header = f.read(string_size)
        self.tree = json.loads(self.raw_header)
        self.base = 8 + header_size

    def entry(self, key):
        entry = self.tree
        for part in key.split("/"):
            entry = entry["files"][part]
        return entry

    def read(self, key):
        entry = self.entry(key)
        if "offset" not in entry:
            raise ValueError("Expected packed file: " + key)
        with self.path.open("rb") as f:
            f.seek(self.base + int(entry["offset"]))
            data = f.read(entry["size"])
        if len(data) != entry["size"]:
            raise ValueError("Truncated archive")
        return data


def entries(tree, prefix=""):
    for name, entry in tree["files"].items():
        key = prefix + name
        if "files" in entry:
            yield from entries(entry, key + "/")
        else:
            yield key, entry


def replace_toolbar(script):
    start = script.index("function ylr(e){")
    end = script.index("var blr,xlr,g3,Slr=", start)
    original = script[start:end]
    tail = original.index("let S;return t[41]")
    expected = "children:[_,v,y,b,x]"
    if original.count(expected) != 1 or "__codexMarks" in script:
        raise ValueError("Toolbar structure does not match the pinned build")
    patched = original[:tail] + (
        "return (0,g3.jsxs)(KZt,{children:[_,v,y,b,x,"
        "(0,g3.jsx)(__codexMarksNativeButton,{selectedText:u,selectionSource:e.markSource})]})}"
    )
    addition = "\n".join((ROOT / "src" / name).read_text() for name in
                         ("toolbar-button.js", "selection-source.js", "underlines.js"))
    script = script[:start] + patched + "\n" + addition + "\n" + script[end:]
    before = 'let{portalTarget:r,rect:o,selectedText:s,selectionRange:l,target:u}=e,d=Jn(u,l,s);return(0,QBr.jsx)(ylr,{selectedText:s,'
    if script.count(before) != 1:
        raise ValueError("Selection source integration does not match the pinned build")
    after = before + 'markSource:__codexMarksSelectionSource(u,l,s,d),'
    script = script.replace(before, after, 1)
    return script, original, patched


def repack(archive, replacements, target):
    tree = copy.deepcopy(archive.tree)
    original_entries = dict(entries(archive.tree))
    for key in replacements:
        current = tree
        parts = key.split("/")
        for part in parts[:-1]:
            current = current["files"].setdefault(part, {"files": {}})
        current["files"].setdefault(parts[-1], {})
    leaves = dict(entries(tree))
    packed = sorted((key for key, e in original_entries.items() if "offset" in e),
                    key=lambda key: int(original_entries[key]["offset"]))
    packed.extend(key for key in replacements if key not in original_entries)
    offset = 0
    for key in packed:
        entry = leaves[key]
        if key in replacements:
            data = replacements[key]
            block_size = entry.get("integrity", {}).get("blockSize", 4194304)
            entry["size"] = len(data)
            entry["integrity"] = {"algorithm": "SHA256", "hash": digest(data), "blockSize": block_size,
                                  "blocks": [digest(data[i:i + block_size]) for i in range(0, len(data), block_size)]}
        entry["offset"] = str(offset)
        offset += entry["size"]
    raw = json.dumps(tree, ensure_ascii=False, separators=(",", ":")).encode()
    padding = b"\0" * ((-len(raw)) % 4)
    payload_size = 4 + len(raw) + len(padding)
    with target.open("xb") as out, archive.path.open("rb") as source:
        out.write(struct.pack("<4I", 4, payload_size + 4, payload_size, len(raw)))
        out.write(raw); out.write(padding)
        for key in packed:
            if key in replacements:
                out.write(replacements[key])
            else:
                old = original_entries[key]
                source.seek(archive.base + int(old["offset"]))
                remaining = old["size"]
                while remaining:
                    data = source.read(min(remaining, 1024 * 1024))
                    if not data:
                        raise ValueError("Truncated source ASAR")
                    out.write(data); remaining -= len(data)
    return digest(raw)


def replace_blocks(archive, primary):
    """Add a child to existing action groups; keep block renderers and actions intact."""
    header = 'import {renderMarkButton as __markBlockButton} from "./codex-marks-blocks.js";\n'
    mermaid = archive.read(MERMAID).decode()
    start = mermaid.index('let De=v?`code-block`:`exclude`')
    end = mermaid.index('let ke=!l&&`invisible`', start)
    old = mermaid[start:end]
    begin = old.index('J=l&&v?') + 2
    finish = old.index(':null,t[51]=') + len(':null')
    expression = old[begin:finish]
    assert expression.count('onCopy:L})]}') == 1
    expression = expression.replace('onCopy:L})]}', 'onCopy:L}),(0,N.jsx)(__MarkMermaid,{kind:"mermaid",source:i,getElement:()=>m.current,serialize:el=>{const svg=el.querySelector("svg");if(!svg)throw Error("图表尚未完成");return ve(svg,el,o).outerHTML}})]}')
    mermaid = mermaid[:start] + 'let De=v?`code-block`:`exclude`,Oe=v?h.fencedCode:void 0,J=' + expression + ';' + mermaid[end:]
    assert mermaid.count('ref:m,className:Y,dir:`ltr`') == 1
    mermaid = mermaid.replace('ref:m,className:Y,dir:`ltr`','ref:m,className:Y,"data-codex-mark-block-kind":"mermaid",dir:`ltr`',1)
    mermaid = header + mermaid + '\nfunction __MarkMermaid(e){return __markBlockButton(M,N,de,e)}\n'
    initial = archive.read(INITIAL).decode()
    a = initial.index('function Gca(')
    start = initial.index('let D;t[27]', a)
    end = initial.index('let O;t[30]', start)
    initial = initial[:start] + '''let D=(0,jJ.jsx)(`div`,{className:lJ.TableActions,"data-markdown-copy":`exclude`,children:(0,jJ.jsxs)(Xsa,{className:`sticky top-1`,children:[T,E,(0,jJ.jsx)(__MarkTable,{kind:"table",source:a,caption:"表格",getElement:button=>button?.closest("[data-markdown-table]")?.querySelector("table")})]})});''' + initial[end:]
    a = initial.index('function Msa(')
    start = initial.index('let te;return t[53]', a)
    end = initial.index('function ', start)
    initial = initial[:start] + '''return (0,EJ.jsxs)("span",{"data-codex-mark-image-wrap":"",style:{display:"inline-flex",alignItems:"flex-start",gap:4,maxWidth:"100%"},children:[(0,EJ.jsx)(poa,{src:E,alt:D,open:_,onOpenChange:v,caption:D,downloadSrc:E,onDownloadClick:p,onPreviousImage:L,onNextImage:R,triggerContent:U}),(0,EJ.jsx)(__MarkImage,{kind:"image",source:u,caption:r,loadImage:()=>u,getElement:button=>button?.closest("[data-codex-mark-image-wrap]")?.querySelector("img")})]})}''' + initial[end:]
    initial = header + initial + '\nfunction __MarkTable(e){return __markBlockButton(qca,jJ,KN,e)}\nfunction __MarkImage(e){return __markBlockButton(TJ,EJ,"button",e)}\n'
    a = primary.index('function qGn(')
    start = primary.index('let ge;return t[93]', a)
    end = primary.index('function ', start)
    old = primary[start:end]
    # The following var initializer belongs to the existing gallery module.
    tail = old[old.index('ge}') + 3:]
    primary = primary[:start] + '''return (0,z1.jsxs)(z1.Fragment,{children:[fe,pe,he,!m&&(0,z1.jsx)("div",{style:{position:"absolute",right:4,top:4,zIndex:10},children:(0,z1.jsx)(__MarkGallery,{kind:"image",source:n,caption:F,getElement:button=>button?.closest("[data-image-transparency-backdrop-scope]")?.querySelector("img"),loadImage:()=>O1({absoluteImageFilePath:kw(n),hostId:T.get(Wb),imageAssetResolver:o,queryClient:T.queryClient,src:n})})})]})}''' + tail + primary[end:]
    primary = header + primary + '\nfunction __MarkGallery(e){return __markBlockButton(R1,z1,"button",e)}\n'
    return primary, initial, mermaid


def replace_sidebar(primary):
    """Insert a destination into the native list without product-mode gating."""
    def once(before, after):
        nonlocal primary
        if primary.count(before) != 1:
            raise ValueError('Sidebar structure changed: ' + before[:70])
        primary = primary.replace(before, after, 1)
    once('function $Sn({desktopNavItemsEnabled:e,destinationDiscoveryEnabled:t,onSelectSpace:n,sidebarMode:r}){',
         'function $Sn({desktopNavItemsEnabled:e,destinationDiscoveryEnabled:t,onSelectSpace:n,sidebarMode:r}){const __markItem=__getMarkSidebar().useItem();')
    once('onPrefetch:()=>{tCn(i,g,m)}}),e&&r===`codex`&&h&&JSn(',
         'onPrefetch:()=>{tCn(i,g,m)}}),e&&M.push(__markItem),e&&r===`codex`&&h&&JSn(')
    once('M.push(...A.filter(({id:e})=>e!==Hy.pullRequests)),M}',
         'M.push(...A.filter(({id:e})=>e!==Hy.pullRequests)),__markItem.isCurrentDestination?M.map(item=>item.id===__markItem.id?item:{...item,isCurrentDestination:false}):M}')
    once('return t===Hy.debug||t===Hy.finance||t===Hy.gpts||!1}',
         'return t===`builtin:mark`||t===Hy.debug||t===Hy.finance||t===Hy.gpts||!1}')
    once('visibleByDefault:e.id===Hy.projects||e.id===Hy.library||!1',
         'visibleByDefault:e.id===`builtin:mark`||e.id===Hy.projects||e.id===Hy.library||!1')
    primary = ('import {createMarkSidebar as __createMarkSidebar} from "./codex-marks-sidebar.js";\n'
               'import {__markNativeComponents} from "./app-initial-cadb12d4a15e.js";\n' + primary)
    primary += '\nlet __markSidebarIntegration;function __getMarkSidebar(){return __markSidebarIntegration??=(__createMarkSidebar(__markNativeComponents()));}\n'
    return primary


def replace_page(initial):
    # Route uses the same parent outlet and access boundary as the Plugins page.
    needle='(0,i3.jsxs)(nT,{path:`/plugins`,children:['
    if initial.count(needle) != 1:
        raise ValueError('Native plugins route changed')
    initial=initial.replace(needle,'(0,i3.jsx)(nT,{path:`/mark`,element:(0,i3.jsx)(__MarkPageRoute,{})}),'+needle,1)
    initial='import {createMarkSidebar as __createMarkPage} from "./codex-marks-sidebar.js";\n'+initial
    initial+='\nlet __markPageIntegration;function __MarkPageRoute(){__markPageIntegration??=__createMarkPage(__markNativeComponents());return G().jsx(__markPageIntegration.Page,{});}\n'
    return initial


def prepare(app, output, plugin):
    app, output, plugin = app.resolve(), output.resolve(), plugin.resolve()
    # Preparation never writes into or over an application bundle.
    if app == output or app in output.parents or output.exists():
        raise ValueError("Use a new output directory outside the installed app")
    info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
    archive = Archive(app / "Contents/Resources/app.asar")
    if info.get("CFBundleIdentifier") != "com.openai.codex" or info.get("CFBundleShortVersionString") != VERSION:
        raise ValueError("Client version mismatch; rebuild the patch for this version")
    if digest(archive.raw_header) != HEADER_HASH:
        raise ValueError("Client archive changed; refusing a blind patch")
    if info["ElectronAsarIntegrity"]["Resources/app.asar"]["hash"] != HEADER_HASH:
        raise ValueError("Client integrity metadata mismatch")
    modified, original_component, patched_component = replace_toolbar(archive.read(ASSET).decode())
    modified, initial, mermaid = replace_blocks(archive, modified)
    modified = replace_sidebar(modified)
    if 'function aTr(e,t,n){return e.set(G8,t,n)' not in modified:
        raise ValueError('Native source navigation registry changed')
    modified += '\n' + (ROOT / 'src/native-source.js').read_text()

    initial = replace_page(initial)
    # Native components are initialized by their original lazy module initializers.
    initial = 'import {n as __initMarkTabs,t as __MarkTabs} from "./tabs-2fa243fa7caf.js";\n' + initial
    initial += '\nexport function __markNativeComponents(){qN();pH();gq();oCo();__initMarkTabs();return {React:c(),jsx:G(),createPortal:pe().createPortal,Button:KN,Tabs:__MarkTabs,PageLayout:$So,Dialog:cH,Title:lH,Description:uH,Input:P6i,useNavigate:$w,useLocation:Zw};}\n'
    rail = archive.read(RAIL).decode()
    expected = 'export{Qt as AppThreadUserMessageNavigationRail};'
    if rail.count(expected) != 1:
        raise ValueError('Native navigation entry changed')
    rail = ('import {createMarksUI as __createMarksUI} from "./codex-marks-library.js";\n'
            'import {__markNativeComponents} from "./app-initial-cadb12d4a15e.js";\n'
            'import {__markUseRevealSource} from "./app-primary-6cd7b8b3f5e3.js";\n' +
            rail.replace(expected, 'export{__MarkRailRoot as AppThreadUserMessageNavigationRail};') +
            '\nconst __markUI=__markNativeComponents();'
            'const __MarkLibrary=__createMarksUI(tn,nn,{...__markUI,Marker:Ke,Preview:qe,Tooltip:ue,Icon:lt,createPortal:Wt.createPortal});'
            'function __MarkRailRoot(e){const {getScrollElement}=Ie(),navigate=__markUI.useNavigate(),location=__markUI.useLocation(),onRevealMark=__markUseRevealSource();'
            'return (0,nn.jsxs)(nn.Fragment,{children:[(0,nn.jsx)(Qt,e),(0,nn.jsx)(__MarkLibrary,{...e,getScrollElement,navigate,onRevealMark,pathname:location.pathname})]});}\n')
    bootstrap = archive.read(BOOTSTRAP)
    if bootstrap.count(b"Promise.resolve().then") != 1:
        raise ValueError("Bootstrap structure changed")
    replacements = {
        ASSET: modified.encode(),
        PRELOAD: archive.read(PRELOAD) + b"\n" + (ROOT / "src/preload-bridge.js").read_bytes(),
        BOOTSTRAP: bootstrap.replace(b"Promise.resolve().then",
            b'(()=>{try{require("./codex-marks-main.cjs").register()}catch(_){}})(),Promise.resolve().then', 1),
        BRIDGE: (ROOT / "src/main-bridge.cjs").read_bytes(),
        INITIAL: initial.encode(), MERMAID: mermaid.encode(), BLOCKS: (ROOT / "src/block-buttons.mjs").read_bytes(),
        RAIL: rail.encode(), LIBRARY: (ROOT / 'src/library-ui.mjs').read_bytes(),
        LIBRARY_BRIDGE: (ROOT / 'src/library-bridge.cjs').read_bytes(),
        UPDATE_BRIDGE: (ROOT / 'src/update-bridge.cjs').read_bytes(),
        SIDEBAR: (ROOT / 'src/sidebar.mjs').read_bytes(),
    }
    resources = output / "Contents/Resources"
    resources.mkdir(parents=True)
    new_hash = repack(archive, replacements, resources / "app.asar")
    info["ElectronAsarIntegrity"]["Resources/app.asar"]["hash"] = new_hash
    (output / "Contents/Info.plist").write_bytes(plistlib.dumps(info))
    backend = resources / "codex-marks"; backend.mkdir()
    shutil.copy2(ROOT / "src/capture.py", backend / "capture.py")
    shutil.copy2(ROOT / "src/list-underlines.py", backend / "list-underlines.py")
    shutil.copy2(ROOT / "src/capture-block.py", backend / "capture-block.py")
    shutil.copy2(ROOT / "src/library.py", backend / "library.py")
    for name in ("marks.py", "resolve_source.py", "block_assets.py"):
        shutil.copy2(plugin / "scripts" / name, backend / name)
    extracted = output / "review"; extracted.mkdir()
    (extracted / "toolbar-before.js").write_text(original_component)
    (extracted / "toolbar-after.js").write_text(patched_component)
    parent_start = modified.index("function XBr(e){")
    parent_end = modified.index("var ZBr,QBr,$Br=", parent_start)
    (extracted / "selection-parent.js").write_text(modified[parent_start:parent_end])
    for key, data in replacements.items():
        (extracted / Path(key).name).write_bytes(data)
    checked = Archive(resources / "app.asar")
    for key, data in replacements.items():
        assert checked.read(key) == data
        assert checked.entry(key)["integrity"]["hash"] == digest(data)
    # Preserve every unaffected entry, including native unpacked modules and symlinks.
    original = dict(entries(archive.tree)); new = dict(entries(checked.tree))
    for key, entry in original.items():
        if key in replacements:
            continue
        assert {k: v for k, v in entry.items() if k != "offset"} == {k: v for k, v in new[key].items() if k != "offset"}
        if "offset" in entry:
            assert digest(archive.read(key)) == digest(checked.read(key)), key
    report = {
        "source_app": str(app), "version": VERSION, "original_header_sha256": HEADER_HASH,
        "patched_header_sha256": new_hash, "changed_archive_files": list(replacements),
        "verified_unchanged_entries": len(original) - len(set(original) & replacements.keys()),
        "state": "prepared_only_not_installed_or_signed",
        "remaining": ["verify embedded binary integrity digest requirements", "sign a separate test copy with a valid identity",
                      "user approves changed signing identity and app restart", "test native toolbar in the actual client"],
    }
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, default=Path("/Applications/ChatGPT.app"))
    parser.add_argument("--plugin", type=Path, default=Path.home() / "plugins/codex-marks")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.app, args.output, args.plugin), ensure_ascii=False, indent=2))
