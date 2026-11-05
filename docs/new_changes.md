# Inventor MCP Server & Skills — Changelog & Implementation Blueprint
*(Compliant with MCP Python SDK `mcp == 2.3.0`, `mcp.server.mcpserver` with `FastMCP` cross-compatibility)*

**Target Package:** Autodesk Inventor MCP Server (`inventor-mcp`) & Antigravity Skills Suite  
**Output Location:** `C:\Users\anton\Desktop\new_tools_inventor\new_changes.md`  
**Protocol Specification:** Model Context Protocol (Official Python SDK `mcp == 2.3.0`)  
**Related Codebases:**
- MCP Server Source: `C:\Users\anton\Desktop\Teste Inventor MCP\inventor-mcp\`
- Active MCP Schemas: `C:\Users\anton\.gemini\antigravity\mcp\inventor\`
- Active Skills: `C:\Users\anton\.gemini\config\skills\inventor-modeling\`, `inventor-din-parts\`

---

## Executive Summary

The existing `inventor-mcp` server and its accompanying `inventor-modeling` skill were originally engineered strictly for **single-part 3D parametric modeling (`.ipt`)**. They provided comprehensive coverage for sketches, extrusions, revolves, holes, fillets, chamfers, and sheet metal tabs, but had **zero coverage for assemblies (`.iam`)**, kinematic mechanisms, subassembly hierarchy management, positional representations, material appearance overrides, camera showcase rendering, and OLE COM process stability.

During the development of the complex multi-zone **DINA Smart Vertical Freezer**, these architectural deficits resulted in:
1. Assemblies being treated as collections of unconstrained coordinate blocks.
2. Rigid static constraints accidentally freezing moving degrees of freedom without structured state management.
3. Subassemblies coming apart during drag operations because internal parts lacked rigidity.
4. Runaway background headless `Inventor.exe` processes deadlocking COM communication.

### Core Engineering Doctrine: Positional Representations vs. Native Joints
- **Standard Industrial CAD Workflow:** Mechanisms are assembled using standard parametric relationships (Mate, Flush, Angle). The range of motion and stroke limits are represented cleanly through **Autodesk Inventor Positional Representations (`PosReps`)** (`[Primary]`, `Porta_Aberta_Max`, `Gaveta_Aberta_Max`, `Posicao_Maxima`).
- **Native Joints Rule:** Native **Joints** (`add_assembly_joint`) are **NOT preferred by default** and must **ONLY be used when explicitly requested by the user**. When not asked, standard constraints paired with Positional Representations of the maximum travel positions are always used.

This document establishes the **exact technical changes required for the MCP server (`inventor_api.py`, `server.py`)** conforming strictly to the **MCP Python SDK (`mcp == 2.3.0`)**, the **updates to existing skills**, and the **specifications for 3 new specialized skills**, preparing the entire ecosystem to be packaged into a unified **Antigravity Inventor Plugin**.

---

# PART 1: Changes to the MCP Server (`inventor-mcp`) via MCP SDK (`mcp == 2.3.0`)

The upgraded MCP server leverages the full architecture of `mcp.server.mcpserver` (aliased as `FastMCP` for backward compatibility):
- **Cross-compatible Server Imports**: In `mcp == 2.3.0`, `FastMCP` was refactored into `MCPServer`. The server imports `from mcp.server.mcpserver import MCPServer as FastMCP, Context, Image` with legacy `mcp.server.fastmcp` fallback.
- **Type-safe Tool Definitions**: Parameters use `Annotated[T, Field(description="...")]` with Pydantic validation (cleanly assigning `= value` without redundant `default=` inside `Field`).
- **Context Injection (`Context`)**: Tools accept `ctx: Context` for real-time progress reporting (`await ctx.report_progress()`) and logging (`await ctx.info()`).
- **Rich Media Primitives (`Image`)**: CAD rendering endpoints return native `Image` objects rather than raw file path strings, enabling immediate visual inspection in agentic chat interfaces.
- **Dynamic MCP Resources (`@mcp.resource`)**: Assemblies expose live kinematics and document properties over URI protocols (`inventor://assembly/kinematics`, `inventor://status`).
- **Reusable Prompt Templates (`@mcp.prompt`)**: Built-in prompts for assembly auditing and kinematic state configuration.
- **Lifespan Management**: Graceful COM initialization, active GUI session attachment, and single-instance process supervisor.

---

## 1.1 Architecture & Core Class Changes in `src/inventor_api.py`

