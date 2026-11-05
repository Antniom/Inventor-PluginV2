# Autodesk Inventor AI Studio Plugin (v2.0.0)

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![MCP SDK 2.3.0](https://img.shields.io/badge/MCP%20SDK-2.3.0-green.svg)](https://github.com/modelcontextprotocol/python-sdk)
[![Autodesk Inventor 2026/2027](https://img.shields.io/badge/Autodesk%20Inventor-2026%20%7C%202027-orange.svg)](https://www.autodesk.com/products/inventor/overview)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> **Complete Antigravity & Agentic CAD Plugin for Autodesk Inventor Professional**  
> **Author:** Antonio Coelho  
> **Repository:** [https://github.com/Antniom/LMInventor-plugin](https://github.com/Antniom/LMInventor-plugin)

The **Autodesk Inventor AI Studio Plugin** is a unified, first-class agentic CAD plugin for AI coding assistants and autonomous engineering agents (Antigravity, Claude Code, Cline, Cursor). It combines a high-performance **51-tool Model Context Protocol (MCP) server** with **5 specialized Antigravity CAD skills** into an integrated engineering suite.

---

## ⚠️ Important: This is a Full Plugin, Not Just an MCP Server

Unlike raw MCP servers that only expose tool endpoints without behavioral knowledge, this package is a **first-class Antigravity Plugin** (`plugin.json`). 

**The 5 bundled skills are essential, required components of the system.** They provide the engineering doctrine, geometric reasoning, and COM API quirk mitigation that prevent AI models from breaking CAD assemblies, causing over-constrained deadlocks, or misinterpreting units.

```
LMInventor-plugin/
├── plugin.json                 # Antigravity Plugin Manifest (MCP Server + 5 Skills)
├── pyproject.toml              # Modern Python packaging (mcp>=2.3.0, pywin32)
├── inventor_mcp_server.py      # Standalone launcher with sys.path resolution
├── src/
│   ├── server.py               # FastMCP Server: 51 tools, 3 dynamic resources, prompts
│   ├── inventor_api.py         # Robust COM API abstraction layer (mm units, topology)
│   └── updater.py              # Safe background auto-updater (throttled, zero stdout, rollback)
├── skills/                     # 5 Non-Optional Antigravity Domain Skills:
│   ├── inventor-modeling/      # Parametric 3D parts, sketches, features, sheet metal
│   ├── inventor-assemblies/    # Assembly architecture, datums, rigidity, constraints
│   ├── inventor-kinematics/    # PosReps, mechanism travel limits, motion driving, joints
│   ├── inventor-diagnostics/   # Process supervisor, orphan cleanup, rebuild diagnostics
│   └── inventor-din-parts/     # Parametric DIN/ISO mechanical hardware generation
├── tests/                      # Full test suite (test_updater.py)
└── docs/                       # Verification bundles and API notes
```

---

## 🌟 Capabilities & Features

### 1. 51 Native MCP Tools
- **Parametric 3D Modeling (`.ipt`)**: Fully constrained 2D sketching, boss/cut extrusions, revolves, native hole wizard (clearance, tapped, counterbore, countersink), fillets, chamfers, and circular patterns.
- **Sheet Metal Modeling**: Sheet metal faces, flanges with automatic radius/relief calculations, cuts, and flat pattern exports.
- **Assembly Architecture (`.iam`)**: Bottom-up component insertion, declarative occurrence transformations, coordinate reference planes, and stationary datum locking.
- **Assembly Constraints & Travel Limits**: Standard Mate, Flush, Angle, and Insert constraints with range-of-motion travel limits (including negative strokes for drawer slides and undirected solution angles).
- **Positional Representations (`PosReps`)**: Creation, activation, and constraint overrides for kinematic maximum travel positions (`[Primary]`, `Porta_Aberta_Max`, `Gaveta_Aberta_Max`, `Posicao_Maxima`).
- **Native Assembly Joints (On-Demand)**: Rotational and slider joints with angular and linear limits. Automatically snapshots and restores stationary occurrence `Grounded` states.
- **Subassembly Internal Rigidity**: Single-pass $O(N + M)$ relationship scanner that safely grounds unconstrained internal parts to origin while preserving dynamic mechanisms via `exclude_keywords`.
- **Dynamic Motion Driving**: Multi-step kinematic motion interpolation for constraint stroke verification.
- **Showcase Perspective Rendering**: High-resolution viewport capture (1280×720, 1920×1080) with explicit camera positioning, returning native MCP `Image` content blocks.
- **Safe Process Supervisor**: Anti-deadlock process auditor that safeguards against orphan headless background instances with strict startup grace periods and explicit PID confirmation.
- **Safe Auto-Updater Tools**: `check_for_updates` (check remote updates with 7-day throttle or force bypass) and `update_plugin` (dry-run preview and atomic fast-forward apply with automatic isolated rollback).
- **`execute_python` Power Tool**: Persistent interactive Python execution environment for deep custom COM automation.

### 2. 3 Dynamic MCP Resources & Prompts
- `inventor://status`: Real-time connection status, active document metadata, units, and software version.
- `inventor://assembly/kinematics`: Live assembly kinematic tree, occurrence hierarchy, constraint health statuses, and free degrees of freedom.
- `inventor://assembly/representations`: Active and available Positional Representations in the active assembly.
- `audit_assembly` Prompt: Automated prompt guiding agents to audit assembly datums, internal rigidity, and mechanism states.

### 3. The 5 Core CAD Skills

| Skill | Directory | Core Doctrine & Responsibility |
| :--- | :--- | :--- |
| **`inventor-modeling`** | [`skills/inventor-modeling/`](skills/inventor-modeling/) | Enforces parametric sketch discipline, origin alignment, dimensioned constraints, topological face/edge selection, and sheet metal rules. |
| **`inventor-assemblies`** | [`skills/inventor-assemblies/`](skills/inventor-assemblies/) | Enforces stationary datum grounding, coordinate datum alignment, and mandatory subassembly internal rigidity before insertion. |
| **`inventor-kinematics`** | [`skills/inventor-kinematics/`](skills/inventor-kinematics/) | Enforces mechanism doctrine: standard constraints paired with Positional Representations by default; native joints strictly on-demand. |
| **`inventor-diagnostics`** | [`skills/inventor-diagnostics/`](skills/inventor-diagnostics/) | Manages orphan process supervisor guardrails, COM threading invariants, and FeatureManager rebuild error recovery. |
| **`inventor-din-parts`** | [`skills/inventor-din-parts/`](skills/inventor-din-parts/) | Generates standard DIN/ISO fasteners from scratch using exact metric engineering tables (DIN 934, DIN 933, DIN 125, DIN 2573). |

---

## 📐 Core Engineering Doctrines Enforced

1. **Units Boundary Invariant:**
   The MCP tool interface strictly accepts millimeters (`offset_mm`, `min_limit`, `max_limit`) and degrees (`angle_deg`). Conversions to Inventor COM internal units ($d_{\text{cm}} = d_{\text{mm}} / 10.0$, $\theta_{\text{rad}} = \theta_{\text{deg}} \times \pi / 180.0$) are performed automatically at the tool boundary.
2. **Mechanism Kinematics (Constraints + PosReps First):**
   Standard constraints paired with Positional Representations are the default standard for CAD mechanisms. Native joints (`add_assembly_joint`) are reserved for explicit on-demand physics verification.
3. **Subassembly Internal Rigidity:**
   Subassembly internal parts must be grounded relative to their subassembly origin (`manage_subassembly_kinematics(action="enforce_rigidity")`) before insertion into a parent assembly to prevent components flying apart during interaction.
4. **Zero False Kills Supervisor:**
   The process supervisor defaults to a safe dry-run (`confirm=False`). When terminating background orphans (`confirm=True`), explicit candidate PIDs (`target_pids=[...]`) copied from the dry-run inspection are strictly required, and young instances (< 45 seconds) are protected from termination.

---

## 🚀 Installation & Setup

### Requirements
- **Windows 10 / 11**
- **Autodesk Inventor Professional 2026 or 2027**
- **Python 3.12+**
- **Model Context Protocol Python SDK (`mcp >= 2.3.0`)** and `pywin32 >= 306`

### Option A: Install as an Antigravity Plugin (Recommended)
Clone directly into your Antigravity plugins directory:
```powershell
cd "$env:USERPROFILE\.gemini\config\plugins"
git clone https://github.com/Antniom/LMInventor-plugin.git inventor
cd inventor
pip install -e .
```
Antigravity automatically discovers `plugin.json` and activates the MCP server and all 5 CAD skills simultaneously.

### Option B: Standalone MCP Client Setup (Claude Code / Cline / Cursor)
1. Clone the repository:
   ```powershell
   git clone https://github.com/Antniom/LMInventor-plugin.git C:\Plugins\inventor
   cd C:\Plugins\inventor
   pip install -e .
   ```
2. Add to your client's `.mcp.json` or MCP configuration:
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
3. Copy or symlink the 5 skills to your agent's skills directory:
   ```powershell
   # For Claude Code:
   Copy-Item -Recurse skills\* "$env:USERPROFILE\.claude\skills\"
   ```

---

## 🔄 Safe Auto-Updater

The plugin features a built-in, completely safe self-updater designed specifically for headless agentic environments (stdio transport):

### Safety Guarantees & Architecture
1. **Zero Stdout Writes (Strict Protocol Invariant):**  
   The updater NEVER writes to `sys.stdout`. All diagnostic logs are sent strictly to `sys.stderr` to avoid corrupting the MCP JSON-RPC protocol framing.
2. **Non-Blocking Startup:**  
   The update check runs in an isolated background daemon thread with strict $\le 10\text{s}$ network timeouts and swallowed exceptions. An offline environment or failed network call will **never** delay or prevent the server from starting.
3. **7-Day Throttling:**  
   Automatic checks run at most once every 7 days. Throttle state is persisted out-of-tree under `%LOCALAPPDATA%/inventor-mcp/updater.json` (Windows) or `~/.config/inventor-mcp/updater.json` (Linux/macOS), ensuring the git working tree remains pristine.
4. **Private Repository Authentication:**  
   Resolves credentials without logging, printing, or storing tokens using a secure priority hierarchy:
   - `INVENTOR_MCP_GITHUB_TOKEN` environment variable
   - `GITHUB_TOKEN` environment variable
   - `gh auth token` (GitHub CLI)
   - Native git credential helper (for git clone installations)
5. **Pre-flight Invariants & Fast-Forward Only:**  
   Updates are strictly refused if the working tree has uncommitted local edits, if the branch is not `main`, or if local history has diverged. Merges strictly use `git merge --ff-only` (never `--hard` or recursive merges).
6. **Isolated Subprocess Verification & Automatic Rollback:**  
   After applying an update, the plugin validates Python syntax across all source files (`py_compile`) and verifies `import src.server` inside a **separate subprocess**. If compilation or importing fails, the updater automatically rolls back to the prior commit (`git reset --keep <pre_sha>`) or restores the zip backup.
7. **Change Detection:**  
   Reports when `pyproject.toml` dependencies change (prompting `pip install -e .`) and flags when `skills/` have been updated so external agent copies can be re-synced.
8. **Scoped File Management & Personal Files:**  
   - **Git clone installations**: Local uncommitted changes to tracked files strictly prevent updates until resolved; untracked scratch files are ignored and remain untouched.
   - **Zip/folder installations**: Managed plugin folders (`src/`, `skills/`, `docs/`, `tests/`, `assets/`) and root repository files are replaced wholesale during update (`dirs_exist_ok=True` ensures graceful merging even under Windows file-locking or antivirus indexers). Personal scratch files, custom scripts, or notes should be kept in the plugin root (e.g. `scratch.ipt`, `render.png`, `.mcp.json`) or in custom unmanaged folders outside `src/`, `skills/`, `docs/`, `tests/`, and `assets/`.

### Configuration & Environment Modes
Configure behavior via the `INVENTOR_MCP_AUTOUPDATE` environment variable:
- `apply` *(default)*: Checks in the background on startup (throttled to 7 days) and automatically applies verified fast-forward updates.
- `check`: Checks for updates and records status without applying.
- `off`: Disables automatic startup checks entirely.

### Interactive MCP Tools & Resources
- **`check_for_updates(force: bool = False)`**: Check remote repository status on-demand (pass `force=True` to bypass the 7-day throttle).
- **`update_plugin(confirm: bool = False)`**: Apply updates. Defaults to a dry-run preview (`confirm=False`). Pass `confirm=True` to execute the verified update.
- **`status()` Tool & `inventor://status` Resource**: Exposes current installed commit SHA, version, update availability, and restart requirements.

### Manual Rollback
If you ever need to manually revert an update:
```powershell
cd "$env:USERPROFILE\.gemini\config\plugins\inventor"
git reset --keep <previous_sha>
```

---

## 🔬 Empirical Verification

This plugin suite has been rigorously tested against live CAD geometry on **Autodesk Inventor Professional 2027.1** and verified via an official MCP Python SDK `ClientSession`:
- **MCP 2.3.0 Conformance:** Fully compatible with `MCPServer` in `mcp.server.mcpserver`.
- **Live Travel Limits:** Verified on negative stroke Drawer Flush ($-220.0 \text{ mm} \le \text{offset} \le 0.0 \text{ mm}$) and Hinge Angle ($0^\circ \to 115^\circ$, `kUndirectedSolution = 78594`).
- **Native Joint Grounding:** Verified automatic restoration of `occ.Grounded = True` post-joint insertion.
- **Showcase Viewport Renders:** Pixel-verified using PIL (PNG format, 1280×720 RGB, non-blank render).

Complete empirical logs and verification matrices are available in [docs/inventor_mcp_review_bundle.md](docs/inventor_mcp_review_bundle.md).

---

## 📄 License
This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
