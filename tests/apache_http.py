#!/usr/bin/env python
# -*- coding: utf-8 -*-
# tests/apache_http.py: ループバック専用の独立Apacheでワーカー終了と補充を検証する。
try:
    import http.client as httpclient
except ImportError:
    import httplib as httpclient
import json
import os
import pwd
import shutil
import socket
import subprocess
import sys
import tempfile
import time


connection = None


def request(method="GET", body=None, headers=None):
    """Keep-Alive接続を再利用し、異常終了時だけ接続を作り直す。"""
    global connection
    if connection is None:
        connection = httpclient.HTTPConnection("127.0.0.1", 18081, timeout=1)
    request_headers = {"Cookie": "PHPSESSID=php2shelltest"}
    request_headers.update(headers or {})
    try:
        connection.request(method, "/index.php", body, request_headers)
        response = connection.getresponse()
        return response.status, response.read()
    except Exception:
        connection.close()
        connection = None
        raise


def write_text(path, content):
    """Python 2.7にも対応し、専用設定だけを書き込む。"""
    with open(path, "w") as stream:
        stream.write(content)
    # 公開インストーラーのumask 077下でも、Apache子が合成fixtureを読めるよう明示する。
    os.chmod(path, 0o644)


def main():
    """既存httpdを操作せず、専用設定・PID・プロセスだけを作成して終了する。"""
    module = os.path.realpath(sys.argv[1])
    assert os.path.isfile(module), "module missing"
    runtime = len(sys.argv) > 2 and sys.argv[2] in ("--runtime", "--cgi")
    cgi = len(sys.argv) > 2 and sys.argv[2] == "--cgi"
    shared_json = "--shared-json" in sys.argv[2:]
    installed_extensions = "--installed-extensions" in sys.argv[2:]
    probe = socket.socket()
    probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        probe.bind(("127.0.0.1", 18081))
    finally:
        probe.close()
    temp = tempfile.mkdtemp(prefix="php2shell-http-", dir="/opt")
    try:
        root = temp
        os.chmod(root, 0o755)
        sessions = os.path.join(root, "sessions")
        os.mkdir(sessions, 0o700)
        account = pwd.getpwnam("apache")
        os.chown(sessions, account.pw_uid, account.pw_gid)
        write_text(os.path.join(root, "php.ini"),
            ("extension=/usr/lib64/php/modules/json.so\n" if shared_json or not runtime else "")
            + ("" if runtime else "extension=" + str(module) + "\n") + "memory_limit=16M\n"
            "session.save_path=" + sessions + "\nsession.upload_progress.cleanup=0\n"
            + "session.upload_progress.enabled=" + ("1" if runtime else "0") + "\n"
            + "max_multipart_body_parts=4\ndisplay_errors=0\nlog_errors=1\n"
        )
        # 外部入力は固定のテスト分岐に限定し、任意コード実行機能は設けない。
        write_text(os.path.join(root, "index.php"), '''<?php
// tests/apache_http.pyの隔離fixture: PID・拡張状態・POST解析とfatalを確認する。
if (isset($_POST['mode']) && $_POST['mode'] === 'oom') {
    file_put_contents(ini_get('session.save_path').'/oom-instance',
        json_encode(array('pid'=>getmypid(), 'stat'=>file_get_contents('/proc/self/stat'))));
    $x = str_repeat('a', 32 * 1024 * 1024);
}
if (isset($_POST['mode']) && $_POST['mode'] === 'fatal') {
    set_error_handler(function() { return false; });
    undefined_function_for_test();
}
if (isset($_POST['mode']) && $_POST['mode'] === 'parse') {
    eval('invalid syntax !!!');
}
if (isset($_POST['mode']) && $_POST['mode'] === 'shutdown_warning') {
    register_shutdown_function(function() { trigger_error('shutdown warning', E_USER_WARNING); });
}
session_start();
if (isset($_POST['mode']) && $_POST['mode'] === 'session_write') {
    $_SESSION['saved'] = 'yes';
}
header('Content-Type: application/json');
echo json_encode(array('pid'=>getmypid(),
    'loaded'=>extension_loaded('php2shell_block'),
    'progress'=>ini_get('session.upload_progress.enabled'), 'post'=>$_POST,
    'session'=>$_SESSION, 'files'=>array_keys($_FILES),
    'version'=>PHP_VERSION, 'exe'=>readlink('/proc/self/exe'),
    'start'=>file_get_contents('/proc/self/stat')));
''')
        if cgi:
            wrapper = os.path.join(root, "run-cgi")
            write_text(wrapper, "#!/bin/sh\n# 検証fixtureのみをPHP CGIで実行する。\nexport SCRIPT_FILENAME='" + os.path.join(root, "index.php") + "'\nexport REDIRECT_STATUS=1\nexec '" + module + "' -c '" + os.path.join(root, "php.ini") + "'\n")
            os.chmod(wrapper, 0o755)
        config = os.path.join(root, "httpd.conf")
        write_text(config, ('''ServerRoot /etc/httpd
LoadModule mpm_prefork_module modules/mod_mpm_prefork.so
LoadModule unixd_module modules/mod_unixd.so
LoadModule authz_core_module modules/mod_authz_core.so
LoadModule php5_module "PLACEHOLDER_LIBPHP"
Listen 127.0.0.1:18081
ServerName localhost
KeepAlive On
KeepAliveTimeout 2
MaxKeepAliveRequests 1000
User apache
Group apache
StartServers 1
MinSpareServers 1
MaxSpareServers 2
ServerLimit 2
MaxRequestWorkers 2
MaxConnectionsPerChild 0
ErrorLog "''' + os.path.join(root, "error.log") + '''"
PidFile "''' + os.path.join(root, "httpd.pid") + '''"
PHPIniDir "''' + str(root) + '''"
DocumentRoot "''' + str(root) + '''"
<Directory "''' + str(root) + '''">
Require all granted
<FilesMatch "\\.php$">
SetHandler application/x-httpd-php
</FilesMatch>
</Directory>
''').replace('PLACEHOLDER_LIBPHP', module if runtime else '/usr/lib64/httpd/modules/libphp5.so'))
        if cgi:
            with open(config) as stream:
                content = stream.read()
            content = content.replace('LoadModule php5_module "' + module + '"',
                'LoadModule cgi_module modules/mod_cgi.so\nLoadModule alias_module modules/mod_alias.so')
            content = content.replace('PHPIniDir "' + root + '"', '')
            content = content.replace('SetHandler application/x-httpd-php', 'SetHandler cgi-script')
            content += '\nScriptAlias /index.php "' + wrapper + '"\n<Directory "' + root + '">\nOptions +ExecCGI\n</Directory>\n'
            write_text(config, content)
        env = dict(os.environ, PHP_INI_SCAN_DIR="/etc/php.d" if installed_extensions else "")
        subprocess.check_call(["httpd", "-t", "-f", str(config)], env=env)
        process = subprocess.Popen(["httpd", "-DFOREGROUND", "-f", str(config)], env=env, preexec_fn=os.setsid)
        try:
            for attempt in range(10):
                try:
                    status, body = request()
                    break
                except (OSError, socket.error, httpclient.HTTPException):
                    assert process.poll() is None, "test Apache exited"
                    time.sleep(0.1)
            else:
                raise RuntimeError("test Apache did not start")
            before = json.loads(body)
            assert before["version"] == "5.4.45"
            if cgi:
                assert before["exe"] == module, "unexpected CGI binary"
            assert status == 200 and (runtime or before["loaded"]) and before["progress"] == ("1" if runtime else "0")
            status, body = request()
            second = json.loads(body)
            next_pid = second["pid"]
            if cgi:
                assert (before["pid"], before["start"].split()[21]) != (second["pid"], second["start"].split()[21])
            assert (next_pid != before["pid"]) if cgi else (next_pid == before["pid"]), "request process policy failed"
            status, body = request("POST", "mode=session_write", {"Content-Type": "application/x-www-form-urlencoded"})
            assert json.loads(body)["session"]["saved"] == "yes"
            status, body = request()
            assert json.loads(body)["session"]["saved"] == "yes", "session persistence failed"
            multipart = b'--test\r\nContent-Disposition: form-data; name="value"\r\n\r\nhello\r\n--test--\r\n'
            status, body = request("POST", multipart, {"Content-Type": "multipart/form-data; boundary=test"})
            assert status == 200 and json.loads(body)["post"]["value"] == "hello"
            upload = (b'--test\r\nContent-Disposition: form-data; name="PHP_SESSION_UPLOAD_PROGRESS"\r\n\r\ntoken\r\n'
                b'--test\r\nContent-Disposition: form-data; name="document"; filename="test.txt"\r\nContent-Type: text/plain\r\n\r\nhello\r\n--test--\r\n')
            status, body = request("POST", upload, {"Content-Type": "multipart/form-data; boundary=test"})
            uploaded = json.loads(body)
            assert status == 200 and "document" in uploaded["files"]
            if runtime:
                status, body = request()
                assert "upload_progress_token" not in json.loads(body)["session"], "progress callback was not disabled"
                # 上限4まで解析し、5番目のpartを受理しないことを確認する。
                for count in (4, 5):
                    parts = b"".join((b'--test\r\nContent-Disposition: form-data; name="k%d"\r\n\r\nv\r\n' % i) for i in range(count)) + b'--test--\r\n'
                    status, body = request("POST", parts, {"Content-Type": "multipart/form-data; boundary=test"})
                    assert len(json.loads(body)["post"]) == 4
            print("PASS: session persistence and file upload")
            if runtime:
                print("PASS: progress disabled despite INI=1, multipart limit boundary")
            for mode in ("oom", "fatal", "parse", "shutdown_warning"):
                try:
                    status, body = request("POST", "mode=" + mode, {"Content-Type": "application/x-www-form-urlencoded"})
                    assert status != 200 or runtime or mode == "shutdown_warning", "fatal unexpectedly returned success"
                except (OSError, socket.error, httpclient.HTTPException):
                    pass  # 即時終了では正常なHTTP応答を送れない場合がある。
                if mode == "oom":
                    with open(os.path.join(sessions, "oom-instance")) as stream:
                        victim = json.load(stream)
                    victim_stat = "/proc/" + str(victim["pid"]) + "/stat"
                    for attempt in range(50):
                        try:
                            with open(victim_stat) as stream:
                                current = stream.read().split()
                            dead = current[21] != victim["stat"].split()[21] or current[2] == "Z"
                        except IOError:
                            dead = True
                        if dead:
                            break
                        time.sleep(0.1)
                    assert dead, "the worker that handled OOM is still running"
                for attempt in range(10):
                    try:
                        status, body = request()
                        after = json.loads(body)
                        break
                    except (OSError, socket.error, httpclient.HTTPException):
                        time.sleep(0.1)
                else:
                    raise RuntimeError("worker was not replaced")
                assert status == 200 and (runtime or after["loaded"])
                if mode == "oom":
                    assert after["pid"] != victim["pid"], "OOM process reused"
                elif not runtime and mode != "shutdown_warning":
                    assert after["pid"] != before["pid"], "fatal process reused"
                before = after
            with open(os.path.join(root, "error.log")) as stream:
                log = stream.read()
            assert ("Allowed memory size" in log) if runtime else log.count("fail-fast exit (86)") >= 2
            print("PASS: CGI fresh process" if cgi else "PASS: mod_php reuse and recovery")
            print("PASS: multipart, OOM process exit, fatal/parse/shutdown-warning recovery")
        finally:
            # ログ読込みに失敗しても、専用Apacheの停止を必ず試行する。
            try:
                if connection is not None:
                    connection.close()
                try:
                    with open(os.path.join(root, "error.log")) as stream:
                        print(stream.read())
                except IOError:
                    pass
            finally:
                if process.poll() is None:
                    process.terminate()
                for attempt in range(10):
                    if process.poll() is not None:
                        break
                    time.sleep(0.1)
                else:
                    process.kill()
                process.wait()

    finally:
        shutil.rmtree(temp)


if __name__ == "__main__":
    main()
