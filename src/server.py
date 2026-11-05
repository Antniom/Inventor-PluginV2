"""MCP Server for Autodesk Inventor parametric modeling."""

import json
from typing import Annotated, Literal, Optional
from pydantic import Field
try:
    from mcp.server.mcpserver import MCPServer as FastMCP, Context, Image
except (ImportError, ModuleNotFoundError):
    from mcp.server.fastmcp import FastMCP, Context, Image
from . import inventor_api as _api
from . import updater as _updater

mcp = FastMCP(
    "Autodesk Inventor",
    instructions=(
        "MCP server for parametric 3D modeling and assembly kinematics in Autodesk Inventor. "
        "Supports parts (.ipt) and assemblies (.iam) with degrees-of-freedom verification. "
        "All linear dimensions are in millimeters; angles are in degrees. "
        "Kinematic Doctrine: Standard constraints (Mate/Flush/Angle) paired with Positional "
        "Representations (PosReps) are used by default for mechanism maximum travel positions. "
        "Native Joints (add_assembly_joint) are ONLY used when explicitly requested by user. "
        "Typical workflow: connect → create_part/create_assembly → add features/components → save. "
        "For anything not covered by a dedicated tool, use execute_python "
        "(persistent namespace, live inv/app/comp/body/tg objects). "
        "After editing inventor_api.py on disk, call reload_api — no server restart needed."
    ),
)

inv = _api.InventorConnection()

# Persistent namespace for execute_python (variables survive between calls)
_exec_ns: dict = {}


# ---------- Power tools (token savers) ----------

@mcp.tool()
def execute_python(code: str) -> str:
    """Execute Python code against the live Inventor connection.

    Pre-bound objects (re-resolved fresh on every call):
      inv  — InventorConnection wrapper (all high-level methods, mm units)
      app  — Inventor.Application COM object
      doc  — active document          comp — its ComponentDefinition
      body — comp.SurfaceBodies.Item(1) (or None)
      tg   — TransientGeometry        math — math module
    Variables you assign persist between calls (one shared namespace).
    Internal COM units are CENTIMETERS — divide mm by 10.
    Returns captured stdout (print your results!) or the traceback on error.
    """
    import io, contextlib, traceback, math as _math
    ctx = {"inv": inv, "math": _math}
    try:
        if not inv.is_connected():
            inv.connect()
        ctx["app"] = inv.app
        ctx["tg"] = inv.app.TransientGeometry
        ctx["doc"] = inv.app.ActiveDocument
        if ctx["doc"] is not None:
            ctx["comp"] = ctx["doc"].ComponentDefinition
            try:
                ctx["body"] = ctx["comp"].SurfaceBodies.Item(1)
            except Exception:
                ctx["body"] = None
    except Exception:
        pass
    _exec_ns.update(ctx)
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            exec(compile(code, "<mcp>", "exec"), _exec_ns)
        out = buf.getvalue().strip()
        if len(out) > 6000:
            out = out[:6000] + "\n... (truncated at 6000 chars)"
        return out if out else "(ok, no output)"
    except Exception:
        partial = buf.getvalue().strip()
        tb = traceback.format_exc(limit=3)
        return (partial + "\n" if partial else "") + f"ERROR:\n{tb}"


@mcp.tool()
def reload_api() -> str:
    """Hot-reload inventor_api.py from disk. Use after editing the wrapper —
    no Claude Code restart needed. Keeps the existing COM connection."""
    st = _updater.load_state()
    if st.get("restart_required"):
        return (
            "Refusing reload: A plugin update has been applied to disk and a server restart is pending. "
            "Hot-reloading inventor_api.py would cause a version mismatch with the running server. "
            "Please restart the MCP server process instead."
        )
    import importlib
    global inv
    importlib.reload(_api)
    old_app = inv._app
    inv = _api.InventorConnection()
    inv._app = old_app
    _exec_ns.clear()
    return "inventor_api.py reloaded (connection preserved)"


@mcp.tool()
def inspect() -> str:
    """Compact snapshot of the active part: volume, bbox, faces/edges count,
    feature tree with names, sketches, sheet metal thickness. One call instead
    of several diagnostic queries."""
    return json.dumps(inv.inspect(), indent=1, ensure_ascii=False)


@mcp.tool()
def list_edges(min_length: float = 0, max_count: int = 60) -> str:
    """Compact edge table of body 1: '[i] L=200.0 mid=(0.0,-225.0,0.8)' per line.
    Use to locate edges for flange/fillet/chamfer. min_length filters small edges (mm)."""
    return inv.list_edges(min_length=min_length, max_count=max_count)


@mcp.tool()
def list_faces(min_area: float = 0, max_count: int = 60) -> str:
    """Compact face table of body 1: '[i] Plane A=90000 c=(0.0,225.0,12.5)' per line.
    Use to locate faces for sketching/cuts. min_area filters small faces (mm²)."""
    return inv.list_faces(min_area=min_area, max_count=max_count)


