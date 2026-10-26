#!/usr/bin/env python3
# tests/installer_bootstrap.py: TarFileのcontext managerがない環境とPython選択処理を再現する回帰試験。
import io
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = (ROOT / "scripts/installer.sh.in").read_text(encoding="utf-8")
EXTRACTOR = re.search(r"<<'PY'\n(.*?)\nPY\n", TEMPLATE, re.S).group(1)
SELECTOR = re.search(r"(select_python\(\) \{\n.*?\n\})", TEMPLATE, re.S).group(1)
PLATFORM_CHECK = re.search(r"(check_platform\(\) \{\n.*?\n\})", TEMPLATE, re.S).group(1)


class LegacyReader:
    """read/closeだけを持ち、with文に対応しない旧ファイルハンドルを再現する。"""
    def __init__(self, stream):
        self.stream = stream
        self.closed = False

    def read(self, count=-1):
        return self.stream.read(count)

    def close(self):
        self.closed = True
        self.stream.close()


class LegacyArchive:
    """__enter__/__exit__を持たないTarFileを再現する。"""
    def __init__(self, stream):
        self.stream = stream
        self.readers = []
        self.closed = False

    def getmembers(self):
        return self.stream.getmembers()

    def extractfile(self, member):
        reader = LegacyReader(self.stream.extractfile(member))
        self.readers.append(reader)
        return reader

    def close(self):
        self.closed = True
        self.stream.close()


class ExtractionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="php2shellblock-bootstrap-")
        self.root = Path(self.temp.name)
        self.archive = self.root / "payload.tar.gz"
        self.destination = self.root / "extracted"
        self.destination.mkdir()
        self.open_archive = tarfile.open
        self.legacy = []

    def tearDown(self):
        self.temp.cleanup()

    def create(self, names, symlink=False):
        with self.open_archive(self.archive, "w:gz") as stream:
            for name in names:
                member = tarfile.TarInfo(name)
                if symlink:
                    member.type = tarfile.SYMTYPE
                    member.linkname = "/etc/passwd"
                    stream.addfile(member)
                else:
                    data = b"fixture"
                    member.size = len(data)
                    stream.addfile(member, io.BytesIO(data))

    def legacy_open(self, *args):
        value = LegacyArchive(self.open_archive(*args))
        self.legacy.append(value)
        return value

    def extract(self, legacy=True):
        opener = self.legacy_open if legacy else self.open_archive
        with patch.object(sys, "argv", ["bootstrap", str(self.archive), str(self.destination)]):
            with patch.object(tarfile, "open", opener):
                exec(compile(EXTRACTOR, "<installer-bootstrap>", "exec"), {"__name__": "__main__"})

    def test_current_tarfile(self):
        self.create(["payload/example.txt"])
        self.extract(legacy=False)
        self.assertEqual((self.destination / "payload/example.txt").read_bytes(), b"fixture")

    def test_tarfile_and_reader_without_context_manager(self):
        self.create(["payload/example.txt"])
        self.extract()
        self.assertFalse(hasattr(self.legacy[0], "__exit__"))
        self.assertTrue(self.legacy[0].closed)
        self.assertTrue(all(reader.closed for reader in self.legacy[0].readers))
        self.assertEqual((self.destination / "payload/example.txt").read_bytes(), b"fixture")

    def test_traversal_rejected_and_closed(self):
        self.create(["payload/../../escape.txt"])
        with self.assertRaises(RuntimeError):
            self.extract()
        self.assertTrue(self.legacy[0].closed)
        self.assertFalse((self.root / "escape.txt").exists())

    def test_symlink_rejected_and_closed(self):
        self.create(["payload/link"], symlink=True)
        with self.assertRaises(RuntimeError):
            self.extract()
        self.assertTrue(self.legacy[0].closed)

    def test_duplicate_rejected_before_writing(self):
        self.create(["payload/example.txt", "payload/example.txt"])
        with self.assertRaises(RuntimeError):
            self.extract()
        self.assertTrue(self.legacy[0].closed)
        self.assertEqual(list(self.destination.iterdir()), [])


@unittest.skipUnless(os.name == "posix" and shutil.which("bash"), "POSIX bash required")
class PlatformTests(unittest.TestCase):
    def check(self, release, architecture):
        with tempfile.TemporaryDirectory(prefix="php2shellblock-platform-") as root:
            path = Path(root) / "centos-release"
            path.write_text(release + "\n", encoding="ascii")
            return subprocess.run([shutil.which("bash"), "-c", "set -eu\n" + PLATFORM_CHECK + '\ncheck_platform "$1" "$2"\n',
                                   "platform-test", str(path), architecture], capture_output=True, text=True)

    def test_centos7_x86_64_supported(self):
        self.assertEqual(self.check("CentOS Linux release 7.9.2009 (Core)", "x86_64").returncode, 0)

    def test_centos6_rejected_before_python(self):
        result = self.check("CentOS release 6.10 (Final)", "x86_64")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("CentOS 7 x86_64 only", result.stderr)
        self.assertIn("CentOS release 6.10", result.stderr)
        self.assertLess(TEMPLATE.index('\ncheck_platform\npython_runtime='), TEMPLATE.index('\nwork=$(mktemp'))

    def test_other_architecture_rejected(self):
        self.assertNotEqual(self.check("CentOS Linux release 7.9.2009 (Core)", "aarch64").returncode, 0)


@unittest.skipUnless(os.name == "posix" and shutil.which("bash"), "POSIX bash required")
class InterpreterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="php2shellblock-python-")
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def interpreter(self, name, supported):
        code = "#!/bin/bash\nexit 0\n" if supported else "#!/bin/bash\ncase \"$*\" in *sys.exit*) exit 1;; *) echo 2.6.9;; esac\n"
        path = self.root / name
        path.write_text(code, encoding="ascii")
        path.chmod(0o700)

    def run_selector(self):
        return subprocess.run([shutil.which("bash"), "-c", "set -eu\n" + SELECTOR + "\nselect_python\n"],
                              env=dict(os.environ, PATH=str(self.root)), capture_output=True, text=True)

    def test_uses_supported_default(self):
        self.interpreter("python", True)
        self.assertEqual(self.run_selector().stdout.strip(), str(self.root / "python"))

    def test_falls_back_to_python27(self):
        self.interpreter("python", False)
        self.interpreter("python2.7", True)
        self.assertEqual(self.run_selector().stdout.strip(), str(self.root / "python2.7"))

    def test_falls_back_to_python3(self):
        self.interpreter("python", False)
        self.interpreter("python3", True)
        self.assertEqual(self.run_selector().stdout.strip(), str(self.root / "python3"))

    def test_legacy_only_fails_with_clear_message(self):
        self.interpreter("python", False)
        result = self.run_selector()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Python 2.7 or Python 3.6+ is required", result.stderr)
        self.assertIn("python=2.6.9", result.stderr)
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
