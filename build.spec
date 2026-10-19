# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 打包配置文件。

使用方法: pyinstaller build.spec
"""

import os
from PyInstaller.utils.hooks import collect_data_files

block_cipher = None

# 资源目录（相对 spec 文件所在目录），用于打包图标等静态资源
SPEC_DIR = globals().get('SPECPATH', os.path.abspath(os.getcwd()))
APP_ICON = os.path.join(SPEC_DIR, 'assets', 'icon', '250px-Manjuu_logo1.ico')

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('sql', 'sql'),
        ('assets', 'assets'),
    ],
    hiddenimports=[
        'PyQt5.sip',
        'PyQt5.QtCore',
        'PyQt5.QtGui',
        'PyQt5.QtWidgets',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    a.zipfiles,
    a.datas,
    [],
    name='AzurLaneTool',
    icon=APP_ICON,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