The `InventorConnection` class in `C:\Users\anton\Desktop\Teste Inventor MCP\inventor-mcp\src\inventor_api.py` must be upgraded from a Part-only wrapper to a **Unified Part & Assembly (`.iam`) Engine**.

### New Enums to Add to `inventor_api.py` (Verified via `RxInventor.tlb`):
```python
# Document Type Enums (Source: RxInventor.tlb)
kUnknownDocumentObject      = 12289
kPartDocumentObject         = 12290
kAssemblyDocumentObject     = 12291
kDrawingDocumentObject      = 12292
kPresentationDocumentObject = 12293

# Assembly Constraint Type Enums (ObjectTypeEnum from RxInventor.tlb)
kAngleConstraintObject   = 100665088
kInsertConstraintObject  = 100665344
kMateConstraintObject    = 100665856
kFlushConstraintObject   = 100666368
kTangentConstraintObject = 100667392

# Angle Constraint Solution Types (AngleConstraintSolutionTypeEnum from RxInventor.tlb)
kDirectedSolution        = 78593
kUndirectedSolution      = 78594  # Required for limits to evaluate
kReferenceVectorSolution = 78595

# Native Assembly Joint Type Enums (AssemblyJointTypeEnum from RxInventor.tlb)
kRigidJointType       = 102401
kRotationalJointType  = 102402
kSlideJointType       = 102403
kCylindricalJointType = 102404
kPlanarJointType      = 102405
kBallJointType        = 102406

# Visual Display Styles (DisplayModeEnum from RxInventor.tlb)
kWireframeRendering               = 8706
kHiddenEdgeRendering              = 8707
kShadedWithHiddenEdgesRendering   = 8707
kShadedRendering                  = 8708
kRealisticRendering               = 8709
kShadedWithEdgesRendering         = 8710
kWireframeNoHiddenEdges           = 8711
kWireframeWithHiddenEdgesRendering= 8712

# HealthStatusEnum (All 14 values verified from RxInventor.tlb)
kUnknownHealth        = 11777  # Safe default on unreadable health
kUpToDateHealth       = 11778  # Nominal healthy status
kOutOfDateHealth      = 11779
kDriverLostHealth     = 11780
kInErrorHealth        = 11781
kDeletedHealth        = 11782
kCannotComputeHealth  = 11783
kSuppressedHealth     = 11784
kBeyondStopNodeHealth = 11785
kInConsistentHealth   = 11786
kRedundantHealth      = 11787
kNewlyAddedHealth     = 11788
kInvalidLimitsHealth  = 11789
kJointDOFLockedHealth = 11790
```

---

### New Core Methods to Add to `InventorConnection` (`inventor_api.py`):

#### 1. Assembly Document Lifecycle
- `create_assembly(template_path=None) -> str`: Creates a new `.iam` document.
- `open_assembly(file_path, visible=True) -> str`: Opens an existing `.iam` document.
- `add_component(component_path, x_cm=0, y_cm=0, z_cm=0) -> str`: Adds a `.ipt` or `.iam` occurrence to the active assembly.

#### 2. Assembly Relationships & Constraints (Default Workflow)
- `add_assembly_constraint(occ1_name, entity1_type, entity1_idx, occ2_name, entity2_type, entity2_idx, constraint_type, offset_cm=0.0, name=None, limits=None) -> str`:
  - Handles proxy geometry creation across occurrences (`occ.CreateGeometryProxy`).
  - Supports Mate, Flush, and Angle constraints.
  - Automatically configures `.ConstraintLimits.MinimumEnabled`, `.Minimum.Expression`, `.MaximumEnabled`, `.Maximum.Expression`.
- `delete_constraint(name) -> bool`: Safely deletes an assembly relationship by name.

#### 3. Positional Representations (`RepresentationsManager.PositionalRepresentations`)
- `manage_positional_representation(action="activate", rep_name="Master", constraint_name=None, override_expression=None) -> str`:
  - `action="create"`: Adds a new named Positional Representation (`pos_reps.Add(rep_name)`).
  - `action="activate"`: Activates an existing representation (`rep.Activate()`), automatically updating the assembly.
  - `action="set_override"`: Applies parameter override to a specific constraint (`rep.SetConstraintValueOverride(target_c, override_expression)`).
  - `action="setup_standard_max_positions"`: Standard automated setup creating `Porta_Aberta_Max`, `Gaveta_Aberta_Max`, and `Posicao_Maxima`.
- `list_positional_representations() -> list[str]`: Enumerates all PosReps in the active assembly.

