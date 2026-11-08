# PyInstaller build recipe. Build with "Build Exe.bat"
# (or: python -m PyInstaller --noconfirm --clean VampireSurvivorsHelper.spec).
#
# Set VSH_ONEDIR=1 to build the folder version (dist/VampireSurvivorsHelper/ with the exe and its
# files) instead of the single exe. Antivirus programs flag folder builds far less often.
import os
import re

from PyInstaller.utils.hooks import collect_all

try:  # needs pefile, which PyInstaller installs on Windows (the only place file details apply)
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo, VarStruct, VSVersionInfo,
    )
except ImportError:
    VSVersionInfo = None

ONEDIR = os.environ.get("VSH_ONEDIR") == "1"
NAME = "VampireSurvivorsHelper"

# File details shown in the exe's Properties > Details (unlabelled programs look more suspicious).
version_text = open("VERSION", encoding="utf-8").read().strip()
numbers = tuple((list(map(int, re.findall(r"\d+", version_text))) + [0, 0, 0, 0])[:4])
version_info = None if VSVersionInfo is None else VSVersionInfo(
    ffi=FixedFileInfo(filevers=numbers, prodvers=numbers),
    kids=[
        StringFileInfo([StringTable("040904B0", [
            StringStruct("CompanyName", "Zephino"),
            StringStruct("FileDescription", "Vampire Survivors Helper - shows how to evolve your items"),
            StringStruct("FileVersion", version_text),
            StringStruct("InternalName", NAME),
            StringStruct("LegalCopyright", "Open source: github.com/Zephino/VampireSurvivorsHelper"),
            StringStruct("OriginalFilename", NAME + ".exe"),
            StringStruct("ProductName", "Vampire Survivors Helper"),
            StringStruct("ProductVersion", version_text),
        ])]),
        VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
    ],
)

datas = [
    ("vshelper/data/evolutions.json", "vshelper/data"),  # bundled wiki data (works offline)
    ("config/game_map.json", "config"),                  # names used to find items in memory
    ("VERSION", "."),
]
binaries = []
hiddenimports = []
# UnityPy (item pictures) loads its texture decoders and data files lazily: bundle them explicitly.
for package in ("UnityPy", "texture2ddecoder", "etcpak", "astc_encoder", "fmod_toolkit", "archspec"):
    try:
        d, b, h = collect_all(package)
    except Exception:  # optional decoder not installed: pictures in that format are skipped
        continue
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    ["run_helper.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["pytest", "unittest.mock"],
    noarchive=False,
)
pyz = PYZ(a.pure)

common = dict(
    name=NAME,
    console=False,  # a window app: no black console window
    upx=False,      # UPX compression makes antivirus false positives more likely
    version=version_info,
)
if ONEDIR:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, **common)
    coll = COLLECT(exe, a.binaries, a.datas, name=NAME, upx=False)
else:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], onefile=True, **common)
