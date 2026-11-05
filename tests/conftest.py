import os
import sys
from unittest.mock import MagicMock

# Mock pywin32 on non-Windows platforms so tests importing server pass everywhere
for mod in [
    "win32com",
    "win32com.client",
    "pythoncom",
    "pywintypes",
    "win32com.client.dynamic",
]:
    if mod not in sys.modules:
        try:
            __import__(mod)
        except ImportError:
            sys.modules[mod] = MagicMock()

# Ensure repository root is on sys.path during test execution
repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)