#### 4. Native Mechanism Joints (Use ONLY When Asked)
- `add_assembly_joint(occ1_name, entity1_name, occ2_name, entity2_name, joint_type="rotational", start_limit=None, end_limit=None, name=None) -> str`:
  - *Engineering Note: Used ONLY when explicitly requested by user.*
  - Creates `GeometryIntent` bindings.
  - Instantiates `AssemblyJointDefinition` (`kRotationalJointType` or `kSlideJointType`).
  - Directly applies `AngularPositionStartLimit` / `LinearPositionStartLimit` properties.
  - Instantiates the active joint in `cdef.Joints.Add(joint_def)`.

#### 5. Subassembly Hierarchy & Kinematic State
- `enforce_subassembly_rigidity(subasm_path_or_occ) -> int`:
  - Traverses all internal occurrences in a subassembly `.iam` and grounds them (`Grounded = True`) relative to the subassembly origin.
  - Prevents handles, tubs, LED bars, and liners from flying apart when the subassembly is dragged in the top assembly.
- `set_occurrence_flexible(occ_name, flexible=True) -> bool`:
  - Sets `occ.Flexible = True`, enabling internal degrees of freedom (like rotating carousel drum tiers or folding flaps) to evaluate at the top assembly level.
- `set_occurrence_grounded(occ_name, grounded=True) -> bool`:
  - Locks or unlocks an occurrence relative to the parent assembly origin.

#### 6. Kinematic Inspection & DOF Audit
- `audit_assembly_kinematics() -> dict`:
  - Inspects occurrences, grounded flags, flexible flags, constraint health statuses, native joints, and positional representations.
  - Detects unconstrained floating components and over-constrained rigid deadlocks.

#### 7. Parametric Motion Simulation
- `drive_kinematic_motion(target_name, start_val, end_val, steps=10, pause_sec=0.05, unit="deg") -> bool`:
  - Smoothly drives constraint or joint parameters across numeric ranges, forcing viewport updates to verify collision clearance.

#### 8. Appearance & Styling Overrides
- `apply_appearance(appearance_name, target_level="part", target_index=1, part_path=None) -> str`:
  - Resolves assets from document or Inventor Asset Libraries (e.g. `"Gold"`, `"Smooth - White"`, `"Aluminum - Polished"`, `"Clear Glass"`).
  - Applies to Part (`ActiveAppearance`), Body (`SurfaceBody.Appearance`), or Feature (`Feature.SetAppearance`).

#### 9. Camera & Viewport Showcase Rendering
- `render_showcase(output_png_path, eye_cm=(120, 100, 150), target_cm=(30, 50, 20), up_vec=(0, 1, 0), width=1920, height=1440, display_style="shaded_with_edges") -> str`:
  - Parametrically orients the camera (`cam.Eye`, `cam.Target`, `cam.UpVector`).
  - Calls `view.Fit()` and `view.SaveAsBitmap()`.

#### 10. Process Supervisor & Anti-Deadlock
- `supervisor_clean_orphaned_instances() -> int`:
  - Identifies duplicate headless background `Inventor.exe` processes that cause OLE COM deadlocks and terminates them, preserving the active user GUI instance.

---

## 1.2 Tool Endpoints in `src/server.py` (Latest FastMCP Syntax)

The following endpoints must be added to `C:\Users\anton\Desktop\Teste Inventor MCP\inventor-mcp\src\server.py`, using modern `FastMCP`, `Annotated`, `Field`, and `Context`:

