#!/usr/bin/env python
# -*- coding: utf-8 -*-
# tests/startup_oom.py: CGI入力解析中のOOMを、外部公開せず単独プロセスで検証する。
import os
import shutil
import subprocess
import sys
import tempfile


def main():
    """7 MiBの通常POSTを16 MiB制限で解析し、PHPコード到達前の終了を確認する。"""
    binary = os.path.realpath(sys.argv[1])
    root = tempfile.mkdtemp(prefix="php2shell-startup-")
    try:
        marker = os.path.join(root, "entered")
        script = os.path.join(root, "index.php")
        with open(script, "w") as stream:
            stream.write("<?php file_put_contents('" + marker + "', 'entered'); echo 'started';")
        data = b"value=" + b"a" * (7 * 1024 * 1024)
        env = dict(os.environ, REDIRECT_STATUS="1", SCRIPT_FILENAME=script,
                   REQUEST_METHOD="POST", CONTENT_TYPE="application/x-www-form-urlencoded",
                   CONTENT_LENGTH=str(len(data)), PHP_INI_SCAN_DIR="")
        process = subprocess.Popen([binary, "-n", "-d", "memory_limit=16M"], env=env,
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = process.communicate(data)
        assert process.returncode == 1, (process.returncode, stdout, stderr)
        assert b"Allowed memory size" in stderr, stderr
        assert not os.path.exists(marker), "PHP script ran before the tested OOM"
        print("PASS: POST parsing OOM exits 1 before application code")
    finally:
        shutil.rmtree(root)


if __name__ == "__main__":
    main()