@mcp.tool()
def transaction(action: str = "begin", name: str = "MCP batch") -> str:
    """Wrap multiple operations in one undo unit with rollback.

    Args:
        action: "begin" before a risky multi-step build, then "commit" on success
                or "abort" to roll back EVERYTHING since begin in one step.
        name: label shown in Inventor's undo list.
    """
    return inv.transaction(action, name)


# ---------- Connection ----------

@mcp.tool()
def connect(visible: bool = True) -> str:
    """Connect to Autodesk Inventor. Starts Inventor if not running.

    Args:
        visible: Show Inventor window (default True).
    """
    return inv.connect(visible)


@mcp.tool()
def status() -> str:
    """Check connection status, active document info, and plugin updater state."""
    updater_summary = _updater.get_updater_status_summary()
    if not inv.is_connected():
        return json.dumps({
            "connected": False,
            "status": "Not connected to Inventor. Call connect() first.",
            "updater": updater_summary,
        }, indent=2, ensure_ascii=False)
    try:
        info = inv.get_document_info()
        res = dict(info) if isinstance(info, dict) else {"document": info}
        res["updater"] = updater_summary
        return json.dumps(res, indent=2, ensure_ascii=False)
    except RuntimeError:
        return json.dumps({
            "connected": True,
            "status": "Connected to Inventor, but no document is open.",
            "updater": updater_summary,
        }, indent=2, ensure_ascii=False)


# ---------- Document management ----------

@mcp.tool()
def create_part(name: str = "", template: str = "metric") -> str:
    """Create a new empty part document.

    Args:
        name: Display name for the part (optional).
        template: Template type — "metric" (mm, default), "english" (inches), or full path to .ipt file.
    """
    return inv.create_part(name or None, template)


@mcp.tool()
def save_document(path: str = "") -> str:
    """Save the active document.

    Args:
        path: Full file path to save as (e.g. "D:/parts/flange.ipt"). If empty, saves in place.
    """
    return inv.save_document(path or None)


@mcp.tool()
def export_document(path: str, format: str = "STEP") -> str:
    """Export active document to another format.

    Args:
        path: Output file path (e.g. "D:/export/part.step").
        format: Export format — STEP, STL, SAT, or IGES.
    """
    return inv.export_document(path, format)


# ---------- Sketches ----------

@mcp.tool()
def create_sketch(plane: str = "XY", face_index: int = 0, offset: float = 0) -> str:
    """Create a new sketch on a work plane, a body face, or an offset work plane.

    Args:
        plane: Work plane — XY, XZ, or YZ. Ignored if face_index > 0.
        face_index: Index of body face to sketch on (1-based). 0 = use work plane. Use list_faces() to locate.
        offset: mm — sketch on a hidden work plane parallel to 'plane' at this distance
                (positive = along plane normal: XY→+Z, XZ→+Y, YZ→+X). For ribs/bosses at a height.
    """
    fi = face_index if face_index > 0 else None
    return inv.create_sketch(plane, fi, offset)


@mcp.tool()
def draw_rectangle(
    x: float = 0, y: float = 0,
    width: float = 100, height: float = 50,
    sketch_index: int = 0,
) -> str:
    """Draw a centered rectangle in a sketch. Dimensions in mm.

    Args:
        x: Center X coordinate in mm.
        y: Center Y coordinate in mm.
        width: Width in mm.
        height: Height in mm.
        sketch_index: Sketch number (0 = latest sketch).
    """
    idx = sketch_index if sketch_index > 0 else None
    return inv.draw_rectangle(x, y, width, height, idx)


@mcp.tool()
def draw_circle(
    x: float = 0, y: float = 0,
    diameter: float = 50,
    sketch_index: int = 0,
    construction: bool = False,
) -> str:
    """Draw a circle in a sketch with an automatic diameter dimension. Dimensions in mm.

    Args:
        x: Center X coordinate in mm.
        y: Center Y coordinate in mm.
        diameter: Diameter in mm. A diameter constraint is added automatically.
        sketch_index: Sketch number (0 = latest sketch).
        construction: If True, draws a reference (construction) circle — not part of profile.
                      Useful for showing bolt PCD (pitch circle diameter) without cutting.
    """
    idx = sketch_index if sketch_index > 0 else None
    return inv.draw_circle(x, y, diameter, idx, construction)


@mcp.tool()
def draw_line(
    x1: float = 0, y1: float = 0,
    x2: float = 100, y2: float = 0,
    sketch_index: int = 0,
    construction: bool = False,
) -> str:
    """Draw a line in a sketch. Coordinates in mm.

    Args:
        x1: Start X in mm.
        y1: Start Y in mm.
        x2: End X in mm.
        y2: End Y in mm.
        sketch_index: Sketch number (0 = latest sketch).
        construction: If True, line becomes a construction line (used as revolve axis, not part of profile).
    """
    idx = sketch_index if sketch_index > 0 else None
    return inv.draw_line(x1, y1, x2, y2, idx, construction)