```python
from typing import Annotated, Literal, Optional
from pydantic import Field
from mcp.server.fastmcp import FastMCP, Context, Image
from . import inventor_api as _api

# FastMCP Server Initialization with Lifespan
mcp = FastMCP(
    "Autodesk Inventor",
    instructions=(
        "MCP server for parametric 3D modeling and assembly kinematics in Autodesk Inventor. "
        "Supports parts (.ipt) and assemblies (.iam) with degrees-of-freedom verification. "
        "All dimensions are in millimeters."
    )
)

# 1. ADD ASSEMBLY CONSTRAINT
@mcp.tool()
async def add_assembly_constraint(
    occ1_name: Annotated[str, Field(description="Name of the first component occurrence")],
    entity1_type: Annotated[Literal["plane", "axis", "point", "face"], Field(description="Type of entity on occurrence 1")],
    entity1_idx: Annotated[int, Field(description="1-based index of the work entity or face on occurrence 1", ge=1)],
    occ2_name: Annotated[str, Field(description="Name of the second component occurrence")],
    entity2_type: Annotated[Literal["plane", "axis", "point", "face"], Field(description="Type of entity on occurrence 2")],
    entity2_idx: Annotated[int, Field(description="1-based index of the work entity or face on occurrence 2", ge=1)],
    constraint_type: Annotated[Literal["mate", "flush", "angle", "insert"], Field(description="Constraint relationship type")],
    offset_mm: Annotated[float, Field(description="Linear offset in mm or angle in degrees")] = 0.0,
    name: Annotated[Optional[str], Field(description="Descriptive engineering name for the constraint")] = None,
    min_limit: Annotated[Optional[str], Field(description="Minimum travel limit expression (e.g. '-220 mm' or '0 deg')")] = None,
    max_limit: Annotated[Optional[str], Field(description="Maximum travel limit expression (e.g. '0 mm' or '115 deg')")] = None,
    ctx: Context = None
) -> str:
    """Add a Mate, Flush, Angle, or Insert assembly constraint with optional range-of-motion limits."""
    if ctx:
        await ctx.info(f"Adding {constraint_type} constraint between {occ1_name} and {occ2_name}...")
    limits = None
    if min_limit or max_limit:
        limits = {"min": min_limit, "max": max_limit}
    return inv.add_assembly_constraint(
        occ1_name, entity1_type, entity1_idx,
        occ2_name, entity2_type, entity2_idx,
        constraint_type, offset_cm=offset_mm / 10.0,
        name=name, limits=limits
    )

# 2. ADD ASSEMBLY JOINT (USE ONLY WHEN EXPLICITLY REQUESTED)
@mcp.tool()
async def add_assembly_joint(
    occ1_name: Annotated[str, Field(description="First component occurrence")],
    occ2_name: Annotated[str, Field(description="Second component occurrence")],
    joint_type: Annotated[Literal["rotational", "slider", "cylindrical", "rigid"], Field(description="Native Inventor joint type")],
    entity1_name: Annotated[str, Field(description="Work geometry or face name on occurrence 1")],
    entity2_name: Annotated[str, Field(description="Work geometry or face name on occurrence 2")],
    start_limit: Annotated[Optional[str], Field(description="Minimum motion limit (e.g. '0 deg' or '0 mm')")] = None,
    end_limit: Annotated[Optional[str], Field(description="Maximum motion limit (e.g. '115 deg' or '220 mm')")] = None,
    name: Annotated[Optional[str], Field(description="Descriptive joint name")] = None,
    ctx: Context = None
) -> str:
    """Create a native Autodesk Inventor Assembly Joint (Revolute/Hinge or Slider). NOTE: Use ONLY when explicitly requested by the user. For standard mechanisms, use add_assembly_constraint and manage_positional_representations."""
    if ctx:
        await ctx.info(f"Instantiating {joint_type} joint '{name}'...")
    return inv.add_assembly_joint(
        occ1_name, entity1_name, occ2_name, entity2_name,
        joint_type=joint_type, start_limit=start_limit, end_limit=end_limit, name=name
    )

# 3. MANAGE SUBASSEMBLY KINEMATICS
@mcp.tool()
async def manage_subassembly_kinematics(
    action: Annotated[Literal["enforce_rigidity", "set_flexible", "set_grounded"], Field(description="Kinematic action to perform")],
    occurrence_name: Annotated[Optional[str], Field(description="Target occurrence name in the active assembly")] = None,
    value: Annotated[bool, Field(description="State value (e.g. True for flexible/grounded)")] = True,
    exclude_keywords: Annotated[Optional[list[str]], Field(description="Optional list of name keywords for dynamic parts to exclude from grounding")] = None,
    ctx: Context = None
) -> str:
    """Manage subassembly internal rigidity, occurrence grounding, and Flexible kinematics evaluation."""
    if action == "enforce_rigidity":
        res = inv.enforce_subassembly_rigidity(occurrence_name, exclude_keywords=exclude_keywords)
        return (
            f"Enforced internal rigidity: {res['newly_grounded_count']} parts grounded, "
            f"{res['skipped_count']} constrained parts skipped, "
            f"{res['skipped_moving_count']} parts excluded by keyword, "
            f"{res['skipped_detection_failed_count']} skipped due to COM query errors."
        )
    elif action == "set_flexible":
        res = inv.set_occurrence_flexible(occurrence_name, value)
        return f"Occurrence '{occurrence_name}' Flexible set to: {res}"
    elif action == "set_grounded":
        res = inv.set_occurrence_grounded(occurrence_name, value)
        return f"Occurrence '{occurrence_name}' Grounded set to: {res}"

# 4. INSPECT ASSEMBLY KINEMATICS
@mcp.tool()
def inspect_assembly_kinematics() -> str:
    """Audit the complete kinematic hierarchy of the active assembly, reporting grounded states, constraints, joints, HealthStatus errors, and floating parts."""
    report = inv.audit_assembly_kinematics()
    import json
    return json.dumps(report, indent=2, ensure_ascii=False)

# 5. DRIVE KINEMATIC MOTION
@mcp.tool()
async def drive_kinematic_motion(
    target_name: Annotated[str, Field(description="Name of the constraint or joint to drive")],
    start_value: Annotated[float, Field(description="Starting parameter value")],
    end_value: Annotated[float, Field(description="Final parameter value")],
    unit: Annotated[Literal["deg", "mm", "cm"], Field(description="Parameter units")] = "deg",
    steps: Annotated[int, Field(description="Number of intermediate interpolation steps", ge=1)] = 10,
    ctx: Context = None
) -> str:
    """Drive a constraint or joint across a travel range, simulating physical movement and clearance."""
    if ctx:
        await ctx.report_progress(0, steps)
    for i in range(steps + 1):
        cur_val = start_value + ((end_value - start_value) / steps) * i
        inv.set_constraint_expression(target_name, f"{cur_val} {unit}")
        if ctx:
            await ctx.report_progress(i, steps)
    return f"Successfully drove '{target_name}' from {start_value}{unit} to {end_value}{unit} across {steps} steps."

# 6. APPLY MATERIAL APPEARANCE
@mcp.tool()
def apply_material_appearance(
    appearance_name: Annotated[str, Field(description="Material appearance asset name (e.g. 'Gold', 'Smooth - White', 'Clear Glass')")],
    target_level: Annotated[Literal["part", "surface_body", "feature"], Field(description="Entity level to apply appearance")] = "part",
    target_index: Annotated[int, Field(description="1-based index of the surface body or feature", ge=1)] = 1
) -> str:
    """Apply an appearance asset override to a part, surface body, or individual feature (e.g. LED accents). Raises ValueError if asset is not found."""
    return inv.apply_appearance(appearance_name, target_level=target_level, target_index=target_index)

# 7. RENDER SHOWCASE VIEWPORT (RETURNING NATIVE IMAGE)
@mcp.tool()
def render_showcase_viewport(
    output_png_path: Annotated[str, Field(description="Destination file path for the captured image")],
    eye_x_cm: Annotated[float, Field(description="Camera eye position X coordinate (cm)")],
    eye_y_cm: Annotated[float, Field(description="Camera eye position Y coordinate (cm)")],
    eye_z_cm: Annotated[float, Field(description="Camera eye position Z coordinate (cm)")],
    target_x_cm: Annotated[float, Field(description="Camera focal target position X coordinate (cm)")],
    target_y_cm: Annotated[float, Field(description="Camera focal target position Y coordinate (cm)")],
    target_z_cm: Annotated[float, Field(description="Camera focal target position Z coordinate (cm)")],
    width: Annotated[int, Field(description="Image pixel width", ge=320)] = 1920,
    height: Annotated[int, Field(description="Image pixel height", ge=240)] = 1440,
    display_mode: Annotated[str, Field(description="Display style (shaded_edges, realistic, shaded, wireframe)")] = "shaded_edges",
    fit_view: Annotated[bool, Field(description="Whether to fit view before applying camera coordinates")] = False
) -> Image:
    """Position the viewport camera and export a high-resolution render, returned directly as an MCP Image."""
    out_path = inv.render_showcase(
        output_png_path,
        eye_cm=(eye_x_cm, eye_y_cm, eye_z_cm),
        target_cm=(target_x_cm, target_y_cm, target_z_cm),
        width=width, height=height,
        display_mode=display_mode, fit_view=fit_view
    )
    return Image(path=out_path)

# 8. SUPERVISOR PROCESS CLEANUP
@mcp.tool()
def supervisor_clean_processes(
    confirm: Annotated[bool, Field(description="Confirm termination of candidate orphaned background processes (default: False for dry-run)")] = False,
    target_pids: Annotated[Optional[list[int]], Field(description="List of specific PIDs from dry-run inspection to terminate")] = None
) -> str:
    """Audit and terminate runaway duplicate background Inventor processes. Defaults to dry-run (confirm=False). Requires explicit target_pids=[...] to terminate. Fails safe on unreadable start time."""
    res = inv.supervisor_clean_orphaned_instances(confirm=confirm, target_pids=target_pids)
    import json
    return json.dumps(res, indent=2)

# 9. MANAGE POSITIONAL REPRESENTATIONS (DEFAULT MECHANISM KINEMATICS)
@mcp.tool()
async def manage_positional_representations(
    action: Annotated[Literal["activate", "create", "set_override", "setup_standard_max_positions", "list"], Field(description="Action to perform on Positional Representations")],
    rep_name: Annotated[Optional[str], Field(description="Name of the Positional Representation (e.g. 'Primary', 'Porta_Aberta_Max', 'Gaveta_Aberta_Max', 'Posicao_Maxima')")] = "Primary",
    constraint_name: Annotated[Optional[str], Field(description="Name of the assembly constraint to override")] = None,
    override_expression: Annotated[Optional[str], Field(description="Parameter override expression (e.g. '115.0 deg', '-22.0 cm')")] = None,
    door_constraint_name: Annotated[Optional[str], Field(description="Door constraint name for setup_standard_max_positions")] = None,
    drawer_constraint_name: Annotated[Optional[str], Field(description="Drawer constraint name for setup_standard_max_positions")] = None,
    ctx: Context = None
) -> str:
    """Manage Autodesk Inventor Positional Representations (PosReps). Controls mechanism maximum states via standard constraint overrides."""
    if ctx:
        await ctx.info(f"Executing Positional Representation action: '{action}'...")
    if action == "activate":
        inv.activate_positional_representation(rep_name)
        return f"Activated Positional Representation: '{rep_name}'."
    elif action == "create":
        inv.create_positional_representation(rep_name)
        return f"Created Positional Representation: '{rep_name}'."
    elif action == "set_override":
        inv.set_constraint_override(rep_name, constraint_name, override_expression)
        return f"Applied override on '{constraint_name}' in PosRep '{rep_name}': {override_expression}"
    elif action == "setup_standard_max_positions":
        inv.setup_standard_max_position_representations(door_constraint_name, drawer_constraint_name)
        return "Standard Positional Representations (Porta_Aberta_Max, Gaveta_Aberta_Max, Posicao_Maxima) configured successfully."
    elif action == "list":
        reps = inv.list_positional_representations()
        import json
        return json.dumps(reps, indent=2)
```

