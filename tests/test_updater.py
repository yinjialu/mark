import hashlib
import io
import json
from pathlib import Path
import plistlib
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import mark
from integration import updater

SOURCE={'bundle_id':'com.openai.codex','version':'client','build':'1','architecture':'arm64','header_sha256':'a'*64}

def release(number,source=SOURCE,draft=False):
    tag='v0.1.0-preview.'+str(number)
    manifest={'release':tag[1:],'update_protocol':1,'adapters':[source]}
    names=['mark-'+tag[1:]+'-macos-arm64.zip','mark-'+tag[1:]+'-macos-arm64.zip.sha256','compatibility.json']
    assets=[{'name':n,'state':'uploaded','browser_download_url':'https://github.com/yinjialu/mark/releases/download/'+tag+'/'+n} for n in names]
    return {'tag_name':tag,'draft':draft,'prerelease':True,'published_at':'date','assets':assets},manifest

def package(manifest):
    files={'mark.py':b'raise RuntimeError("fixture must not execute")', 'compatibility.json':json.dumps(manifest).encode()}
    checks={p:hashlib.sha256(v).hexdigest() for p,v in files.items()}
    data=io.BytesIO()
    with zipfile.ZipFile(data,'w') as z:
        for p,v in files.items():z.writestr('mark/'+p,v)
        z.writestr('mark/SHA256SUMS.json',json.dumps(checks))
    return data.getvalue()

