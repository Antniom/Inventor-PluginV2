"""Wrapper around Autodesk Inventor COM API."""

import glob
import os
import time

try:
    import win32com.client
    import pythoncom
except ImportError:
    win32com = None
    pythoncom = None


# ==============================================================================
# INVENTOR ENUM CONSTANTS
# Verified against Autodesk Inventor 2026/2027 Type Library (RxInventor.tlb)
#
# NOTE ON SOURCE OF TRUTH:
# The Autodesk Inventor 2027 online API reference documentation starting at:
# https://help.autodesk.com/view/INVNTOR/2027/ENU/?guid=GUID-6FD7AA08-1E43-43FC-971B-5F20E56C8846
# is JavaScript-rendered (an empty client-side shell without static HTML).
# All values below were extracted and verified directly from the official Autodesk
# Inventor Type Library (RxInventor.tlb in the Inventor Bin directory) using
# pythoncom.LoadTypeLib in a throwaway process.
# ==============================================================================

# PartFeatureExtentDirectionEnum (Source: RxInventor.tlb)
kPositiveExtentDirection = 20993
kNegativeExtentDirection = 20994
kSymmetricExtentDirection = 20995

# PartFeatureOperationEnum (Source: RxInventor.tlb)
kJoinOperation = 20481
kCutOperation = 20482
kIntersectOperation = 20483
kSurfaceOperation = 20484
kNewBodyOperation = 20485

# DocumentTypeEnum (Source: RxInventor.tlb)
kUnknownDocumentObject = 12289
kPartDocumentObject = 12290
kAssemblyDocumentObject = 12291
kDrawingDocumentObject = 12292
kPresentationDocumentObject = 12293

# DimensionOrientationEnum (Source: RxInventor.tlb - NOT 40706/40707/40708!)
kHorizontalDim = 19201
kVerticalDim   = 19202
kAlignedDim    = 19203

# Assembly Constraint Types - ObjectTypeEnum (Source: RxInventor.tlb)
kAngleConstraintObject = 100665088
kInsertConstraintObject = 100665344       # Verified: RxInventor.tlb (was guessed as 100666880)
kMateConstraintObject = 100665856
kFlushConstraintObject = 100666368
kTangentConstraintObject = 100667392
kTransitionalConstraintObject = 100667904
kSymmetryConstraintObject = 100668416

# Constraint Proxy Object Types - ObjectTypeEnum (Source: RxInventor.tlb)
kAngleConstraintProxyObject = 100675584
kInsertConstraintProxyObject = 100676096
kMateConstraintProxyObject = 100676352
kFlushConstraintProxyObject = 100675840

# AngleConstraintSolutionTypeEnum (Source: RxInventor.tlb)
# Used as SolutionType argument in AssemblyConstraints.AddAngleConstraint
# Note: Replaces guessed 78081/78082, which are actually OccurrenceDOFStateEnum
# (kCanRetainDegreeOfFreedom=78081, kCanIgnoreDegreeOfFreedom=78082).
kDirectedSolution = 78593         # AngleConstraintSolutionTypeEnum (RxInventor.tlb)
kUndirectedSolution = 78594       # AngleConstraintSolutionTypeEnum (RxInventor.tlb, required for limits)
kReferenceVectorSolution = 78595  # AngleConstraintSolutionTypeEnum (RxInventor.tlb)

# Backward-compatibility aliases for existing scripts:
kUndirectedAngle = kUndirectedSolution
kDirectedAngle = kDirectedSolution

# AssemblyJointTypeEnum (Source: RxInventor.tlb)
# Note: Replaces guessed 129793-129798, which were actually BoundingTypeEnum
# (kOrthogonalBoundingBox=129793, kOrientedMinimumBoundingBox=129794).
kRigidJointType = 102401        # AssemblyJointTypeEnum (RxInventor.tlb; verified - NOT 129793)
kRotationalJointType = 102402   # AssemblyJointTypeEnum (RxInventor.tlb; verified - NOT 129794)
kSlideJointType = 102403        # AssemblyJointTypeEnum (RxInventor.tlb; verified - NOT 129795)
kCylindricalJointType = 102404  # AssemblyJointTypeEnum (RxInventor.tlb; verified - NOT 129796)
kPlanarJointType = 102405       # AssemblyJointTypeEnum (RxInventor.tlb; verified - NOT 129797)
kBallJointType = 102406         # AssemblyJointTypeEnum (RxInventor.tlb; verified - NOT 129798)

# DisplayModeEnum (Source: RxInventor.tlb)
# Note: 8708 is kShadedRendering (RxInventor.tlb; was guessed as 8709),
# 8709 is kRealisticRendering (RxInventor.tlb; was guessed as 8711),
# 8711 is kWireframeNoHiddenEdges (RxInventor.tlb; was mistaken for Realistic).
kWireframeRendering = 8706                 # DisplayModeEnum (RxInventor.tlb)
kHiddenEdgeRendering = 8707                # DisplayModeEnum (RxInventor.tlb)
kShadedWithHiddenEdgesRendering = 8707     # DisplayModeEnum (RxInventor.tlb)
kShadedRendering = 8708                    # DisplayModeEnum (RxInventor.tlb)
kRealisticRendering = 8709                 # DisplayModeEnum (RxInventor.tlb)
kShadedWithEdgesRendering = 8710           # DisplayModeEnum (RxInventor.tlb)
kWireframeNoHiddenEdges = 8711             # DisplayModeEnum (RxInventor.tlb)
kWireframeWithHiddenEdgesRendering = 8712  # DisplayModeEnum (RxInventor.tlb)
kMonochromeRendering = 8713                # DisplayModeEnum (RxInventor.tlb)
kWatercolorRendering = 8714                # DisplayModeEnum (RxInventor.tlb)
kIllustrationRendering = 8715              # DisplayModeEnum (RxInventor.tlb)
kTechnicalIllustrationRendering = 8716     # DisplayModeEnum (RxInventor.tlb)

# HealthStatusEnum (Source: RxInventor.tlb - all 14 enum codes)
kUnknownHealth        = 11777  # Safe default on unreadable health
kUpToDateHealth       = 11778  # Nominal healthy status
kOutOfDateHealth      = 11779
kDriverLostHealth     = 11780
kInErrorHealth        = 11781
kDeletedHealth        = 11782
kCannotComputeHealth  = 11783
kSuppressedHealth     = 11784
kBeyondStopNodeHealth = 11785
kInconsistentHealth   = 11786
kRedundantHealth      = 11787
kNewlyAddedHealth     = 11788
kInvalidLimitsHealth  = 11789
kJointDOFLockedHealth = 11790

HEALTH_STATUS_MAP = {
    kUnknownHealth: "Unknown",
    kUpToDateHealth: "UpToDate",
    kOutOfDateHealth: "OutOfDate",
    kDriverLostHealth: "DriverLost",
    kInErrorHealth: "InError",
    kDeletedHealth: "Deleted",
    kCannotComputeHealth: "CannotCompute",
    kSuppressedHealth: "Suppressed",
    kBeyondStopNodeHealth: "BeyondStopNode",
    kInconsistentHealth: "Inconsistent",
    kRedundantHealth: "Redundant",
    kNewlyAddedHealth: "NewlyAdded",
    kInvalidLimitsHealth: "InvalidLimits",
    kJointDOFLockedHealth: "JointDOFLocked",
}


def verify_api_constants() -> dict[str, int]:
    """Startup self-check verifying enum constants against Inventor's type library.

    Uses pythoncom.LoadTypeLib to inspect RxInventor.tlb in a separate throwaway check.
    NEVER uses win32com.client.gencache.EnsureDispatch so the COM registration remains clean.
    Fails loudly with RuntimeError on any mismatch.
    """
    tlb_candidates = [
        r"C:\Program Files\Autodesk\Inventor 2027\Bin\RxInventor.tlb",
        r"C:\Program Files\Autodesk\Inventor 2026\Bin\RxInventor.tlb",
    ] + glob.glob(r"C:\Program Files\Autodesk\Inventor *\Bin\RxInventor.tlb")

    found_tlb = None
    for p in tlb_candidates:
        if os.path.exists(p):
            found_tlb = p
            break

    if not found_tlb:
        return {}

    tlb = pythoncom.LoadTypeLib(found_tlb)
    enums: dict[str, dict[str, int]] = {}
    for i in range(tlb.GetTypeInfoCount()):
        tinfo = tlb.GetTypeInfo(i)
        if tinfo.GetTypeAttr().typekind == 0:  # TKIND_ENUM
            enum_name = tlb.GetDocumentation(i)[0]
            enums[enum_name] = {}
            for v in range(tinfo.GetTypeAttr().cVars):
                vdesc = tinfo.GetVarDesc(v)
                vname = tinfo.GetNames(vdesc.memid)[0]
                enums[enum_name][vname] = vdesc.value

    expected_checks = [
        ("DocumentTypeEnum", "kPartDocumentObject", kPartDocumentObject),
        ("DocumentTypeEnum", "kAssemblyDocumentObject", kAssemblyDocumentObject),
        ("ObjectTypeEnum", "kAngleConstraintObject", kAngleConstraintObject),
        ("ObjectTypeEnum", "kInsertConstraintObject", kInsertConstraintObject),
        ("ObjectTypeEnum", "kMateConstraintObject", kMateConstraintObject),
        ("ObjectTypeEnum", "kFlushConstraintObject", kFlushConstraintObject),
        ("AngleConstraintSolutionTypeEnum", "kDirectedSolution", kDirectedSolution),
        ("AngleConstraintSolutionTypeEnum", "kUndirectedSolution", kUndirectedSolution),
        ("AssemblyJointTypeEnum", "kRigidJointType", kRigidJointType),
        ("AssemblyJointTypeEnum", "kRotationalJointType", kRotationalJointType),
        ("AssemblyJointTypeEnum", "kSlideJointType", kSlideJointType),
        ("AssemblyJointTypeEnum", "kCylindricalJointType", kCylindricalJointType),
        ("AssemblyJointTypeEnum", "kPlanarJointType", kPlanarJointType),
        ("AssemblyJointTypeEnum", "kBallJointType", kBallJointType),
        ("DisplayModeEnum", "kShadedRendering", kShadedRendering),
        ("DisplayModeEnum", "kRealisticRendering", kRealisticRendering),
        ("DisplayModeEnum", "kShadedWithEdgesRendering", kShadedWithEdgesRendering),
        ("DisplayModeEnum", "kWireframeNoHiddenEdges", kWireframeNoHiddenEdges),
        ("HealthStatusEnum", "kUnknownHealth", kUnknownHealth),
        ("HealthStatusEnum", "kUpToDateHealth", kUpToDateHealth),
        ("HealthStatusEnum", "kOutOfDateHealth", kOutOfDateHealth),
        ("HealthStatusEnum", "kInErrorHealth", kInErrorHealth),
    ]

    verified = {}
    for enum_name, const_name, expected in expected_checks:
        actual = enums.get(enum_name, {}).get(const_name)
        if actual is None:
            continue
        if actual != expected:
            raise RuntimeError(
                f"FATAL: Inventor API Enum Mismatch in {found_tlb}! "
                f"{enum_name}.{const_name} expected {expected}, got {actual}."
            )
        verified[f"{enum_name}.{const_name}"] = actual

    return verified


# Run verification on import if typelib is found
try:
    verify_api_constants()
except Exception as _e:
    import sys
    print(f"[inventor_api] Startup constant verification warning: {_e}", file=sys.stderr)


def _build_relationship_counts(cdef) -> dict[str, int] | None:
    """Build relationship reference counts across all occurrences in a single pass.

    Drops COM overhead from O(N * M) to O(N + M) and prevents silent false zeros.
    - Tracks read exceptions; if any occur, returns None.
    - If constraints/joints exist in the assembly, but total matched relationships is 0,
      detection is deemed failed and returns None.
    """
    try:
        counts = {cdef.Occurrences.Item(i).Name: 0 for i in range(1, cdef.Occurrences.Count + 1)}
    except Exception:
        return None

    errors = 0
    total_constraints = 0
    total_joints = 0

    try:
        total_constraints = cdef.Constraints.Count
        for c in cdef.Constraints:
            try:
                occ1 = c.OccurrenceOne
                if occ1:
                    name1 = occ1.Name
                    if name1 in counts:
                        counts[name1] += 1
            except Exception:
                errors += 1

            try:
                occ2 = c.OccurrenceTwo
                if occ2:
                    name2 = occ2.Name
                    if name2 in counts:
                        counts[name2] += 1
            except Exception:
                errors += 1
    except Exception:
        return None

    try:
        total_joints = cdef.Joints.Count
        for j in cdef.Joints:
            try:
                occ1 = j.OccurrenceOne
                if occ1:
                    name1 = occ1.Name
                    if name1 in counts:
                        counts[name1] += 1
            except Exception:
                errors += 1

            try:
                occ2 = j.OccurrenceTwo
                if occ2:
                    name2 = occ2.Name
                    if name2 in counts:
                        counts[name2] += 1
            except Exception:
                errors += 1
    except Exception:
        return None

    # Fail safe 1: Any read error aborts
    if errors > 0:
        return None

    # Fail safe 2: Sanity check (relationships exist, but 0 matched)
    if (total_constraints + total_joints) > 0 and sum(counts.values()) == 0:
        return None

    return counts


