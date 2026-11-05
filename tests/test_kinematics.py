"""Unit tests for Inventor assembly rigidity enforcement and kinematic audit.

Tests safe-fail invariants with mocked COM objects:
1. Read-failure -> nothing grounded
2. Sanity-check failure -> nothing grounded
3. Normal case -> grounds ONLY unconstrained parts
4. Keyword exclusion -> skips moving parts matching substrings
5. Audit kinematics -> maps all 14 HealthStatus enum codes, defaults unreadable to Unknown,
   and warns on non-nominal health, floating components, and missing grounded datum.
6. Never calls occ.Constraints.Count on occurrence objects.
"""

from unittest.mock import MagicMock, PropertyMock
import json
import pytest

from src import inventor_api as _api
from src.inventor_api import (
    InventorConnection,
    kUnknownHealth,
    kUpToDateHealth,
    kOutOfDateHealth,
    kDriverLostHealth,
    kInErrorHealth,
    kDeletedHealth,
    kCannotComputeHealth,
    kSuppressedHealth,
    kBeyondStopNodeHealth,
    kInconsistentHealth,
    kRedundantHealth,
    kNewlyAddedHealth,
    kInvalidLimitsHealth,
    kJointDOFLockedHealth,
    HEALTH_STATUS_MAP,
)
from src import server


class MockOccurrence:
    """Mock Inventor ComponentOccurrence COM object."""

    def __init__(self, name: str, grounded: bool = False, is_subasm: bool = False):
        self.Name = name
        self.Grounded = grounded
        self.Definition = MagicMock()
        self.Definition.Document.FullFileName = (
            f"C:\\models\\{name}.iam" if is_subasm else f"C:\\models\\{name}.ipt"
        )
        self.Flexible = False

        # If code erroneously attempts to access occ.Constraints.Count, raise AttributeError
        type(self).Constraints = PropertyMock(
            side_effect=AssertionError("Violation of hard constraint: occ.Constraints was accessed directly!")
        )
        type(self).Joints = PropertyMock(
            side_effect=AssertionError("Violation of hard constraint: occ.Joints was accessed directly!")
        )


class MockCollection:
    """Mock 1-based COM collection (Occurrences, Constraints, Joints)."""

    def __init__(self, items):
        self._items = list(items)

    @property
    def Count(self) -> int:
        return len(self._items)

    def Item(self, idx: int):
        return self._items[idx - 1]

    def ItemByName(self, name: str):
        for item in self._items:
            if getattr(item, "Name", "").lower() == name.lower():
                return item
        raise KeyError(f"Item '{name}' not found")

    def __iter__(self):
        return iter(self._items)


def create_mock_assembly(occurrences, constraints=None, joints=None):
    """Helper to assemble a mocked InventorConnection with active assembly."""
    cdef = MagicMock()
    cdef.Occurrences = MockCollection(occurrences)
    cdef.Constraints = MockCollection(constraints or [])
    cdef.Joints = MockCollection(joints or [])

    doc = MagicMock()
    doc.DisplayName = "TestAssembly.iam"
    doc.ComponentDefinition = cdef
    doc.Dirty = False

    inv = InventorConnection()
    inv._app = MagicMock()
    inv._app.ActiveDocument = doc
    inv.active_assembly = lambda: cdef
    inv.list_positional_representations = lambda: ["Master", "Posicao_Aberta"]
    return inv, cdef, doc