---

## 1.3 Dynamic MCP Resources & Prompt Templates

In accordance with Model Context Protocol Specification V2 (FastMCP 2.0), the server exposes read-only CAD resources and reusable prompt templates:

### Dynamic MCP Resources (`@mcp.resource`)
```python
@mcp.resource("inventor://assembly/kinematics")
def get_assembly_kinematics_resource() -> str:
    """Provides real-time kinematic tree state (grounded occurrences, constraints, joints, free DOFs)."""
    import json
    return json.dumps(inv.audit_assembly_kinematics(), indent=2)

@mcp.resource("inventor://assembly/representations")
def get_assembly_representations_resource() -> str:
    """Provides active and available Positional Representations in the active assembly."""
    import json
    return json.dumps(inv.list_positional_representations(), indent=2)

@mcp.resource("inventor://status")
def get_status_resource() -> str:
    """Provides active document path, document type, units, and software version."""
    import json
    return json.dumps(inv.get_document_info(), indent=2)
```

### Prompt Templates (`@mcp.prompt`)
```python
@mcp.prompt("audit_assembly")
def audit_assembly_prompt(assembly_name: str = ""):
    """Guide the agent to audit assembly degrees of freedom, grounded datums, and mechanism representations."""
    return f"Audit the assembly '{assembly_name}'. Verify that the base chassis is Grounded, internal subassembly parts are rigid, and kinematic mechanisms are properly configured using standard constraints and Positional Representations for maximum positions (using native Joints only if explicitly requested)."
```

