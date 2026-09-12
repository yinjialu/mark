#!/usr/bin/env python3
"""Prepare a version-pinned Codex toolbar patch; never modify an installed app."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import plistlib
import re
import shutil
import struct

ROOT = Path(__file__).resolve().parent
PROFILES = {
    ("26.901.51231", "e2ab6e5985856e148ff78e79658e1241e9ab258d82453d201326bdd2e6779717"): {
        "generation": 1,
        "asset": "webview/assets/app-primary-6cd7b8b3f5e3.js",
        "initial": "webview/assets/app-initial-cadb12d4a15e.js",
        "mermaid": "webview/assets/mermaid-diagram-e0f2bd6686a8.js",
        "rail": "webview/assets/thread-user-message-navigation-rail-app-555e91d9ccfc.js",
        "tabs": "webview/assets/tabs-2fa243fa7caf.js",
        "main": ".vite/build/main-BT6ViFC-.js",
    },
    ("26.908.40834", "517e720853645405849b726c8e32862c020154780d0c319d8df44b88d84086f1"): {
        "generation": 2,
        "asset": "webview/assets/app-primary-44ec287874b7.js",
        "initial": "webview/assets/app-initial-9b95fa538c62.js",
        "mermaid": "webview/assets/mermaid-diagram-d7ab7d6ebbc1.js",
        "rail": "webview/assets/thread-user-message-navigation-rail-app-3f607bba867e.js",
        "tabs": "webview/assets/tabs-90f6572747cb.js",
        "main": ".vite/build/main-DaMR-wdT.js",
    },
}
VERSION = HEADER_HASH = ASSET = INITIAL = MERMAID = RAIL = TABS = MAIN = None
GENERATION = None
PRELOAD = ".vite/build/preload.js"
BOOTSTRAP = ".vite/build/early-bootstrap.js"
BRIDGE = ".vite/build/codex-marks-main.cjs"
BLOCKS = "webview/assets/codex-marks-blocks.js"
LIBRARY = "webview/assets/codex-marks-library.js"
LIBRARY_BRIDGE = ".vite/build/codex-marks-library.cjs"
UPDATE_BRIDGE = ".vite/build/codex-marks-update.cjs"
SIDEBAR = "webview/assets/codex-marks-sidebar.js"


def configure(version, header_hash):
    global VERSION, HEADER_HASH, ASSET, INITIAL, MERMAID, RAIL, TABS, MAIN, GENERATION
    profile = PROFILES.get((version, header_hash))
    if profile is None:
        raise ValueError("Client version mismatch; rebuild the patch for this version")
    VERSION, HEADER_HASH = version, header_hash
    ASSET, INITIAL, MERMAID, RAIL, TABS, MAIN = (profile[name] for name in
        ("asset", "initial", "mermaid", "rail", "tabs", "main"))
    GENERATION = profile["generation"]


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
    function_name = "ylr" if GENERATION == 1 else "u4n"
    next_declaration = "var blr,xlr,g3,Slr=" if GENERATION == 1 else "var d4n,f4n,q3,p4n="
    start = script.index(f"function {function_name}(e){{")
    end = script.index(next_declaration, start)
    original = script[start:end]
    tail = original.index("let S;return t[41]")
    expected = "children:[_,v,y,b,x]"
    if original.count(expected) != 1 or "__codexMarks" in script:
        raise ValueError("Toolbar structure does not match the pinned build")
    jsx, container = ("g3", "KZt") if GENERATION == 1 else ("q3", "MOe")
    patched = original[:tail] + (
        f"return (0,{jsx}.jsxs)({container},{{children:[_,v,y,b,x,"
        f"(0,{jsx}.jsx)(__codexMarksNativeButton,{{selectedText:u,selectionSource:e.markSource}})]}})}}"
    )
    addition = "\n".join((ROOT / "src" / name).read_text() for name in
                         ("toolbar-button.js", "selection-source.js", "underlines.js"))
    script = script[:start] + patched + "\n" + addition + "\n" + script[end:]
    before = ('let{portalTarget:r,rect:o,selectedText:s,selectionRange:l,target:u}=e,d=Jn(u,l,s);return(0,QBr.jsx)(ylr,{selectedText:s,'
              if GENERATION == 1 else
              'let{portalTarget:r,rect:o,selectedText:s,selectionRange:l,target:u}=e,d=vge(u,l,s);return(0,s7.jsx)(u4n,{selectedText:s,')
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
    if GENERATION == 2:
        return replace_blocks_v2(archive, primary)
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


def replace_blocks_v2(archive, primary):
    """Patch the 26.908 renderer structures after validating each native action group."""
    header = 'import {renderMarkButton as __markBlockButton} from "./codex-marks-blocks.js";\n'
    mermaid = archive.read(MERMAID).decode()
    before = 'onCopy:L})]}):null,t[51]=U'
    after = ('onCopy:L}),(0,I.jsx)(__MarkMermaid,{kind:"mermaid",source:r,getElement:()=>g.current,'
             'serialize:el=>{const svg=el.querySelector("svg");if(!svg)throw Error("图表尚未完成");'
             'return _e(svg,el,a).outerHTML}})]}):null,t[51]=U')
    if mermaid.count(before) != 1:
        raise ValueError('Mermaid action group changed')
    mermaid = mermaid.replace(before, after, 1)
    before = 'ref:g,className:X,dir:`ltr`'
    if mermaid.count(before) != 1:
        raise ValueError('Mermaid render target changed')
    mermaid = mermaid.replace(before, 'ref:g,className:X,"data-codex-mark-block-kind":"mermaid",dir:`ltr`', 1)
    mermaid = header + mermaid + '\nfunction __MarkMermaid(e){return __markBlockButton(F,I,ue,e)}\n'

    initial = archive.read(INITIAL).decode()
    before = ('let O;t[27]!==E||t[28]!==D?(O=(0,eq.jsx)(`div`,{className:NK.TableActions,'
              '"data-markdown-copy":`exclude`,children:(0,eq.jsxs)(Tqi,{className:`sticky top-1`,children:[E,D]})}),'
              't[27]=E,t[28]=D,t[29]=O):O=t[29];')
    after = ('let O;t[27]!==E||t[28]!==D?(O=(0,eq.jsx)(`div`,{className:NK.TableActions,'
             '"data-markdown-copy":`exclude`,children:(0,eq.jsxs)(Tqi,{className:`sticky top-1`,'
             'children:[E,D,(0,eq.jsx)(__MarkTable,{kind:"table",source:a,caption:"表格",'
             'getElement:button=>button?.closest("[data-markdown-table]")?.querySelector("table")})]})}),'
             't[27]=E,t[28]=D,t[29]=O):O=t[29];')
    if initial.count(before) != 1:
        raise ValueError('Table action group changed')
    initial = initial.replace(before, after, 1)

    start = initial.index('function sqi(e){')
    end = initial.index('var KK,qK,JK,', start)
    component = initial[start:end]
    before = 'let te;return t[53]'
    cut = component.index(before)
    replacement = ('return (0,JK.jsxs)("span",{"data-codex-mark-image-wrap":"",'
                   'style:{display:"inline-flex",alignItems:"flex-start",gap:4,maxWidth:"100%"},children:['
                   '(0,JK.jsx)(HGi,{src:D,alt:O,open:_,onOpenChange:v,caption:O,downloadSrc:D,'
                   'onDownloadClick:p,onPreviousImage:R,onNextImage:z,triggerContent:ee}),(0,JK.jsx)(__MarkImage,'
                   '{kind:"image",source:u,caption:r,loadImage:()=>u,getElement:button=>button?.closest('
                   '"[data-codex-mark-image-wrap]")?.querySelector("img")})]})}')
    component = component[:cut] + replacement
    initial = initial[:start] + component + initial[end:]
    initial = header + initial + ('\nfunction __MarkTable(e){return __markBlockButton(xJi,eq,Ir,e)}\n'
                                  'function __MarkImage(e){return __markBlockButton(qK,JK,Ir,e)}\n')

    before = 'onDownloadClick:m==null?void 0:()=>m(e)})'
    if primary.count(before) != 1:
        raise ValueError('Generated image action target changed')
    source = 'e.src??e.previewSrc??``'
    after = (before + ',i&&(0,vX.jsx)("div",{style:{position:"absolute",right:4,top:4,zIndex:10},'
             'children:(0,vX.jsx)(__MarkGallery,{kind:"image",source:' + source + ',caption:Fgn(k,t+1),'
             'getElement:button=>button?.closest("[data-image-transparency-backdrop-scope]")?.querySelector("img"),'
             'loadImage:()=>{const n=' + source + ';return tX({absoluteImageFilePath:nx(n),hostId:O.get(Wb),'
             'imageAssetResolver:l,queryClient:O.queryClient,src:n})}})})')
    primary = primary.replace(before, after, 1)
    primary = header + primary + '\nfunction __MarkGallery(e){return __markBlockButton(_X,vX,HE,e)}\n'
    return primary, initial, mermaid


def replace_sidebar(primary):
    """Insert a destination into the native list without product-mode gating."""
    def once(before, after):
        nonlocal primary
        if primary.count(before) != 1:
            raise ValueError('Sidebar structure changed: ' + before[:70])
        primary = primary.replace(before, after, 1)
    function_name = '$Sn' if GENERATION == 1 else 'jQt'
    list_name = 'M' if GENERATION == 1 else 'L'
    destination_name = 'Hy' if GENERATION == 1 else '_w'
    once(f'function {function_name}({{desktopNavItemsEnabled:e,destinationDiscoveryEnabled:t,onSelectSpace:n,sidebarMode:r}}){{',
         f'function {function_name}({{desktopNavItemsEnabled:e,destinationDiscoveryEnabled:t,onSelectSpace:n,sidebarMode:r}}){{const __markItem=__getMarkSidebar().useItem();')
    if GENERATION == 2:
        once('onPrefetch:()=>{MQt(i,x,y)}}),e&&r===`codex`&&b&&EQt(',
             'onPrefetch:()=>{MQt(i,x,y)}}),e&&L.push(__markItem),e&&r===`codex`&&b&&EQt(')
    else:
        once('onPrefetch:()=>{tCn(i,g,m)}}),e&&r===`codex`&&h&&JSn(',
             'onPrefetch:()=>{tCn(i,g,m)}}),e&&M.push(__markItem),e&&r===`codex`&&h&&JSn(')
    if GENERATION == 1:
        once('M.push(...A.filter(({id:e})=>e!==Hy.pullRequests)),M}',
             'M.push(...A.filter(({id:e})=>e!==Hy.pullRequests)),__markItem.isCurrentDestination?M.map(item=>item.id===__markItem.id?item:{...item,isCurrentDestination:false}):M}')
    else:
        once('L.push(...F.filter(({id:e})=>e!==_w.pullRequests)),L}',
             'L.push(...F.filter(({id:e})=>e!==_w.pullRequests)),__markItem.isCurrentDestination?L.map(item=>item.id===__markItem.id?item:{...item,isCurrentDestination:false}):L}')
    gate = f'return t==={destination_name}.debug'
    once(gate, f'return t===`builtin:mark`||t==={destination_name}.debug')
    visibility = f'visibleByDefault:e.id==={destination_name}.projects||e.id==={destination_name}.library||!1'
    once(visibility, f'visibleByDefault:e.id===`builtin:mark`||e.id==={destination_name}.projects||e.id==={destination_name}.library||!1')
    primary = ('import {createMarkSidebar as __createMarkSidebar} from "./codex-marks-sidebar.js";\n'
               f'import {{__markNativeComponents}} from "./{Path(INITIAL).name}";\n' + primary)
    primary += '\nlet __markSidebarIntegration;function __getMarkSidebar(){return __markSidebarIntegration??=(__createMarkSidebar(__markNativeComponents()));}\n'
    return primary


def replace_page(initial):
    # Route uses the same parent outlet and access boundary as the Plugins page.
    jsx, route = ('i3', 'nT') if GENERATION == 1 else ('O2', 'sb')
    needle=f'(0,{jsx}.jsxs)({route},{{path:`/plugins`,children:['
    if initial.count(needle) != 1:
        raise ValueError('Native plugins route changed')
    initial=initial.replace(needle,f'(0,{jsx}.jsx)({route},{{path:`/mark`,element:(0,{jsx}.jsx)(__MarkPageRoute,{{}})}}),'+needle,1)
    initial='import {createMarkSidebar as __createMarkPage} from "./codex-marks-sidebar.js";\n'+initial
    runtime = 'G()' if GENERATION == 1 else 'y()'
    initial+=f'\nlet __markPageIntegration;function __MarkPageRoute(){{__markPageIntegration??=__createMarkPage(__markNativeComponents());return {runtime}.jsx(__markPageIntegration.Page,{{}});}}\n'
    return initial


def disable_official_updater(script):
    """The locally signed copy cannot be safely replaced by the official updater."""
    pattern = re.compile(r'([A-Za-z_$][\w$]*)=([A-Za-z_$][\w$]*\.[A-Za-z_$][\w$]*)\.shouldIncludeUpdater\(([^()]*)\)')
    matches = list(pattern.finditer(script))
    if len(matches) != 1:
        raise ValueError('Official updater initialization changed')
    match = matches[0]
    return script[:match.start()] + match.group(1) + '=!1' + script[match.end():]


def prepare(app, output, plugin):
    app, output, plugin = app.resolve(), output.resolve(), plugin.resolve()
    # Preparation never writes into or over an application bundle.
    if app == output or app in output.parents or output.exists():
        raise ValueError("Use a new output directory outside the installed app")
    info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
    archive = Archive(app / "Contents/Resources/app.asar")
    source_hash = digest(archive.raw_header)
    if info.get("CFBundleIdentifier") != "com.openai.codex":
        raise ValueError("Client bundle identifier mismatch")
    configure(info.get("CFBundleShortVersionString"), source_hash)
    if source_hash != HEADER_HASH:
        raise ValueError("Client archive changed; refusing a blind patch")
    if info["ElectronAsarIntegrity"]["Resources/app.asar"]["hash"] != HEADER_HASH:
        raise ValueError("Client integrity metadata mismatch")
    modified, original_component, patched_component = replace_toolbar(archive.read(ASSET).decode())
    modified, initial, mermaid = replace_blocks(archive, modified)
    modified = replace_sidebar(modified)
    if GENERATION == 1:
        if 'function aTr(e,t,n){return e.set(G8,t,n)' not in modified:
            raise ValueError('Native source navigation registry changed')
        modified += '\n' + (ROOT / 'src/native-source.js').read_text()
    else:
        if 'function C6n(e,t,n,r){return e.get(g6,t)?.revealResponseTextAnnotation' not in modified:
            raise ValueError('Native source navigation registry changed')
        modified += '\n' + (ROOT / 'src/native-source-v2.js').read_text()

    initial = replace_page(initial)
    main = disable_official_updater(archive.read(MAIN).decode())
    # Native components are initialized by their original lazy module initializers.
    initial = f'import {{n as __initMarkTabs,t as __MarkTabs}} from "./{Path(TABS).name}";\n' + initial
    if GENERATION == 1:
        initial += '\nexport function __markNativeComponents(){qN();pH();gq();oCo();__initMarkTabs();return {React:c(),jsx:G(),createPortal:pe().createPortal,Button:KN,Tabs:__MarkTabs,PageLayout:$So,Dialog:cH,Title:lH,Description:uH,Input:P6i,useNavigate:$w,useLocation:Zw};}\n'
    else:
        initial += '\nexport function __markNativeComponents(){i7a();IG();Rnn();__initMarkTabs();return {React:a(),jsx:y(),createPortal:b().createPortal,Button:Ir,Tabs:__MarkTabs,PageLayout:Z5a,Input:TPi,useNavigate:nb,useLocation:eb};}\n'
    rail = archive.read(RAIL).decode()
    expected = ('export{Qt as AppThreadUserMessageNavigationRail};' if GENERATION == 1 else
                'export{$t as AppThreadUserMessageNavigationRail};')
    if rail.count(expected) != 1:
        raise ValueError('Native navigation entry changed')
    prefix = ('import {createMarksUI as __createMarksUI} from "./codex-marks-library.js";\n'
              f'import {{__markNativeComponents}} from "./{Path(INITIAL).name}";\n'
              f'import {{__markUseRevealSource}} from "./{Path(ASSET).name}";\n')
    if GENERATION == 1:
        suffix = ('\nconst __markUI=__markNativeComponents();'
                  'const __MarkLibrary=__createMarksUI(tn,nn,{...__markUI,Marker:Ke,Preview:qe,Tooltip:ue,Icon:lt,createPortal:Wt.createPortal});'
                  'function __MarkRailRoot(e){const {getScrollElement}=Ie(),navigate=__markUI.useNavigate(),location=__markUI.useLocation(),onRevealMark=__markUseRevealSource();'
                  'return (0,nn.jsxs)(nn.Fragment,{children:[(0,nn.jsx)(Qt,e),(0,nn.jsx)(__MarkLibrary,{...e,getScrollElement,navigate,onRevealMark,pathname:location.pathname})]});}\n')
    else:
        suffix = ('\nconst __markUI=__markNativeComponents();'
                  'const __MarkLibrary=__createMarksUI(nn,rn,{...__markUI,Marker:Ke,Preview:qe,Tooltip:Fe,Icon:lt,createPortal:Gt.createPortal});'
                  'function __MarkRailRoot(e){const {getScrollElement}=Ie(),navigate=__markUI.useNavigate(),location=__markUI.useLocation(),onRevealMark=__markUseRevealSource();'
                  'return (0,rn.jsxs)(rn.Fragment,{children:[(0,rn.jsx)($t,e),(0,rn.jsx)(__MarkLibrary,{...e,getScrollElement,navigate,onRevealMark,pathname:location.pathname})]});}\n')
    rail = prefix + rail.replace(expected, 'export{__MarkRailRoot as AppThreadUserMessageNavigationRail};') + suffix
    bootstrap = archive.read(BOOTSTRAP)
    if bootstrap.count(b"Promise.resolve().then") != 1:
        raise ValueError("Bootstrap structure changed")
    replacements = {
        ASSET: modified.encode(),
        PRELOAD: archive.read(PRELOAD) + b"\n" + (ROOT / "src/preload-bridge.js").read_bytes(),
        BOOTSTRAP: bootstrap.replace(b"Promise.resolve().then",
            b'(()=>{try{require("./codex-marks-main.cjs").register()}catch(_){}})(),Promise.resolve().then', 1),
        BRIDGE: (ROOT / "src/main-bridge.cjs").read_bytes(),
        INITIAL: initial.encode(), MAIN: main.encode(), MERMAID: mermaid.encode(), BLOCKS: (ROOT / "src/block-buttons.mjs").read_bytes(),
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
    parent_name, parent_declaration = (("XBr", "var ZBr,QBr,$Br=") if GENERATION == 1 else
                                       ("clr", "var llr,s7,ulr="))
    parent_start = modified.index(f"function {parent_name}(e){{")
    parent_end = modified.index(parent_declaration, parent_start)
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
