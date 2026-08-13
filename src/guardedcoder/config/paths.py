from __future__ import annotations

import os
import sys
from pathlib import Path


def user_config_path(root: Path | None = None) -> Path:
    if root is None:
        if sys.platform == "win32":
            root = Path(os.environ["APPDATA"])
        elif sys.platform == "darwin":
            root = Path.home() / "Library" / "Application Support"
        else:
            xdg = os.environ.get("XDG_CONFIG_HOME")
            root = Path(xdg) if xdg else Path.home() / ".config"
    return Path(root) / "guardedcoder" / "config.toml"