---

# PART 2: Changes to Existing MCP Skills (`inventor-modeling`)

The file `C:\Users\anton\.gemini\config\skills\inventor-modeling\SKILL.md` must be updated with the following 4 engineering sections:

### 2.1 The "Hollow Enclosure" Rule vs. Solid Block Occlusion
- **The Problem:** Emitting a single solid rectangular extrusion for a cabinet or chassis creates an opaque block that conceals all interior components when subassemblies are merged.
- **The Rule:** Always model hollow enclosures either by creating a secondary sketch and cutting out internal cavities (`extrude(..., operation="cut")`), or applying `create_shell(thickness, open_face_indices)`.

### 2.2 Feature-Level Appearance Assignment Doctrine
- When components feature illuminated elements (e.g. RGB rings, LED bars, touch displays), agents must never leave them sharing the default base body material.
- Feature appearances must be assigned via `apply_material_appearance` with `target_level="feature"` immediately after the feature is generated.

### 2.3 The Polygon Circumradius vs. Apothem Invariant
- For regular hex heads, nuts, and sectors, `draw_polygon` takes the **circumradius** ($R = s / \sqrt{3}$), not the width across flats or apothem ($s / 2$).

### 2.4 Document Save and Dirty State Management
- Never attempt to overwrite an open document via `save_document` without checking if it is actively checked out or dirty. Handle `E_INVALIDARG (-2147024809)` by calling `app.ActiveDocument.Save()`.

