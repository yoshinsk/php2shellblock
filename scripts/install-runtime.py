#!/usr/bin/env python
# -*- coding: utf-8 -*-
# scripts/install-runtime.py: 対応環境を限定し、隔離試験・退避・graceful適用・復旧を行う公開用インストーラー。
from __future__ import print_function
import argparse
import errno
import fcntl
import hashlib
import json
import os
import platform
import pwd
import re
import shutil
import signal
import socket
import ssl
import subprocess
import sys
import tempfile
import time
try:
    from shlex import quote as shell_quote
except ImportError:
    from pipes import quote as shell_quote
try:
    import httplib as http
    from urlparse import urlsplit
except ImportError:
    import http.client as http
    from urllib.parse import urlsplit

CANDIDATE_SHA = "f83e471ca70d691b06f2f8957204d6a8e37821a7bb31b9e864e06d8497abae23"
PREVIOUS_SHA = "2b343438ad940ce1d5429f27e7b51ad2f16078687a3c3caa62b67502f4a2c315"
ORIGINAL_SHA = "eeefbd609a2db685b419fb222c4863c598398b57ec08d7246ac5d49f2ed07641"
ORIGINAL_SHA_18 = "35202da3529ffda4e585a1c443bdce86e372d4aced99053f023b31f219e4b8ae"
ORIGINAL_SHA_17 = "83cc21b009dd32360f8091f4ec131f12535a8b5c5fc1433c24b195e3ba89957a"
RPM_19 = "5.4.45-19.el7.remi.x86_64"
RPM_18 = "5.4.45-18.el7.remi.x86_64"
RPM_17 = "5.4.45-17.el7.remi.x86_64"


def require(condition, message):
    """python -Oでも検査が省略されないよう、assertを使用しない。"""
    if not condition:
        raise RuntimeError(message)


def select_profile(manifest, installed):
    """RPM三種を同一版で照合し、実測済み元モジュールと依存ライブラリだけを許可する。"""
    names = ("php", "php-common", "php-cli")
    if all(installed.get(name) == name + "-" + RPM_19 for name in names):
        return manifest["libraries"], (ORIGINAL_SHA, PREVIOUS_SHA, CANDIDATE_SHA)
    if all(installed.get(name) == name + "-" + RPM_18 for name in names):
        profile = manifest.get("profiles", {}).get("remi-5.4.45-18-el7", {})
        require(profile.get("rpm_release") == RPM_18 and profile.get("original_module_sha256") == ORIGINAL_SHA_18,
                "Invalid Remi 5.4.45-18 profile")
        return profile["libraries"], (ORIGINAL_SHA_18, CANDIDATE_SHA)
    if all(installed.get(name) == name + "-" + RPM_17 for name in names):
        profile = manifest.get("profiles", {}).get("remi-5.4.45-17-el7", {})
        require(profile.get("rpm_release") == RPM_17 and profile.get("original_module_sha256") == ORIGINAL_SHA_17,
                "Invalid Remi 5.4.45-17 profile")
        return profile["libraries"], (ORIGINAL_SHA_17, CANDIDATE_SHA)
    raise RuntimeError("Unsupported PHP RPM set: " + ", ".join(installed.get(name, "missing") for name in names))


def expected_ini_additions(original_sha):
    """未修正モジュールから切り替える場合だけ、追加したINI項目を許可する。"""
    return set(["max_multipart_body_parts"]) if original_sha in (ORIGINAL_SHA, ORIGINAL_SHA_18, ORIGINAL_SHA_17) else set()


def digest(path):
    value = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def read(path):
    with open(path) as stream:
        return stream.read()


def write(path, content):
    with open(path, "w") as stream:
        stream.write(content)


def save_json(path, data):
    write(path + ".tmp", json.dumps(data, indent=2, sort_keys=True) + "\n")
    os.rename(path + ".tmp", path)


def command(args, optional=False):
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               env=dict(os.environ, LC_ALL="C", PYTHONOPTIMIZE=""))
    output, error = process.communicate()
    require(optional or process.returncode == 0, "Command failed: " + " ".join(args) + ": " + error.decode("utf-8", "replace")[:600])
    return output.decode("utf-8", "replace").strip()