def test_read_failure_nothing_grounded():
    """If reading OccurrenceOne/OccurrenceTwo raises a COM exception,
    relationship detection aborts, nothing is grounded, and all parts are skipped with reason.
    """
    occ1 = MockOccurrence("Part1:1", grounded=False)
    occ2 = MockOccurrence("Part2:1", grounded=False)

    broken_constraint = MagicMock()
    broken_constraint.Name = "SickConstraint"
    # Reading OccurrenceOne raises COM read error
    type(broken_constraint).OccurrenceOne = PropertyMock(
        side_effect=RuntimeError("COM exception reading OccurrenceOne")
    )
    broken_constraint.OccurrenceTwo = None

    inv, cdef, _ = create_mock_assembly([occ1, occ2], [broken_constraint])

    res = inv.enforce_subassembly_rigidity()

    # Invariant assertions:
    assert res["newly_grounded_count"] == 0
    assert len(res["newly_grounded"]) == 0
    assert occ1.Grounded is False
    assert occ2.Grounded is False
    assert res["skipped_detection_failed_count"] == 2
    assert "Relationship detection failed" in res["message"]


def test_sanity_check_failure_nothing_grounded():
    """If constraints/joints exist in the assembly, but total matched relationships is 0,
    the detection sanity check fails, nothing is grounded, and parts are skipped safely.
    """
    occ1 = MockOccurrence("Housing:1", grounded=False)
    occ2 = MockOccurrence("Shaft:1", grounded=False)

    unmatched_constraint = MagicMock()
    unmatched_constraint.Name = "OrphanConstraint"
    # OccurrenceOne and OccurrenceTwo are None or point to phantom entities
    unmatched_constraint.OccurrenceOne = None
    unmatched_constraint.OccurrenceTwo = None

    inv, cdef, _ = create_mock_assembly([occ1, occ2], [unmatched_constraint])

    res = inv.enforce_subassembly_rigidity()

    assert res["newly_grounded_count"] == 0
    assert len(res["newly_grounded"]) == 0
    assert occ1.Grounded is False
    assert occ2.Grounded is False
    assert res["skipped_detection_failed_count"] == 2
    assert "sanity check failed" in res["message"]


def test_normal_case_grounds_only_unconstrained_parts():
    """Normal assembly:
    - Constrained parts must be skipped (relationship_count > 0).
    - Already grounded parts must remain grounded and reported.
    - Only unconstrained, non-grounded parts are newly grounded.
    """
    base = MockOccurrence("Base_Plate:1", grounded=True)
    bracket = MockOccurrence("Bracket:1", grounded=False)
    loose_pin = MockOccurrence("Loose_Pin:1", grounded=False)

    c1 = MagicMock()
    c1.Name = "Mate_Bracket_Base"
    c1.OccurrenceOne = bracket
    c1.OccurrenceTwo = base
    c1.HealthStatus = kUpToDateHealth
    c1.Type = 100665856

    inv, cdef, _ = create_mock_assembly([base, bracket, loose_pin], [c1])

    res = inv.enforce_subassembly_rigidity()

    assert res["newly_grounded_count"] == 1
    assert res["newly_grounded"] == ["Loose_Pin:1"]
    assert loose_pin.Grounded is True

    assert res["skipped_count"] == 1
    assert res["skipped_constrained"][0]["name"] == "Bracket:1"
    assert res["skipped_constrained"][0]["relationship_count"] == 1
    assert bracket.Grounded is False

    assert res["already_grounded_count"] == 1
    assert res["already_grounded"] == ["Base_Plate:1"]
    assert base.Grounded is True


def test_keyword_exclusion_preserves_moving_parts():
    """Mechanism parts matching exclude_keywords substrings must be skipped
    even if they currently have 0 active relationships.
    """
    rotor = MockOccurrence("Drum_Rotor:1", grounded=False)
    slider = MockOccurrence("Defrost_Slider:1", grounded=False)
    frame = MockOccurrence("Fixed_Frame:1", grounded=False)

    inv, cdef, _ = create_mock_assembly([rotor, slider, frame], [])

    res = inv.enforce_subassembly_rigidity(exclude_keywords=["Rotor", "slider"])

    assert res["newly_grounded_count"] == 1
    assert res["newly_grounded"] == ["Fixed_Frame:1"]
    assert frame.Grounded is True

    assert res["skipped_moving_count"] == 2
    names = [s["name"] for s in res["skipped_moving"]]
    assert "Drum_Rotor:1" in names
    assert "Defrost_Slider:1" in names
    assert rotor.Grounded is False
    assert slider.Grounded is False


