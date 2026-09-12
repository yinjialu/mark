"""Explicit GitHub release updates; no executable download during update checks."""
from __future__ import annotations
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import platform
import plistlib
import re
import stat
import subprocess
import tempfile
import time
from urllib.parse import urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler
import uuid
import zipfile

REPO = 'yinjialu/mark'
API = 'https://api.github.com/repos/' + REPO + '/releases'
HOSTS = {'api.github.com', 'github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com'}
MAX_ZIP = 50 * 1024 * 1024


class UpdateError(ValueError):
    pass


def version(value):
    match = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)(?:-preview\.(\d+))?', value or '')
    if not match:
        raise UpdateError('不支持的发布版本号')
    a, b, c, preview = match.groups()
    return int(a), int(b), int(c), preview is None, int(preview or 0)


def allowed_url(url):
    p = urlparse(url)
    if p.scheme != 'https' or p.hostname not in HOSTS or p.port not in (None, 443) or p.username or p.password:
        raise UpdateError('更新地址不属于 GitHub 发布服务')


class Redirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        allowed_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url, limit):
    allowed_url(url)
    request = Request(url, headers={'User-Agent': 'mark-updater', 'Accept': 'application/vnd.github+json' if url.startswith(API) else 'application/octet-stream'})
    with build_opener(Redirects()).open(request, timeout=15) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise UpdateError('更新文件超过大小限制')
    return data


def asset(release, name):
    expected = 'https://github.com/' + REPO + '/releases/download/' + release['tag_name'] + '/' + name
    matches = [a for a in release.get('assets', []) if isinstance(a, dict) and a.get('name') == name and a.get('state') == 'uploaded' and a.get('browser_download_url') == expected]
    return matches[0] if len(matches) == 1 else None


def verify_asset(data, item):
    digest = item.get('digest')
    if digest and digest != 'sha256:' + hashlib.sha256(data).hexdigest():
        raise UpdateError('发布文件与 GitHub 校验值不一致')


def identity(manager, app):
    if platform.system() != 'Darwin':
        raise UpdateError('界面更新仅支持 macOS')
    info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
    header = manager.digest(manager.Archive(app / 'Contents/Resources/app.asar').raw_header)
    if info.get('ElectronAsarIntegrity', {}).get('Resources/app.asar', {}).get('hash') != header:
        raise UpdateError('正式客户端完整性检查失败')
    return {'bundle_id': info.get('CFBundleIdentifier'), 'version': info.get('CFBundleShortVersionString'),
            'build': str(info.get('CFBundleVersion')), 'architecture': platform.machine(), 'header_sha256': header}


def compatible(manifest, source):
    return any(all(adapter.get(key) == value for key, value in source.items()) for adapter in manifest.get('adapters', []) if isinstance(adapter, dict))


def select_release(releases, source, download=fetch):
    candidates = []
    for release in releases:
        if not isinstance(release, dict):
            continue
        try:
            tag = release.get('tag_name', '')
            if release.get('draft') or not release.get('published_at') or not tag.startswith('v'):
                continue
            rank = version(tag)
            name = 'mark-' + tag[1:] + '-macos-arm64.zip'
            files = [asset(release, n) for n in (name, name + '.sha256', 'compatibility.json')]
            if all(files):
                candidates.append((rank, release, files))
        except (TypeError, UpdateError):
            continue
    for _, release, files in sorted(candidates, key=lambda row: row[0], reverse=True):
        raw = download(files[2]['browser_download_url'], 65536)
        verify_asset(raw, files[2])
        manifest = json.loads(raw)
        if not isinstance(manifest, dict):
            raise UpdateError('兼容性清单无效')
        if manifest.get('update_protocol') != 1 or manifest.get('release') != release['tag_name'][1:]:
            continue
        if compatible(manifest, source):
            return {'tag': release['tag_name'], 'version': manifest['release'], 'manifest': manifest,
                    'zip': files[0], 'checksum': files[1], 'release_url': 'https://github.com/' + REPO + '/releases/tag/' + release['tag_name']}
    return None


def current_version(manager, state):
    active = manager.read_json(state / 'state.json', {}).get('active', {})
    pid = active.get('package_id', '')
    if not re.fullmatch('[0-9a-f]{16}', pid):
        return None
    return manager.read_json(state / 'packages' / pid / 'compatibility.json', {}).get('release')


