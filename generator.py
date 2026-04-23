"""
generator.py
------------
Generates chip layout XML files from a config dict.
All output conforms to schemas/chip_layout.xsd.
"""

import random
import uuid
from datetime import datetime
from lxml import etree

NS = "http://amtc.example.com/ChipLayout"
NSM = {"tns": NS}

LAYER_TYPES    = ["metal", "dielectric", "poly", "diffusion"]
LAYER_MATS     = {"metal": "Copper", "dielectric": "SiO2", "poly": "Polysilicon", "diffusion": "Silicon"}
COMP_TYPES     = ["transistor", "via", "wire", "pad", "resistor"]
SIGNAL_TYPES   = ["voltage", "current", "resistance", "capacitance"]
SIGNAL_UNITS   = {"voltage": "V", "current": "mA", "resistance": "Ohm", "capacitance": "fF"}
SIGNAL_RANGES  = {"voltage": (0.5, 3.3), "current": (0.1, 10.0),
                  "resistance": (100, 10000), "capacitance": (1.0, 100.0)}


def _el(parent, tag, text=None, **attribs):
    """Helper: create a child element with optional text and attributes."""
    e = etree.SubElement(parent, f"{{{NS}}}{tag}", **attribs)
    if text is not None:
        e.text = str(text)
    return e


def _position(parent, x, y, unit="um"):
    pos = _el(parent, "Position", unit=unit)
    _el(pos, "X", round(x, 3))
    _el(pos, "Y", round(y, 3))
    return pos


def _dimensions(parent, w, h, unit="um"):
    dim = _el(parent, "Dimensions", unit=unit)
    _el(dim, "Width",  round(w, 3))
    _el(dim, "Height", round(h, 3))
    return dim


def generate_layout(
    project_name: str,
    created_by: str,
    description: str,
    num_components: int,
    num_test_points: int,
    layer_count: int,
    layout_id: str = None,
) -> etree._Element:
    """
    Build and return the root lxml Element for one chip layout.
    Does NOT write to disk — caller decides what to do with it.
    """
    if layout_id is None:
        layout_id = "L_" + uuid.uuid4().hex[:8].upper()

    root = etree.Element(f"{{{NS}}}ChipLayout",
                         attrib={"layout_id": layout_id, "version": "1.0"})

    # ── Metadata ────────────────────────────────────────────────────
    meta = _el(root, "Metadata")
    _el(meta, "ProjectName", project_name)
    _el(meta, "CreatedBy",   created_by)
    _el(meta, "CreatedAt",   datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"))
    _el(meta, "Description", description)

    # ── Layers ──────────────────────────────────────────────────────
    layers_el   = _el(root, "Layers")
    layer_count = max(1, min(layer_count, 4))
    chosen_types = random.sample(LAYER_TYPES, layer_count)
    layer_ids   = []
    for i, ltype in enumerate(chosen_types):
        lid = f"LYR_{i+1:02d}"
        layer_ids.append(lid)
        lyr = _el(layers_el, "Layer", layer_id=lid, type=ltype)
        _el(lyr, "Name",      f"{ltype.capitalize()} Layer {i+1}")
        _el(lyr, "Material",  LAYER_MATS[ltype])
        _el(lyr, "Thickness", round(random.uniform(0.1, 2.0), 3))

    # ── Components ──────────────────────────────────────────────────
    comp_ids = []
    comps_el = _el(root, "Components", count=str(num_components))
    for i in range(num_components):
        cid   = f"C_{layout_id}_{i+1:03d}"
        ctype = random.choice(COMP_TYPES)
        comp  = _el(comps_el, "Component",
                    comp_id=cid, type=ctype,
                    net=f"NET_{random.randint(1,20)}")
        comp_ids.append(cid)
        _position(comp, random.uniform(0, 500), random.uniform(0, 500))
        _dimensions(comp, random.uniform(0.5, 20), random.uniform(0.5, 20))
        _el(comp, "LayerRef", random.choice(layer_ids))

    # ── Test Points ─────────────────────────────────────────────────
    tps_el = _el(root, "TestPoints")
    for i in range(num_test_points):
        sig   = random.choice(SIGNAL_TYPES)
        lo, hi = SIGNAL_RANGES[sig]
        val   = round(random.uniform(lo, hi), 4)
        tol   = round(val * random.uniform(0.01, 0.05), 4)
        tp    = _el(tps_el, "TestPoint",
                    tp_id=f"TP_{layout_id}_{i+1:03d}",
                    signal=sig,
                    comp_ref=random.choice(comp_ids))
        _position(tp, random.uniform(0, 500), random.uniform(0, 500))
        _el(tp, "ExpectedValue", val)
        _el(tp, "Tolerance",     tol)
        _el(tp, "Unit",          SIGNAL_UNITS[sig])

    return root


def save_layout(root: etree._Element, path: str):
    """Serialise element tree to a pretty-printed XML file."""
    tree = etree.ElementTree(root)
    etree.indent(tree, space="  ")
    tree.write(path, xml_declaration=True, encoding="UTF-8", pretty_print=True)