def mapped(pid):
    try:
        return sorted(set(line.split()[-1] for line in read("/proc/%s/maps" % pid).splitlines() if "libphp5.so" in line))
    except IOError:
        return []


def apache_pids(parent):
    """指定したApache親と直下のpreforkワーカーだけを対象にする。"""
    result = [parent]
    for entry in os.listdir("/proc"):
        if entry.isdigit():
            try:
                fields = read("/proc/" + entry + "/stat").split()
                if fields[1] == "(httpd)" and fields[2] != "Z" and int(fields[3]) == parent:
                    result.append(int(entry))
            except IOError:
                pass
    return result


def wait_maps(parent, module, seconds=120):
    deadline = time.time() + seconds
    while time.time() < deadline:
        pids = apache_pids(parent)
        if len(pids) > 1 and all(mapped(pid) == [module] for pid in pids):
            return pids
        time.sleep(0.2)
    raise RuntimeError("Apache worker generation did not switch within the deadline")


def parse_url(value):
    parsed = urlsplit(value)
    require(parsed.scheme in ("http", "https") and parsed.hostname == "127.0.0.1", "Use an http(s)://127.0.0.1/... health URL; use --host-header for a local virtual host")
    require(not parsed.username and not parsed.password and not parsed.query and not parsed.fragment, "Health URL credentials, query and fragment are unsupported")
    require(not any(char in value for char in "\r\n"), "Invalid health URL")
    return parsed


def health(urls, host_header=None):
    """指定画面をGETし、本文は保存せず200・サイズ・ハッシュだけを比較する。"""
    result = {}
    for value in urls:
        parsed = parse_url(value)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        connection = (http.HTTPConnection("127.0.0.1", port, timeout=8) if parsed.scheme == "http" else
                      http.HTTPSConnection("127.0.0.1", port, timeout=8, context=ssl._create_unverified_context()))
        try:
            headers = {"User-Agent": "php2shellblock-installer"}
            if host_header:
                headers["Host"] = host_header
            connection.request("GET", parsed.path or "/", headers=headers)
            response = connection.getresponse()
            body = response.read(2 * 1024 * 1024 + 1)
            require(response.status == 200 and 0 < len(body) <= 2 * 1024 * 1024, "Health page must return a nonempty HTTP 200 response under 2 MiB: " + value)
            require(b"Fatal error" not in body and b"Parse error" not in body, "PHP error in health response")
            result[value] = {"status": response.status, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}
        finally:
            connection.close()
    return result