def active_source(manager, state):
    return manager.read_json(state / 'state.json', {}).get('active', {})


def active_matches_source(manager, state, source):
    active = active_source(manager, state)
    return bool(active and active.get('version') == source.get('version')
                and active.get('source_header_sha256') == source.get('header_sha256'))


def check(manager, app, state, force=False):
    source = identity(manager, app)
    current = current_version(manager, state)
    active = active_source(manager, state)
    source_current = active_matches_source(manager, state, source)
    cache = manager.read_json(state / 'update-check.json', {})
    lifetime = 900 if cache.get('status') == 'offline' else 86400
    if (not force and cache.get('source') == source and cache.get('current_version') == current
            and cache.get('active_source_header_sha256') == active.get('source_header_sha256')
            and time.time() - cache.get('checked_at', 0) < lifetime):
        return cache
    result = {'current_version': current, 'source': source, 'source_current': source_current,
              'active_client_version': active.get('version'), 'active_client_build': active.get('source_build'),
              'active_source_header_sha256': active.get('source_header_sha256'), 'checked_at': time.time()}
    try:
        releases = []
        for page in range(1, 4):
            rows = json.loads(fetch(API + '?per_page=100&page=' + str(page), 4 * 1024 * 1024))
            if not isinstance(rows, list):
                raise UpdateError('发布列表无效')
            releases.extend(rows)
            if len(rows) < 100:
                break
        candidate = select_release(releases, source)
        if not candidate:
            if current and not source_current:
                result.update(status='waiting_for_adapter', message='正式版已升级，适配尚未发布；当前 ChatGPT mark 可继续使用')
            else:
                result.update(status='no_compatible_release', message='暂未发现支持当前客户端的更新版本，现有副本可继续使用')
        elif current and version(candidate['version']) < version(current):
            result.update(status='waiting_for_adapter' if not source_current else 'up_to_date',
                          message='正式版已升级，适配尚未发布；当前 ChatGPT mark 可继续使用' if not source_current else '已是最新兼容版本')
        elif current and version(candidate['version']) == version(current) and source_current:
            result.update(status='up_to_date', message='已是最新兼容版本')
        else:
            rebuild = bool(current and version(candidate['version']) == version(current) and not source_current)
            offer = {**candidate, 'source': source, 'rebuild_for_client': rebuild,
                     'ticket': str(uuid.uuid4()), 'expires': time.time() + 86400}
            manager.atomic_json(state / 'update-offer.json', offer)
            result.update(status='available', version=candidate['version'], ticket=offer['ticket'],
                          release_url=candidate['release_url'], rebuild_for_client=rebuild,
                          message='当前正式客户端已有适配，可生成新版副本' if rebuild else '发现兼容更新')
    except (OSError, ValueError, KeyError, TypeError):
        result.update(status='offline', message='暂时无法检查更新，现有版本可继续使用；请稍后重试')
    manager.atomic_json(state / 'update-check.json', result)
    return result


def offer_for(manager, state, ticket):
    offer = manager.read_json(state / 'update-offer.json', {})
    if offer.get('ticket') != ticket or offer.get('expires', 0) < time.time():
        raise UpdateError('更新信息已过期，请重新检查更新')
    version(offer['version'])
    return offer


def extract_verified(data, destination):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        infos = archive.infolist()
        if len(infos) > 2000 or sum(i.file_size for i in infos) > 100 * 1024 * 1024:
            raise UpdateError('更新包解压大小异常')
        seen = set()
        for item in infos:
            path = PurePosixPath(item.filename)
            kind = stat.S_IFMT(item.external_attr >> 16)
            if ('\\' in item.filename or path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0] != 'mark'
                    or kind not in (0, stat.S_IFREG, stat.S_IFDIR) or item.flag_bits & 1):
                raise UpdateError('更新包含不安全路径或文件类型')
            key = item.filename.rstrip('/').casefold()
            if key in seen:
                raise UpdateError('更新包含重复路径')
            seen.add(key)
        archive.extractall(destination)
    root = destination / 'mark'
    expected = json.loads((root / 'SHA256SUMS.json').read_text())
    actual = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in root.rglob('*') if p.is_file() and p.relative_to(root).as_posix() != 'SHA256SUMS.json'}
    if not expected or expected != actual or not (root / 'mark.py').is_file():
        raise UpdateError('更新包文件校验失败')
    return root