@mcp.tool()
def draw_polygon(
    x: float = 0, y: float = 0,
    radius: float = 25,
    sides: int = 6,
    sketch_index: int = 0,
) -> str:
    """Draw a regular polygon in a sketch. Dimensions in mm.

    Args:
        x: Center X in mm.
        y: Center Y in mm.
        radius: Circumscribed radius in mm.
        sides: Number of sides (e.g. 6 for hexagon).
        sketch_index: Sketch number (0 = latest sketch).
    """
    idx = sketch_index if sketch_index > 0 else None
    return inv.draw_polygon(x, y, radius, sides, idx)


@mcp.tool()
def draw_closed_profile(
    points: str,
    sketch_index: int = 0,
) -> str:
    """Draw a closed profile (polygon) from connected points. All coordinates in mm.
    Lines share endpoints so Inventor recognizes the closed loop for extrude/revolve.

    Args:
        points: JSON array of [x,y] pairs in mm. Example: "[[0,0],[50,0],[25,40]]" for a triangle.
        sketch_index: Sketch number (0 = latest sketch).
    """
    import json as _json
    pts = _json.loads(points)
    idx = sketch_index if sketch_index > 0 else None
    return inv.draw_closed_profile(pts, idx)


# ---------- Features ----------

@mcp.tool()
def extrude(
    distance: float = 10,
    direction: str = "positive",
    operation: str = "join",
    sketch_index: int = 0,
    extent_type: str = "distance",
) -> str:
    """Extrude a sketch profile to create 3D geometry. Distance in mm.

    Args:
        distance: Extrusion distance in mm. Ignored when extent_type="all".
        direction: Direction — positive, negative, or symmetric.
        operation: Boolean operation — join, cut, intersect, surface, or new.
        sketch_index: Sketch number to extrude (0 = latest sketch).
        extent_type: Extent type — "distance" (fixed distance, default) or "all" (through entire body).
    """
    idx = sketch_index if sketch_index > 0 else None
    return inv.extrude(distance, direction, operation, idx, extent_type=extent_type)


@mcp.tool()
def revolve(
    angle: float = 360,
    axis: str = "Y",
    sketch_index: int = 0,
    operation: str = "join",
) -> str:
    """Revolve a sketch profile around a work axis to create or cut 3D geometry.

    PREFERRED workflow — no construction line needed in sketch:
      1. create_sketch("XY")
      2. draw_closed_profile([[0,0],[30,0],[30,8],[15,60],[0,60]])  ← profile only
      3. revolve(axis="Y", operation="join")

    For a revolve CUT (e.g. groove):
      1. create_sketch("XY")
      2. draw_closed_profile([[8,26],[15,26],[15,34],[8,34]])  ← groove cross-section
      3. revolve(axis="Y", operation="cut")

    Profile must be on one side of the axis (all X ≥ 0 when axis="Y").

    Args:
        angle: Revolution angle in degrees (360 = full revolution, default).
        axis: Rotation axis — "X", "Y", or "Z". Default "Y" for lathe parts on XY plane.
        sketch_index: Sketch number (0 = latest sketch).
        operation: Boolean operation — join (add material), cut (remove), intersect, or new.
    """
    idx = sketch_index if sketch_index > 0 else None
    return inv.revolve(angle, idx, axis, operation)


@mcp.tool()
def fillet(radius: float = 2, edge_indices: str = "1") -> str:
    """Add fillet (rounded edge) to edges of the solid body. Radius in mm.

    Args:
        radius: Fillet radius in mm.
        edge_indices: Comma-separated edge indices (e.g. "1,2,3"). Use status() to see edge count.
    """
    indices = [int(i.strip()) for i in edge_indices.split(",")]
    return inv.fillet(radius, indices)


@mcp.tool()
def chamfer(distance: float = 2, edge_indices: str = "1") -> str:
    """Add chamfer (angled edge) to edges of the solid body. Distance in mm.

    Args:
        distance: Chamfer distance in mm.
        edge_indices: Comma-separated edge indices (e.g. "1,2,3").
    """
    indices = [int(i.strip()) for i in edge_indices.split(",")]
    return inv.chamfer(distance, indices)


@mcp.tool()
def hole(
    x: float = 0, y: float = 0,
    diameter: float = 10,
    depth: float = 0,
    tapped: bool = False,
    pitch: float = 0,
) -> str:
    """Create a native Inventor HoleFeature. Dimensions in mm.
    Creates a proper Hole feature (not extrude cut) — works with circular_pattern.
    Supports both plain drilled holes and tapped (threaded) metric holes.

    Args:
        x: Hole center X in mm.
        y: Hole center Y in mm.
        diameter: Hole diameter in mm. For tapped holes this is the nominal thread diameter (e.g. 16 for M16).
        depth: Hole depth in mm. 0 = through-all (default).
        tapped: True = create tapped (threaded) hole with ISO Metric profile (6H). False = plain drilled hole.
        pitch: Thread pitch in mm (e.g. 2.0 for M16x2). 0 = auto-select standard coarse pitch.
    """
    p = pitch if pitch > 0 else None
    return inv.hole(x, y, diameter, depth, tapped, p)


