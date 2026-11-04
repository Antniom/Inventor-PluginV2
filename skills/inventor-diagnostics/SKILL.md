---
name: inventor-diagnostics
description: Autodesk Inventor process management, OLE COM deadlock prevention, safe orphan cleanup, modal dialog mitigation, and FeatureManager rebuild diagnostics.
---

# Autodesk Inventor — Diagnostics & Process Supervisor

## Core Principles

1. **Safe Process Supervisor**:
   - Runaway headless instances of `Inventor.exe` occur when background scripts dispatch without interactive window handles or fail to exit cleanly.
   - Run `supervisor_clean_processes(confirm=False)` to safely audit running instances.
   - **Safety Invariants**:
     - Never pick the "biggest working set" and force-kill the rest.
     - Only target instances that have NO main window (`MainWindowHandle == 0`) AND are not the active COM session returned by `GetActiveObject`.
     - Default to dry-run (lists candidates). Require explicit `confirm=True` to terminate.
     - Never use `taskkill /F /IM Inventor.exe`.
     - Warn immediately if any open document is dirty (unsaved).

2. **Interactive Session Respect**:
   - If the user has Inventor open on their desktop with an active modal command or dialog, out-of-process COM calls block until the dialog is dismissed.
