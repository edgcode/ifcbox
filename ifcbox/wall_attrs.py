"""Per-element wall attribute readers (IfcWallType name, FireRating).

Shared by floor-geometry extraction (for the 3D colour modes) and the debug
images. Geometry-derived thickness is computed at the call site from the mesh.
"""

from __future__ import annotations


def wall_type_name(element) -> str:
    """IfcWallType name, falling back to the element name or 'Unknown'."""
    try:
        import ifcopenshell.util.element
        wtype = ifcopenshell.util.element.get_type(element)
        if wtype is not None:
            n = (wtype.Name or "").strip()
            if n:
                return n
    except Exception:
        pass
    return (element.Name or "").strip() or "Unknown"


def wall_fire_rating(element) -> str:
    """FireRating, walking IsDefinedBy directly (get_psets() skips null values)."""
    try:
        for rel in getattr(element, "IsDefinedBy", []):
            if not rel.is_a("IfcRelDefinesByProperties"):
                continue
            pset = rel.RelatingPropertyDefinition
            if not pset.is_a("IfcPropertySet"):
                continue
            for prop in pset.HasProperties:
                if prop.Name == "FireRating":
                    nv = prop.NominalValue
                    if nv is not None:
                        s = str(nv.wrappedValue).strip()
                        return s if s else "—"
    except Exception:
        pass
    return "—"