@mcp.tool()
def hole_linear(
    face_axis: str, face_value: float,
    ref1_axis: str, ref1_value: float, dist1: float,
    ref2_axis: str, ref2_value: float, dist2: float,
    diameter: float = 5.5,
    depth: float = 0,
    tapped: bool = False,
    pitch: float = 0,
    cbore_diameter: float = 0,
    cbore_depth: float = 0,
) -> str:
    """Hole placed parametrically from two edges of a face (Linear placement).
    Survives part resizing — hole keeps its distance from the edges.
    Drill direction resolved automatically (volume check).

    Args:
        face_axis/face_value: planar face to drill into, e.g. ("z", 25) = top face at Z=25mm.
        ref1_axis/ref1_value/dist1: first edge of that face + distance from it, e.g. ("x", -34.5, 8).
        ref2_axis/ref2_value/dist2: second edge + distance.
        diameter: hole diameter mm (or thread nominal if tapped, e.g. 5 for M5).
        depth: 0 = through-all, otherwise depth in mm.
        tapped: True = ISO metric thread 6H (standard coarse pitch unless pitch given).
        pitch: thread pitch mm (0 = auto standard coarse).
        cbore_diameter/cbore_depth: >0 adds counterbore seat (M5 ISO 4762: 10 and 5.5).
    """
    p = pitch if pitch > 0 else None
    return inv.hole_linear(face_axis, face_value, ref1_axis, ref1_value, dist1,
                           ref2_axis, ref2_value, dist2, diameter, depth,
                           tapped, p, cbore_diameter, cbore_depth)


@mcp.tool()
def circular_pattern(
    feature_index: int,
    count: int = 8,
    angle: float = 360,
    axis: str = "Z",
) -> str:
    """Create a circular (rotational) pattern of a feature around a work axis.
    Ideal for bolt holes around a flange — one hole + circular_pattern instead of 8 holes.

    Args:
        feature_index: Index of the feature to pattern (from list_features()).
        count: Number of instances (total including the original).
        angle: Total span angle in degrees (360 = full circle).
        axis: Rotation axis — X, Y, or Z (default Z for flanges).
    """
    return inv.circular_pattern(feature_index, count, angle, axis)


# ---------- Parameters ----------

@mcp.tool()
def get_parameters() -> str:
    """Get all parameters of the active document. Returns JSON list."""
    params = inv.get_parameters()
    return json.dumps(params, indent=2, ensure_ascii=False)


@mcp.tool()
def set_parameter(name: str, expression: str) -> str:
    """Set a parameter value by name.

    Args:
        name: Parameter name (e.g. "d0", "width").
        expression: New value or expression (e.g. "50 mm", "d0 * 2").
    """
    return inv.set_parameter(name, expression)


@mcp.tool()
def add_parameter(name: str, expression: str, units: str = "mm") -> str:
    """Add a new user parameter.

    Args:
        name: Parameter name (e.g. "flange_diameter").
        expression: Value or expression (e.g. "100", "width * 2").
        units: Units — mm, cm, m, deg, etc.
    """
    return inv.add_parameter(name, expression, units)


# ---------- Sheet Metal ----------

@mcp.tool()
def set_sheet_metal_thickness(thickness: float = 0.8) -> str:
    """Set the active sheet metal style's thickness. Use after create_part(template="sheet_metal")."""
    return inv.set_sheet_metal_thickness(thickness)


@mcp.tool()
def sheet_metal_face(sketch_index: int = 0) -> str:
    """Create a base Sheet Metal Face from a closed sketch profile.
    The first flat panel in a sheet metal part. Uses style's Thickness automatically."""
    idx = sketch_index if sketch_index > 0 else None
    return inv.sheet_metal_face(idx)


@mcp.tool()
def flange(edge_indices: str, distance: float = 25, angle: float = 90) -> str:
    """Add a Sheet Metal Flange (bent wall) to one or more edges.

    Real sheet-metal feature (vs Extrude) — supports Flat Pattern unfolding,
    has proper bend radius, depth ties to Thickness.

    Args:
        edge_indices: Comma-separated edge indices (use find_edge to locate).
        distance: Flange height in mm (default 25 = Inventor default).
        angle: Bend angle in degrees (default 90 = perpendicular).
    """
    idx_list = [int(i.strip()) for i in edge_indices.split(",")]
    return inv.flange(idx_list, distance, angle)


@mcp.tool()
def sheet_metal_cut(sketch_index: int = 0) -> str:
    """Cut through the panel — depth = Thickness automatically (parametric!).
    Sketch should be on the panel face (not a work plane) for correct behavior.
    One sketch with multiple closed shapes = one Cut feature with multiple holes.
    """
    idx = sketch_index if sketch_index > 0 else None
    return inv.sheet_metal_cut(idx)


