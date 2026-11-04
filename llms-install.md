# Installation Guide for AI Agents & Autonomous Workflows

This document is an automated installation runbook for AI coding assistants (Antigravity, Claude Code, Cline, Cursor). Follow the steps in sequence.

## 1. Prerequisites Check

1. **Operating System:** Windows 10/11 (Autodesk Inventor runs exclusively on Windows).
2. **CAD Software:** Autodesk Inventor Professional 2026 or 2027 installed. Verify:
   ```powershell
   Test-Path "C:\Program Files\Autodesk"
   ```
3. **Python Environment:** Python 3.12+ available on PATH:
   ```powershell
   python --version
   ```

## 2. Core Architecture: Plugin Structure

**Note:** This package is an **Antigravity Plugin**, not a standalone MCP server. The 5 bundled skills are required and non-optional — they enforce critical CAD doctrines (datum grounding, subassembly rigidity, millimeter units boundary, and PosRep mechanism controls).

```
plugin.json          -> Registers MCP server ('inventor') and all 5 skills
pyproject.toml       -> Defines python package with mcp>=2.3.0 and pywin32
skills/              -> 5 Required domain skills
src/                 -> FastMCP server and Inventor COM abstraction wrapper
```

## 3. Setup Steps

### Step 3.1: Clone the Repository
Clone to a persistent directory:
```powershell
git clone https://github.com/Antniom/LMInventor-plugin.git C:\Plugins\inventor
cd C:\Plugins\inventor
```

### Step 3.2: Install Python Dependencies
Install the package in editable mode:
```powershell
pip install -e .
```
*(Dependencies: `mcp[cli]>=2.3.0`, `pywin32>=306`)*

### Step 3.3: Client Configuration

#### Option A: Antigravity / Gemini CLI
If cloning into the Antigravity plugins directory (`%USERPROFILE%\.gemini\config\plugins\inventor`), `plugin.json` automatically activates the MCP server and all 5 skills with zero extra configuration.

#### Option B: Claude Code / Cline / Cursor
1. Add the MCP server to your client configuration (`.mcp.json` or equivalent):
   ```json
   {
     "mcpServers": {
       "inventor": {
         "command": "python",
         "args": ["-m", "src.server"],
         "cwd": "C:/Plugins/inventor"
       }
     }
   }
   ```
2. Copy the 5 skills to your client's skills directory:
   ```powershell
   Copy-Item -Recurse C:\Plugins\inventor\skills\* "$env:USERPROFILE\.claude\skills\"
   ```

## 4. Verification Smoke Test

1. Launch Autodesk Inventor.
2. In the AI client chat, run:
   - `connect` -> Should return `Connected to running Inventor ...`
   - `status` -> Should report connection and document metadata
   - `create_part` with `name="SmokeTest"` -> Generates empty `.ipt`
   - `inspect` -> Snapshot of topology and volume

## 5. Troubleshooting & Invariants

- **Stale COM cache:** If `KeyError: '_dispobj_'` or COM dispatch errors occur, clear the cache:
  ```powershell
  Remove-Item -Recurse -Force "$env:LOCALAPPDATA\Temp\gen_py"
  ```
- **Units Boundary:** All MCP tool parameters expect **millimeters** for linear dimensions and **degrees** for angles. Internal conversions to cm/rad are performed automatically.
- **Process Supervisor:** If background headless processes accumulate, call `supervisor_clean_processes(confirm=False)` to list candidates, then `confirm=True, target_pids=[...]` to terminate.
