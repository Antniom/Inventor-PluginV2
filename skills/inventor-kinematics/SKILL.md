---
name: inventor-kinematics
description: Mechanism kinematics, degrees of freedom (DOF), positional representations (PosReps), motion limits, and multi-tier flexible indexing in Autodesk Inventor via the inventor MCP server.
---

# Autodesk Inventor — Mechanism Kinematics & Positional Representations

## Core Principles

1. **Anti-Locking Rule (Never Freeze Intended Motion Permanently)**:
   - When modeling parts intended to move (e.g. doors, drawers, levers, rotors), never apply an unconstrained fixed constraint that permanently locks the part across all states.
   - Constrain the part at its nominal reference state (e.g. 0° or 0 mm), and configure Positional Representations for kinematics.

2. **Positional Representations Doctrine (Default Mechanism Workflow)**:
   - **Do NOT prefer native Joints (`add_assembly_joint`) by default.** Use native joints **ONLY when explicitly requested by the user**.
   - **When NOT requested, standard constraints paired with Positional Representations (`PosReps`) of maximum positions MUST be used:**
     - `[Master]` / `Fechado`: Baseline nominal state (Door closed at 0°, Drawer closed at 0 mm).
     - `Porta_Aberta_Max`: Angle constraint overridden to max open angle (e.g. 115.0°) via `SetConstraintValueOverride`.
     - `Gaveta_Aberta_Max`: Slide flush constraint overridden to max open stroke (e.g. -220 mm).
     - `Posicao_Maxima`: Both door and drawer set concurrently to maximum travel positions for total envelope and clearance validation.
   - Use `manage_positional_representations` to switch between states or define new positions.

3. **Native Joints Rule (On-Demand Only)**:
   - Instantiate native `AssemblyJoint` objects (`kRotationalJointType`, `kSlideJointType`) strictly when the user explicitly prompts for joints.

4. **Multi-Tier Indexing via `Flexible = True`**:
   - For internal mechanisms (like carousel drums or planetary gears) to rotate inside a parent assembly, the subassembly occurrence must have `Flexible = True` enabled.