---

# PART 3: Specifications for 3 New MCP-Related Skills

To structure AI behavior across different CAD engineering disciplines, we establish 3 new skills:

---

## Skill 1: `inventor-assemblies`
**Path:** `C:\Users\anton\.gemini\config\skills\inventor-assemblies\SKILL.md`  
**Description:** Assembly architecture, bottom-up insertion, coordinate reference datum alignment, subassembly internal rigidity rules, and constraint management in Autodesk Inventor via the `inventor` MCP server.

### Core Doctrine to Enforce:
1. **Stationary Datum Grounding**:
   - The primary chassis or cabinet must always be grounded as the immovable world datum:
     `manage_subassembly_kinematics(action="set_grounded", occurrence_name="1A_Gabinete", value=True)`.
2. **Subassembly Internal Rigidity Rule**:
   - Before inserting a subassembly (e.g. a door with handles and display, or a drawer with tub and slides) into a top-level assembly, all internal parts within that subassembly `.iam` must be grounded:
     `manage_subassembly_kinematics(action="enforce_rigidity", occurrence_name="4A_Gaveta")`.
   - *Failure to follow this rule causes individual parts to fly off when the user clicks and drags the subassembly in the top assembly.*
3. **Geometry Proxy Binding**:
   - Entities belonging to occurrences cannot be mated directly; they must always be wrapped via `occ.CreateGeometryProxy(entity)`.

---

## Skill 2: `inventor-kinematics`
**Path:** `C:\Users\anton\.gemini\config\skills\inventor-kinematics\SKILL.md`  
**Description:** Mechanism kinematics, degrees of freedom (DOF), positional representations (`PosReps`), native joints (`kRotationalJointType`, `kSlideJointType`), motion limits, and multi-tier flexible indexing in Autodesk Inventor via the `inventor` MCP server.

### Core Doctrine to Enforce:
1. **The Anti-Locking Rule (Never Freeze Intended Motion Permanently)**:
   - When modeling parts intended to move (e.g. doors, drawers, levers, rotors), **never** apply an unconstrained fixed constraint that permanently locks the part across all states.
   - Constrain the part at its nominal reference state ($0^\circ$ or $0\text{ mm}$), and configure **Positional Representations** for kinematics.
2. **Positional Representations Doctrine (Default Mechanism Workflow)**:
   - **Do NOT prefer native Joints (`add_assembly_joint`) by default.** Use native joints **ONLY when explicitly requested by the user** (e.g. when interactive live drag or physics simulation is specifically required).
   - **When NOT requested, standard constraints paired with Positional Representations (`PosReps`) of maximum positions MUST be used:**
     * `[Master]` / `Fechado`: Baseline nominal state (Door closed at $0^\circ$, Drawer closed at $0\text{ mm}$, Drum index at $0^\circ$).
     * `Porta_Aberta_Max`: Angle constraint overridden to $115.0^\circ$ via `SetConstraintValueOverride`.
     * `Gaveta_Aberta_Max`: Slide flush constraint overridden to $-22.0\text{ cm}$ ($-220\text{ mm}$).
     * `Posicao_Maxima`: Both door and drawer set concurrently to maximum travel positions for total envelope and clearance validation.
   - Use `manage_positional_representations` to switch between states or define new positions.
3. **Native Joints Rule (On-Demand Only)**:
   - Instantiate native `AssemblyJoint` objects (`kRotationalJointType`, `kSlideJointType`) *strictly* when the user explicitly prompts for joints.
4. **Multi-Tier Indexing via `Flexible = True`**:
   - For internal mechanisms (like carousel drums or planetary gears) to rotate inside a parent assembly, the subassembly occurrence must have `Flexible = True` enabled.

---

## Skill 3: `inventor-diagnostics`
**Path:** `C:\Users\anton\.gemini\config\skills\inventor-diagnostics\SKILL.md`  
**Description:** Autodesk Inventor process management, OLE COM deadlock prevention, orphan cleanup, modal dialog mitigation, and FeatureManager rebuild diagnostics.

