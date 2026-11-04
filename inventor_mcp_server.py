#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Autodesk Inventor MCP Server - Entry Point

Launches the Inventor FastMCP server with proper sys.path resolution.
"""

import os
import sys

# Ensure repository root is on sys.path
package_dir = os.path.dirname(os.path.abspath(__file__))
if package_dir not in sys.path:
    sys.path.insert(0, package_dir)

from src.server import main

if __name__ == "__main__":
    try:
        with open(r"C:\Users\anton\Desktop\Teste Inventor MCP\inventor-mcp\startup.log", "a") as f:
            f.write(f"Starting inventor MCP server... sys.argv={sys.argv}\n")
        main()
    except Exception as e:
        import traceback
        with open(r"C:\Users\anton\Desktop\Teste Inventor MCP\inventor-mcp\startup.log", "a") as f:
            f.write(f"CRASH: {e}\n{traceback.format_exc()}\n")
        raise