class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='mark-update-test-');self.addCleanup(self.temp.cleanup)
        self.state=Path(self.temp.name);self.app=Path('/test/ChatGPT.app')
        self.release,self.manifest=release(12)
    def offer(self):
        r=self.release
        offer={'version':self.manifest['release'],'tag':r['tag_name'],'ticket':'ticket','expires':time.time()+1000,'source':SOURCE,'manifest':self.manifest,'zip':r['assets'][0],'checksum':r['assets'][1]}
        mark.atomic_json(self.state/'update-offer.json',offer)
        return offer
    def test_semantic_preview_order_and_stable(self):
        self.assertGreater(updater.version('v0.1.0-preview.12'),updater.version('v0.1.0-preview.9'))
        self.assertGreater(updater.version('v0.1.0'),updater.version('v0.1.0-preview.99'))
        with self.assertRaises(updater.UpdateError):updater.version('../main')
    def test_latest_compatible_includes_previews_and_skips_drafts_and_incomplete(self):
        newer,new_manifest=release(13,{**SOURCE,'build':'2'})
        draft,_=release(14,draft=True);incomplete,_=release(15);incomplete['assets'].pop()
        calls=[]
        def fetch(url,limit):
            calls.append(url);return json.dumps(new_manifest if 'preview.13/' in url else self.manifest).encode()
        selected=updater.select_release([self.release,newer,draft,incomplete],SOURCE,fetch)
        self.assertEqual(selected['tag'],'v0.1.0-preview.12')
        self.assertTrue(all(u.endswith('/compatibility.json') for u in calls))
        self.assertEqual(len(calls),2)
    def test_no_compatible_release(self):
        self.assertIsNone(updater.select_release([self.release],{**SOURCE,'architecture':'x86_64'},lambda *_:json.dumps(self.manifest).encode()))
    def test_reject_other_repo_assets_and_insecure_redirects(self):
        self.release['assets'][0]['browser_download_url']='https://github.com/attacker/mark/releases/download/test.zip'
        self.assertIsNone(updater.select_release([self.release],SOURCE))
        for url in ['http://github.com/x','https://localhost/x','https://github.com.evil.test/x','https://name:secret@github.com/x']:
            with self.assertRaises(updater.UpdateError):updater.allowed_url(url)
    def test_cache_avoids_network_and_force_refreshes(self):
        cached={'source':SOURCE,'current_version':None,'checked_at':time.time(),'status':'up_to_date'}
        mark.atomic_json(self.state/'update-check.json',cached)
        with patch.object(updater,'identity',return_value=SOURCE),patch.object(updater,'fetch',return_value=b'[]') as fetch:
            self.assertEqual(updater.check(mark,self.app,self.state)['status'],'up_to_date');fetch.assert_not_called()
            self.assertEqual(updater.check(mark,self.app,self.state,True)['status'],'no_compatible_release');fetch.assert_called_once()
    def test_offline_is_nonfatal_and_does_not_modify_active(self):
        active={'active':{'app':'old'}};mark.atomic_json(self.state/'state.json',active)
        with patch.object(updater,'identity',return_value=SOURCE),patch.object(updater,'fetch',side_effect=OSError('offline')):
            self.assertEqual(updater.check(mark,self.app,self.state,True)['status'],'offline')
        self.assertEqual(mark.read_json(self.state/'state.json'),active)
    def test_verified_extraction_and_corrupt_inventory(self):
        root=updater.extract_verified(package(self.manifest),self.state/'valid')
        self.assertTrue((root/'mark.py').is_file())
        data=io.BytesIO(package(self.manifest))
        with zipfile.ZipFile(data,'a') as z:z.writestr('mark/extra.py','bad')
        with self.assertRaises(updater.UpdateError):updater.extract_verified(data.getvalue(),self.state/'bad')
    def test_archive_paths_symlinks_and_duplicates(self):
        for names in [['mark/../../escape'],['/mark/file'],['other/file'],['mark/a','mark/A'],['mark/link']]:
            data=io.BytesIO()
            with zipfile.ZipFile(data,'w') as z:
                for name in names:
                    item=zipfile.ZipInfo(name)
                    if name.endswith('link'):item.external_attr=(stat.S_IFLNK|0o777)<<16
                    z.writestr(item,'bad')
            with self.assertRaises(updater.UpdateError):updater.extract_verified(data.getvalue(),self.state/'bad-path')
        self.assertFalse((self.state/'escape').exists())
    def test_checksum_failure_never_executes_download(self):
        offer=self.offer();data=package(self.manifest)
        def fetch(url,limit):return (('0'*64+'  '+offer['zip']['name']).encode() if url.endswith('.sha256') else data)
        with patch.object(updater,'identity',return_value=SOURCE),patch.object(updater,'fetch',side_effect=fetch),patch.object(updater.subprocess,'run') as run:
            with self.assertRaises(updater.UpdateError):updater.apply(mark,self.app,self.state,'ticket')
            run.assert_not_called()
        self.assertEqual(mark.read_json(self.state/'update-job.json')['status'],'error')
    def test_verified_download_runs_one_upgrade_transaction(self):
        offer=self.offer();data=package(self.manifest)
        def fetch(url,limit):return ((hashlib.sha256(data).hexdigest()+'  '+offer['zip']['name']).encode() if url.endswith('.sha256') else data)
        with patch.object(updater,'identity',return_value=SOURCE),patch.object(updater,'fetch',side_effect=fetch),patch.object(updater.subprocess,'run') as run:
            self.assertEqual(updater.apply(mark,self.app,self.state,'ticket')['status'],'complete')
            argv=run.call_args.args[0];self.assertIn('upgrade',argv);self.assertIn('--switch',argv)
            self.assertTrue(Path(argv[2]).exists());run.assert_called_once()
    def test_expired_offer_and_changed_client_stop_before_download(self):
        offer=self.offer();offer['expires']=0;mark.atomic_json(self.state/'update-offer.json',offer)
        with self.assertRaises(updater.UpdateError):updater.offer_for(mark,self.state,'ticket')
        self.offer()
        with patch.object(updater,'identity',return_value={**SOURCE,'build':'changed'}),patch.object(updater,'fetch') as fetch:
            with self.assertRaises(updater.UpdateError):updater.apply(mark,self.app,self.state,'ticket')
            fetch.assert_not_called()
    def test_duplicate_schedules_are_rejected(self):
        self.offer();mark.atomic_json(self.state/'update-job.json',{'status':'installing','started_at':time.time()})
        with patch.object(updater.subprocess,'Popen') as spawn:
            with self.assertRaises(updater.UpdateError):updater.schedule(mark,self.app,self.state,'ticket')
            spawn.assert_not_called()
    def test_launch_failure_restores_launcher_and_active_state(self):
        launcher=self.state/'apps/mark.app';(launcher/'Contents').mkdir(parents=True)
        (launcher/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':'local.mark.launcher'}))
        (launcher/'old').write_text('working launcher')
        mark.atomic_json(self.state/'launcher.json',{'path':str(launcher)})
        before={'active':{'app':'old'},'prepared':{'app':'old'}};mark.atomic_json(self.state/'state.json',before)
        def build(*args):mark.atomic_json(self.state/'state.json',{**before,'prepared':{'app':'new'}});return {'app':'new'}
        def install(*args):
            (launcher/'old').unlink();(launcher/'new').write_text('new launcher')
        with patch.object(mark,'build',side_effect=build),patch.object(mark,'install_launcher',side_effect=install),patch.object(mark,'launch_record',side_effect=mark.MarkError('failed')):
            with self.assertRaises(mark.MarkError):mark.upgrade_transaction(self.app,self.state,switch=True)
        self.assertEqual((launcher/'old').read_text(),'working launcher');self.assertFalse((launcher/'new').exists())
        self.assertEqual(mark.read_json(self.state/'state.json'),before)
