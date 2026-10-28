#!/usr/bin/env python3
# scripts/package-release.py: 検証済みバイナリーと公開ソースだけから自己展開シェル・配布アーカイブを生成する。
import argparse
import base64
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parent.parent
MODULE_SHA = "f83e471ca70d691b06f2f8957204d6a8e37821a7bb31b9e864e06d8497abae23"
LIBRARIES = {
    "/lib64/libc.so.6": "18c9eb148ec8bf8f6018d3021e7395bd9de847f280dde5d65e73522195fa35f9",
    "/lib64/libssl.so.10": "cd1d62209c3e14cd9809d76cc446fdf54c2a272f4e9cba24278a38e72254931b",
    "/lib64/libxml2.so.2": "3998bec4f844bab78f102637a3fcfc123662ff5bf307f628c8cbfa37a749b953",
    "/lib64/libpcre.so.1": "9513aab50d64bb4655550e1ba0c62fbcf6e7cbe0d64cba0814224d2631a85027",
}
REMI_18_PROFILE = {
    "rpm_release": "5.4.45-18.el7.remi.x86_64",
    "original_module_sha256": "35202da3529ffda4e585a1c443bdce86e372d4aced99053f023b31f219e4b8ae",
    "libraries": {
        "/lib64/libc.so.6": "fe9ca97275c3e5009374e2eb36184fab05a63848a6c377fce8b518f381760fc8",
        "/lib64/libssl.so.10": "84c8c57bba0cfb2c0237879d5dd0c803932ead2916d5d6b1647588ca73610e40",
        "/lib64/libxml2.so.2": "a7aef045babce59124326cc90e41f167644ce309fc7620820a27d77aff4d2e1e",
        "/lib64/libpcre.so.1": "9513aab50d64bb4655550e1ba0c62fbcf6e7cbe0d64cba0814224d2631a85027",
    },
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def text(path):
    """Windowsの改行変換を配布物へ持ち込まない。"""
    return path.read_bytes().replace(b"\r\n", b"\n")


def archive(files):
    """時刻・所有者・並び順を固定し、同じ内容から同じ配布物を生成する。"""
    result = io.BytesIO()
    with gzip.GzipFile(fileobj=result, mode="wb", filename="", mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w") as stream:
            for name, content in sorted(files.items()):
                member = tarfile.TarInfo(name)
                member.size = len(content)
                member.mode = 0o644
                member.mtime = 315532800
                stream.addfile(member, io.BytesIO(content))
    return result.getvalue()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--module", required=True, type=Path)
    parser.add_argument("--php-source", required=True, type=Path, help="Remi patch適用後のPHP 5.4.45ソース")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if not re.fullmatch(r"v\d+\.\d+\.\d+(?:-[a-z0-9.]+)?", args.version):
        raise ValueError("Invalid version")
    module = args.module.read_bytes()
    if sha(module) != MODULE_SHA:
        raise ValueError("This release supports only the previously validated module hash")
    if args.output.exists():
        raise ValueError("Output directory already exists; refusing overwrite")
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    payload = {"libphp5.so": module, "install-runtime.py": text(ROOT / "scripts/install-runtime.py"),
               "tests/apache_http.py": text(ROOT / "tests/apache_http.py"), "LICENSE": text(ROOT / "LICENSE"),
               "NOTICE.md": text(ROOT / "NOTICE.md"), "INSTALL.md": text(ROOT / "docs/install.md"),
               "scripts/build-remi54.sh": text(ROOT / "scripts/build-remi54.sh"),
               "patches/php-5.4.45-php2shell.patch": text(ROOT / "patches/php-5.4.45-php2shell.patch")}
    for path in (ROOT / "licenses").iterdir():
        if path.is_file():
            payload["licenses/" + path.name] = path.read_bytes()
    # 変更したPHPコードの全文と再ビルド手順を同梱し、差分だけの配布にしない。
    changed = re.findall(r"^\+\+\+ b/(.+)$", payload["patches/php-5.4.45-php2shell.patch"].decode(), re.M)
    source_manifest = json.loads((ROOT / "release/php54-source-manifest.json").read_text(encoding="utf-8"))
    if len(changed) != 10 or set(changed) != set(source_manifest["files"]) or sha(payload["patches/php-5.4.45-php2shell.patch"]) != source_manifest["patch_sha256"]:
        raise ValueError("Unexpected PHP patch/source provenance")
    for name in changed:
        if name.startswith("/") or ".." in name.split("/"):
            raise ValueError("Unsafe PHP source path")
        content = (args.php_source / name).read_bytes()
        if sha(content) != source_manifest["files"][name]:
            raise ValueError("Modified PHP source does not match the validated build: " + name)
        payload["php54-modified-sources/" + name] = content
    payload["php54-source-manifest.json"] = (json.dumps(source_manifest, indent=2, sort_keys=True) + "\n").encode()
    manifest = {"version": args.version, "revision": revision, "module_sha256": MODULE_SHA,
                "libraries": LIBRARIES, "profiles": {"remi-5.4.45-18-el7": REMI_18_PROFILE},
                "security_validation": "documented_oom_stale_session_crash_path",
                "rce_validation": "not_performed",
                "files": {path: sha(content) for path, content in payload.items()}}
    payload["manifest.json"] = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    packed = archive({"payload/" + path: content for path, content in payload.items()})
    template = text(ROOT / "scripts/installer.sh.in").decode()
    executable = template.replace("@VERSION@", args.version).replace("@PAYLOAD_SHA256@", sha(packed))
    executable = executable.encode() + base64.encodebytes(packed)
    args.output.mkdir(parents=True)
    outputs = {"php2shellblock-install.sh": executable, "php2shellblock-" + args.version + "-payload.tar.gz": packed}
    for name, data in outputs.items():
        (args.output / name).write_bytes(data)
    (args.output / "php2shellblock-install.sh.sha256").write_text(sha(executable) + "  php2shellblock-install.sh\n", encoding="ascii", newline="\n")
    (args.output / "SHA256SUMS").write_text("".join(sha(data) + "  " + name + "\n" for name, data in sorted(outputs.items())), encoding="ascii", newline="\n")
    print(json.dumps({"version": args.version, "module_sha256": MODULE_SHA, "payload_sha256": sha(packed),
                      "assets": {name: len(data) for name, data in outputs.items()}}, indent=2))


if __name__ == "__main__":
    main()
