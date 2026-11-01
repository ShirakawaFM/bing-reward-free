from __future__ import annotations

import sys
from pathlib import Path


def app_root() -> Path:
    """可写数据目录：源码运行时是项目根目录，打包后是 exe 所在目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resource_root() -> Path:
    """只读资源目录：PyInstaller onefile 解压到 _MEIPASS，源码运行时即项目根目录。"""
    bundle_dir = getattr(sys, "_MEIPASS", None)
    if bundle_dir:
        return Path(bundle_dir)
    return app_root()


PROJECT_ROOT = app_root()
RESOURCE_ROOT = resource_root()
