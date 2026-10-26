#!/usr/bin/env python
# -*- coding: utf-8 -*-
# tests/installer_integration.py: 本番サービスを操作せず、別Apacheで配布エンジンの適用・復旧・障害時復旧を実行する。
from __future__ import print_function
import imp
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time

payload = os.path.realpath(sys.argv[1])
runtime = imp.load_source("install_runtime", payload + "/install-runtime.py")


def main():
    runtime.require(os.geteuid() == 0, "root required")
    production = runtime.System().services()
    root = tempfile.mkdtemp(prefix="php2shellblock-integration-", dir="/opt")
    os.chmod(root, 0o755)
    process = None
    try:
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        os.mkdir(root + "/www", 0o755)
        os.chmod(root + "/www", 0o755)
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
DocumentRoot "ROOT/www"
<Directory "ROOT/www">
 Require ip 127.0.0.1
 <FilesMatch "\\.php$">
  SetHandler application/x-httpd-php
 </FilesMatch>
</Directory>
'''.replace("ROOT", root).replace("PORT", str(port))
        runtime.write(root + "/httpd.conf", config)
        runtime.write(root + "/module.conf", "LoadModule php5_module /usr/lib64/httpd/modules/libphp5.so\n")
        runtime.write(root + "/www/health.php", "<?php echo 'OK '.PHP_VERSION;\n")
        os.chmod(root + "/www/health.php", 0o644)
        process = subprocess.Popen(["httpd", "-DFOREGROUND", "-f", root + "/httpd.conf"], preexec_fn=os.setsid)
        target = ["http://127.0.0.1:" + str(port) + "/health.php"]
        for attempt in range(50):
            try:
                runtime.health(target)
                break
            except socket.error:
                runtime.require(process.poll() is None, "Test Apache exited")
                time.sleep(0.1)
        else:
            raise RuntimeError("Test Apache did not start")
        class IsolatedSystem(runtime.System):
            config = root + "/module.conf"
            base = root + "/backups"
            installed = root + "/candidate/libphp5.so"
            def pid(self, name):
                return process.pid if name == "httpd" else super(IsolatedSystem, self).pid(name)
            def syntax(self):
                runtime.command(["httpd", "-t", "-f", root + "/httpd.conf"])
            def reload(self):
                # このテストで作成したApacheだけにシグナルを送り、systemctl reloadは呼ばない。
                os.kill(process.pid, signal.SIGUSR1)
        system = IsolatedSystem()
        instance = runtime.Installer(payload, system)
        result = instance.install(target, check=True)
        runtime.require(result["result"] == "checks_passed_no_service_changes", "Check mode failed")
        result = instance.install(target)
        runtime.require(result["result"] == "applied", "Apply mode failed")
        runtime.require(instance.install(target)["result"] == "already_applied_no_changes", "Repeat application was not idempotent")
        runtime.require(instance.rollback(result["backup"])["result"] == "rolled_back", "Explicit rollback failed")
        # 実HTTP応答が候補だけで変わるfixtureを使い、自動復旧を発火させる。
        runtime.write(root + "/www/health.php", "<?php echo ini_get('max_multipart_body_parts') === false ? 'OK '.PHP_VERSION : 'INTENTIONAL_TEST_FAILURE';\n")
        failed = False
        try:
            instance.install(target)
        except RuntimeError:
            failed = True
        runtime.require(failed, "Post-apply failure was not detected")
        runtime.wait_maps(process.pid, "/usr/lib64/httpd/modules/libphp5.so", 15)
        runtime.require(runtime.health(target)[target[0]]["bytes"] == 9, "Automatic rollback did not restore the response")
        runtime.require(runtime.System().services() == production, "Production service PID changed")
        print("PASS: isolated check/apply/idempotence/rollback/failed-health rollback; production PIDs unchanged")
    finally:
        if process is not None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except OSError:
                pass
            for attempt in range(30):
                if process.poll() is not None:
                    break
                time.sleep(0.1)
            else:
                os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        shutil.rmtree(root)


if __name__ == "__main__":
    main()
