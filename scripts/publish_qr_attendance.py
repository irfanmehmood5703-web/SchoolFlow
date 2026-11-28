"""Sign and publish the native QR Attendance APK from the trusted main workflow."""

import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

from school_app_worker import AUDIENCE, oidc_token, tools


def request_json(url, data=None):
    for attempt in range(12):
        request = urllib.request.Request(url)
        if data is not None:
            request.data = json.dumps(data).encode()
            request.add_header("Authorization", "Bearer " + oidc_token())
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code not in (404, 502, 503) or attempt == 11:
                raise
        time.sleep(15)


def publish(unsigned):
    aapt, signer = tools()
    metadata = subprocess.check_output([aapt, "dump", "badging", unsigned], text=True)
    package = re.search(
        r"^package: name='com\.schoolflow\.gate' versionCode='([0-9]+)' versionName='([0-9.]+)'",
        metadata,
        re.MULTILINE,
    )
    if not package or "application-debuggable" in metadata:
        raise RuntimeError("Expected the production QR Attendance package.")
    version = int(package[1])
    manifest_url = AUDIENCE.removesuffix("/api/app-builder") + "/api/mobile-app/update/qr-attendance"
    if request_json(manifest_url).get("version_code", 0) >= version:
        print("This QR Attendance version is already published.")
        return
    credentials = request_json(AUDIENCE + "/qr-attendance/signing", {})
    tag = f"qr-attendance-{version}-{os.environ['GITHUB_RUN_ID']}-{os.environ['GITHUB_RUN_ATTEMPT']}"
    source = os.environ["GITHUB_SHA"]
    with tempfile.TemporaryDirectory(prefix="qr-release-") as temporary:
        folder = Path(temporary)
        keystore = folder / "signing.p12"
        keystore.write_bytes(base64.b64decode(credentials["keystore"], validate=True))
        aligned = folder / "aligned.apk"
        apk = folder / "InstituteAxis-QR-Attendance.apk"
        subprocess.run([aapt.with_name("zipalign"), "-P", "16", "-f", "4", unsigned, aligned], check=True)
        subprocess.run(
            [signer, "sign", "--ks", keystore, "--ks-key-alias", "schoolflow",
             "--ks-pass", "env:SCHOOLFLOW_QR_SIGNING_PASSWORD", "--out", apk, aligned],
            env={**os.environ, "SCHOOLFLOW_QR_SIGNING_PASSWORD": credentials["password"]},
            check=True,
        )
        report = subprocess.check_output([signer, "verify", "--print-certs", apk], text=True)
        certificates = re.findall(r"certificate SHA-256 digest: ([0-9a-f]+)", report)
        if certificates != [credentials["fingerprint"]]:
            raise RuntimeError("QR Attendance signing identity did not match.")
        with apk.open("rb") as stream:
            checksum = hashlib.file_digest(stream, "sha256").hexdigest()
        legacy_apk = folder / "SchoolFlow-QR-Attendance.apk"
        shutil.copyfile(apk, legacy_apk)  # Existing installs validate this exact asset name.
        subprocess.run(
            ["gh", "release", "create", tag, apk, legacy_apk, "--target", source,
             "--title", f"InstituteAxis QR Attendance {package[2]}", "--latest=false",
             "--notes", "Official Android APK for InstituteAxis QR Attendance."],
            check=True,
        )
        request_json(AUDIENCE + "/qr-attendance/publish", {
            "package": "com.schoolflow.gate", "version_code": version, "version_name": package[2],
            "fingerprint": credentials["fingerprint"], "source_commit": source, "sha256": checksum,
            "size": apk.stat().st_size, "branded_asset": True,
        })


if __name__ == "__main__":
    publish(Path(sys.argv[1]))