def atomic_copy(source, target):
    """既存ファイルの所有者・モードを維持して、同じディレクトリで原子的に交換する。"""
    info = os.stat(target)
    handle, temporary = tempfile.mkstemp(prefix=".php2shellblock-", dir=os.path.dirname(target))
    os.close(handle)
    try:
        shutil.copy2(source, temporary)
        os.chown(temporary, info.st_uid, info.st_gid)
        os.chmod(temporary, info.st_mode & 0o777)
        os.rename(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class System(object):
    """サービスへの書込み操作は、このクラスのApache reloadだけに限定する。"""
    config = "/etc/httpd/conf.modules.d/10-php.conf"
    base = "/var/lib/php2shellblock"
    installed = "/usr/local/lib64/php2shellblock/php54-" + CANDIDATE_SHA[:12] + "/libphp5.so"

    def pid(self, name):
        output = command(["systemctl", "show", name, "-p", "MainPID"], optional=True)
        match = re.search(r"^MainPID=(\d+)$", output, re.M)
        return int(match.group(1)) if match else 0

    def services(self):
        return {name: self.pid(name) for name in ("httpd", "asterisk", "mariadb")}

    def syntax(self):
        command(["httpd", "-t"])

    def reload(self):
        command(["systemctl", "reload", "httpd"])


def module_path(config):
    matches = re.findall(r"(?m)^\s*LoadModule\s+php5_module\s+(\S*libphp5\.so)\s*$", config)
    require(len(matches) == 1, "Expected exactly one NTS libphp5.so LoadModule directive")
    value = matches[0]
    return value, os.path.realpath(value if value.startswith("/") else "/etc/httpd/" + value)


class Checker(object):
    """公開リスナーやアプリDBを作らず、明示したモジュールだけを別Apacheで比較する。"""
    def __init__(self, original, candidate):
        self.original, self.candidate = original, candidate
        self.root = None
        self.process = None

    def metadata(self):
        connection = http.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            connection.request("GET", "/probe.php")
            response = connection.getresponse()
            require(response.status == 200, "Isolated PHP metadata request failed")
            return json.loads(response.read())
        finally:
            connection.close()

    def select(self, path, include_path=None):
        content = 'LoadModule php5_module "' + path + '"\n'
        if include_path is not None:
            require(not any(char in include_path for char in '"\r\n\\'), "Unsupported include_path characters")
            content += 'php_value include_path "' + include_path + '"\n'
        write(self.root + "/module.conf", content)

    def run(self):
        self.root = tempfile.mkdtemp(prefix="php2shellblock-check-", dir="/opt")
        os.chmod(self.root, 0o755)
        try:
            account = pwd.getpwnam("apache")
            os.mkdir(self.root + "/sessions", 0o700)
            os.chown(self.root + "/sessions", account.pw_uid, account.pw_gid)
            probe = socket.socket()
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
            probe.close()
            self.select(self.original)
            write(self.root + "/probe.php", '''<?php
// scripts/install-runtime.py: 隔離Apacheだけに配置するAPI・INI確認fixture。
$extensions = get_loaded_extensions(); sort($extensions);
$functions = get_defined_functions(); sort($functions['internal']);
header('Content-Type: application/json');
echo json_encode(array('version'=>PHP_VERSION, 'extensions'=>$extensions,
    'functions'=>$functions['internal'], 'ini'=>ini_get_all(NULL, false)));
''')
            os.chmod(self.root + "/probe.php", 0o644)
            config = '''ServerRoot /etc/httpd
LoadModule mpm_prefork_module modules/mod_mpm_prefork.so
LoadModule unixd_module modules/mod_unixd.so
LoadModule authz_core_module modules/mod_authz_core.so
LoadModule authz_host_module modules/mod_authz_host.so
Include "ROOT/module.conf"
Listen 127.0.0.1:PORT
ServerName localhost
User apache
Group apache
StartServers 1
MinSpareServers 1
MaxSpareServers 2
ServerLimit 2
MaxRequestWorkers 2
PidFile "ROOT/httpd.pid"
ErrorLog "ROOT/error.log"
DocumentRoot "ROOT"
php_admin_value session.save_path "ROOT/sessions"
<Directory "ROOT">
  Require ip 127.0.0.1
  AllowOverride None
  <FilesMatch "\\.php$">
    SetHandler application/x-httpd-php
  </FilesMatch>
</Directory>
'''.replace("ROOT", self.root).replace("PORT", str(self.port))
            write(self.root + "/httpd.conf", config)
            command(["httpd", "-t", "-f", self.root + "/httpd.conf"])
            self.process = subprocess.Popen(["httpd", "-DFOREGROUND", "-f", self.root + "/httpd.conf"], preexec_fn=os.setsid,
                                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            for attempt in range(50):
                try:
                    before = self.metadata()
                    break
                except (socket.error, http.HTTPException):
                    require(self.process.poll() is None, "Isolated Apache stopped")
                    time.sleep(0.1)
            else:
                raise RuntimeError("Isolated Apache did not start")
            wait_maps(self.process.pid, self.original, 15)
            include_path = before["ini"]["include_path"]
            self.select(self.candidate, include_path)
            command(["httpd", "-t", "-f", self.root + "/httpd.conf"])
            os.kill(self.process.pid, signal.SIGUSR1)
            wait_maps(self.process.pid, self.candidate, 15)
            after = self.metadata()
            require(before["version"] == after["version"] == "5.4.45", "PHP version mismatch")
            require(before["extensions"] == after["extensions"], "PHP extension list changed")
            require(before["functions"] == after["functions"], "Internal PHP function list changed")
            require(all(after["ini"].get(key) == value for key, value in before["ini"].items()), "Existing PHP INI values changed")
            # v0.1.1 からの更新では、このINI項目はすでに存在する。
            expected_ini = expected_ini_additions(digest(self.original))
            require(set(after["ini"]) - set(before["ini"]) == expected_ini, "Unexpected new INI entries")
            self.select(self.original)
            os.kill(self.process.pid, signal.SIGUSR1)
            wait_maps(self.process.pid, self.original, 15)
            require(self.metadata() == before, "Isolated rollback metadata mismatch")
            return {"include_path": include_path, "extensions": len(before["extensions"]),
                    "functions": len(before["functions"]), "graceful_and_rollback": True}
        finally:
            if self.process is not None:
                try:
                    os.killpg(self.process.pid, signal.SIGTERM)
                except OSError as error:
                    if error.errno != errno.ESRCH:
                        raise
                for attempt in range(30):
                    if self.process.poll() is not None:
                        break
                    time.sleep(0.1)
                else:
                    os.killpg(self.process.pid, signal.SIGKILL)
                self.process.communicate()
            if self.root:
                shutil.rmtree(self.root)


class Installer(object):
    def __init__(self, payload, system=None):
        self.payload = payload
        self.system = system or System()

    def preflight(self):
        manifest = json.loads(read(self.payload + "/manifest.json"))
        require(platform.machine() == "x86_64" and "CentOS Linux release 7." in read("/etc/centos-release"), "Only CentOS 7 x86_64 is supported")
        for path in ("/opt", "/var", "/usr/local"):
            space = os.statvfs(path)
            require(space.f_bavail * space.f_frsize >= 100 * 1024 * 1024, "At least 100 MiB free space is required: " + path)
        require(command(["getenforce"]) in ("Disabled", "Permissive"), "SELinux Enforcing is not supported by this release")
        names = ("php", "php-common", "php-cli")
        libraries, allowed_modules = select_profile(manifest, {name: command(["rpm", "-q", name]) for name in names})
        require("mpm_prefork_module" in command(["httpd", "-M"]), "Apache prefork/mod_php is required")
        require("Apache/2.4.6" in command(["httpd", "-v"]), "Unsupported Apache version")
        for path, expected in libraries.items():
            require(digest(path) == expected, "Untested dependency library: " + path)
        for path, expected in manifest["files"].items():
            require(not path.startswith("/") and ".." not in path.split("/"), "Invalid manifest member")
            require(digest(self.payload + "/" + path) == expected, "Payload hash mismatch: " + path)
        candidate = self.payload + "/libphp5.so"
        require(digest(candidate) == CANDIDATE_SHA, "Unexpected candidate module")
        require("not found" not in command(["ldd", candidate]), "Missing module dependency")
        require(not os.path.islink(self.system.config), "Symlinked Apache PHP config is unsupported")
        config = read(self.system.config)
        directive, original = module_path(config)
        services = self.system.services()
        require(services["httpd"] > 0, "Apache must already be running")
        require(mapped(services["httpd"]) == [original], "Configured and active PHP modules differ")
        current = digest(original)
        require(current in allowed_modules, "Unsupported current PHP module; nothing changed")
        wait_maps(services["httpd"], original, 15)
        self.system.syntax()
        return manifest, candidate, config, directive, original, services, current

    def install(self, urls, host_header=None, check=False):
        print("Checking supported environment and payload...")
        sys.stdout.flush()
        manifest, candidate, config, directive, original, services, current = self.preflight()
        require(bool(urls), "Specify at least one stable, read-only --health-url")
        baseline = health(urls, host_header)
        require(health(urls, host_header) == baseline, "Health response changes between requests; select a stable page")
        if current == CANDIDATE_SHA:
            wait_maps(services["httpd"], original, 15)
            return {"result": "already_applied_no_changes", "module_sha256": current, "http": baseline}
        print("Comparing PHP APIs/INI and graceful rollback in an isolated Apache...")
        compatibility = Checker(original, candidate).run()
        print("Running isolated POST/session/upload/OOM recovery fixtures...")
        command(["nice", "-n", "15", sys.executable, "-E", self.payload + "/tests/apache_http.py", candidate, "--runtime", "--installed-extensions"])
        require(read(self.system.config) == config and self.system.services() == services, "Service/config changed concurrently")
        require(digest(original) == current and digest(candidate) == CANDIDATE_SHA, "PHP binary changed during preflight")
        require(health(urls, host_header) == baseline, "Health response changed during preflight")
        if check:
            return {"result": "checks_passed_no_service_changes", "compatibility": compatibility, "http": baseline}
        directory = self.prepare(manifest, config, directive, original, services, baseline, urls, host_header, compatibility)
        state = json.loads(read(directory + "/state.json"))
        print("Rollback prepared: sh " + directory + "/rollback.sh")
        sys.stdout.flush()
        try:
            require(digest(self.system.config) == state["original_config_sha256"], "Configuration changed before activation")
            atomic_copy(directory + "/new.conf", self.system.config)
            self.system.syntax()
            self.system.reload()
            wait_maps(services["httpd"], self.system.installed)
            for attempt in range(3):
                require(health(urls, host_header) == baseline, "Post-apply health response mismatch")
                time.sleep(0.3)
            require(self.system.services() == services, "A service PID changed during application")
            state.update(result="applied", completed_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"))
            save_json(directory + "/state.json", state)
        except BaseException:
            # 復旧中の二重割込みで設定だけが戻る状態を避ける。SIGKILL・電源断は手動復旧対象。
            for value in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
                signal.signal(value, signal.SIG_IGN)
            print("Application failed; attempting rollback...")
            self.rollback(directory)
            raise
        return {"result": "applied", "backup": directory, "module_sha256": CANDIDATE_SHA,
                "compatibility": compatibility, "http": baseline, "attack_reproduction": "not_performed_during_install"}

    def prepare(self, manifest, config, directive, original, services, baseline, urls, host_header, compatibility):
        """元RPMは上書きせず、復旧に必要なファイルをネットワーク不要の形で先に保存する。"""
        interpreter = os.path.realpath(sys.executable)
        require(os.path.isfile(interpreter) and os.access(interpreter, os.X_OK), "Selected Python interpreter is not executable")
        if not os.path.exists(self.system.base):
            os.mkdir(self.system.base, 0o700)
        require(not os.path.islink(self.system.base) and os.stat(self.system.base).st_uid == 0 and os.stat(self.system.base).st_mode & 0o077 == 0, "State directory must be root-owned and private")
        directory = tempfile.mkdtemp(prefix=time.strftime("%Y%m%d-%H%M%S-"), dir=self.system.base)
        shutil.copy2(self.system.config, directory + "/original.conf")
        shutil.copy2(original, directory + "/libphp5-original.so")
        shutil.copy2(os.path.realpath(__file__), directory + "/rollback.py")
        parent = os.path.dirname(self.system.installed)
        if not os.path.isdir(parent):
            os.makedirs(parent, 0o755)
        if os.path.exists(self.system.installed):
            require(digest(self.system.installed) == CANDIDATE_SHA, "Installed versioned module has changed")
        else:
            shutil.copy2(self.payload + "/libphp5.so", self.system.installed)
            os.chown(self.system.installed, 0, 0)
            os.chmod(self.system.installed, 0o755)
        include_path = compatibility["include_path"]
        new = config.replace(directive, self.system.installed, 1)
        # 旧版の設定には同じ指定があるため、更新時に重複させない。
        if not re.search(r'(?m)^[ \t]*php_value[ \t]+include_path[ \t]+', new):
            new += '\n# php2shellblock: preserve the existing PHP include_path.\nphp_value include_path "' + include_path + '"\n'
        write(directory + "/new.conf", new)
        state = {"version": manifest["version"], "result": "prepared", "config": self.system.config,
                 "original_module": original, "original_module_sha256": digest(original),
                 "original_config_sha256": digest(directory + "/original.conf"), "new_config_sha256": digest(directory + "/new.conf"),
                 "installed_module": self.system.installed, "services_before": services, "http_before": baseline,
                 "health_urls": urls, "host_header": host_header, "python_executable": interpreter, "attack_reproduction": "not_performed_during_install"}
        save_json(directory + "/state.json", state)
        write(directory + "/rollback.sh", "#!/bin/sh\n# Network-independent rollback using the selected Python interpreter.\nset -eu\nexec " + shell_quote(interpreter) + " -E " + shell_quote(directory + "/rollback.py") + " --rollback " + shell_quote(directory) + "\n")
        os.chmod(directory + "/rollback.sh", 0o700)
        save_json(self.system.base + "/latest.json", {"backup": directory})
        return directory

    def rollback(self, directory):
        directory = os.path.realpath(directory)
        require(directory.startswith(os.path.realpath(self.system.base) + "/"), "Rollback directory is outside the state directory")
        require(os.stat(directory).st_uid == 0 and os.stat(directory).st_mode & 0o077 == 0, "Unsafe rollback directory ownership/mode")
        state = json.loads(read(directory + "/state.json"))
        require(state["config"] == self.system.config, "Rollback belongs to another Apache configuration")
        require(digest(directory + "/original.conf") == state["original_config_sha256"], "Backup config changed")
        require(digest(directory + "/libphp5-original.so") == state["original_module_sha256"], "Backup module changed")
        require(digest(state["original_module"]) == state["original_module_sha256"], "Original RPM module changed independently")
        require(digest(self.system.config) in (state["original_config_sha256"], state["new_config_sha256"]), "Configuration changed independently; refusing overwrite")
        parent = self.system.pid("httpd")
        if digest(self.system.config) == state["original_config_sha256"] and all(mapped(pid) == [state["original_module"]] for pid in apache_pids(parent)):
            return {"result": "already_rolled_back"}
        atomic_copy(directory + "/original.conf", self.system.config)
        self.system.syntax()
        self.system.reload()
        wait_maps(parent, state["original_module"])
        require(health(state["health_urls"], state["host_header"]) == state["http_before"], "Rollback HTTP response mismatch")
        state["result"] = "rolled_back"
        save_json(directory + "/state.json", state)
        return {"result": "rolled_back", "backup": directory}


def main():
    parser = argparse.ArgumentParser(description="PHP 5.4.45/EL7/Remi/mod_php installer; tested crash path, RCE unverified")
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--check", action="store_true")
    modes.add_argument("--apply", action="store_true")
    modes.add_argument("--status", action="store_true")
    modes.add_argument("--rollback", metavar="BACKUP_DIRECTORY")
    parser.add_argument("--payload", default=os.path.dirname(os.path.realpath(__file__)))
    parser.add_argument("--health-url", action="append", default=[])
    parser.add_argument("--host-header")
    args = parser.parse_args()
    require(os.geteuid() == 0, "Run with sudo/root")
    require(not args.host_header or re.match(r"^[A-Za-z0-9.-]+(?::[0-9]+)?$", args.host_header), "Invalid Host header")
    for value in args.health_url:
        parse_url(value)
    def interrupted(signum, frame):
        raise KeyboardInterrupt("Interrupted by signal " + str(signum))
    for value in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        signal.signal(value, interrupted)
    # 別のインストーラーが適用中なら待たずに終了し、同時変更を防ぐ。
    lock = os.open("/run/lock/php2shellblock.lock", os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    instance = Installer(os.path.realpath(args.payload))
    if args.rollback:
        directory = args.rollback
        if directory == "latest":
            latest = instance.system.base + "/latest.json"
            require(os.path.isfile(latest), "No rollback record from this installer; use your original deployment backup")
            directory = json.loads(read(latest))["backup"]
        result = instance.rollback(directory)
    elif args.status:
        pid = instance.system.pid("httpd")
        paths = mapped(pid)
        result = {"apache_pid": pid, "mapped_modules": paths,
                  "candidate_active": len(paths) == 1 and digest(paths[0]) == CANDIDATE_SHA and
                  all(mapped(item) == paths for item in apache_pids(pid))}
        latest = instance.system.base + "/latest.json"
        if os.path.isfile(latest):
            result["latest"] = json.loads(read(latest))
    else:
        result = instance.install(args.health_url, args.host_header, args.check)
    print(json.dumps(result, indent=2, sort_keys=True))
    os.close(lock)


if __name__ == "__main__":
    try:
        main()
    except (Exception, KeyboardInterrupt) as error:
        print("ERROR: " + str(error), file=sys.stderr)
        sys.exit(1)