@mcp.tool()
def find_edge(x: float = 0, y: float = 0, z: float = 0,
              use_x: bool = False, use_y: bool = False, use_z: bool = False,
              tolerance: float = 0.1) -> str:
    """Find an edge by its midpoint coordinates (mm). Returns edge index (string).
    Useful for flange — locate the edge to bend without printing all edges.

    Args:
        x/y/z: Target midpoint coordinates (mm).
        use_x/y/z: Set True for each coord that should be matched (False = ignored).
        tolerance: How close midpoint must be (mm). Default 0.1.
    """
    kwargs = {}
    if use_x: kwargs['x'] = x
    if use_y: kwargs['y'] = y
    if use_z: kwargs['z'] = z
    idx = inv.find_edge(tolerance=tolerance, **kwargs)
    return f"Edge {idx}"


@mcp.tool()
def find_face(x: float = 0, y: float = 0, z: float = 0,
              use_x: bool = False, use_y: bool = False, use_z: bool = False,
              min_area: float = 100, tolerance: float = 0.5) -> str:
    """Find a planar face by its centroid coordinates (mm). Returns face index (string).
    Useful for sheet metal Cut — locate the outer panel face to sketch on.

    Args:
        x/y/z: Target centroid coordinates (mm).
        use_x/y/z: Set True for each coord that should be matched.
        min_area: Minimum area in mm² (filters tiny edge faces). Default 100.
        tolerance: Centroid match tolerance (mm). Default 0.5.
    """
    kwargs = {}
    if use_x: kwargs['x'] = x
    if use_y: kwargs['y'] = y
    if use_z: kwargs['z'] = z
    idx = inv.find_face(min_area=min_area, tolerance=tolerance, **kwargs)
    return f"Face {idx}"


# ---------- Query ----------

@mcp.tool()
def list_features() -> str:
    """List all features in the active part. Returns JSON list."""
    features = inv.list_features()
    return json.dumps(features, indent=2, ensure_ascii=False)


@mcp.tool()
def delete_feature(indices: str) -> str:
    """Delete one or more features by index. Use list_features() to find indices.

    Args:
        indices: Comma-separated feature indices to delete (e.g. "3,4,5"). Deletes in reverse order automatically.
    """
    idx_list = [int(i.strip()) for i in indices.split(",")]
    return inv.delete_feature(idx_list)


@mcp.tool()
def suppress_feature(indices: str, suppressed: bool = True) -> str:
    """Suppress or unsuppress features (hide without deleting). Use list_features() to find indices.

    Args:
        indices: Comma-separated feature indices (e.g. "3,4,5").
        suppressed: True to suppress (hide), False to unsuppress (show).
    """
    idx_list = [int(i.strip()) for i in indices.split(",")]
    return inv.suppress_feature(idx_list, suppressed)


# ---------- Assembly & Kinematics tools ----------

@mcp.tool()
def create_assembly(name: str | None = None, template: str = "metric") -> str:
    """Create a new Autodesk Inventor assembly document (.iam).
    template can be 'metric' (Standard (mm).iam) or a custom template file path.
    """
    return inv.create_assembly(name=name, template=template)


@mcp.tool()
def add_component(
    component_path: Annotated[str, Field(description="Full or relative path to .ipt or .iam component file")],
    x_mm: Annotated[float, Field(description="X placement coordinate in millimeters", default=0.0)] = 0.0,
    y_mm: Annotated[float, Field(description="Y placement coordinate in millimeters", default=0.0)] = 0.0,
    z_mm: Annotated[float, Field(description="Z placement coordinate in millimeters", default=0.0)] = 0.0,
) -> str:
    """Insert a component occurrence (.ipt or .iam) into the active assembly document.
    Input coordinates are in millimeters.
    """
    return inv.add_component(component_path=component_path, x=x_mm, y=y_mm, z=z_mm)


@mcp.tool()
async def add_assembly_constraint(
    occ1_name: Annotated[str, Field(description="Name of the first component occurrence in assembly")],
    entity1_type: Annotated[Literal["plane", "axis", "point", "face", "edge"], Field(description="Type of entity on occurrence 1")],
    entity1_idx: Annotated[int, Field(description="1-based index or name of the work entity or face/edge on occurrence 1", ge=1)],
    occ2_name: Annotated[str, Field(description="Name of the second component occurrence in assembly")],
    entity2_type: Annotated[Literal["plane", "axis", "point", "face", "edge"], Field(description="Type of entity on occurrence 2")],
    entity2_idx: Annotated[int, Field(description="1-based index or name of the work entity or face/edge on occurrence 2", ge=1)],
    constraint_type: Annotated[Literal["mate", "flush", "angle", "insert"], Field(description="Constraint relationship type")],
    offset_mm: Annotated[float, Field(description="Linear offset in mm or angle in degrees", default=0.0)] = 0.0,
    name: Annotated[Optional[str], Field(description="Descriptive engineering name for the constraint", default=None)] = None,
    min_limit: Annotated[Optional[str], Field(description="Minimum travel limit expression (e.g. '-220 mm' or '0 deg')", default=None)] = None,
    max_limit: Annotated[Optional[str], Field(description="Maximum travel limit expression (e.g. '0 mm' or '115 deg')", default=None)] = None,
    ctx: Context = None,
) -> str:
    """Add a Mate, Flush, Angle, or Insert assembly constraint with optional range-of-motion travel limits.
    Linear offsets are in millimeters; angles are in degrees.
    """
    if ctx:
        await ctx.info(f"Adding {constraint_type} constraint between {occ1_name} and {occ2_name}...")
    limits = None
    if min_limit or max_limit:
        limits = {"min": min_limit, "max": max_limit}
    return inv.add_assembly_constraint(
        occ1_name=occ1_name,
        entity1_type=entity1_type,
        entity1_idx=entity1_idx,
        occ2_name=occ2_name,
        entity2_type=entity2_type,
        entity2_idx=entity2_idx,
        constraint_type=constraint_type,
        offset_cm=offset_mm / 10.0 if constraint_type.lower() != "angle" else offset_mm,
        name=name,
        limits=limits,
    )


