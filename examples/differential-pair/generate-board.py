#!/usr/bin/env python3
"""Create the synthetic fixture with KiCad's /usr/bin/python3 bindings.

The saved board is supplied with the example; regeneration is optional and
requires an explicit output path. This never opens or modifies another design.
"""
import argparse
from pathlib import Path
import pcbnew


def create(destination):
    board = pcbnew.BOARD()
    board.SetCopperLayerCount(2)
    board.GetDesignSettings().SetBoardThickness(pcbnew.FromMM(1.03))
    point = lambda x, y: pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y))
    nets = {}
    for name in ('P', 'N', 'GND'):
        net = pcbnew.NETINFO_ITEM(board, name)
        board.Add(net)
        nets[name] = net
    corners = [(0, 0), (20, 0), (20, 12), (0, 12)]
    for start, end in zip(corners, corners[1:] + corners[:1]):
        edge = pcbnew.PCB_SHAPE()
        edge.SetShape(pcbnew.SHAPE_T_SEGMENT)
        edge.SetStart(point(*start)); edge.SetEnd(point(*end))
        edge.SetLayer(pcbnew.Edge_Cuts); edge.SetWidth(pcbnew.FromMM(.05))
        board.Add(edge)
    for reference, x in [('J1', 2), ('J2', 18)]:
        footprint = pcbnew.FOOTPRINT(board)
        footprint.SetReference(reference); footprint.SetValue('Differential port')
        footprint.SetPosition(point(x, 6))
        footprint.Reference().SetPosition(point(x, 3.8))
        footprint.Value().SetVisible(False)
        for number, name, y in [('1', 'P', 5.3), ('2', 'N', 6.7)]:
            pad = pcbnew.PAD(footprint)
            pad.SetNumber(number); pad.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
            pad.SetShape(pcbnew.PAD_SHAPE_RECT)
            pad.SetSize(point(1.2, .8)); pad.SetPosition(point(x, y))
            layers = pcbnew.LSET()
            layers.AddLayer(pcbnew.F_Cu); layers.AddLayer(pcbnew.F_Mask)
            pad.SetLayerSet(layers)
            pad.SetNet(nets[name]); footprint.Add(pad)
        board.Add(footprint)
    for name, y in [('P', 5.3), ('N', 6.7)]:
        track = pcbnew.PCB_TRACK(board)
        track.SetStart(point(2, y)); track.SetEnd(point(18, y))
        track.SetWidth(pcbnew.FromMM(.8)); track.SetLayer(pcbnew.F_Cu)
        track.SetNet(nets[name]); board.Add(track)
    # A rectangular saved ground fill, independent of installed libraries.
    zone = pcbnew.ZONE(board)
    zone.SetLayer(pcbnew.B_Cu); zone.SetNet(nets['GND'])
    polygon = pcbnew.SHAPE_POLY_SET()
    polygon.NewOutline()
    for x, y in [(1, 1), (19, 1), (19, 11), (1, 11)]:
        polygon.Append(point(x, y))
    zone.Outline().NewOutline()
    for x, y in [(1, 1), (19, 1), (19, 11), (1, 11)]:
        zone.Outline().Append(point(x, y))
    zone.SetFilledPolysList(pcbnew.B_Cu, polygon)
    zone.SetIsFilled(True); board.Add(zone)
    text = pcbnew.PCB_TEXT(board)
    text.SetText('PCB EM LAB - DEMO'); text.SetPosition(point(10, 2))
    text.SetTextSize(point(.7, .7)); text.SetTextThickness(pcbnew.FromMM(.12))
    text.SetLayer(pcbnew.F_SilkS); board.Add(text)
    section = pcbnew.PCB_SHAPE()
    section.SetShape(pcbnew.SHAPE_T_SEGMENT)
    section.SetStart(point(10, 0)); section.SetEnd(point(10, 12))
    section.SetLayer(pcbnew.Dwgs_User); section.SetWidth(pcbnew.FromMM(.1))
    board.Add(section)
    destination.parent.mkdir(parents=True, exist_ok=True)
    pcbnew.SaveBoard(str(destination), board)
    # The bindings do not expose all physical stackup fields. Insert an explicit
    # saved stackup in this new fixture only, before a normal KiCad load/save.
    stack = '''(stackup
      (layer "F.Mask" (type "Top Solder Mask") (thickness 0.015) (epsilon_r 3.3))
      (layer "F.Cu" (type "copper") (thickness 0.035))
      (layer "dielectric 1" (type "core") (thickness 0.93) (material "FR4") (epsilon_r 4.2) (loss_tangent 0.0))
      (layer "B.Cu" (type "copper") (thickness 0.035))
      (layer "B.Mask" (type "Bottom Solder Mask") (thickness 0.015) (epsilon_r 3.3)))'''
    saved = destination.read_text()
    destination.write_text(saved.replace('(setup', '(setup\n' + stack, 1))
    check = pcbnew.LoadBoard(str(destination))
    assert check.GetCopperLayerCount() == 2
    assert len(check.GetFootprints()) == 2
    assert any(z.HasFilledPolysForLayer(pcbnew.B_Cu) for z in check.Zones())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output already exists; choose a new path')
    create(args.output)
