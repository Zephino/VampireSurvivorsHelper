# PyInstaller build recipe for the standalone exe. Build with "Build Exe.bat"
# (or: python -m PyInstaller --noconfirm --clean VampireSurvivorsHelper.spec).
from PyInstaller.utils.hooks import collect_all

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
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="VampireSurvivorsHelper",
    console=False,  # a window app: no black console window
    upx=False,      # UPX compression makes antivirus false positives more likely
    onefile=True,
)
