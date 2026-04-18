# PyInstaller spec for pdf-translator-mcp
#
# Builds a single-file executable with all native dependencies bundled:
#   pymupdf, onnxruntime, opencv, pdfminer-six, babeldoc, mcp (FastMCP)
#
# Usage:
#   uv run pyinstaller pdf_translator_mcp.spec --clean --noconfirm
#
# Output:
#   dist/pdf-translator-mcp         (macOS/Linux)
#   dist/pdf-translator-mcp.exe     (Windows)

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

block_cipher = None

# Packages whose native libs, data files, and dynamic submodules must be
# collected wholesale. These are the ones PyInstaller's automatic dependency
# scanner tends to miss due to runtime imports / data lookups.
_collect_targets = [
    "mcp",
    "pymupdf",
    "fitz",
    "onnx",
    "onnxruntime",
    "cv2",
    "pdfminer",
    "babeldoc",
    "rapidocr_onnxruntime",
    "huggingface_hub",
    "fontTools",
    "tiktoken",
    "tiktoken_ext",
]

datas = []
binaries = []
hiddenimports = []

for pkg in _collect_targets:
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        # Optional deps (e.g. tiktoken_ext) may not be installed; skip cleanly.
        pass

# Extra explicit submodules that tend to be imported dynamically
hiddenimports += collect_submodules("pdfminer")
hiddenimports += collect_submodules("babeldoc")


a = Analysis(
    ["pdf_translator/mcp_server.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # opencv-python duplicates opencv-python-headless; the headless one is
        # what we actually use. Exclude the GUI build to shave ~60 MB.
        "opencv_python",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="pdf-translator-mcp",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # upx breaks onnxruntime on macOS; leave disabled.
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # MCP speaks JSON-RPC over stdio — must stay a console app.
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,  # inherit from build host; CI matrix handles arch fanout.
    codesign_identity=None,
    entitlements_file=None,
)
