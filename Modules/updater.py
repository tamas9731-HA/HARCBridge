"""Betöltőképernyőből vezérelt, opcionális HTTPS frissítésellenőrzés."""
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

# TESZT -> éles kiadásnál ezt az egy sort kell módosítani.
VERSION_URL = "https://harcbridge.hu/version.html"
INSTALLER_URL = "https://harcbridge.hu/windows/HARCBridge_Installer.exe"
MAX_INSTALLER_BYTES = 500 * 1024 * 1024
VERSION_RE = re.compile(r"\A[A-Za-z0-9._-]+\Z")
ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
VERSION_FILE = ROOT / "version"
TEMP_DIR = Path(tempfile.gettempdir()) / "HARCBridge_Embedded_Update"


def check_update():
    """Visszatér: (új_verzió, hiba). Nincs új verzió esetén (None, None)."""
    try:
        local = VERSION_FILE.read_text(encoding="utf-8-sig").strip()
        if not VERSION_RE.fullmatch(local):
            raise ValueError("Hibás helyi verziószám")
        request = urllib.request.Request(VERSION_URL, headers={"User-Agent": "HARCBridge/0.2", "Cache-Control": "no-cache"})
        with urllib.request.urlopen(request, timeout=8) as response:
            raw = response.read(129)
        if len(raw) > 128:
            raise ValueError("Túl nagy távoli verziófájl")
        remote = raw.decode("utf-8-sig").strip()
        if not VERSION_RE.fullmatch(remote):
            raise ValueError("Hibás távoli verziószám")
        if remote != local:
            return remote, None
        return None, None
    except Exception as exc:
        return None, str(exc)


def download_installer(progress=None):
    """A telepítőt külön ideiglenes mappába tölti; nem módosít saját adatokat."""
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    destination = TEMP_DIR / "HARCBridge_Installer.exe"
    partial = TEMP_DIR / "HARCBridge_Installer.part"
    partial.unlink(missing_ok=True)
    try:
        request = urllib.request.Request(INSTALLER_URL, headers={"User-Agent": "HARCBridge/0.2", "Cache-Control": "no-cache"})
        with urllib.request.urlopen(request, timeout=25) as response:
            length = int(response.headers.get("Content-Length", "0") or 0)
            if length > MAX_INSTALLER_BYTES:
                raise ValueError("Túl nagy telepítő")
            received = 0
            with partial.open("wb") as output:
                while chunk := response.read(256 * 1024):
                    received += len(chunk)
                    if received > MAX_INSTALLER_BYTES:
                        raise ValueError("Túl nagy telepítő")
                    output.write(chunk)
                    if progress and length:
                        progress(min(100, int(received * 100 / length)))
        if received < 4096 or (length and received != length):
            raise ValueError("Hiányos telepítő")
        with partial.open("rb") as check:
            if check.read(2) != b"MZ":
                raise ValueError("Nem Windows EXE érkezett")
        os.replace(partial, destination)
        return destination
    finally:
        partial.unlink(missing_ok=True)


def start_installer(path):
    if sys.platform != "win32":
        raise RuntimeError("Ez a telepítő csak Windows alatt használható.")
    subprocess.Popen([str(path), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS", "/DIR=" + str(ROOT)], cwd=str(TEMP_DIR))
