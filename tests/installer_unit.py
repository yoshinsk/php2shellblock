#!/usr/bin/env python
# -*- coding: utf-8 -*-
# tests/installer_unit.py: 公開インストーラーの入力検査・退避・成功・自動復旧・競合拒否を一時ファイルで確認する。
from __future__ import print_function
import contextlib
import hashlib
import imp
import json
import os
import shutil
import signal
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
runtime = imp.load_source("install_runtime", ROOT + "/scripts/install-runtime.py")


@contextlib.contextmanager
def patched(**changes):
    original = {key: getattr(runtime, key) for key in changes}
    try:
        for key, value in changes.items():
            setattr(runtime, key, value)
        yield
    finally:
        for key, value in original.items():
            setattr(runtime, key, value)


class InputTests(unittest.TestCase):
    def test_loopback_urls(self):
        self.assertEqual(runtime.parse_url("https://127.0.0.1:50443/login.php").port, 50443)
        for url in ("http://example.com/", "file:///etc/passwd", "http://127.0.0.1/?save=1", "http://user:secret@127.0.0.1/", "http://127.0.0.1/#x"):
            with self.assertRaises(RuntimeError):
                runtime.parse_url(url)

    def test_module_directive(self):
        value, path = runtime.module_path("<IfModule prefork.c>\nLoadModule php5_module modules/libphp5.so\n</IfModule>\nLoadModule php5_module modules/libphp5-zts.so\n")
        self.assertEqual(value, "modules/libphp5.so")
        for config in ("", "LoadModule php5_module a/libphp5.so\nLoadModule php5_module b/libphp5.so\n"):
            with self.assertRaises(RuntimeError):
                runtime.module_path(config)

    def test_require_is_not_an_assert(self):
        with self.assertRaises(RuntimeError):
            runtime.require(False, "guard")


@unittest.skipUnless(hasattr(os, "geteuid") and os.geteuid() == 0, "Transaction file ownership checks require root")
class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="php2shellblock-unit-")
        self.payload = self.root + "/payload"
        os.mkdir(self.payload)
        self.original = self.root + "/original/libphp5.so"
        os.mkdir(os.path.dirname(self.original))
        runtime.write(self.original, "original fixture module")
        runtime.write(self.payload + "/libphp5.so", "candidate fixture module")
        self.candidate_sha = runtime.digest(self.payload + "/libphp5.so")
        self.original_sha = runtime.digest(self.original)
        owner = self
        class FakeSystem(runtime.System):
            config = owner.root + "/10-php.conf"
            base = owner.root + "/state"
            installed = owner.root + "/installed/libphp5.so"
            reload_count = 0
            def services(self):
                return {"httpd": 4321, "asterisk": 0, "mariadb": 0}
            def pid(self, name):
                return self.services()[name]
            def syntax(self):
                pass
            def reload(self):
                self.reload_count += 1
        self.system = FakeSystem()
        runtime.write(self.system.config, "LoadModule php5_module " + self.original + "\n")
        os.chmod(self.system.config, 0o644)
        self.config = runtime.read(self.system.config)
        class FakeInstaller(runtime.Installer):
            def preflight(inner):
                return ({"version": "test"}, owner.payload + "/libphp5.so", owner.config, owner.original,
                        owner.original, owner.system.services(), owner.original_sha)
        self.instance = FakeInstaller(self.payload, self.system)
        self.urls = ["http://127.0.0.1/login.php"]
        self.baseline = {self.urls[0]: {"status": 200, "bytes": 2, "sha256": "fixture"}}
        self.signals = {key: signal.getsignal(key) for key in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}

    def tearDown(self):
        for key, handler in self.signals.items():
            signal.signal(key, handler)
        shutil.rmtree(self.root)

    @contextlib.contextmanager
    def environment(self, unhealthy=False):
        owner = self
        class FakeChecker(object):
            def __init__(self, *args):
                pass
            def run(self):
                return {"include_path": ".:/usr/share/php", "graceful_and_rollback": True}
        def health(urls, host_header=None):
            if unhealthy and owner.system.installed in runtime.read(owner.system.config):
                raise RuntimeError("Injected post-apply failure")
            return owner.baseline
        with patched(Checker=FakeChecker, health=health, command=lambda args: "", wait_maps=lambda *args: [4321, 4322],
                     mapped=lambda pid: [runtime.module_path(runtime.read(owner.system.config))[1]], apache_pids=lambda pid: [4321, 4322],
                     CANDIDATE_SHA=self.candidate_sha, ORIGINAL_SHA=self.original_sha):
            yield

    def test_check_never_changes_service_or_config(self):
        with self.environment():
            self.assertEqual(self.instance.install(self.urls, check=True)["result"], "checks_passed_no_service_changes")
        self.assertEqual(runtime.read(self.system.config), self.config)
        self.assertEqual(self.system.reload_count, 0)
        self.assertFalse(os.path.exists(self.system.base))

    def test_apply_and_explicit_rollback(self):
        with self.environment():
            result = self.instance.install(self.urls)
            self.assertEqual(result["result"], "applied")
            self.assertEqual(self.system.reload_count, 1)
            backup = result["backup"]
            self.assertEqual(os.stat(backup).st_mode & 0o777, 0o700)
            self.assertEqual(os.stat(backup + "/rollback.sh").st_mode & 0o777, 0o700)
            self.assertEqual(self.instance.rollback(backup)["result"], "rolled_back")
            self.assertEqual(runtime.read(self.system.config), self.config)
            self.assertEqual(self.system.reload_count, 2)

    def test_rollback_uses_selected_interpreter(self):
        with self.environment():
            result = self.instance.install(self.urls)
        expected = os.path.realpath(sys.executable)
        state = json.loads(runtime.read(result["backup"] + "/state.json"))
        self.assertEqual(state["python_executable"], expected)
        self.assertIn("exec " + runtime.shell_quote(expected) + " -E ", runtime.read(result["backup"] + "/rollback.sh"))

    def test_failed_health_automatically_rolls_back(self):
        with self.environment(unhealthy=True):
            with self.assertRaises(RuntimeError):
                self.instance.install(self.urls)
        self.assertEqual(runtime.read(self.system.config), self.config)
        latest = json.loads(runtime.read(self.system.base + "/latest.json"))["backup"]
        self.assertEqual(json.loads(runtime.read(latest + "/state.json"))["result"], "rolled_back")

    def test_rollback_refuses_unrelated_config_change(self):
        with self.environment():
            result = self.instance.install(self.urls)
            runtime.write(self.system.config, "# changed independently\n")
            with self.assertRaises(RuntimeError):
                self.instance.rollback(result["backup"])
        self.assertEqual(runtime.read(self.system.config), "# changed independently\n")

    def test_rollback_refuses_changed_backup(self):
        with self.environment():
            result = self.instance.install(self.urls)
            runtime.write(result["backup"] + "/original.conf", "tampered backup")
            with self.assertRaises(RuntimeError):
                self.instance.rollback(result["backup"])

    def test_rollback_refuses_foreign_directory(self):
        with self.assertRaises(RuntimeError):
            self.instance.rollback(self.root)


if __name__ == "__main__":
    unittest.main(verbosity=2)