@mcp.tool()
def delete_assembly_constraint(
    name: Annotated[str, Field(description="Name of the assembly constraint to delete")]
) -> str:
    """Delete an assembly constraint by name."""
    success = inv.delete_assembly_constraint(name)
    if success:
        return f"Successfully deleted constraint '{name}'."
    return f"Constraint '{name}' not found."


@mcp.tool()
async def add_assembly_joint(
    occ1_name: Annotated[str, Field(description="First component occurrence name")],
    occ2_name: Annotated[str, Field(description="Second component occurrence name")],
    joint_type: Annotated[Literal["rotational", "slider", "cylindrical", "rigid", "planar", "ball"], Field(description="Native Inventor joint type")],
    entity1_name: Annotated[str, Field(description="Work geometry, face index, or edge index on occurrence 1")],
    entity2_name: Annotated[str, Field(description="Work geometry, face index, or edge index on occurrence 2")],
    start_limit: Annotated[Optional[str], Field(description="Minimum motion limit (e.g. '0 deg' or '0 mm')", default=None)] = None,
    end_limit: Annotated[Optional[str], Field(description="Maximum motion limit (e.g. '115 deg' or '220 mm')", default=None)] = None,
    name: Annotated[Optional[str], Field(description="Descriptive joint name", default=None)] = None,
    ctx: Context = None,
) -> str:
    """Create a native Autodesk Inventor Assembly Joint (Rotational/Slider/etc.).
    NOTE ON DOCTRINE: Native joints are NOT preferred by default. Use native joints
    ONLY when explicitly requested by the user. When not asked, standard constraints
    paired with Positional Representations (manage_positional_representations) MUST be used.
    """
    if ctx:
        await ctx.info(f"Instantiating native {joint_type} joint '{name}'...")
    return inv.add_assembly_joint(
        occ1_name=occ1_name,
        entity1_name=entity1_name,
        occ2_name=occ2_name,
        entity2_name=entity2_name,
        joint_type=joint_type,
        start_limit=start_limit,
        end_limit=end_limit,
        name=name,
    )


@mcp.tool()
def delete_assembly_joint(
    name: Annotated[str, Field(description="Name of the assembly joint to delete")]
) -> str:
    """Delete an assembly joint by name."""
    success = inv.delete_assembly_joint(name)
    if success:
        return f"Successfully deleted joint '{name}'."
    return f"Joint '{name}' not found."


@mcp.tool()
async def manage_subassembly_kinematics(
    action: Annotated[Literal["enforce_rigidity", "set_flexible", "set_grounded"], Field(description="Kinematic action to perform")],
    occurrence_name: Annotated[Optional[str], Field(description="Target occurrence name in active assembly", default=None)] = None,
    value: Annotated[bool, Field(description="State value for flexible or grounded", default=True)] = True,
    ctx: Context = None,
) -> str:
    """Manage subassembly internal rigidity, occurrence grounding, and Flexible kinematics evaluation.
    When enforcing rigidity, occurrences with existing constraints or joints are safely skipped.
    """
    if action == "enforce_rigidity":
        res = inv.enforce_subassembly_rigidity(occurrence_name)
        return json.dumps(res, indent=2, ensure_ascii=False)
    elif action == "set_flexible":
        res = inv.set_occurrence_flexible(occurrence_name, value)
        return f"Occurrence '{occurrence_name}' Flexible set to: {res}"
    elif action == "set_grounded":
        res = inv.set_occurrence_grounded(occurrence_name, value)
        return f"Occurrence '{occurrence_name}' Grounded set to: {res}"
    else:
        raise ValueError(f"Unknown action: '{action}'")


@mcp.tool()
def inspect_assembly_kinematics() -> str:
    """Audit the complete kinematic hierarchy of the active assembly, reporting
    grounded states, constraints, joints, positional representations, and free DOFs.
    """
    report = inv.audit_assembly_kinematics()
    return json.dumps(report, indent=2, ensure_ascii=False)