def test_audit_assembly_kinematics_health_status_and_warnings():
    """Kinematic audit must:
    1. Map HealthStatus using the 14 RxInventor enum codes.
    2. Default unreadable health to kUnknownHealth (11777).
    3. Generate warnings for any constraint not UpToDate (11778).
    4. Warn on floating unconstrained parts.
    5. Warn when no grounded reference datum exists in the assembly.
    """
    fixed = MockOccurrence("Frame:1", grounded=False)
    floating = MockOccurrence("FloatingBracket:1", grounded=False)

    c_ok = MagicMock()
    c_ok.Name = "MateGood"
    c_ok.OccurrenceOne = fixed
    c_ok.OccurrenceTwo = None
    c_ok.HealthStatus = kUpToDateHealth
    c_ok.Type = 100665856

    c_bad = MagicMock()
    c_bad.Name = "MateBroken"
    c_bad.OccurrenceOne = fixed
    c_bad.OccurrenceTwo = None
    c_bad.HealthStatus = kInErrorHealth
    c_bad.Type = 100665856

    c_unreadable = MagicMock()
    c_unreadable.Name = "MateUnreadable"
    c_unreadable.OccurrenceOne = fixed
    c_unreadable.OccurrenceTwo = None
    type(c_unreadable).HealthStatus = PropertyMock(
        side_effect=RuntimeError("HealthStatus property unreadable")
    )
    c_unreadable.Type = 100665856

    inv, cdef, _ = create_mock_assembly([fixed, floating], [c_ok, c_bad, c_unreadable])

    report = inv.audit_assembly_kinematics()

    assert report["occurrences_count"] == 2
    assert report["constraints_count"] == 3

    # Check HealthStatus codes and labels
    c_map = {c["name"]: c for c in report["constraints"]}
    assert c_map["MateGood"]["health"] == "UpToDate"
    assert c_map["MateGood"]["health_code"] == 11778

    assert c_map["MateBroken"]["health"] == "InError"
    assert c_map["MateBroken"]["health_code"] == 11781

    assert c_map["MateUnreadable"]["health"] == "Unknown"
    assert c_map["MateUnreadable"]["health_code"] == 11777

    # Check generated warnings
    warnings = report["warnings"]
    assert any("UNHEALTHY/UNVERIFIED CONSTRAINT: 'MateBroken'" in w for w in warnings)
    assert any("UNHEALTHY/UNVERIFIED CONSTRAINT: 'MateUnreadable'" in w for w in warnings)
    assert any("FLOATING COMPONENT: Occurrence 'FloatingBracket:1'" in w for w in warnings)
    assert any("NO GROUNDED DATUM" in w for w in warnings)


def test_audit_all_14_health_status_enum_mapping():
    """Confirm all 14 HealthStatusEnum values map to expected label names."""
    expected_enum_labels = {
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
    assert HEALTH_STATUS_MAP == expected_enum_labels
    assert len(HEALTH_STATUS_MAP) == 14


@pytest.mark.anyio
async def test_server_manage_subassembly_kinematics_tool(monkeypatch):
    """Test manage_subassembly_kinematics in server.py passes exclude_keywords correctly."""
    occ1 = MockOccurrence("Rotor_Part:1", grounded=False)
    occ2 = MockOccurrence("Fixed_Part:1", grounded=False)

    inv, cdef, _ = create_mock_assembly([occ1, occ2], [])
    monkeypatch.setattr(server, "inv", inv)

    res_str = await server.manage_subassembly_kinematics(
        action="enforce_rigidity",
        exclude_keywords=["Rotor"]
    )
    res = json.loads(res_str)

    assert res["newly_grounded_count"] == 1
    assert res["newly_grounded"] == ["Fixed_Part:1"]
    assert res["skipped_moving_count"] == 1
    assert res["skipped_moving"][0]["name"] == "Rotor_Part:1"
