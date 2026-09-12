"""macOS integration check: python3 -B tests/check_native_launcher.py."""
from pathlib import Path
from unittest.mock import patch
import sys,tempfile,shutil,json,subprocess,plistlib,time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import mark
with tempfile.TemporaryDirectory(prefix='mark-launcher-check-') as tmp:
 root=Path(tmp);package=root/'source';(package/'integration/src').mkdir(parents=True)
 (package/'assets').mkdir()
 shutil.copyfile(mark.ROOT/'integration/src/launcher.c',package/'integration/src/launcher.c')
 shutil.copyfile(mark.ROOT/'assets/mark.icns',package/'assets/mark.icns')
 result=root/'launched.json'
 (package/'mark.py').write_text('import platform,json\nfrom pathlib import Path\nPath('+repr(str(result))+').write_text(json.dumps({"architecture":platform.machine()}))\n')
 legacy=root/'apps/mark.app';(legacy/'Contents').mkdir(parents=True)
 (legacy/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':'local.mark.launcher'}))
 with patch.object(mark,'ROOT',package),patch.object(mark,'verify_package',return_value='fixture'):
  _,launcher=mark.install_launcher(root/'state',Path('/not-used.app'),root/'apps')
 assert launcher.name=='ChatGPT mark.app' and not legacy.exists()
 info=plistlib.loads((launcher/'Contents/Info.plist').read_bytes())
 assert info['CFBundleDisplayName']=='ChatGPT mark'
 info['CFBundleIdentifier']='local.mark.launcher.check';(launcher/'Contents/Info.plist').write_bytes(plistlib.dumps(info))
 subprocess.run(['/usr/bin/codesign','--force','--sign','-',str(launcher)],check=True,capture_output=True)
 print(subprocess.check_output(['/usr/bin/file',str(launcher/'Contents/MacOS/mark')],text=True).strip())
 subprocess.run(['/usr/bin/open','-n','-W',str(launcher)],check=True,timeout=25)
 assert json.loads(result.read_text())['architecture']=='arm64'
 print('LaunchServices opened native launcher; child Python ran as arm64')