@mcp.tool()
async def drive_kinematic_motion(
    target_name: Annotated[str, Field(description="Name of the constraint to drive")],
    start_value: Annotated[float, Field(description="Starting parameter value")],
    end_value: Annotated[float, Field(description="Final parameter value")],
    unit: Annotated[Literal["deg", "mm", "cm"], Field(description="Parameter units", default="deg")] = "deg",
    steps: Annotated[int, Field(description="Number of intermediate interpolation steps", default=10, ge=1)] = 10,
    ctx: Context = None,
) -> str:
    """Drive a constraint across a travel range, simulating physical movement and clearance."""
    if ctx:
        await ctx.report_progress(0, steps)
    for i in range(steps + 1):
        cur_val = start_value + ((end_value - start_value) / steps) * i
        inv.set_constraint_expression(target_name, f"{cur_val} {unit}")
        if ctx:
            await ctx.report_progress(i, steps)
    return f"Successfully drove '{target_name}' from {start_value} {unit} to {end_value} {unit} across {steps} steps."


@mcp.tool()
def apply_material_appearance(
    appearance_name: Annotated[str, Field(description="Material appearance asset name (e.g. 'Gold', 'Smooth - White', 'Clear Glass')")],
    target_level: Annotated[Literal["part", "surface_body", "feature"], Field(description="Entity level to apply appearance", default="part")] = "part",
    target_index: Annotated[int, Field(description="1-based index of the surface body or feature", default=1, ge=1)] = 1,
) -> str:
    """Apply an appearance asset override to a part, surface body, or individual feature."""
    return inv.apply_appearance(appearance_name, target_level=target_level, target_index=target_index)


@mcp.tool()
def render_showcase_viewport(
    output_png_path: Annotated[str, Field(description="Destination file path for captured image (PNG)")],
    eye_x_mm: Annotated[float, Field(description="Camera eye position X coordinate in mm", default=1200.0)] = 1200.0,
    eye_y_mm: Annotated[float, Field(description="Camera eye position Y coordinate in mm", default=1000.0)] = 1000.0,
    eye_z_mm: Annotated[float, Field(description="Camera eye position Z coordinate in mm", default=1500.0)] = 1500.0,
    target_x_mm: Annotated[float, Field(description="Camera focal target position X coordinate in mm", default=300.0)] = 300.0,
    target_y_mm: Annotated[float, Field(description="Camera focal target position Y coordinate in mm", default=500.0)] = 500.0,
    target_z_mm: Annotated[float, Field(description="Camera focal target position Z coordinate in mm", default=200.0)] = 200.0,
    width: Annotated[int, Field(description="Image pixel width", default=1920, ge=320)] = 1920,
    height: Annotated[int, Field(description="Image pixel height", default=1440, ge=240)] = 1440,
    display_style: Annotated[Literal["shaded_with_edges", "realistic", "shaded", "wireframe"], Field(description="Visual rendering style", default="shaded_with_edges")] = "shaded_with_edges",
):
    """Position the viewport camera and export a high-resolution render.
    Returns an MCP Image object directly into chat.
    """
    out_path = inv.render_showcase(
        output_png_path,
        eye_cm=(eye_x_mm / 10.0, eye_y_mm / 10.0, eye_z_mm / 10.0),
        target_cm=(target_x_mm / 10.0, target_y_mm / 10.0, target_z_mm / 10.0),
        width=width,
        height=height,
        display_style=display_style,
    )
    try:
        return Image(path=out_path)
    except Exception:
        return out_path


@mcp.tool()
def supervisor_clean_processes(
    confirm: Annotated[bool, Field(description="Must be set to True to terminate orphan background instances. Defaults to False (safe dry-run).")] = False,
    target_pids: Annotated[Optional[list[int]], Field(description="Explicit list of PIDs to terminate from dry-run candidate_pids. Required when confirm=True.")] = None,
) -> str:
    """Safe Inventor process supervisor.
    Audits running Inventor processes. Only targets headless instances without a main window
    that are not the active COM session and were started > 45s ago. Warns on unsaved dirty documents.
    Default confirm=False only lists candidate orphans without killing anything.
    When confirm=True, target_pids MUST be explicitly provided.
    """
    report = inv.supervisor_clean_orphaned_instances(confirm=confirm, target_pids=target_pids)
    return json.dumps(report, indent=2, ensure_ascii=False)