### Core Doctrine to Enforce:
1. **Single-Instance Enforcement**:
   - Runaway headless instances of `Inventor.exe` occur when Python scripts call `Dispatch` without handling ROT registration.
   - Run `supervisor_clean_processes()` before launching multi-step automation pipelines.
2. **Interactive Session Respect**:
   - If the user has Inventor open on their desktop with an active command or dialog, out-of-process COM calls block until the user dismisses the dialog.

---

# PART 4: Antigravity Plugin Packaging Architecture

The entire suite can now be bundled and distributed as the **`inventor-plugin`**:

```
.gemini/config/plugins/inventor-plugin/
├── plugin.json
├── rules/
│   └── INVENTOR_RULES.md
├── skills/
│   ├── inventor-modeling/
│   │   └── SKILL.md
│   ├── inventor-assemblies/
│   │   └── SKILL.md
│   ├── inventor-kinematics/
│   │   └── SKILL.md
│   └── inventor-diagnostics/
│       └── SKILL.md
├── mcp/
│   └── inventor/
│       ├── (36 base tool JSONs)
│       ├── create_assembly.json
│       ├── add_component.json
│       ├── add_assembly_constraint.json
│       ├── delete_assembly_constraint.json
│       ├── add_assembly_joint.json
│       ├── delete_assembly_joint.json
│       ├── manage_subassembly_kinematics.json
│       ├── inspect_assembly_kinematics.json
│       ├── drive_kinematic_motion.json
│       ├── apply_material_appearance.json
│       ├── render_showcase_viewport.json
│       ├── supervisor_clean_processes.json
│       └── manage_positional_representations.json
└── src/
    ├── inventor_api.py (Unified Part + Assembly Engine)
    ├── updater.py (Safe Background Auto-Updater with Rollback)
    └── server.py (FastMCP 2.0 Server with 51 Tools, 3 Resources & 1 Prompt)
```

### Manifest `plugin.json` Specification:
```json
{
  "name": "inventor-plugin",
  "version": "2.0.0",
  "description": "Enterprise Autodesk Inventor Professional 2026/2027 Automation Suite: Parametric Parts, Top-Down Assemblies, Positional Representations, Kinematics, and Photorealistic Showcase Rendering conforming to Model Context Protocol SDK (mcp == 2.3.0).",
  "author": "Antonio Coelho",
  "skills": [
    "skills/inventor-modeling",
    "skills/inventor-assemblies",
    "skills/inventor-kinematics",
    "skills/inventor-diagnostics"
  ],
  "mcpServers": {
    "inventor": {
      "command": "python",
      "args": ["-u", "src/server.py"]
    }
  }
}
```

---

## Summary of Files in `new_tools_inventor/`

The folder `C:\Users\anton\Desktop\new_tools_inventor\` now contains the full blueprint and the exact Python implementations conforming to MCP SDK `mcp == 2.3.0`:
1. `new_changes.md`: This comprehensive MCP SDK 2.x and Skills blueprint.
2. `inventor_mcp_review_bundle.md`: The complete unified 1,850+ line master document containing the blueprint, all tool codes, dynamic resources, skills, plugin manifest, and empirical smoke test reports for Claude review.
3. `01_manage_assembly_constraints.py`: Backend code for `add_assembly_constraint`.
4. `02_manage_assembly_joints.py`: Backend code for `add_assembly_joint` (Reserved for on-demand joint requests).
5. `03_manage_subassembly_kinematics.py`: Backend code for `manage_subassembly_kinematics` (Single-pass rigidity scan, error fail-safe, keyword exclusions, Grounding, Flexibility).
6. `04_inspect_assembly_mechanisms.py`: Backend code for `inspect_assembly_kinematics` (Complete 14 HealthStatusEnum check, floating part detection).
7. `05_drive_kinematic_motion.py`: Backend code for `drive_kinematic_motion`.
8. `06_apply_material_appearances.py`: Backend code for `apply_material_appearance`.
9. `07_render_perspective_showcase.py`: Backend code for `render_showcase_viewport` (Native MCP `Image` return, `fit_view=False` preserving camera distance).
10. `08_inventor_process_supervisor.py`: Backend code for `supervisor_clean_processes` (Fails safe on unreadable start time, re-checks PID after kill, dry-run by default).
11. `09_manage_positional_representations.py`: Backend code for `manage_positional_representations` (Creates and manages `[Primary]`, `Porta_Aberta_Max`, `Gaveta_Aberta_Max`, `Posicao_Maxima` via constraint overrides with string try and internal numeric fallback).