def schedule(manager, app, state, ticket, accept=False):
    offer_for(manager, state, ticket)
    state.mkdir(parents=True, exist_ok=True)
    job = manager.read_json(state / 'update-job.json', {})
    if job.get('status') in ('scheduled', 'downloading', 'installing') and time.time() - job.get('started_at', 0) < 1800:
        raise UpdateError('另一个更新正在进行')
    result_file = state / ('update-' + uuid.uuid4().hex + '.json')
    log = result_file.with_suffix('.log')
    args = [manager.sys.executable, '-B', str(manager.ROOT / 'mark.py'), '--app', str(app), '--state-dir', str(state),
            'update', '--yes', '--ticket', ticket, '--deferred-result', str(result_file)]
    if accept:
        args.append('--accept-local-resign')
    job = {'status': 'scheduled', 'started_at': time.time(), 'result_file': str(result_file), 'log': str(log)}
    with log.open('x') as output:
        log.chmod(0o600)
        process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT, start_new_session=True, close_fds=True)
    manager.atomic_json(state / 'update-job.json', {**job, 'pid': process.pid})
    return {**job, 'message': '已安排更新；完成下载和构建后将重启客户端'}


def apply(manager, app, state, ticket, accept=False):
    offer = offer_for(manager, state, ticket)
    if identity(manager, app) != offer['source']:
        raise UpdateError('正式客户端已变化，请重新检查更新')
    current = current_version(manager, state)
    if current and version(offer['version']) < version(current):
        raise UpdateError('不会自动降级 mark；请等待当前版本适配新版客户端')
    if current and version(offer['version']) == version(current) and active_matches_source(manager, state, offer['source']):
        manager.atomic_json(state / 'update-job.json', {**manager.read_json(state / 'update-job.json', {}), 'status': 'complete', 'version': current})
        return {'status': 'up_to_date', 'message': '已是最新兼容版本'}
    job = manager.read_json(state / 'update-job.json', {})
    def progress(status, **extra):
        manager.atomic_json(state / 'update-job.json', {**job, 'status': status, **extra})
    try:
        progress('downloading')
        checksum = fetch(offer['checksum']['browser_download_url'], 1024)
        verify_asset(checksum, offer['checksum'])
        parts = checksum.decode('ascii').strip().split()
        if len(parts) != 2 or not re.fullmatch('[0-9a-f]{64}', parts[0]) or parts[1].lstrip('*') != offer['zip']['name']:
            raise UpdateError('发布包校验文件无效')
        data = fetch(offer['zip']['browser_download_url'], MAX_ZIP)
        verify_asset(data, offer['zip'])
        if hashlib.sha256(data).hexdigest() != parts[0]:
            raise UpdateError('下载校验失败，已保留当前版本')
        downloads = state / 'downloads'
        downloads.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='incoming-', dir=downloads) as temporary:
            root = extract_verified(data, Path(temporary))
            manifest = json.loads((root / 'compatibility.json').read_text())
            if manifest != offer['manifest'] or not compatible(manifest, identity(manager, app)):
                raise UpdateError('更新包兼容性与检查结果不一致')
            destination = downloads / (offer['tag'] + '-' + hashlib.sha256(data).hexdigest()[:12] + '-' + uuid.uuid4().hex[:8])
            root.rename(destination)
        progress('installing')
        args = ['/usr/bin/python3', '-B', str(destination / 'mark.py'), '--app', str(app), '--state-dir', str(state), 'upgrade', '--switch']
        if accept:
            args.append('--accept-local-resign')
        # The verified package performs one locked install/switch transaction.
        subprocess.run(args, check=True, timeout=900)
        progress('complete', version=offer['version'])
        return {'status': 'complete', 'version': offer['version'], 'message': '更新已完成'}
    except Exception as error:
        progress('error', message='更新未完成，已保留旧版本；可重试或通过启动器回退')
        raise UpdateError('更新未完成，当前收藏和旧版本保留，请重试或查看更新日志') from error