class InventorConnection:
    _build_relationship_counts = staticmethod(_build_relationship_counts)

    def __init__(self):
        self._app = None

    @property
    def app(self):
        if self._app is None:
            raise RuntimeError(
                "Not connected to Inventor. Call connect() first."
            )
        return self._app

    def connect(self, visible: bool = True) -> str:
        if win32com is None or pythoncom is None:
            raise RuntimeError(
                "pywin32 is not installed. Autodesk Inventor automation requires pywin32>=306. "
                "Please run: pip install pywin32>=306"
            )
        pythoncom.CoInitialize()
        try:
            self._app = win32com.client.GetActiveObject("Inventor.Application")
            return f"Connected to running Inventor {self._app.SoftwareVersion.DisplayVersion}"
        except Exception:
            pass
        try:
            self._app = win32com.client.Dispatch("Inventor.Application")
            self._app.Visible = visible
            return f"Started Inventor {self._app.SoftwareVersion.DisplayVersion}"
        except Exception as e:
            raise RuntimeError(f"Cannot connect to Inventor: {e}")

    def is_connected(self) -> bool:
        if self._app is None:
            return False
        try:
            _ = self._app.SoftwareVersion
            return True
        except Exception:
            self._app = None
            return False

    # ---------- Document management ----------

    def create_part(self, name: str | None = None, template: str = "metric") -> str:
        import glob

        templates_path = self.app.FileLocations.TemplatesPath

        if template.lower() in ("sheet_metal", "sheetmetal", "sm"):
            # Sheet Metal template (metric mm)
            candidates_patterns = [
                os.path.join(templates_path, "Metric", "Sheet Metal (mm).ipt"),
                os.path.join(templates_path, "**", "Sheet Metal (mm).ipt"),
                os.path.join(templates_path, "Sheet Metal.ipt"),
            ]
            template_file = None
            for pattern in candidates_patterns:
                if "*" in pattern:
                    found = glob.glob(pattern, recursive=True)
                    if found:
                        template_file = found[0]
                        break
                elif os.path.exists(pattern):
                    template_file = pattern
                    break
            if template_file is None:
                raise RuntimeError(f"Cannot find Sheet Metal template in {templates_path}")
        elif template.lower() == "metric":
            # Search for metric template (mm)
            candidates_patterns = [
                os.path.join(templates_path, "Metric", "Standard (mm).ipt"),
                os.path.join(templates_path, "Metric", "Standard.ipt"),
                os.path.join(templates_path, "**", "Standard (mm).ipt"),
            ]
            template_file = None
            for pattern in candidates_patterns:
                if "*" in pattern:
                    found = glob.glob(pattern, recursive=True)
                    if found:
                        template_file = found[0]
                        break
                elif os.path.exists(pattern):
                    template_file = pattern
                    break
            if template_file is None:
                # Fallback: any .ipt template
                fallback = glob.glob(os.path.join(templates_path, "**", "*.ipt"), recursive=True)
                if fallback:
                    template_file = fallback[0]
                else:
                    raise RuntimeError(f"Cannot find metric template in {templates_path}")
        elif template.lower() == "english":
            candidates_patterns = [
                os.path.join(templates_path, "en-US", "Standard.ipt"),
                os.path.join(templates_path, "Standard.ipt"),
                os.path.join(templates_path, "**", "Standard.ipt"),
            ]
            template_file = None
            for pattern in candidates_patterns:
                if "*" in pattern:
                    found = glob.glob(pattern, recursive=True)
                    if found:
                        template_file = found[0]
                        break
                elif os.path.exists(pattern):
                    template_file = pattern
                    break
            if template_file is None:
                raise RuntimeError(f"Cannot find English template in {templates_path}")
        else:
            # template is a direct file path
            template_file = template
            if not os.path.exists(template_file):
                raise RuntimeError(f"Template not found: {template_file}")

        doc = self.app.Documents.Add(12290, template_file, True)
        if name:
            try:
                doc.DisplayName = name
            except Exception:
                pass  # DisplayName may be read-only before first save
        return f"Part created: {doc.DisplayName}"

    def active_document(self):
        doc = self.app.ActiveDocument
        if doc is None:
            raise RuntimeError("No active document open in Inventor.")
        return doc

    def active_part(self):
        doc = self.active_document()
        if doc.DocumentType != 12290:  # kPartDocumentObject
            raise RuntimeError(
                f"Active document is not a part (type={doc.DocumentType})."
            )
        return doc.ComponentDefinition

    def save_document(self, path: str | None = None) -> str:
        doc = self.active_document()
        if path:
            path = os.path.abspath(path)
            doc.SaveAs(path, False)
            return f"Saved as: {path}"
        doc.Save()
        return f"Saved: {doc.FullFileName}"

    def export_document(self, path: str, format: str = "STEP") -> str:
        doc = self.active_document()
        path = os.path.abspath(path)

        format_upper = format.upper()
        if format_upper == "STEP":
            translator = "Autodesk Inventor STEP Translator"
        elif format_upper == "STL":
            translator = "Autodesk Inventor STL Translator"
        elif format_upper == "SAT":
            translator = "Autodesk Inventor SAT Translator"
        elif format_upper == "IGES":
            translator = "Autodesk Inventor IGES Translator"
        else:
            raise ValueError(f"Unsupported format: {format}. Use STEP, STL, SAT, or IGES.")

        context = self.app.TransientObjects.CreateTranslationContext()
        context.Type = 13059  # kFileBrowseIOMechanism
        options = self.app.TransientObjects.CreateNameValueMap()
        data_medium = self.app.TransientObjects.CreateDataMedium()
        data_medium.FileName = path

        addins = self.app.ApplicationAddIns
        found = None
        for i in range(1, addins.Count + 1):
            addin = addins.Item(i)
            if hasattr(addin, "DisplayName") and translator.lower() in addin.DisplayName.lower():
                found = addin
                break

        if found is None:
            raise RuntimeError(f"Translator not found: {translator}")

        if hasattr(found, "SaveCopyAs"):
            found.SaveCopyAs(doc, context, options, data_medium)
        else:
            doc.SaveAs(path, False)

        return f"Exported to: {path} ({format_upper})"

    # ---------- Sketches ----------

    def create_sketch(
        self,
        plane: str = "XY",
        face_index: int | None = None,
        offset: float = 0,
    ) -> str:
        """Create a sketch on a work plane, a body face, or an OFFSET work plane.

        offset (mm): creates a hidden work plane parallel to 'plane' at this
        distance and sketches on it. Offset direction: positive = along the
        plane's normal (XY→+Z, XZ→+Y, YZ→+X). Essential for features that
        don't start at the origin planes (ribs, bosses at a height).
        """
        comp = self.active_part()

        if face_index is not None:
            # Create sketch on a body face
            body = comp.SurfaceBodies.Item(1)
            if face_index < 1 or face_index > body.Faces.Count:
                raise ValueError(
                    f"face_index={face_index} out of range. Body has {body.Faces.Count} faces."
                )
            face = body.Faces.Item(face_index)
            sketch = comp.Sketches.Add(face)
            return f"Sketch created on face {face_index} (Sketch{comp.Sketches.Count})"

        planes = {
            "XY": comp.WorkPlanes.Item(3),  # XY plane
            "XZ": comp.WorkPlanes.Item(2),  # XZ plane
            "YZ": comp.WorkPlanes.Item(1),  # YZ plane
        }
        wp = planes.get(plane.upper())
        if wp is None:
            raise ValueError(f"Unknown plane: {plane}. Use XY, XZ, or YZ.")

        if offset:
            wp = comp.WorkPlanes.AddByPlaneAndOffset(wp, offset / 10.0)
            wp.Visible = False
            sketch = comp.Sketches.Add(wp)
            return (f"Sketch created on {plane.upper()}{offset:+g}mm offset plane "
                    f"(Sketch{comp.Sketches.Count})")

        sketch = comp.Sketches.Add(wp)
        return f"Sketch created on {plane.upper()} plane (Sketch{comp.Sketches.Count})"

    def _get_sketch(self, sketch_index: int | None = None):
        comp = self.active_part()
        if sketch_index is not None:
            return comp.Sketches.Item(sketch_index)
        return comp.Sketches.Item(comp.Sketches.Count)

    def _tg(self):
        return self.app.TransientGeometry

    def draw_rectangle(
        self,
        x: float = 0, y: float = 0,
        width: float = 100, height: float = 50,
        sketch_index: int | None = None,
    ) -> str:
        sketch = self._get_sketch(sketch_index)
        tg = self._tg()
        # All dimensions in cm (Inventor internal units)
        w = width / 10.0
        h = height / 10.0
        cx = x / 10.0
        cy = y / 10.0
        sketch.SketchLines.AddAsTwoPointRectangle(
            tg.CreatePoint2d(cx - w / 2, cy - h / 2),
            tg.CreatePoint2d(cx + w / 2, cy + h / 2),
        )
        return f"Rectangle {width}x{height}mm at ({x},{y})"

    def draw_circle(
        self,
        x: float = 0, y: float = 0,
        diameter: float = 50,
        sketch_index: int | None = None,
        construction: bool = False,
    ) -> str:
        """Draw a circle with an automatic diameter dimension constraint.
        construction=True draws a reference (non-profile) circle, e.g. bolt PCD.
        """
        sketch = self._get_sketch(sketch_index)
        tg = self._tg()
        r = (diameter / 10.0) / 2.0
        cx = x / 10.0
        cy = y / 10.0
        circle = sketch.SketchCircles.AddByCenterRadius(
            tg.CreatePoint2d(cx, cy), r
        )
        if construction:
            circle.Construction = True

        # Add diameter dimension — text placed just outside the circle
        text_x = cx + r * 0.8
        text_y = cy + r * 0.6
        try:
            sketch.DimensionConstraints.AddDiameter(
                circle, tg.CreatePoint2d(text_x, text_y)
            )
        except Exception:
            pass  # dimension already exists or sketch is consumed

        suffix = " [construction]" if construction else ""
        return f"Circle D={diameter}mm at ({x},{y}){suffix}"

    def draw_line(
        self,
        x1: float = 0, y1: float = 0,
        x2: float = 100, y2: float = 0,
        sketch_index: int | None = None,
        construction: bool = False,
    ) -> str:
        sketch = self._get_sketch(sketch_index)
        tg = self._tg()
        line = sketch.SketchLines.AddByTwoPoints(
            tg.CreatePoint2d(x1 / 10.0, y1 / 10.0),
            tg.CreatePoint2d(x2 / 10.0, y2 / 10.0),
        )
        if construction:
            line.Construction = True
        suffix = " [construction]" if construction else ""
        return f"Line from ({x1},{y1}) to ({x2},{y2})mm{suffix}"

    def draw_polygon(
        self,
        x: float = 0, y: float = 0,
        radius: float = 25,
        sides: int = 6,
        sketch_index: int | None = None,
    ) -> str:
        import math
        sketch = self._get_sketch(sketch_index)
        tg = self._tg()
        r = radius / 10.0
        cx = x / 10.0
        cy = y / 10.0
        points = []
        for i in range(sides):
            angle = 2 * math.pi * i / sides - math.pi / 2
            px = cx + r * math.cos(angle)
            py = cy + r * math.sin(angle)
            points.append(tg.CreatePoint2d(px, py))
        # Draw connected lines — share endpoints for proper profile
        first_line = sketch.SketchLines.AddByTwoPoints(points[0], points[1])
        prev_line = first_line
        for i in range(2, sides):
            prev_line = sketch.SketchLines.AddByTwoPoints(
                prev_line.EndSketchPoint, points[i]
            )
        # Close the polygon
        sketch.SketchLines.AddByTwoPoints(
            prev_line.EndSketchPoint, first_line.StartSketchPoint
        )
        return f"Polygon {sides} sides, R={radius}mm at ({x},{y})"

    def draw_closed_profile(
        self,
        points: list[list[float]],
        sketch_index: int | None = None,
    ) -> str:
        """Draw a closed profile from a list of [x,y] points (mm).
        Lines share endpoints for proper profile recognition by Inventor."""
        sketch = self._get_sketch(sketch_index)
        tg = self._tg()

        if len(points) < 3:
            raise ValueError("Need at least 3 points for a closed profile")

        # First line
        pt1 = tg.CreatePoint2d(points[0][0] / 10.0, points[0][1] / 10.0)
        pt2 = tg.CreatePoint2d(points[1][0] / 10.0, points[1][1] / 10.0)
        first_line = sketch.SketchLines.AddByTwoPoints(pt1, pt2)

        # Subsequent lines — connect to previous endpoint
        prev_line = first_line
        for i in range(2, len(points)):
            next_pt = tg.CreatePoint2d(points[i][0] / 10.0, points[i][1] / 10.0)
            prev_line = sketch.SketchLines.AddByTwoPoints(
                prev_line.EndSketchPoint, next_pt
            )

        # Close the loop — connect last endpoint to first startpoint
        sketch.SketchLines.AddByTwoPoints(
            prev_line.EndSketchPoint, first_line.StartSketchPoint
        )

        return f"Closed profile with {len(points)} points ({len(points)} lines)"

    # ---------- Features ----------

    def extrude(
        self,
        distance: float = 10,
        direction: str = "positive",
        operation: str = "join",
        sketch_index: int | None = None,
        profile_index: int = 1,
        extent_type: str = "distance",
    ) -> str:
        comp = self.active_part()
        sketch = self._get_sketch(sketch_index)
        profile = sketch.Profiles.AddForSolid()

        dir_map = {
            "positive": kPositiveExtentDirection,
            "negative": kNegativeExtentDirection,
            "symmetric": kSymmetricExtentDirection,
        }
        op_map = {
            "join": kJoinOperation,
            "cut": kCutOperation,
            "intersect": kIntersectOperation,
            "surface": kSurfaceOperation,
            "new": kNewBodyOperation,
        }

        direction_enum = dir_map.get(direction.lower(), kPositiveExtentDirection)
        operation_enum = op_map.get(operation.lower(), kJoinOperation)
        before = self._vol_state()

        if extent_type.lower() == "all":
            feature = comp.Features.ExtrudeFeatures.AddByThroughAllExtent(
                profile, direction_enum, operation_enum
            )
            return f"Extrude through-all {direction} ({operation}): {feature.Name}{self._fmt_delta(before)}"
        else:
            dist_cm = distance / 10.0
            feature = comp.Features.ExtrudeFeatures.AddByDistanceExtent(
                profile, dist_cm, direction_enum, operation_enum
            )
            return f"Extrude {distance}mm {direction} ({operation}): {feature.Name}{self._fmt_delta(before)}"

    def revolve(
        self,
        angle: float = 360,
        sketch_index: int | None = None,
        axis: str = "Y",
        operation: str = "join",
        axis_line_index: int | None = None,
    ) -> str:
        """Revolve a sketch profile around an axis.

        axis: "X" / "Y" / "Z"  — use a named WorkAxis (preferred, no construction line needed)
        axis_line_index: sketch line index (legacy); overrides axis when provided.
        """
        import math
        comp = self.active_part()
        sketch = self._get_sketch(sketch_index)
        profile = sketch.Profiles.AddForSolid()

        # Resolve axis entity: named WorkAxis (preferred) or sketch line (legacy)
        _work_axis_map = {"X": 1, "Y": 2, "Z": 3}
        if axis_line_index is not None:
            # Explicit keyword: legacy sketch-line mode
            axis_entity = sketch.SketchLines.Item(axis_line_index)
            axis_label = f"sketch line {axis_line_index}"
        elif isinstance(axis, str) and axis.upper() in _work_axis_map:
            # Named work axis — preferred, no construction line needed
            axis_entity = comp.WorkAxes.Item(_work_axis_map[axis.upper()])
            axis_label = f"{axis.upper()} work axis"
        elif isinstance(axis, int):
            # Backward compat: integer passed positionally from old server.py
            axis_entity = sketch.SketchLines.Item(axis)
            axis_label = f"sketch line {axis}"
        else:
            axis_entity = sketch.SketchLines.Item(1)
            axis_label = "sketch line 1"

        op_map = {
            "join": kJoinOperation,
            "cut": kCutOperation,
            "intersect": kIntersectOperation,
            "new": kNewBodyOperation,
        }
        operation_enum = op_map.get(operation.lower(), kJoinOperation)

        revolve_features = comp.Features.RevolveFeatures
        before = self._vol_state()

        if angle >= 360:
            revolve_features.AddFull(profile, axis_entity, operation_enum)
        else:
            angle_rad = math.radians(angle)
            revolve_features.AddByAngle(
                profile, axis_entity, angle_rad,
                kPositiveExtentDirection, operation_enum
            )

        return f"Revolve {angle}° around {axis_label} ({operation}){self._fmt_delta(before)}"

    def fillet(self, radius: float = 2, edge_indices: list[int] | None = None) -> str:
        comp = self.active_part()
        r_cm = radius / 10.0

        edges_collection = self.app.TransientObjects.CreateEdgeCollection()
        body = comp.SurfaceBodies.Item(1)

        if edge_indices:
            for idx in edge_indices:
                edges_collection.Add(body.Edges.Item(idx))
        else:
            edges_collection.Add(body.Edges.Item(1))

        before = self._vol_state()
        fillet_def = comp.Features.FilletFeatures.CreateFilletDefinition()
        fillet_def.AddConstantRadiusEdgeSet(edges_collection, r_cm)
        comp.Features.FilletFeatures.Add(fillet_def)
        return f"Fillet R={radius}mm on {edges_collection.Count} edge(s){self._fmt_delta(before)}"

    def chamfer(self, distance: float = 2, edge_indices: list[int] | None = None) -> str:
        """Add equal-distance chamfer to edges.
        Inventor 2026 API: ChamferFeatures.AddUsingDistance(EdgeCollection, dist_cm)
        NOT CreateChamferDefinition (removed in 2026).
        Requires EdgeCollection (not ObjectCollection).
        """
        comp = self.active_part()
        d_cm = distance / 10.0

        ec = self.app.TransientObjects.CreateEdgeCollection()
        body = comp.SurfaceBodies.Item(1)

        if edge_indices:
            for idx in edge_indices:
                ec.Add(body.Edges.Item(idx))
        else:
            ec.Add(body.Edges.Item(1))

        before = self._vol_state()
        comp.Features.ChamferFeatures.AddUsingDistance(ec, d_cm)
        return f"Chamfer {distance}mm on {ec.Count} edge(s){self._fmt_delta(before)}"

    # Standard ISO metric coarse thread pitches (mm)
    _METRIC_COARSE_PITCH = {
        1: 0.25, 1.2: 0.25, 1.4: 0.3, 1.6: 0.35, 2: 0.4, 2.5: 0.45,
        3: 0.5, 3.5: 0.6, 4: 0.7, 5: 0.8, 6: 1.0, 8: 1.25, 10: 1.5,
        12: 1.75, 14: 2.0, 16: 2.0, 18: 2.5, 20: 2.5, 22: 2.5, 24: 3.0,
        27: 3.0, 30: 3.5, 33: 3.5, 36: 4.0, 39: 4.0, 42: 4.5, 45: 4.5,
        48: 5.0, 52: 5.0, 56: 5.5, 60: 5.5, 64: 6.0,
    }

    def hole(
        self,
        x: float = 0, y: float = 0,
        diameter: float = 10,
        depth: float = 0,
        tapped: bool = False,
        pitch: float | None = None,
    ) -> str:
        """Create a proper Inventor HoleFeature using native HoleFeatures API.
        depth=0 means through-all (default).
        tapped=True creates a tapped (threaded) hole with ISO Metric profile.
        pitch: thread pitch in mm (auto-selected from standard coarse series if None).
        Uses CreateSketchPlacementDefinition(ObjectCollection_of_SketchPoints) API.
        """
        comp = self.active_part()
        tg = self._tg()
        hf = comp.Features.HoleFeatures
        before = self._vol_state()

        # Create sketch on XY work plane for hole center point
        wp = comp.WorkPlanes.Item(3)  # XY plane
        sketch = comp.Sketches.Add(wp)
        pt = sketch.SketchPoints.Add(tg.CreatePoint2d(x / 10.0, y / 10.0))

        # Create ObjectCollection with the SketchPoint (required by API)
        col = self.app.TransientObjects.CreateObjectCollection()
        col.Add(pt)

        # Create sketch-based placement definition
        placement = hf.CreateSketchPlacementDefinition(col)

        diameter_cm = diameter / 10.0

        # Build second argument: TapInfo for tapped holes, float diameter for drilled holes
        if tapped:
            # Determine pitch (standard coarse if not given)
            if pitch is None:
                dia_int = int(round(diameter))
                pitch = self._METRIC_COARSE_PITCH.get(dia_int)
                if pitch is None:
                    raise ValueError(
                        f"No standard coarse pitch for M{dia_int}. "
                        "Pass pitch= explicitly."
                    )
            # Format designation: "M16x2" (not "M16x2.0")
            dia_int = int(round(diameter))
            pitch_str = str(int(pitch)) if pitch == int(pitch) else str(pitch)
            designation = f"M{dia_int}x{pitch_str}"
            tap_info = hf.CreateTapInfo(
                True,                   # RightHanded
                "ISO Metric profile",   # ThreadType (exact string from thread.xlsx)
                designation,            # ThreadDesignation e.g. "M16x2"
                "6H",                   # Class (standard internal metric)
                True,                   # FullTapDepth
            )
            hole_arg = tap_info
            type_str = f"M{dia_int} tapped (pitch {pitch}mm, 6H)"
        else:
            hole_arg = diameter_cm
            type_str = f"drilled D={diameter}mm"

        if depth <= 0:
            feature = hf.AddDrilledByThroughAllExtent(
                placement, hole_arg, kNegativeExtentDirection
            )
            extent_str = "through-all"
        else:
            depth_cm = depth / 10.0
            feature = hf.AddDrilledByDistanceExtent(
                placement, hole_arg, depth_cm, kNegativeExtentDirection
            )
            extent_str = f"{depth}mm deep"

        # --- Add position dimensions in a separate sketch (after hole creation) ---
        # HoleFeature placement sketch must have ONLY SketchPoints — construction lines
        # cannot be in the same sketch. So we create a dedicated dimension sketch.
        self._add_hole_position_dims(comp, x, y)

        return f"Hole {type_str} {extent_str} at ({x},{y}): {feature.Name}{self._fmt_delta(before)}"

    def _add_hole_position_dims(self, comp, x: float, y: float) -> None:
        """Add a dimension sketch showing the hole center position from origin.
        Uses a separate sketch with construction line(s) to allow AddTwoPointDistance.
        Only adds dimensions if hole is not at origin.
        """
        tg = self._tg()
        x_cm = x / 10.0
        y_cm = y / 10.0

        if abs(x) < 0.01 and abs(y) < 0.01:
            return  # hole at origin — nothing to dimension

        wp = comp.WorkPlanes.Item(3)  # XY plane
        dim_sketch = comp.Sketches.Add(wp)
        dc = dim_sketch.DimensionConstraints

        if abs(y) < 0.01:
            # Hole on X axis — one horizontal construction line
            line = dim_sketch.SketchLines.AddByTwoPoints(
                tg.CreatePoint2d(0.0, 0.0),
                tg.CreatePoint2d(x_cm, 0.0)
            )
            line.Construction = True
            text_pt = tg.CreatePoint2d(x_cm / 2, -1.5)
            dc.AddTwoPointDistance(line.StartSketchPoint, line.EndSketchPoint,
                                   kHorizontalDim, text_pt)
        elif abs(x) < 0.01:
            # Hole on Y axis — one vertical construction line
            line = dim_sketch.SketchLines.AddByTwoPoints(
                tg.CreatePoint2d(0.0, 0.0),
                tg.CreatePoint2d(0.0, y_cm)
            )
            line.Construction = True
            text_pt = tg.CreatePoint2d(-1.5, y_cm / 2)
            dc.AddTwoPointDistance(line.StartSketchPoint, line.EndSketchPoint,
                                   kVerticalDim, text_pt)
        else:
            # Hole at (x, y) — two construction lines: H and V legs
            h_line = dim_sketch.SketchLines.AddByTwoPoints(
                tg.CreatePoint2d(0.0, 0.0),
                tg.CreatePoint2d(x_cm, 0.0)
            )
            h_line.Construction = True
            v_line = dim_sketch.SketchLines.AddByTwoPoints(
                tg.CreatePoint2d(x_cm, 0.0),
                tg.CreatePoint2d(x_cm, y_cm)
            )
            v_line.Construction = True
            # Horizontal dim (X distance from center)
            dc.AddTwoPointDistance(h_line.StartSketchPoint, h_line.EndSketchPoint,
                                   kHorizontalDim, tg.CreatePoint2d(x_cm / 2, -1.5))
            # Vertical dim (Y distance)
            dc.AddTwoPointDistance(v_line.StartSketchPoint, v_line.EndSketchPoint,
                                   kVerticalDim, tg.CreatePoint2d(x_cm + 1.5, y_cm / 2))

    # ---------- Diagnostics / token-saving helpers ----------

    def _vol_state(self):
        """(volume_mm3, faces, edges) of body 1, or None if no body."""
        try:
            comp = self.active_part()
            mp = comp.MassProperties
            body = comp.SurfaceBodies.Item(1)
            return (mp.Volume * 1000, body.Faces.Count, body.Edges.Count)
        except Exception:
            return None

    def _fmt_delta(self, before):
        """Compact ' | V 35271 (−7854) | F7 E16' suffix comparing to 'before' state."""
        after = self._vol_state()
        if not after:
            return ""
        if not before:
            # first feature — no 'before' body existed
            return f" | V {after[0]:.0f} mm³ | F{after[1]} E{after[2]}"
        dv = after[0] - before[0]
        return f" | V {after[0]:.0f} ({dv:+.0f} mm³) | F{after[1]} E{after[2]}"

    def inspect(self) -> dict:
        """Compact one-call snapshot of the active part."""
        doc = self.active_document()
        comp = doc.ComponentDefinition
        info: dict = {"document": doc.DisplayName}
        try:
            body = comp.SurfaceBodies.Item(1)
            rb = body.RangeBox
            mp = comp.MassProperties
            info["volume_mm3"] = round(mp.Volume * 1000)
            info["bbox_mm"] = {
                "x": [round(rb.MinPoint.X * 10, 2), round(rb.MaxPoint.X * 10, 2)],
                "y": [round(rb.MinPoint.Y * 10, 2), round(rb.MaxPoint.Y * 10, 2)],
                "z": [round(rb.MinPoint.Z * 10, 2), round(rb.MaxPoint.Z * 10, 2)],
            }
            info["faces"] = body.Faces.Count
            info["edges"] = body.Edges.Count
        except Exception:
            info["body"] = "none"
        feats = []
        for i in range(1, comp.Features.Count + 1):
            f = comp.Features.Item(i)
            nm = f.Name
            if getattr(f, "Suppressed", False):
                nm += " [suppressed]"
            feats.append(f"[{i}] {nm}")
        info["features"] = feats
        info["sketches"] = [comp.Sketches.Item(i).Name for i in range(1, comp.Sketches.Count + 1)]
        try:
            info["sheet_metal_thickness"] = str(comp.ActiveSheetMetalStyle.Thickness)
        except Exception:
            pass
        return info

    def list_edges(self, body_index: int = 1, min_length: float = 0, max_count: int = 60) -> str:
        """Compact edge table: '[i] L=200.0 mid=(0.0,-225.0,0.8)' one per line.
        min_length filters out tiny edges (mm)."""
        body = self.active_part().SurfaceBodies.Item(body_index)
        lines = []
        for i in range(1, body.Edges.Count + 1):
            try:
                e = body.Edges.Item(i)
                sv, ev = e.StartVertex.Point, e.StopVertex.Point
                L = ((ev.X - sv.X) ** 2 + (ev.Y - sv.Y) ** 2 + (ev.Z - sv.Z) ** 2) ** 0.5 * 10
                if L < min_length:
                    continue
                mx, my, mz = (sv.X + ev.X) / 2 * 10, (sv.Y + ev.Y) / 2 * 10, (sv.Z + ev.Z) / 2 * 10
                lines.append(f"[{i}] L={L:.1f} mid=({mx:.1f},{my:.1f},{mz:.1f})")
            except Exception:
                lines.append(f"[{i}] (closed curve)")
            if len(lines) >= max_count:
                lines.append(f"... truncated at {max_count}")
                break
        return "\n".join(lines) if lines else "(no edges match)"

    def list_faces(self, body_index: int = 1, min_area: float = 0, max_count: int = 60) -> str:
        """Compact face table: '[i] Plane A=90000 c=(0.0,225.0,12.5)' one per line.
        min_area in mm²."""
        type_names = {5890: "Plane", 5891: "Cyl", 5892: "Cone", 5893: "Cone",
                      5894: "Sphere", 5895: "Torus"}
        body = self.active_part().SurfaceBodies.Item(body_index)
        lines = []
        for i in range(1, body.Faces.Count + 1):
            try:
                f = body.Faces.Item(i)
                a = f.Evaluator.Area * 100
                if a < min_area:
                    continue
                xs, ys, zs = [], [], []
                for v in range(1, f.Vertices.Count + 1):
                    p = f.Vertices.Item(v).Point
                    xs.append(p.X * 10); ys.append(p.Y * 10); zs.append(p.Z * 10)
                t = type_names.get(f.SurfaceType, str(f.SurfaceType))
                if xs:
                    c = f"c=({sum(xs)/len(xs):.1f},{sum(ys)/len(ys):.1f},{sum(zs)/len(zs):.1f})"
                else:
                    c = "c=(closed)"
                lines.append(f"[{i}] {t} A={a:.0f} {c}")
            except Exception:
                lines.append(f"[{i}] ?")
            if len(lines) >= max_count:
                lines.append(f"... truncated at {max_count}")
                break
        return "\n".join(lines) if lines else "(no faces match)"

    # ---------- Transactions (rollback support) ----------

    def transaction(self, action: str = "begin", name: str = "MCP batch") -> str:
        """begin: start an undo-transaction wrapping subsequent operations.
        commit: finalize. abort: roll back EVERYTHING since begin (one undo unit)."""
        action = action.lower()
        if action == "begin":
            if getattr(self, "_txn", None) is not None:
                return "Transaction already open — commit or abort it first"
            self._txn = self.app.TransactionManager.StartTransaction(
                self.app.ActiveDocument, name)
            return f"Transaction '{name}' started"
        if action == "commit":
            if getattr(self, "_txn", None) is None:
                return "No open transaction"
            self._txn.End()
            self._txn = None
            return "Transaction committed"
        if action == "abort":
            if getattr(self, "_txn", None) is None:
                return "No open transaction"
            self._txn.Abort()
            self._txn = None
            return "Transaction aborted — all changes since 'begin' rolled back"
        return f"Unknown action '{action}'. Use begin / commit / abort."

    def _plane_face(self, axis: str, value: float, body_index: int = 1, tol: float = 0.1):
        """Largest planar face whose vertices ALL lie at <axis>==value (mm).
        Re-resolve after every feature — face objects/indices go stale."""
        body = self.active_part().SurfaceBodies.Item(body_index)
        best_f, best_a = None, 0
        for i in range(1, body.Faces.Count + 1):
            f = body.Faces.Item(i)
            if f.SurfaceType != 5890:  # plane
                continue
            ok = True
            for v in range(1, f.Vertices.Count + 1):
                p = f.Vertices.Item(v).Point
                c = {"x": p.X, "y": p.Y, "z": p.Z}[axis.lower()] * 10
                if abs(c - value) > tol:
                    ok = False
                    break
            if ok:
                a = f.Evaluator.Area
                if a > best_a:
                    best_a, best_f = a, f
        if best_f is None:
            raise ValueError(f"No planar face at {axis}={value}mm")
        return best_f

    def _face_edge(self, face, axis: str, value: float, tol: float = 0.1):
        """Edge of a face whose BOTH vertices lie at <axis>==value (mm)."""
        for i in range(1, face.Edges.Count + 1):
            e = face.Edges.Item(i)
            sv, ev = e.StartVertex.Point, e.StopVertex.Point
            cs = {"x": sv.X, "y": sv.Y, "z": sv.Z}[axis.lower()] * 10
            ce = {"x": ev.X, "y": ev.Y, "z": ev.Z}[axis.lower()] * 10
            if abs(cs - value) < tol and abs(ce - value) < tol:
                return e
        raise ValueError(f"No edge of face at {axis}={value}mm")

    def hole_linear(
        self,
        face_axis: str, face_value: float,
        ref1_axis: str, ref1_value: float, dist1: float,
        ref2_axis: str, ref2_value: float, dist2: float,
        diameter: float = 5.5,
        depth: float = 0,
        tapped: bool = False,
        pitch: float | None = None,
        cbore_diameter: float = 0,
        cbore_depth: float = 0,
    ) -> str:
        """Hole placed parametrically from two face edges (Linear placement).

        The hole stays attached to the edges — change the part length and the
        hole keeps its 8mm-from-edge distance. This is the preferred way to
        place fastener holes (vs sketch-point placement with absolute coords).

        face_axis/face_value: the planar face to drill into, e.g. ("z", 25) = top.
        ref1/ref2: two edges OF THAT FACE by their constant coordinate,
                   e.g. ("x", -34.5, 8) = 8mm from the left edge.
        depth: 0 = through-all, otherwise mm.
        tapped: ISO metric thread (uses standard coarse pitch unless pitch given).
        cbore_diameter/cbore_depth: >0 adds a counterbore (e.g. 10 and 5.5 for
                   an M5 ISO 4762 socket head cap screw seat).

        Direction is resolved automatically: try positive, check that material
        was actually removed (volume), flip to negative if not.
        """
        comp = self.active_part()
        tg = self._tg()
        hf = comp.Features.HoleFeatures
        doc = self.active_document()

        # Build the hole argument (diameter or TapInfo)
        if tapped:
            if pitch is None:
                dia_int = int(round(diameter))
                pitch = self._METRIC_COARSE_PITCH.get(dia_int)
                if pitch is None:
                    raise ValueError(f"No standard coarse pitch for M{dia_int}")
            dia_int = int(round(diameter))
            pitch_str = str(int(pitch)) if pitch == int(pitch) else str(pitch)
            hole_arg = hf.CreateTapInfo(
                True, "ISO Metric profile", f"M{dia_int}x{pitch_str}", "6H", True)
            type_str = f"M{dia_int} tapped"
        else:
            hole_arg = diameter / 10.0
            type_str = f"D={diameter}mm"

        v0 = comp.MassProperties.Volume * 1000

        for direction in (kPositiveExtentDirection, kNegativeExtentDirection):
            # Re-resolve topology fresh each attempt
            face = self._plane_face(face_axis, face_value)
            e1 = self._face_edge(face, ref1_axis, ref1_value)
            e2 = self._face_edge(face, ref2_axis, ref2_value)

            # BiasPoint: 3D point near the intended hole location. Compute by
            # stepping from each reference edge toward the face centroid.
            xs, ys, zs = [], [], []
            for v in range(1, face.Vertices.Count + 1):
                p = face.Vertices.Item(v).Point
                xs.append(p.X * 10); ys.append(p.Y * 10); zs.append(p.Z * 10)
            centroid = {"x": sum(xs)/len(xs), "y": sum(ys)/len(ys), "z": sum(zs)/len(zs)}
            coords = dict(centroid)
            coords[face_axis.lower()] = face_value
            sgn1 = 1 if centroid[ref1_axis.lower()] >= ref1_value else -1
            coords[ref1_axis.lower()] = ref1_value + sgn1 * dist1
            sgn2 = 1 if centroid[ref2_axis.lower()] >= ref2_value else -1
            coords[ref2_axis.lower()] = ref2_value + sgn2 * dist2
            bias = tg.CreatePoint(coords["x"] / 10, coords["y"] / 10, coords["z"] / 10)

            placement = hf.CreateLinearPlacementDefinition(
                face, e1, dist1 / 10.0, e2, dist2 / 10.0, bias)

            if cbore_diameter > 0:
                d_cm = depth / 10.0 if depth > 0 else 10.0  # cbore needs finite depth
                feature = hf.AddCBoreByDistanceExtent(
                    placement, hole_arg, d_cm, direction,
                    cbore_diameter / 10.0, cbore_depth / 10.0)
                extent_str = f"{depth}mm deep, cbore Ø{cbore_diameter}x{cbore_depth}"
            elif depth > 0:
                feature = hf.AddDrilledByDistanceExtent(
                    placement, hole_arg, depth / 10.0, direction)
                extent_str = f"{depth}mm deep"
            else:
                feature = hf.AddDrilledByThroughAllExtent(
                    placement, hole_arg, direction)
                extent_str = "through-all"

            doc.Update()
            v1 = comp.MassProperties.Volume * 1000
            if v1 < v0 - 1:  # material removed — direction correct
                return (f"Hole {type_str} {extent_str} on {face_axis}={face_value} "
                        f"({dist1}mm from {ref1_axis}={ref1_value}, "
                        f"{dist2}mm from {ref2_axis}={ref2_value}): {feature.Name}"
                        f" | V {v1:.0f} ({v1-v0:+.0f} mm³)")
            feature.Delete()
            doc.Update()

        raise RuntimeError("Hole removed no material in either direction — check placement")

    def circular_pattern(
        self,
        feature_index: int,
        count: int = 8,
        angle: float = 360,
        axis: str = "Z",
    ) -> str:
        """Create a circular pattern of a feature around a work axis.
        Distributes 'count' instances evenly within 'angle' degrees.
        """
        import math
        comp = self.active_part()
        cpf = comp.Features.CircularPatternFeatures

        # Get the feature to pattern
        feature = comp.Features.Item(feature_index)

        feat_col = self.app.TransientObjects.CreateObjectCollection()
        feat_col.Add(feature)

        # Work axis selection (X=1, Y=2, Z=3)
        axis_map = {"X": 1, "Y": 2, "Z": 3}
        axis_index = axis_map.get(axis.upper(), 3)
        axis_obj = comp.WorkAxes.Item(axis_index)

        angle_rad = math.radians(angle)

        pattern = cpf.Add(
            feat_col,    # ParentFeatures — ObjectCollection
            axis_obj,    # AxisEntity — WorkAxis
            True,        # NaturalAxisDirection
            count,       # Count
            angle_rad,   # Angle (radians, total span)
            True,        # FitWithinAngle — distribute evenly within angle
            47363,       # ComputeType = kOptimizedCompute (default)
        )

        return (
            f"Circular pattern: {count}x '{feature.Name}' "
            f"around {axis.upper()}-axis, {angle} deg: {pattern.Name}"
        )

    # ---------- Parameters ----------

    def get_parameters(self) -> list[dict]:
        doc = self.active_document()
        params = doc.ComponentDefinition.Parameters
        result = []
        for i in range(1, params.Count + 1):
            p = params.Item(i)
            try:
                result.append({
                    "name": p.Name,
                    "value": p.Value,
                    "expression": p.Expression,
                    "unit": p.Units if hasattr(p, "Units") else "",
                })
            except Exception:
                pass
        return result

    def set_parameter(self, name: str, expression: str) -> str:
        doc = self.active_document()
        params = doc.ComponentDefinition.Parameters
        for i in range(1, params.Count + 1):
            p = params.Item(i)
            if p.Name.lower() == name.lower():
                p.Expression = expression
                doc.Update()
                return f"Parameter '{name}' set to '{expression}' (value={p.Value})"
        raise ValueError(f"Parameter '{name}' not found.")

    def add_parameter(self, name: str, expression: str, units: str = "mm") -> str:
        doc = self.active_document()
        params = doc.ComponentDefinition.Parameters.UserParameters
        params.AddByExpression(name, expression, units)
        doc.Update()
        return f"User parameter '{name}' = '{expression}' ({units}) added"

    # ---------- Query ----------

    def get_document_info(self) -> dict:
        doc = self.active_document()
        comp = doc.ComponentDefinition
        info = {
            "name": doc.DisplayName,
            "full_path": doc.FullFileName,
            "type": str(doc.DocumentType),
            "sketches_count": comp.Sketches.Count,
            "features_count": comp.Features.Count if hasattr(comp.Features, "Count") else 0,
            "bodies_count": comp.SurfaceBodies.Count,
        }
        if comp.SurfaceBodies.Count > 0:
            body = comp.SurfaceBodies.Item(1)
            info["edges_count"] = body.Edges.Count
            info["faces_count"] = body.Faces.Count
        return info

    def list_features(self) -> list[dict]:
        comp = self.active_part()
        result = []
        for i in range(1, comp.Features.Count + 1):
            f = comp.Features.Item(i)
            result.append({
                "index": i,
                "name": f.Name,
                "type": str(f.Type),
                "suppressed": f.Suppressed if hasattr(f, "Suppressed") else False,
            })
        return result

    def delete_feature(self, indices: list[int]) -> str:
        """Delete features by index. Always deletes in reverse order to avoid index shifting."""
        comp = self.active_part()
        total = comp.Features.Count
        for idx in sorted(indices, reverse=True):
            if idx < 1 or idx > total:
                raise ValueError(f"Feature index {idx} out of range (1–{total})")
            name = comp.Features.Item(idx).Name
            comp.Features.Item(idx).Delete()
            total -= 1
        deleted = sorted(indices)
        return f"Deleted {len(indices)} feature(s): indices {deleted}"

    def suppress_feature(self, indices: list[int], suppressed: bool = True) -> str:
        """Suppress or unsuppress features by index."""
        comp = self.active_part()
        names = []
        for idx in indices:
            f = comp.Features.Item(idx)
            f.Suppressed = suppressed
            names.append(f.Name)
        state = "Suppressed" if suppressed else "Unsuppressed"
        return f"{state}: {', '.join(names)}"

    # ---------- Sheet Metal Features ----------

    def set_sheet_metal_thickness(self, thickness_mm: float) -> str:
        """Set the thickness of the active sheet metal style. Inventor 2026.
        Uses local decimal (comma) — required by Inventor for European locales.
        """
        comp = self.active_part()
        style = comp.ActiveSheetMetalStyle
        # Try comma decimal first (European), fall back to dot
        try:
            style.Thickness = f"{thickness_mm:.3f}".replace(".", ",") + " mm"
        except Exception:
            style.Thickness = f"{thickness_mm:.3f} mm"
        return f"Sheet metal thickness set to {thickness_mm}mm (style: {style.Name})"

    def sheet_metal_face(self, sketch_index: int | None = None) -> str:
        """Create a base sheet-metal Face from a closed sketch profile.
        Equivalent of the 'Face' command in Inventor Sheet Metal UI.
        Uses the active sheet metal style's thickness automatically.
        """
        comp = self.active_part()
        sketch = self._get_sketch(sketch_index)
        profile = sketch.Profiles.AddForSolid()
        ff = comp.Features.FaceFeatures
        before = self._vol_state()
        fdef = ff.CreateFaceFeatureDefinition(profile)
        feat = ff.Add(fdef)
        return f"Sheet metal face: {feat.Name}{self._fmt_delta(before)}"

    def flange(
        self,
        edge_indices: list[int],
        distance: float = 25,
        angle: float = 90,
        body_index: int = 1,
    ) -> str:
        """Add a Sheet Metal Flange to one or more edges. Inventor 2026.

        distance: flange height in mm (default 25mm = Inventor's own default)
        angle: bend angle in degrees, default 90° (perpendicular)
        edge_indices: 1-based indices into the body's Edges collection

        IMPORTANT (Inventor 2026 sheet metal quirk):
          - CreateFlangeDefinition(Edges, AngleRad, Distance) ignores the Distance arg.
          - The resulting flange always defaults to height 25mm regardless of what you pass.
          - We work around by editing the resulting feature's parameter:
              feat.Definition.HeightExtent.Distance.Expression = "<distance> mm"
          - The Distance is a Parameter (d15-ish name) — changing its Expression
            re-evaluates the feature correctly.
          - Angle must be in RADIANS (Inventor multiplies by 180/π for display).
            Passing 90 → 5156°. Always convert via math.radians().

        Measurement default = "From Outer Intersection" (HeightDatumType=75521).
        With this datum the Distance value EQUALS the visible perpendicular height
        of the flange — material thickness is NOT subtracted. So distance=450 gives
        a body that reaches Z=450 (when the flange goes upward from a Z=0 dno).
        """
        import math
        comp = self.active_part()
        body = comp.SurfaceBodies.Item(body_index)
        ec = self.app.TransientObjects.CreateEdgeCollection()
        for idx in edge_indices:
            ec.Add(body.Edges.Item(idx))

        flf = comp.Features.FlangeFeatures
        angle_rad = math.radians(angle)
        before = self._vol_state()
        # Distance arg is ignored by Inventor — we set it explicitly after Add
        fdef = flf.CreateFlangeDefinition(ec, angle_rad, 2.5)
        feat = flf.Add(fdef)
        # Set actual distance via the Parameter
        feat.Definition.HeightExtent.Distance.Expression = f"{distance} mm"
        # Update so subsequent feature/edge operations see correct geometry
        self.active_document().Update()
        return f"Flange {distance}mm @ {angle}° on {ec.Count} edge(s): {feat.Name}{self._fmt_delta(before)}"

    def sheet_metal_cut(
        self,
        sketch_index: int | None = None,
        cut_across_bends: bool = False,
    ) -> str:
        """Cut through the sheet using a sketch profile. Sheet Metal Cut.
        Default: cut perpendicular to the face (through thickness).
        cut_across_bends: if True, cut wraps around bends (unfolds first).
        """
        comp = self.active_part()
        sketch = self._get_sketch(sketch_index)
        profile = sketch.Profiles.AddForSolid()

        cf = comp.Features.CutFeatures
        before = self._vol_state()
        cdef = cf.CreateCutDefinition(profile)
        # Default extent = through thickness (kThroughAllExtent style)
        feat = cf.Add(cdef)
        return f"Sheet metal cut: {feat.Name}{self._fmt_delta(before)}"

    def find_edge(
        self,
        body_index: int = 1,
        x: float | None = None,
        y: float | None = None,
        z: float | None = None,
        tolerance: float = 0.1,
    ) -> int:
        """Locate a body edge by its midpoint coordinates (mm). Returns 1-based index.
        Pass any subset of x/y/z — None values are not constrained.
        Useful for finding the edge to flange (no need to print all 20 edges).
        """
        comp = self.active_part()
        body = comp.SurfaceBodies.Item(body_index)
        for i in range(1, body.Edges.Count + 1):
            e = body.Edges.Item(i)
            sv, ev = e.StartVertex.Point, e.StopVertex.Point
            mx = (sv.X + ev.X) / 2 * 10
            my = (sv.Y + ev.Y) / 2 * 10
            mz = (sv.Z + ev.Z) / 2 * 10
            if x is not None and abs(mx - x) > tolerance: continue
            if y is not None and abs(my - y) > tolerance: continue
            if z is not None and abs(mz - z) > tolerance: continue
            return i
        criteria = ", ".join(
            f"{k}={v}" for k, v in [("x", x), ("y", y), ("z", z)] if v is not None
        )
        raise ValueError(f"No edge found matching midpoint ({criteria}) tol={tolerance}mm")

    def find_face(
        self,
        body_index: int = 1,
        x: float | None = None,
        y: float | None = None,
        z: float | None = None,
        min_area: float = 100,
        surface_type: int = 5890,
        tolerance: float = 0.5,
    ) -> int:
        """Locate a body face by its centroid coordinates (mm). Returns 1-based index.

        Useful for: finding a panel face to sketch on for sheet metal Cut.
        Centroid is computed as the average of the face's vertices.

        surface_type: 5890=Plane (default), 5891=Cylinder, 5892=Cone, 5893=Sphere, 5894=Torus
        min_area: filter out small auxiliary faces (mm²)
        tolerance: how close the centroid must be (mm)
        """
        comp = self.active_part()
        body = comp.SurfaceBodies.Item(body_index)
        for i in range(1, body.Faces.Count + 1):
            f = body.Faces.Item(i)
            if surface_type is not None and f.SurfaceType != surface_type: continue
            try:
                xs, ys, zs = [], [], []
                for vi in range(1, f.Vertices.Count + 1):
                    v = f.Vertices.Item(vi)
                    xs.append(v.Point.X * 10)
                    ys.append(v.Point.Y * 10)
                    zs.append(v.Point.Z * 10)
                if not xs: continue
                cx = sum(xs) / len(xs)
                cy = sum(ys) / len(ys)
                cz = sum(zs) / len(zs)
                area_mm2 = f.Evaluator.Area * 100
                if area_mm2 < min_area: continue
                if x is not None and abs(cx - x) > tolerance: continue
                if y is not None and abs(cy - y) > tolerance: continue
                if z is not None and abs(cz - z) > tolerance: continue
                return i
            except Exception:
                continue
        criteria = ", ".join(
            f"{k}={v}" for k, v in [("x", x), ("y", y), ("z", z)] if v is not None
        )
        raise ValueError(f"No face matching centroid ({criteria}) area≥{min_area} tol={tolerance}mm")

    # ---------- Assembly & Kinematics management ----------

    def active_assembly(self):
        """Return the active AssemblyComponentDefinition, or raise RuntimeError if not an assembly."""
        try:
            doc = self.app.ActiveDocument
        except Exception as e:
            raise RuntimeError(f"app.ActiveDocument call failed: {e}") from e
        if doc is None:
            raise RuntimeError("No document open in Inventor.")
        if doc.DocumentType != kAssemblyDocumentObject:
            raise RuntimeError(
                f"Active document is not an assembly (DocumentType={doc.DocumentType}): {doc.DisplayName}"
            )
        try:
            return doc.ComponentDefinition
        except Exception as e:
            raise RuntimeError(f"doc.ComponentDefinition call failed: {e}") from e

    def create_assembly(self, name: str | None = None, template: str = "metric") -> str:
        """Create a new assembly document (.iam)."""
        try:
            templates_path = self.app.FileLocations.TemplatesPath
        except Exception as e:
            raise RuntimeError(f"app.FileLocations.TemplatesPath call failed: {e}") from e

        candidates_patterns = [
            os.path.join(templates_path, "Metric", "Standard (mm).iam"),
            os.path.join(templates_path, "Metric", "Standard.iam"),
            os.path.join(templates_path, "**", "Standard (mm).iam"),
            os.path.join(templates_path, "**", "*.iam"),
            os.path.join(templates_path, "Standard.iam"),
        ]
        template_file = None
        for pattern in candidates_patterns:
            if "*" in pattern:
                found = glob.glob(pattern, recursive=True)
                if found:
                    template_file = found[0]
                    break
            elif os.path.exists(pattern):
                template_file = pattern
                break

        try:
            if template_file:
                doc = self.app.Documents.Add(kAssemblyDocumentObject, template_file, True)
            else:
                doc = self.app.Documents.Add(kAssemblyDocumentObject, "", True)
        except Exception as e:
            raise RuntimeError(f"app.Documents.Add(kAssemblyDocumentObject) failed: {e}") from e

        if name:
            try:
                doc.DisplayName = name
            except Exception:
                pass
        return f"Created assembly: {doc.DisplayName}"

    def open_assembly(self, file_path: str, visible: bool = True) -> str:
        """Open an existing assembly document."""
        if not os.path.isabs(file_path):
            file_path = os.path.abspath(file_path)
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Assembly file not found: {file_path}")
        try:
            doc = self.app.Documents.Open(file_path, visible)
            return f"Opened assembly: {doc.DisplayName} ({file_path})"
        except Exception as e:
            raise RuntimeError(f"app.Documents.Open failed for '{file_path}': {e}") from e

    def add_component(
        self, component_path: str, x: float = 0.0, y: float = 0.0, z: float = 0.0
    ) -> str:
        """Add a component occurrence (.ipt or .iam) to the active assembly.
        Input coordinates x, y, z are in millimeters; converted to cm internally.
        """
        cdef = self.active_assembly()
        if not os.path.isabs(component_path):
            component_path = os.path.abspath(component_path)
        if not os.path.exists(component_path):
            raise FileNotFoundError(f"Component file not found: {component_path}")

        try:
            tg = self.app.TransientGeometry
            matrix = tg.CreateMatrix()
            matrix.SetTranslation(tg.CreateVector(x / 10.0, y / 10.0, z / 10.0))
        except Exception as e:
            raise RuntimeError(f"TransientGeometry matrix setup failed: {e}") from e

        try:
            occ = cdef.Occurrences.Add(component_path, matrix)
            return (
                f"Added occurrence '{occ.Name}' from '{os.path.basename(component_path)}' "
                f"at ({x:.1f}, {y:.1f}, {z:.1f}) mm"
            )
        except Exception as e:
            raise RuntimeError(f"cdef.Occurrences.Add failed for '{component_path}': {e}") from e

    def _resolve_occurrence_entity(self, occ, entity_type: str, entity_idx_or_name: int | str):
        """Resolve a work plane, axis, point, face, or edge on an occurrence."""
        cdef_sub = occ.Definition
        etype = entity_type.lower().strip()
        try:
            if etype in ("plane", "workplane"):
                if isinstance(entity_idx_or_name, int) or str(entity_idx_or_name).isdigit():
                    return cdef_sub.WorkPlanes.Item(int(entity_idx_or_name))
                for wp in cdef_sub.WorkPlanes:
                    if wp.Name.lower() == str(entity_idx_or_name).lower():
                        return wp
                return cdef_sub.WorkPlanes.Item(entity_idx_or_name)
            elif etype in ("axis", "workaxis"):
                if isinstance(entity_idx_or_name, int) or str(entity_idx_or_name).isdigit():
                    return cdef_sub.WorkAxes.Item(int(entity_idx_or_name))
                for wa in cdef_sub.WorkAxes:
                    if wa.Name.lower() == str(entity_idx_or_name).lower():
                        return wa
                return cdef_sub.WorkAxes.Item(entity_idx_or_name)
            elif etype in ("point", "workpoint"):
                if isinstance(entity_idx_or_name, int) or str(entity_idx_or_name).isdigit():
                    return cdef_sub.WorkPoints.Item(int(entity_idx_or_name))
                for pt in cdef_sub.WorkPoints:
                    if pt.Name.lower() == str(entity_idx_or_name).lower():
                        return pt
                return cdef_sub.WorkPoints.Item(entity_idx_or_name)
            elif etype in ("face",):
                idx = int(entity_idx_or_name)
                body = cdef_sub.SurfaceBodies.Item(1)
                return body.Faces.Item(idx)
            elif etype in ("edge",):
                idx = int(entity_idx_or_name)
                body = cdef_sub.SurfaceBodies.Item(1)
                return body.Edges.Item(idx)
            else:
                raise ValueError(
                    f"Unsupported entity type: '{entity_type}'. Must be plane, axis, point, face, or edge."
                )
        except Exception as e:
            raise RuntimeError(
                f"_resolve_occurrence_entity failed for occurrence '{occ.Name}', "
                f"type '{entity_type}', entity '{entity_idx_or_name}': {e}"
            ) from e

    def add_assembly_constraint(
        self,
        occ1_name: str,
        entity1_type: str,
        entity1_idx: int | str,
        occ2_name: str,
        entity2_type: str,
        entity2_idx: int | str,
        constraint_type: str,
        offset_cm: float = 0.0,
        name: str | None = None,
        limits: dict | None = None,
    ) -> str:
        """Add an assembly constraint (mate, flush, angle, insert) between occurrences with optional travel limits."""
        cdef = self.active_assembly()
        try:
            occ1 = cdef.Occurrences.ItemByName(occ1_name)
        except Exception as e:
            raise RuntimeError(f"Occurrence '{occ1_name}' not found: {e}") from e
        try:
            occ2 = cdef.Occurrences.ItemByName(occ2_name)
        except Exception as e:
            raise RuntimeError(f"Occurrence '{occ2_name}' not found: {e}") from e

        e1 = self._resolve_occurrence_entity(occ1, entity1_type, entity1_idx)
        e2 = self._resolve_occurrence_entity(occ2, entity2_type, entity2_idx)

        try:
            proxy1 = occ1.CreateGeometryProxy(e1)
        except Exception as e:
            raise RuntimeError(f"occ1.CreateGeometryProxy failed on '{occ1_name}': {e}") from e
        try:
            proxy2 = occ2.CreateGeometryProxy(e2)
        except Exception as e:
            raise RuntimeError(f"occ2.CreateGeometryProxy failed on '{occ2_name}': {e}") from e

        ctype = constraint_type.lower().strip()
        c = None
        try:
            if ctype == "mate":
                c = cdef.Constraints.AddMateConstraint(proxy1, proxy2, float(offset_cm))
            elif ctype == "flush":
                c = cdef.Constraints.AddFlushConstraint(proxy1, proxy2, float(offset_cm))
            elif ctype == "angle":
                # kUndirectedSolution (78594) required for limits in Inventor; kDirectedSolution (78593) otherwise
                angle_sol = kUndirectedSolution if limits else kDirectedSolution
                angle_expr = f"{offset_cm} deg" if isinstance(offset_cm, (int, float)) else str(offset_cm)
                c = cdef.Constraints.AddAngleConstraint(proxy1, proxy2, angle_expr, angle_sol)
            elif ctype == "insert":
                c = cdef.Constraints.AddInsertConstraint(proxy1, proxy2, True, float(offset_cm))
            else:
                raise ValueError(
                    f"Unknown constraint type '{constraint_type}'. Expected mate, flush, angle, or insert."
                )
        except Exception as e:
            raise RuntimeError(f"cdef.Constraints.Add{ctype.capitalize()}Constraint failed: {e}") from e

        if name:
            try:
                c.Name = name
            except Exception:
                pass

        if limits:
            try:
                min_val = limits.get("min") or limits.get("min_cm") or limits.get("min_deg")
                max_val = limits.get("max") or limits.get("max_cm") or limits.get("max_deg")

                if min_val is not None:
                    c.ConstraintLimits.MinimumEnabled = True
                    expr = f"{min_val} cm" if ("min_cm" in limits and not str(min_val).endswith("cm")) else (
                        f"{min_val} deg" if ("min_deg" in limits and not str(min_val).endswith("deg")) else str(min_val)
                    )
                    c.ConstraintLimits.Minimum.Expression = expr

                if max_val is not None:
                    c.ConstraintLimits.MaximumEnabled = True
                    expr = f"{max_val} cm" if ("max_cm" in limits and not str(max_val).endswith("cm")) else (
                        f"{max_val} deg" if ("max_deg" in limits and not str(max_val).endswith("deg")) else str(max_val)
                    )
                    c.ConstraintLimits.Maximum.Expression = expr
            except Exception as e:
                return f"Constraint '{c.Name}' created, but failed setting limits: {e}"

        return f"Added {ctype} constraint '{c.Name}' between '{occ1_name}' and '{occ2_name}'"

    def delete_assembly_constraint(self, name: str) -> bool:
        """Delete an assembly constraint by name."""
        cdef = self.active_assembly()
        try:
            for c in list(cdef.Constraints):
                if c.Name.lower() == name.lower():
                    c.Delete()
                    return True
            return False
        except Exception as e:
            raise RuntimeError(f"Failed deleting constraint '{name}': {e}") from e

    def delete_constraint(self, name: str) -> bool:
        """Alias for delete_assembly_constraint."""
        return self.delete_assembly_constraint(name)

    def set_constraint_expression(self, constraint_name: str, expression: str) -> str:
        """Set parameter expression for a constraint (e.g. '15 deg', '20 mm', '-5 cm')."""
        cdef = self.active_assembly()
        target_c = None
        for c in cdef.Constraints:
            if c.Name.lower() == constraint_name.lower():
                target_c = c
                break
        if not target_c:
            raise ValueError(f"Constraint '{constraint_name}' not found.")

        try:
            if hasattr(target_c, "Angle"):
                target_c.Angle.Expression = str(expression)
            elif hasattr(target_c, "Offset"):
                target_c.Offset.Expression = str(expression)
            elif hasattr(target_c, "Distance"):
                target_c.Distance.Expression = str(expression)
            else:
                raise ValueError(f"Constraint '{constraint_name}' does not expose a parameter.")
            self.app.ActiveDocument.Update()
            return f"Updated '{constraint_name}' expression to '{expression}'"
        except Exception as e:
            raise RuntimeError(f"Setting expression on '{constraint_name}' failed: {e}") from e

    def add_assembly_joint(
        self,
        occ1_name: str,
        entity1_name: str | int,
        occ2_name: str,
        entity2_name: str | int,
        joint_type: str = "rotational",
        start_limit: str | None = None,
        end_limit: str | None = None,
        name: str | None = None,
    ) -> str:
        """Create a native Autodesk Inventor Assembly Joint.
        NOTE: Use ONLY when explicitly requested by user. Otherwise, standard constraints
        paired with Positional Representations (PosReps) are the default doctrine.
        """
        cdef = self.active_assembly()
        try:
            occ1 = cdef.Occurrences.ItemByName(occ1_name)
            occ2 = cdef.Occurrences.ItemByName(occ2_name)
        except Exception as e:
            raise RuntimeError(f"Occurrences not found ({occ1_name}, {occ2_name}): {e}") from e

        def _get_entity(occ, e_id):
            if isinstance(e_id, int):
                return occ.Definition.WorkPlanes.Item(e_id)
            for wp in occ.Definition.WorkPlanes:
                if wp.Name.lower() == str(e_id).lower():
                    return wp
            for wa in occ.Definition.WorkAxes:
                if wa.Name.lower() == str(e_id).lower():
                    return wa
            for pt in occ.Definition.WorkPoints:
                if pt.Name.lower() == str(e_id).lower():
                    return pt
            if str(e_id).isdigit():
                return occ.Definition.SurfaceBodies.Item(1).Faces.Item(int(e_id))
            raise ValueError(f"Could not resolve entity '{e_id}' on {occ.Name}")

        e1 = _get_entity(occ1, entity1_name)
        e2 = _get_entity(occ2, entity2_name)

        try:
            proxy1 = occ1.CreateGeometryProxy(e1)
            proxy2 = occ2.CreateGeometryProxy(e2)
            intent1 = cdef.CreateGeometryIntent(proxy1)
            intent2 = cdef.CreateGeometryIntent(proxy2)
        except Exception as e:
            raise RuntimeError(f"Geometry intent creation failed: {e}") from e

        jt = joint_type.lower().strip()
        type_map = {
            "rigid": kRigidJointType,
            "rotational": kRotationalJointType,
            "revolute": kRotationalJointType,
            "slide": kSlideJointType,
            "slider": kSlideJointType,
            "cylindrical": kCylindricalJointType,
            "planar": kPlanarJointType,
            "ball": kBallJointType,
        }
        if jt not in type_map:
            raise ValueError(f"Unknown joint type '{joint_type}'. Valid: {list(type_map.keys())}")
        type_code = type_map[jt]

        try:
            joint_def = cdef.Joints.CreateAssemblyJointDefinition(type_code, intent1, intent2)
        except Exception as e:
            raise RuntimeError(f"Joints.CreateAssemblyJointDefinition failed: {e}") from e

        if type_code == kRotationalJointType:
            if start_limit is not None or end_limit is not None:
                try:
                    joint_def.HasAngularPositionLimits = True
                except Exception:
                    pass
                if start_limit is not None:
                    try:
                        joint_def.AngularPositionStartLimit = str(start_limit)
                    except Exception:
                        val = float(str(start_limit).lower().replace("deg", "").strip())
                        joint_def.AngularPositionStartLimit = math.radians(val)
                if end_limit is not None:
                    try:
                        joint_def.AngularPositionEndLimit = str(end_limit)
                    except Exception:
                        val = float(str(end_limit).lower().replace("deg", "").strip())
                        joint_def.AngularPositionEndLimit = math.radians(val)
        elif type_code == kSlideJointType:
            if start_limit is not None:
                try:
                    joint_def.HasLinearPositionStartLimit = True
                    joint_def.LinearPositionStartLimit = str(start_limit)
                except Exception:
                    val = float(str(start_limit).lower().replace("mm", "").strip())
                    joint_def.LinearPositionStartLimit = val / 10.0
            if end_limit is not None:
                try:
                    joint_def.HasLinearPositionEndLimit = True
                    joint_def.LinearPositionEndLimit = str(end_limit)
                except Exception:
                    val = float(str(end_limit).lower().replace("mm", "").strip())
                    joint_def.LinearPositionEndLimit = val / 10.0

        # Snapshot Grounded flags prior to joint insertion
        # (Autodesk Inventor's internal solver can unground connected occurrences upon Joints.Add)
        occ1_was_grounded = getattr(occ1, "Grounded", False)
        occ2_was_grounded = getattr(occ2, "Grounded", False)

        try:
            joint = cdef.Joints.Add(joint_def)
            if name:
                joint.Name = name

            # Automatically restore Grounded state if solver ungrounded stationary occurrence
            restored = []
            if occ1_was_grounded and not getattr(occ1, "Grounded", False):
                try:
                    occ1.Grounded = True
                    restored.append(occ1_name)
                except Exception as e:
                    pass
            if occ2_was_grounded and not getattr(occ2, "Grounded", False):
                try:
                    occ2.Grounded = True
                    restored.append(occ2_name)
                except Exception as e:
                    pass

            restored_msg = f" (restored Grounded on: {', '.join(restored)})" if restored else ""
            return f"Created {jt} joint '{joint.Name}' between '{occ1_name}' and '{occ2_name}'{restored_msg}"
        except Exception as e:
            raise RuntimeError(f"cdef.Joints.Add failed: {e}") from e

    def delete_assembly_joint(self, name: str) -> bool:
        """Delete an assembly joint by name."""
        cdef = self.active_assembly()
        try:
            for j in list(cdef.Joints):
                if j.Name.lower() == name.lower():
                    j.Delete()
                    return True
            return False
        except Exception as e:
            raise RuntimeError(f"Failed deleting joint '{name}': {e}") from e

    def delete_joint(self, name: str) -> bool:
        """Alias for delete_assembly_joint."""
        return self.delete_assembly_joint(name)

    def enforce_subassembly_rigidity(
        self,
        occurrence_name: str | None = None,
        exclude_keywords: list[str] | None = None,
    ) -> dict:
        """Enforce internal rigidity on an assembly or subassembly occurrence.
        Performs safe grounding: skips occurrences that already have constraints
        or joints to other occurrences to prevent over-constraining or conflicting relationships.
        Dynamic mechanism parts matching exclude_keywords are excluded from grounding.
        If relationship detection fails (read errors or sanity check failure), ALL occurrences
        are skipped to prevent improper grounding.
        """
        cdef = self.active_assembly()
        subasm_label = "active assembly"

        if occurrence_name:
            try:
                occ = cdef.Occurrences.ItemByName(occurrence_name)
                target_cdef = occ.Definition
                target_doc = target_cdef.Document
                subasm_label = f"subassembly '{occurrence_name}'"
            except Exception as e:
                raise RuntimeError(f"Occurrence '{occurrence_name}' not found: {e}") from e
        else:
            target_cdef = cdef
            target_doc = self.app.ActiveDocument

        newly_grounded = []
        skipped_constrained = []
        skipped_detection_failed = []
        skipped_moving = []
        already_grounded = []

        try:
            rel_counts = _build_relationship_counts(target_cdef)

            if rel_counts is None:
                fail_reason = (
                    "Relationship detection failed (COM read error or sanity check failed: "
                    "relationships exist but matched 0 occurrences). "
                    "All occurrences skipped to prevent improper grounding."
                )
                for i in range(1, target_cdef.Occurrences.Count + 1):
                    child = target_cdef.Occurrences.Item(i)
                    skipped_detection_failed.append({
                        "name": child.Name,
                        "reason": fail_reason,
                    })
                return {
                    "subassembly": subasm_label,
                    "total_occurrences": target_cdef.Occurrences.Count,
                    "newly_grounded_count": 0,
                    "newly_grounded": [],
                    "skipped_count": 0,
                    "skipped_constrained": [],
                    "skipped_detection_failed_count": len(skipped_detection_failed),
                    "skipped_detection_failed": skipped_detection_failed,
                    "skipped_moving_count": 0,
                    "skipped_moving": [],
                    "already_grounded_count": 0,
                    "already_grounded": [],
                    "message": f"Subassembly rigidity skipped for {subasm_label}: {fail_reason}",
                }

            for i in range(1, target_cdef.Occurrences.Count + 1):
                child = target_cdef.Occurrences.Item(i)
                occ_name = child.Name

                if child.Grounded:
                    already_grounded.append(occ_name)
                    continue

                if exclude_keywords and any(kw.lower() in occ_name.lower() for kw in exclude_keywords):
                    skipped_moving.append({
                        "name": occ_name,
                        "reason": f"Excluded by user keyword match ({exclude_keywords}).",
                    })
                    continue

                rel_count = rel_counts.get(occ_name, 0)
                if rel_count > 0:
                    skipped_constrained.append({
                        "name": occ_name,
                        "relationship_count": rel_count,
                        "reason": f"Already constrained/jointed ({rel_count} active relationship(s)).",
                    })
                else:
                    child.Grounded = True
                    newly_grounded.append(occ_name)

            if target_doc and getattr(target_doc, "Dirty", False):
                try:
                    target_doc.Save()
                except Exception:
                    pass

            return {
                "subassembly": subasm_label,
                "total_occurrences": target_cdef.Occurrences.Count,
                "newly_grounded_count": len(newly_grounded),
                "newly_grounded": newly_grounded,
                "skipped_count": len(skipped_constrained),
                "skipped_constrained": skipped_constrained,
                "skipped_detection_failed_count": 0,
                "skipped_detection_failed": [],
                "skipped_moving_count": len(skipped_moving),
                "skipped_moving": skipped_moving,
                "already_grounded_count": len(already_grounded),
                "already_grounded": already_grounded,
                "message": (
                    f"Subassembly rigidity enforced for {subasm_label}: "
                    f"{len(newly_grounded)} parts grounded, {len(skipped_constrained)} constrained parts skipped, "
                    f"{len(skipped_moving)} moving parts excluded, {len(already_grounded)} already grounded."
                ),
            }
        except Exception as e:
            raise RuntimeError(f"enforce_subassembly_rigidity failed: {e}") from e

    def enforce_subassembly_internal_rigidity(
        self,
        occurrence_name: str | None = None,
        exclude_keywords: list[str] | None = None,
    ) -> dict:
        """Alias for enforce_subassembly_rigidity."""
        return self.enforce_subassembly_rigidity(occurrence_name, exclude_keywords=exclude_keywords)

    def set_occurrence_flexible(self, occ_name: str, flexible: bool = True) -> bool:
        """Set whether a subassembly occurrence evaluates internal degrees of freedom in parent."""
        cdef = self.active_assembly()
        try:
            occ = cdef.Occurrences.ItemByName(occ_name)
            occ.Flexible = bool(flexible)
            return occ.Flexible
        except Exception as e:
            raise RuntimeError(f"set_occurrence_flexible failed on '{occ_name}': {e}") from e

    def set_occurrence_grounded(self, occ_name: str, grounded: bool = True) -> bool:
        """Lock or unlock an occurrence relative to the assembly origin."""
        cdef = self.active_assembly()
        try:
            occ = cdef.Occurrences.ItemByName(occ_name)
            occ.Grounded = bool(grounded)
            return occ.Grounded
        except Exception as e:
            raise RuntimeError(f"set_occurrence_grounded failed on '{occ_name}': {e}") from e

    def audit_assembly_kinematics(self) -> dict:
        """Audit active assembly occurrences, grounded flags, flexible flags,
        constraints, joints, PosReps, and unconstrained components.
        """
        doc = self.app.ActiveDocument
        cdef = self.active_assembly()

        report = {
            "assembly_name": doc.DisplayName,
            "occurrences_count": cdef.Occurrences.Count,
            "constraints_count": cdef.Constraints.Count,
            "joints_count": cdef.Joints.Count,
            "occurrences": [],
            "constraints": [],
            "joints": [],
            "positional_representations": self.list_positional_representations(),
            "warnings": [],
            "kinematic_warnings": [],
        }

        # Single-pass relationship scan
        occ_rel_counts = _build_relationship_counts(cdef)
        if occ_rel_counts is None:
            try:
                occ_rel_counts = {cdef.Occurrences.Item(i).Name: 0 for i in range(1, cdef.Occurrences.Count + 1)}
            except Exception:
                occ_rel_counts = {}
            det_warn = (
                "Relationship detection failed (COM read error or sanity check failed: "
                "relationships exist but matched 0 occurrences). Occurrence relationship counts may be incomplete."
            )
            report["warnings"].append(det_warn)
            report["kinematic_warnings"].append(det_warn)

        # 1. Audit Constraints
        for c in cdef.Constraints:
            try:
                raw_health = c.HealthStatus
            except Exception:
                raw_health = kUnknownHealth

            health_label = HEALTH_STATUS_MAP.get(raw_health, f"Unknown_{raw_health}")
            c_info = {
                "name": c.Name,
                "type_code": c.Type,
                "health_code": raw_health,
                "health": health_label,
            }
            report["constraints"].append(c_info)

            if raw_health != kUpToDateHealth:
                w = (
                    f"UNHEALTHY/UNVERIFIED CONSTRAINT: '{c.Name}' has HealthStatus='{health_label}' (code {raw_health}). "
                    "Relationship is sick, broken, unverified, or non-nominal."
                )
                report["warnings"].append(w)
                report["kinematic_warnings"].append(w)

        # 2. Audit Joints
        for j in cdef.Joints:
            j_info = {
                "name": j.Name,
                "type_code": j.Definition.JointType,
                "visible": j.Visible,
            }
            report["joints"].append(j_info)

        # 3. Audit Occurrences & detect floating components / missing grounded datum
        grounded_count = 0
        for i in range(1, cdef.Occurrences.Count + 1):
            occ = cdef.Occurrences.Item(i)
            doc_file = ""
            is_subasm = False
            try:
                doc_file = occ.Definition.Document.FullFileName
                is_subasm = doc_file.lower().endswith(".iam")
            except Exception:
                pass

            flexible = False
            try:
                if is_subasm:
                    flexible = occ.Flexible
            except Exception:
                pass

            rel_count = occ_rel_counts.get(occ.Name, 0)
            occ_info = {
                "index": i,
                "name": occ.Name,
                "file": os.path.basename(doc_file) if doc_file else "",
                "is_subassembly": is_subasm,
                "grounded": occ.Grounded,
                "flexible": flexible,
                "relationship_count": rel_count,
            }
            report["occurrences"].append(occ_info)

            if occ.Grounded:
                grounded_count += 1
            elif rel_count == 0:
                w = f"FLOATING COMPONENT: Occurrence '{occ.Name}' has Grounded=False and 0 active constraints/joints."
                report["warnings"].append(w)
                report["kinematic_warnings"].append(w)

        if grounded_count == 0 and cdef.Occurrences.Count > 0:
            w = "NO GROUNDED DATUM: Zero occurrences in the assembly are grounded. The assembly lacks a stationary reference datum."
            report["warnings"].append(w)
            report["kinematic_warnings"].append(w)

        return report

    def drive_kinematic_motion(
        self,
        target_name: str,
        start_val: float,
        end_val: float,
        steps: int = 10,
        pause_sec: float = 0.05,
        unit: str = "deg",
    ) -> bool:
        """Drive a constraint or joint across a travel range, simulating physical movement."""
        doc = self.app.ActiveDocument
        cdef = self.active_assembly()

        target_c = None
        for c in cdef.Constraints:
            if c.Name.lower() == target_name.lower():
                target_c = c
                break

        param = None
        if target_c:
            if hasattr(target_c, "Angle"):
                param = target_c.Angle
            elif hasattr(target_c, "Offset"):
                param = target_c.Offset
            elif hasattr(target_c, "Distance"):
                param = target_c.Distance

        if not param:
            raise ValueError(f"Constraint '{target_name}' not found or has no drivable parameter.")

        delta = (end_val - start_val) / max(1, steps)
        for i in range(steps + 1):
            cur_val = start_val + delta * i
            param.Expression = f"{cur_val} {unit}"
            doc.Update()
            if pause_sec > 0:
                time.sleep(pause_sec)

        return True

    def _get_asset(self, doc, asset_name: str, lib_name: str | None = None):
        """Retrieve an appearance asset from the document or Inventor material libraries."""
        for a in doc.AppearanceAssets:
            if a.DisplayName.lower() == asset_name.lower():
                return a

        for lib in self.app.AssetLibraries:
            if lib_name and lib.DisplayName.lower() != lib_name.lower():
                continue
            try:
                for a in lib.AppearanceAssets:
                    if a.DisplayName.lower() == asset_name.lower():
                        return a.CopyTo(doc)
            except Exception:
                pass
        return doc.ActiveAppearance

    def apply_appearance(
        self,
        appearance_name: str,
        target_level: str = "part",
        target_index: int = 1,
        part_path: str | None = None,
    ) -> str:
        """Apply material appearance asset override to part, surface body, or feature."""
        doc = self.app.ActiveDocument
        if doc is None:
            raise RuntimeError("No document open in Inventor.")
        asset = self._get_asset(doc, appearance_name)

        lvl = target_level.lower().strip()
        try:
            if lvl == "part":
                doc.ActiveAppearance = asset
                if hasattr(doc, "ComponentDefinition") and hasattr(doc.ComponentDefinition, "SurfaceBodies"):
                    for i in range(1, doc.ComponentDefinition.SurfaceBodies.Count + 1):
                        doc.ComponentDefinition.SurfaceBodies.Item(i).Appearance = asset
                return f"Applied appearance '{asset.DisplayName}' to entire part document."
            elif lvl in ("body", "surface_body"):
                body = doc.ComponentDefinition.SurfaceBodies.Item(target_index)
                body.Appearance = asset
                return f"Applied appearance '{asset.DisplayName}' to body {target_index}."
            elif lvl == "feature":
                cdef = doc.ComponentDefinition
                feat = None
                if isinstance(target_index, int):
                    feat = cdef.Features.Item(target_index)
                else:
                    for f in cdef.Features:
                        if f.Name.lower() == str(target_index).lower():
                            feat = f
                            break
                if not feat:
                    raise ValueError(f"Feature '{target_index}' not found.")
                feat.SetAppearance(asset)
                return f"Applied appearance '{asset.DisplayName}' to feature '{feat.Name}'."
            else:
                raise ValueError(
                    f"Unknown target_level '{target_level}'. Expected 'part', 'surface_body', or 'feature'."
                )
        except Exception as e:
            raise RuntimeError(f"apply_appearance failed at level '{target_level}': {e}") from e

    def render_showcase(
        self,
        output_png_path: str,
        eye_cm: tuple[float, float, float] = (120.0, 100.0, 150.0),
        target_cm: tuple[float, float, float] = (30.0, 50.0, 20.0),
        up_vec: tuple[float, float, float] = (0.0, 1.0, 0.0),
        width: int = 1920,
        height: int = 1440,
        display_style: str = "shaded_with_edges",
    ) -> str:
        """Position camera and render showcase bitmap. Coordinates in centimeters internally."""
        view = self.app.ActiveView
        if view is None:
            raise RuntimeError("No active view in Inventor.")

        try:
            tg = self.app.TransientGeometry
            cam = view.Camera
            cam.Eye = tg.CreatePoint(float(eye_cm[0]), float(eye_cm[1]), float(eye_cm[2]))
            cam.Target = tg.CreatePoint(float(target_cm[0]), float(target_cm[1]), float(target_cm[2]))
            cam.UpVector = tg.CreateUnitVector(float(up_vec[0]), float(up_vec[1]), float(up_vec[2]))
            cam.ApplyWithoutTransition()
        except Exception as e:
            raise RuntimeError(f"Camera orientation setup failed: {e}") from e

        style_map = {
            "shaded_with_edges": kShadedWithEdgesRendering,
            "realistic": kRealisticRendering,
            "shaded": kShadedRendering,
            "wireframe": kWireframeRendering,
        }
        mode = style_map.get(display_style.lower().strip(), kShadedWithEdgesRendering)
        try:
            view.DisplayMode = mode
        except Exception:
            pass

        try:
            view.Fit()
        except Exception:
            pass

        if not os.path.isabs(output_png_path):
            output_png_path = os.path.abspath(output_png_path)
        os.makedirs(os.path.dirname(output_png_path), exist_ok=True)

        try:
            view.SaveAsBitmap(output_png_path, int(width), int(height))
            return output_png_path
        except Exception as e:
            raise RuntimeError(f"view.SaveAsBitmap failed for '{output_png_path}': {e}") from e

    def list_positional_representations(self) -> list[str]:
        """List all positional representations in the active assembly."""
        try:
            cdef = self.active_assembly()
            pos_reps = cdef.RepresentationsManager.PositionalRepresentations
            return [rep.Name for rep in pos_reps]
        except Exception:
            return []

    def create_positional_representation(self, rep_name: str) -> str:
        """Create a new named Positional Representation."""
        cdef = self.active_assembly()
        pos_reps = cdef.RepresentationsManager.PositionalRepresentations
        for rep in pos_reps:
            if rep.Name.lower() == rep_name.lower():
                return f"Positional representation '{rep_name}' already exists."
        try:
            new_rep = pos_reps.Add(rep_name)
            return f"Created positional representation '{new_rep.Name}'."
        except Exception as e:
            raise RuntimeError(f"PositionalRepresentations.Add('{rep_name}') failed: {e}") from e

    def activate_positional_representation(self, rep_name: str) -> str:
        """Activate a named Positional Representation."""
        cdef = self.active_assembly()
        pos_reps = cdef.RepresentationsManager.PositionalRepresentations
        for rep in pos_reps:
            if rep.Name.lower() == rep_name.lower():
                try:
                    rep.Activate()
                    self.app.ActiveDocument.Update()
                    return f"Activated positional representation '{rep.Name}'."
                except Exception as e:
                    raise RuntimeError(f"rep.Activate failed for '{rep_name}': {e}") from e
        raise ValueError(f"Positional representation '{rep_name}' not found.")

    def set_constraint_override(
        self, rep_name: str, constraint_name: str, override_expression: str
    ) -> str:
        """Set a parameter value override on a constraint in a named Positional Representation."""
        cdef = self.active_assembly()
        target_c = None
        for c in cdef.Constraints:
            if c.Name.lower() == constraint_name.lower():
                target_c = c
                break
        if not target_c:
            raise ValueError(f"Constraint '{constraint_name}' not found in assembly.")

        pos_reps = cdef.RepresentationsManager.PositionalRepresentations
        target_rep = None
        for rep in pos_reps:
            if rep.Name.lower() == rep_name.lower():
                target_rep = rep
                break
        if not target_rep:
            target_rep = pos_reps.Add(rep_name)

        try:
            target_rep.Activate()
            target_rep.SetConstraintValueOverride(target_c, str(override_expression))
            self.app.ActiveDocument.Update()
            return f"Applied override on '{constraint_name}' in PosRep '{target_rep.Name}': {override_expression}"
        except Exception as e:
            raise RuntimeError(f"SetConstraintValueOverride failed: {e}") from e

    def setup_standard_max_position_representations(
        self,
        door_constraint_name: str | None = None,
        drawer_constraint_name: str | None = None,
        door_max: str = "115.0 deg",
        drawer_max: str = "-22.0 cm",
    ) -> str:
        """Setup standard appliance PosReps: Porta_Aberta_Max, Gaveta_Aberta_Max, Posicao_Maxima."""
        doc = self.app.ActiveDocument
        if door_constraint_name:
            self.set_constraint_override("Porta_Aberta_Max", door_constraint_name, door_max)
        if drawer_constraint_name:
            self.set_constraint_override("Gaveta_Aberta_Max", drawer_constraint_name, drawer_max)
        if door_constraint_name or drawer_constraint_name:
            if door_constraint_name:
                self.set_constraint_override("Posicao_Maxima", door_constraint_name, door_max)
            if drawer_constraint_name:
                self.set_constraint_override("Posicao_Maxima", drawer_constraint_name, drawer_max)

        self.activate_positional_representation("Master")
        try:
            doc.Save()
        except Exception:
            pass
        return "Configured standard maximum Positional Representations (Porta_Aberta_Max, Gaveta_Aberta_Max, Posicao_Maxima)."

    def manage_positional_representation(
        self,
        action: str = "activate",
        rep_name: str = "Master",
        constraint_name: str | None = None,
        override_expression: str | None = None,
        door_constraint_name: str | None = None,
        drawer_constraint_name: str | None = None,
    ) -> str:
        """Unified manager for Positional Representations."""
        act = action.lower().strip()
        if act == "activate":
            return self.activate_positional_representation(rep_name)
        elif act == "create":
            return self.create_positional_representation(rep_name)
        elif act == "set_override":
            if not constraint_name or not override_expression:
                raise ValueError("constraint_name and override_expression required for set_override.")
            return self.set_constraint_override(rep_name, constraint_name, override_expression)
        elif act == "setup_standard_max_positions":
            return self.setup_standard_max_position_representations(
                door_constraint_name, drawer_constraint_name
            )
        elif act == "list":
            import json
            return json.dumps(self.list_positional_representations(), indent=2)
        else:
            raise ValueError(
                f"Unknown action: '{action}'. Expected activate, create, set_override, setup_standard_max_positions, list."
            )

    def supervisor_clean_orphaned_instances(self, confirm: bool = False, target_pids: list[int] | None = None) -> dict:
        """Safe Inventor process supervisor.
        Only targets Inventor.exe instances that:
          1. Have NO main window (MainWindowHandle == 0)
          2. Are NOT the active COM instance returned by GetActiveObject
          3. Were started > 45 seconds ago (safeguard against startup races).
        Defaults to dry-run (confirm=False). When confirm=True, target_pids MUST be explicitly
        provided from a prior dry-run inspection to prevent unintended terminations.
        Verifies termination via Get-Process (never assumes success from exit codes).
        """
        import subprocess
        import json
        import time

        active_pid = None
        dirty_docs = []
        try:
            active_app = win32com.client.GetActiveObject("Inventor.Application")
            hwnd = active_app.MainFrameHWND
            import win32process
            _, active_pid = win32process.GetWindowThreadProcessId(hwnd)
            for d in active_app.Documents:
                if getattr(d, "Dirty", False):
                    dirty_docs.append(d.FullFileName or d.DisplayName)
        except Exception:
            pass

        cmd = (
            'Get-Process -Name Inventor -ErrorAction SilentlyContinue | '
            'Select-Object Id, MainWindowHandle, MainWindowTitle, WorkingSet64, '
            '@{Name="AgeSeconds"; Expression={try { [math]::Round(((Get-Date) - $_.StartTime).TotalSeconds) } catch { 0 } }} | '
            'ConvertTo-Json'
        )
        res = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True)
        procs = []
        if res.stdout.strip():
            try:
                data = json.loads(res.stdout)
                procs = [data] if isinstance(data, dict) else data
            except Exception:
                pass

        candidates = []
        safe_procs = []
        starting_procs = []
        for p in procs:
            pid = p.get("Id")
            mw_handle = p.get("MainWindowHandle", 0)
            mw_title = p.get("MainWindowTitle", "")
            ws_mb = round(p.get("WorkingSet64", 0) / (1024 * 1024), 1)
            age_sec = p.get("AgeSeconds", 0)

            is_active = (pid == active_pid)
            has_window = bool(mw_handle and mw_handle != 0)
            is_young = (age_sec < 45)

            proc_info = {
                "pid": pid,
                "main_window_handle": mw_handle,
                "main_window_title": mw_title,
                "working_set_mb": ws_mb,
                "age_seconds": age_sec,
                "is_active_com": is_active,
                "has_window": has_window,
            }

            if is_active or has_window:
                safe_procs.append(proc_info)
            elif is_young:
                proc_info["reason"] = f"Started recently ({age_sec}s ago); allowed time to initialize."
                starting_procs.append(proc_info)
            else:
                candidates.append(proc_info)

        report = {
            "active_com_pid": active_pid,
            "dirty_docs_warning": dirty_docs,
            "candidates_for_termination": candidates,
            "initializing_processes": starting_procs,
            "safe_active_or_gui_processes": safe_procs,
            "dry_run": not confirm,
        }

        if dirty_docs:
            report["warning"] = (
                f"CAUTION: {len(dirty_docs)} unsaved document(s) detected in active Inventor session: {dirty_docs}"
            )

        candidate_pids = {c["pid"] for c in candidates}

        if not confirm or not target_pids:
            report["action"] = "dry_run"
            if confirm and not target_pids:
                report["message"] = (
                    f"SAFETY GUARD: confirm=True was passed without explicit target_pids=[...]. "
                    f"To prevent terminating active automation when COM lookup is unavailable, "
                    f"you MUST supply explicit PIDs copied from a prior dry-run inspection (candidates: {list(candidate_pids)})."
                )
            else:
                report["message"] = (
                    f"Supervisor dry-run completed: found {len(candidates)} orphan background instance(s) "
                    f"(headless, not registered in COM, age > 45s). No processes were killed. "
                    f"To terminate these specific orphaned instances, re-run with confirm=True and target_pids={list(candidate_pids)}."
                )
            return report

        pids_to_kill = [pid for pid in target_pids if pid in candidate_pids]
        if not pids_to_kill:
            report["action"] = "no_match"
            report["message"] = (
                f"None of the requested target_pids ({target_pids}) match current verified "
                f"orphaned candidates ({list(candidate_pids)})."
            )
            return report

        terminated = []
        failed = []
        for pid in pids_to_kill:
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", f"Stop-Process -Id {pid} -Force -ErrorAction SilentlyContinue"],
                capture_output=True,
                text=True,
            )
            time.sleep(0.5)
            verify_cmd = f"Get-Process -Id {pid} -ErrorAction SilentlyContinue"
            check_res = subprocess.run(["powershell", "-NoProfile", "-Command", verify_cmd], capture_output=True, text=True)
            if not check_res.stdout.strip():
                terminated.append(pid)
            else:
                failed.append({"pid": pid, "error": "Process still exists after termination attempt."})

        report["action"] = "terminated"
        report["terminated_pids"] = terminated
        report["failed_pids"] = failed
        report["message"] = f"Supervisor terminated {len(terminated)} verified orphaned Inventor instance(s)."
        return report

