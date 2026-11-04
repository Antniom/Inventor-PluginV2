---
name: inventor-assemblies
description: Assembly architecture, bottom-up component insertion, coordinate reference datum alignment, subassembly internal rigidity rules, and constraint management in Autodesk Inventor via the inventor MCP server.
---

# Autodesk Inventor — Assembly Architecture & Constraint Management

## Core Principles

1. **Stationary Datum Grounding**:
   - The primary chassis, cabinet, or base component must always be grounded as the immovable world datum:
     `manage_subassembly_kinematics(action="set_grounded", occurrence_name="1A_Gabinete", value=True)`.

2. **Subassembly Internal Rigidity Rule (Safe Grounding)**:
   - Before inserting a subassembly (e.g. a door with handles and display, or a drawer with tub and slides) into a top-level assembly, ensure internal parts are rigid.
   - Use `manage_subassembly_kinematics(action="enforce_rigidity", occurrence_name="<subasm_name>")`.
   - **Safety Invariant**: Occurrences that already have constraints or joints to other occurrences are automatically skipped from grounding to prevent over-constraining or conflicting relationships.

3. **Geometry Proxy Binding**:
   - Entities belonging to occurrences cannot be mated directly; they must always be wrapped via `occ.CreateGeometryProxy(entity)`.
   - Dedicated tools (`add_assembly_constraint`) handle proxy generation automatically.

4. **Coordinate Reference Planes**:
   - Align primary reference planes (XY, XZ, YZ) using Flush or Mate constraints with millimeter offsets.