@mcp.tool()
async def manage_positional_representations(
    action: Annotated[Literal["activate", "create", "set_override", "setup_standard_max_positions", "list"], Field(description="Action to perform on Positional Representations")],
    rep_name: Annotated[Optional[str], Field(description="Name of the Positional Representation (e.g. 'Master', 'Porta_Aberta_Max', 'Gaveta_Aberta_Max', 'Posicao_Maxima')", default="Master")] = "Master",
    constraint_name: Annotated[Optional[str], Field(description="Name of the assembly constraint to override", default=None)] = None,
    override_expression: Annotated[Optional[str], Field(description="Parameter override expression (e.g. '115.0 deg', '-220 mm')", default=None)] = None,
    door_constraint_name: Annotated[Optional[str], Field(description="Door constraint name for setup_standard_max_positions", default=None)] = None,
    drawer_constraint_name: Annotated[Optional[str], Field(description="Drawer constraint name for setup_standard_max_positions", default=None)] = None,
    ctx: Context = None,
) -> str:
    """Manage Autodesk Inventor Positional Representations (PosReps).
    Controls mechanism kinematic maximum states via standard constraint overrides.
    """
    if ctx:
        await ctx.info(f"Executing Positional Representation action '{action}'...")
    if action == "activate":
        return inv.activate_positional_representation(rep_name)
    elif action == "create":
        return inv.create_positional_representation(rep_name)
    elif action == "set_override":
        if not constraint_name or not override_expression:
            raise ValueError("constraint_name and override_expression required for set_override.")
        return inv.set_constraint_override(rep_name, constraint_name, override_expression)
    elif action == "setup_standard_max_positions":
        return inv.setup_standard_max_position_representations(
            door_constraint_name, drawer_constraint_name
        )
    elif action == "list":
        reps = inv.list_positional_representations()
        return json.dumps(reps, indent=2)
    else:
        raise ValueError(f"Unknown action: '{action}'")


# ---------- Plugin Self-Update Management ----------

@mcp.tool()
def check_for_updates(
    force: Annotated[bool, Field(description="If True, bypass the 7-day throttle and query GitHub remote immediately.")] = False,
) -> str:
    """Check whether an update is available from the GitHub repository.

    Reports current vs latest commit SHA / tag, commit messages if available,
    install type, and whether dependencies changed. Does not apply the update.
    """
    res = _updater.check_for_updates(force=force)
    return json.dumps(res, indent=2, ensure_ascii=False)


@mcp.tool()
def update_plugin(
    confirm: Annotated[bool, Field(description="Must be set to True to apply the update. If False, performs a dry-run.")] = False,
) -> str:
    """Safely update the Autodesk Inventor plugin to the latest version from GitHub main.

    If confirm is False (default), performs a dry-run and describes what would change.
    If confirm is True:
      - Validates that working tree is clean and branch is 'main'
      - Fetches latest changes and performs fast-forward merge (git) or archive extract (zip)
      - Verifies Python syntax and imports in an isolated subprocess
      - Automatically rolls back to the prior version if verification fails
      - Reminds you to restart the MCP server and run 'pip install -e .' if dependencies changed.
    """
    res = _updater.update_plugin(confirm=confirm)
    return json.dumps(res, indent=2, ensure_ascii=False)


# ---------- Dynamic MCP Resources & Prompts ----------

@mcp.resource("inventor://assembly/kinematics")
def get_assembly_kinematics_resource() -> str:
    """Real-time kinematic state (grounded occurrences, constraints, joints, free DOFs)."""
    if not inv.is_connected():
        return json.dumps({"connected": False, "status": "Not connected to Inventor. Call connect() first."}, indent=2)
    try:
        return json.dumps(inv.audit_assembly_kinematics(), indent=2, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"connected": True, "error": str(e)}, indent=2, ensure_ascii=False)


@mcp.resource("inventor://assembly/representations")
def get_assembly_representations_resource() -> str:
    """Active and available Positional Representations in the active assembly."""
    if not inv.is_connected():
        return json.dumps({"connected": False, "status": "Not connected to Inventor. Call connect() first."}, indent=2)
    try:
        return json.dumps(inv.list_positional_representations(), indent=2, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"connected": True, "error": str(e)}, indent=2, ensure_ascii=False)


@mcp.resource("inventor://status")
def get_status_resource() -> str:
    """Active document status, units, software version, and plugin updater state."""
    updater_summary = _updater.get_updater_status_summary()
    if not inv.is_connected():
        return json.dumps({
            "connected": False,
            "status": "Not connected to Inventor. Call connect() first.",
            "updater": updater_summary,
        }, indent=2, ensure_ascii=False)
    try:
        info = inv.get_document_info()
        return json.dumps({
            "connected": True,
            "document": info,
            "updater": updater_summary,
        }, indent=2, ensure_ascii=False)
    except Exception:
        return json.dumps({
            "connected": True,
            "document": None,
            "status": "Connected, but no active document.",
            "updater": updater_summary,
        }, indent=2, ensure_ascii=False)


@mcp.prompt("audit_assembly")
def audit_assembly_prompt(assembly_name: str = ""):
    """Guide the agent to audit assembly degrees of freedom, grounded datums, and mechanism representations."""
    return (
        f"Audit the assembly '{assembly_name}'. Verify that the base chassis is Grounded, "
        f"internal subassembly parts are rigid, and kinematic mechanisms are properly configured "
        f"using standard constraints and Positional Representations for maximum positions "
        f"(using native Joints only if explicitly requested)."
    )


def main():
    try:
        _updater.start_background_autoupdate()
    except Exception:
        pass
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
