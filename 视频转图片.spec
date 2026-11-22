# -*- mode: python ; coding: utf-8 -*-
# 视频转图片/动图工具打包配置（onedir，内置 u2net AI 模型，同表情包生成器方案）
import os

from PyInstaller.utils.hooks import collect_dynamic_libs

datas = [
    (os.path.join(SPECPATH, '图标.png'), '.'),
    # u2net 模型来自同级项目「AI去背景工具」，相对定位，整个目录可迁移
    (os.path.join(SPECPATH, '..', 'AI去背景工具', 'models', 'u2net.onnx'), 'models'),
]
binaries = []
binaries += collect_dynamic_libs('imageio_ffmpeg')
binaries += collect_dynamic_libs('onnxruntime')   # AI 去背景推理库
hiddenimports = ['onnxruntime']

a = Analysis(
    ['视频转图片.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='视频转图片',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version='version.txt',
    icon=['图标.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='视频转图片',
)
