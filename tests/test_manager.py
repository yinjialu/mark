import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('mark_manager', ROOT / 'mark.py')
manager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manager)
import patch_client


class ManagerTests(unittest.TestCase):
    def setUp(self):
        dock_sync = patch("dock.sync_dock")
        dock_sync.start()
        self.addCleanup(dock_sync.stop)
        self.temp = tempfile.TemporaryDirectory(prefix='mark-manager-test-')
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name)
        self.adapter = manager.read_json(ROOT / 'compatibility.json')['adapters'][0]
        self.info = {'CFBundleIdentifier': self.adapter['bundle_id'], 'CFBundleShortVersionString': self.adapter['version'], 'CFBundleVersion': self.adapter['build']}

    def test_adapter_requires_exact_version_build_hash_architecture(self):
        a = self.adapter
        self.assertEqual(manager.select_adapter(self.info, a['header_sha256'], a['architecture'], [a]), a)
        for key, value in [('CFBundleIdentifier', 'another.app'), ('CFBundleShortVersionString', 'new-version'), ('CFBundleVersion', '9999')]:
            self.assertIsNone(manager.select_adapter({**self.info, key: value}, a['header_sha256'], a['architecture'], [a]))
        self.assertIsNone(manager.select_adapter(self.info, '0' * 64, a['architecture'], [a]))
        self.assertIsNone(manager.select_adapter(self.info, a['header_sha256'], 'x86_64', [a]))

    def test_every_manifest_adapter_has_an_exact_patch_profile(self):
        adapters = manager.read_json(ROOT / 'compatibility.json')['adapters']
        self.assertEqual(len(adapters), 2)
        for adapter in adapters:
            key = (adapter['version'], adapter['header_sha256'])
            self.assertIn(key, patch_client.PROFILES)
            patch_client.configure(*key)
            self.assertEqual(patch_client.VERSION, adapter['version'])
            self.assertEqual(patch_client.HEADER_HASH, adapter['header_sha256'])
        with self.assertRaises(ValueError):
            patch_client.configure('future-version', '0' * 64)

    def test_unknown_upgrade_preserves_current_and_never_patches(self):
        active = {'active': {'app': '/existing/ChatGPT mark.app'}}
        manager.atomic_json(self.state / 'state.json', active)
        with patch.object(manager, 'verify_package', return_value='hash'), patch.object(manager, 'doctor', return_value={'status': 'unsupported_client', 'version': 'future', 'message': 'unsupported'}), patch.object(manager, 'prepare') as prepare:
            with self.assertRaises(manager.MarkError):
                manager.build(Path('/source/Codex.app'), self.state, accept=True)
            prepare.assert_not_called()
        self.assertEqual(manager.read_json(self.state / 'state.json'), active)

    def test_first_install_requires_explicit_local_signing_consent(self):
        with patch.object(manager, 'verify_package', return_value='hash'), patch.object(manager, 'doctor', return_value={'status': 'supported'}), patch.object(manager, 'prepare') as prepare:
            with self.assertRaises(manager.MarkError):
                manager.build(Path('/source/Codex.app'), self.state)
            prepare.assert_not_called()

    def test_prepare_does_not_promote_active_build(self):
        manager.atomic_json(self.state / 'state.json', {'active': {'app': 'old'}})
        manager.remember_build(self.state, {'app': 'new'})
        result = manager.read_json(self.state / 'state.json')
        self.assertEqual(result['active']['app'], 'old')
        self.assertEqual(result['prepared']['app'], 'new')

    def test_successful_launch_promotion_and_rollback_keep_both_versions(self):
        manager.promote(self.state, {'app': 'old'})
        manager.promote(self.state, {'app': 'new'})
        result = manager.read_json(self.state / 'state.json')
        self.assertEqual(result['previous']['app'], 'old')
        manager.promote(self.state, result['previous'])
        result = manager.read_json(self.state / 'state.json')
        self.assertEqual(result['active']['app'], 'old')
        self.assertEqual(result['previous']['app'], 'new')

    def test_existing_app_requires_switch_flag(self):
        with patch.object(manager, 'verified', return_value=Path('/new.app')), patch.object(manager, 'active_codex', return_value=[Path('/old.app')]), patch.object(manager, 'terminate') as terminate:
            with self.assertRaises(manager.MarkError):
                manager.launch_record({'app': '/new.app'}, self.state)
            terminate.assert_not_called()

    def test_failed_launch_reopens_previous_app_without_promoting(self):
        previous = {'active': {'app': '/old.app'}}
        manager.atomic_json(self.state / 'state.json', previous)
        calls = []
        def fake_run(args, **kwargs):
            calls.append(args)
            if args[-1] == Path('/new.app'):
                raise OSError('simulated launch failure')
        with patch.object(manager, 'verified', return_value=Path('/new.app')), patch.object(manager, 'active_codex', return_value=[Path('/old.app')]), patch.object(manager, 'terminate') as terminate, patch.object(manager, 'run', side_effect=fake_run), patch.object(manager, 'pids', return_value=[]):
            with self.assertRaises(OSError):
                manager.launch_record({'app': '/new.app'}, self.state, switch=True)
            terminate.assert_called_once_with(Path('/old.app'))
        self.assertEqual(calls[-1][-1], Path('/old.app'))
        self.assertEqual(manager.read_json(self.state / 'state.json'), previous)

    def test_managed_start_keeps_working_copy_when_official_update_is_unsupported(self):
        active = {'app': '/old/ChatGPT mark.app', 'version': 'old'}
        manager.atomic_json(self.state / 'state.json', {'active': active})
        with patch.object(manager, 'doctor', return_value={'status': 'unsupported_client', 'version': 'new', 'build': '2', 'message': 'unsupported'}), \
             patch.object(manager, 'build') as build, \
             patch.object(manager, 'launch_record', return_value={'status': 'running', 'app': active['app']}) as launch:
            result = manager.start_managed(Path('/Applications/ChatGPT.app'), self.state)
        build.assert_not_called()
        launch.assert_called_once_with(active, self.state, switch=True)
        self.assertEqual(result['compatibility_status'], 'waiting_for_adapter')
        self.assertEqual(manager.read_json(self.state / 'startup-status.json')['status'], 'waiting_for_adapter')

    def test_managed_start_uses_compatible_current_source(self):
        record = {'app': '/new/ChatGPT mark.app', 'version': 'new'}
        supported = {'status': 'supported', 'version': 'new', 'build': '2'}
        with patch.object(manager, 'doctor', return_value=supported), \
             patch.object(manager, 'build', return_value=record) as build, \
             patch.object(manager, 'launch_record', return_value={'status': 'running', 'app': record['app']}) as launch:
            result = manager.start_managed(Path('/Applications/ChatGPT.app'), self.state)
        build.assert_called_once()
        launch.assert_called_once_with(record, self.state, switch=True)
        self.assertEqual(result['status'], 'running')
        self.assertEqual(manager.read_json(self.state / 'startup-status.json')['status'], 'current')

    def test_integrity_rejects_changed_or_extra_package_files(self):
        package = self.state / 'package'; package.mkdir()
        (package / 'code.py').write_text('trusted local code')
        manager.atomic_json(package / 'SHA256SUMS.json', manager.inventory(package))
        self.assertEqual(len(manager.verify_package(package)), 16)
        (package / 'extra').write_text('unexpected')
        with self.assertRaises(manager.MarkError):
            manager.verify_package(package)

    def test_git_metadata_does_not_break_clone_integrity(self):
        package = self.state / 'repo'; package.mkdir()
        (package / 'mark.py').write_text('package')
        manager.atomic_json(package / 'SHA256SUMS.json', manager.inventory(package))
        original = manager.verify_package(package)
        (package / '.git').mkdir()
        (package / '.git/config').write_text('local git config')
        self.assertEqual(manager.verify_package(package), original)
        (package / '.git/config').unlink(); (package / '.git').rmdir()
        (package / '.git').write_text('gitdir: /some/worktree')
        self.assertEqual(manager.verify_package(package), original)
        (package / 'mark.py').write_text('changed')
        with self.assertRaises(manager.MarkError):
            manager.verify_package(package)

    def test_detached_switch_returns_result_path_and_detaches_process(self):
        with patch.object(manager.subprocess, 'Popen') as popen:
            popen.return_value.pid = 123
            result = manager.schedule_switch(Path('/source/Codex.app'), self.state, 'launch', True)
            args, options = popen.call_args
            self.assertIn('--switch', args[0])
            self.assertIn('--deferred-result', args[0])
            self.assertNotIn('--detached', args[0])
            self.assertTrue(options['start_new_session'])
            self.assertTrue(options['close_fds'])
            self.assertEqual(result['status'], 'switch_scheduled')
            self.assertFalse(Path(result['result_file']).exists())
            self.assertEqual(Path(result['log']).stat().st_mode & 0o777, 0o600)

    def test_exclusive_install_lock_is_released(self):
        with manager.lock(self.state):
            with self.assertRaises(manager.MarkError):
                with manager.lock(self.state):
                    pass
        with manager.lock(self.state):
            pass


if __name__ == '__main__':
    unittest.main()
