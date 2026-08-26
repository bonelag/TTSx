import os
import sys
from pathlib import Path


from typing import Optional

_CUSTOM_BUNDLE_ROOT: Optional[str] = None


def set_bundle_root(path: str) -> None:
    """Override the root directory for models, bin, and temp programmatically."""
    global _CUSTOM_BUNDLE_ROOT
    _CUSTOM_BUNDLE_ROOT = os.path.abspath(str(path))


def bundle_root() -> str:
    """Returns the portable root directory of TTS-App."""
    if _CUSTOM_BUNDLE_ROOT:
        return _CUSTOM_BUNDLE_ROOT
    env_root = os.getenv("TTS_APP_ROOT")
    if env_root and os.path.exists(env_root):
        return os.path.abspath(env_root)
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return str(Path(__file__).resolve().parent.parent)


def app_path(*subpaths: str) -> str:
    return os.path.join(bundle_root(), *subpaths)


def models_path(*subpaths: str) -> str:
    return os.path.join(bundle_root(), "models", *subpaths)


def bin_path(*subpaths: str) -> str:
    return os.path.join(bundle_root(), "bin", *subpaths)


def temp_path(*subpaths: str) -> str:
    p = os.path.join(bundle_root(), "temp", *subpaths)
    os.makedirs(os.path.dirname(p) if subpaths else p, exist_ok=True)
    return p


def subprocess_text_kwargs() -> dict:
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(__import__("subprocess"), "CREATE_NO_WINDOW", 0)
        startupinfo = __import__("subprocess").STARTUPINFO()
        startupinfo.dwFlags |= __import__("subprocess").STARTF_USESHOWWINDOW
        kwargs["startupinfo"] = startupinfo
    return kwargs
