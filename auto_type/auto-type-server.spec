# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for building auto-type-server binary.

This spec file configures PyInstaller to create a one-file executable
of the Python LSP server. The output is then processed by staticx in CI
to produce a fully static Linux binary for distribution with the VSCode
extension.

Build command:
    pyinstaller auto_type/auto-type-server.spec

Output:
    dist/auto-type-server (single executable)
"""

import glob
import os
import sys
from pathlib import Path

from PyInstaller.building.build_main import Analysis, PYZ, EXE


# ---------------------------------------------------------------------------
# Explicit data files for mypy's typeshed.
#
# collect_all=['mypy'] should include typeshed, but in one-file mode the data
# files can end up packed inside the PYZ archive where they are invisible to
# os.path.isfile().  Adding an explicit datas entry guarantees the typeshed
# directory is extracted to _MEIPASS/mypy/typeshed/ at runtime.
# ---------------------------------------------------------------------------
import mypy as _mypy_pkg

_mypy_pkg_dir = os.path.dirname(_mypy_pkg.__file__)
_typeshed_src = os.path.join(_mypy_pkg_dir, 'typeshed')

EXTRA_DATAS = [
    (_typeshed_src, os.path.join('mypy', 'typeshed')),
]

def _discover_mypyc_hidden_imports() -> list[str]:
    """Find hash-prefixed mypyc helper modules in site-packages.

    Mypy wheels built with mypyc may contain top-level extension modules with
    names like ``edfc647aaf02b20aa651__mypyc``. PyInstaller does not always
    discover these automatically, so include them explicitly.
    """
    modules: set[str] = set()
    for path_entry in sys.path:
        if "site-packages" not in path_entry:
            continue
        for match in glob.glob(os.path.join(path_entry, "*__mypyc.*")):
            module_name = Path(match).name.split(".")[0]
            if module_name.endswith("__mypyc"):
                modules.add(module_name)
    return sorted(modules)


# Modules excluded from the bundle to reduce binary size.
EXCLUDES = [
# ========== Standard Library (unused) ==========
    'tkinter',
    'tkinter.*',
    '_tkinter',
    'turtle',
    'turtledemo',
    'idlelib',
    'idlelib.*',
    'lib2to3',
    'lib2to3.*',
    'ensurepip',
    'ensurepip.*',
    'curses',
    'curses.*',
    'distutils',
    'distutils.*',

    # ========== Test Frameworks ==========
    'test',
    'test.*',
    'tests',
    'tests.*',
    'unittest',
    'unittest.*',
    'doctest',
    'doctest.*',
    'pytest',
    'pytest.*',
    '_pytest',
    '_pytest.*',
    'hypothesis',
    'hypothesis.*',

    # ========== mypy (unused submodules) ==========
    'mypy.test',
    'mypy.test.*',
    'mypy.dmypy',
    'mypy.dmypy.*',
    'mypy.stubgen',
    'mypy.stubtest',
    'mypy.report',
    # mypyc compiler package -- only needed to compile mypy itself, not at runtime.
    # The compiled output lives in the standalone *__mypyc.so shared object.
    'mypyc',
    'mypyc.*',

    # ========== libcst (unused submodules) ==========
    # Only parse_module, parse_expression, CSTTransformer, CSTVisitor,
    # and metadata.PositionProvider are used by this project.
    'libcst.codemod',
    'libcst.codemod.*',
    'libcst.matchers',
    'libcst.matchers.*',
    'libcst.display',
    'libcst.display.*',
    'libcst.tool',
    'libcst.testing',
    'libcst.testing.*',
    'libcst.tests',
    'libcst.tests.*',
    'libcst.*.tests',
    'libcst.metadata.tests',
    'libcst.metadata.tests.*',
    'libcst._nodes.tests',
    'libcst._parser.tests',
    'libcst._parser.parso.tests',
]

# Analysis phase: discovers all dependencies
HIDDEN_IMPORTS = [
    # Explicit imports for modules that may be dynamically loaded
    'pygls.lsp.server',
    'pygls.workspace',
    'lsprotocol.types',
    'injector',
    'jedi',
    'libcst',
    'libcst.metadata',
]

HIDDEN_IMPORTS.extend(_discover_mypyc_hidden_imports())

a = Analysis(
    # Entry point script - the LSP server main file
    ['src/auto_type/server.py'],
    pathex=[],
    datas=EXTRA_DATAS,
    hiddenimports=HIDDEN_IMPORTS,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    noarchive=False,
    optimize=2,
    # module_collection_mode: Controls how modules are packaged.
    # 'pyz' (bytecode only) is significantly smaller than 'pyz+py'.
    # mypy may still need 'pyz+py' if it relies on source inspection.
    module_collection_mode={
        'mypy': 'pyz+py',
        'jedi': 'pyz',
        'libcst': 'pyz',
        'pygls': 'pyz',
        'injector': 'pyz',
        'lsprotocol': 'pyz',
    },
    collect_all=['mypy']
)

# PYZ phase: creates the Python zip archive containing pure Python modules
pyz = PYZ(a.pure, a.zipped_data)

# EXE phase: creates a single-file executable
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='auto-type-server',
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    copy_metadata=['mypy'],
)
