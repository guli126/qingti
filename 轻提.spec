# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置（窗口版）。

产物：dist/轻提.exe —— 单文件，双击直接出窗口，不开浏览器。

要点：
  - 必须用带 tkinter 的 Python 打包（官方安装包自带；精简版 Python 没有）
  - prompts/ 打进去，但只在首次运行时释放到 exe 旁边，之后读外面那份，
    用户拿记事本就能改提示词
  - console=False：纯窗口程序，不留黑框。所以 app.py 里对 sys.stdout/stderr
    为 None 的情况做了兜底，否则任何 print 都会崩
"""

import os

ROOT = os.path.abspath(os.path.dirname(SPEC))

a = Analysis(
    [os.path.join(ROOT, 'app.py')],
    pathex=[ROOT],
    binaries=[],
    datas=[
        (os.path.join(ROOT, 'prompts'), 'prompts'),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # 只剔真正无关的东西。
    # 注意别动 tkinter（这是界面本体），也别动 urllib 依赖的
    # email / http.cookiejar / ftplib——排掉之后整个网络层直接起不来。
    excludes=[
        'unittest', 'pydoc', 'pydoc_data', 'test',
        'distutils', 'setuptools', 'pip', 'wheel', 'lib2to3',
        'sqlite3', 'ensurepip', 'venv', 'idlelib',
        'turtle', 'turtledemo', 'this', 'antigravity',
        'numpy', 'PIL', 'pytest',
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='轻提',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # 纯窗口程序
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(ROOT, 'tools', 'app.ico'),
)
