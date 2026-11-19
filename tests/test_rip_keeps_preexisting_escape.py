#!/usr/bin/env python3
"""A ripped pre-existing net keeps its fanout escape: pad stub and via.

route.py registers a small finished pre-existing net as a main-pass rip
candidate, custody-backed: ripped, it is rerouted this run or its copper is
restored. The rip used to take ALL its copper, the dog-bone stubs and vias
a fanout step left at its pads included. The net that ripped it was then
free to route through the vacated via site, the victim had no way back to
its pad, and the #468 terminal restore put back only the escape pieces that
clear the new copper -- the via the attacker had crossed was dropped. The
victim shipped with a bare stub where its via had been, and on a step
restricted to inner layers no later step could route it again.

A rip now leaves each pad's escape on the board: the stub from a pad to a
via, and that via (or a via in the pad). Only the route beyond it is
ripped, so the attacker routes around the via and the victim is rerouted
from it. A pad stub that ends in no via is ripped as before.

The board (synthetic, 4 layers, routed on In1.Cu only): /V is dog-boned at
both pads, its left via 0.9 mm from the edge, and routed on In1.Cu across
the board, so the selected net /A -- dog-boned at (0.9, 5) and (3, 15) --
must cross it, and its shortest path runs down x=0.9 through /V's left via.
Via-in-pad and the off-pad escape rung are off (--same-net-pad-clearance,
KICAD_ESCAPE_STUB_RADIUS=0), as in a dense ball field where neither fits:
the dog-bone is /V's only way in.

  1. the run rips /V for /A (non-vacuity);
  2. every input stub and via ships (uuids);
  3. /A and /V are both connected (before: /V shipped broken, its left via
     gone, "Broken by this run, outside its routing scope");
  4. a pad stub that ends in no via is not an escape (row on
     rip_restore.via_escape_subset).

    python3 tests/test_rip_keeps_preexisting_escape.py
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TESTS_DIR)
sys.path.insert(0, TESTS_DIR)
sys.path.insert(0, os.path.join(ROOT, 'py_router'))

from run_utils import check as run_check, evidence, tool        # noqa: E402

FAILS = []


def ok(cond, msg, detail=''):
    print(f"  [{'ok' if cond else 'FAIL'}] {msg}"
          + (f': {detail}' if detail and not cond else ''))
    if not cond:
        FAILS.append(msg)


def _pad(ref, x, y, net_no, net, uid):
    return ('  (footprint "synth:TP" (layer "F.Cu") (uuid "%s-fp") (at %s %s)\n'
            '    (property "Reference" "%s" (at 0 -1 0) (layer "F.SilkS") '
            '(uuid "%s-ref")\n      (effects (font (size 0.5 0.5) '
            '(thickness 0.1))))\n'
            '    (pad "1" smd circle (at 0 0) (size 0.4 0.4) '
            '(layers "F.Cu" "F.Mask") (net %d "%s") (uuid "%s-pad"))\n  )'
            % (uid, x, y, ref, uid, net_no, net, uid))


def _seg(x1, y1, x2, y2, layer, net_no, uid):
    return ('  (segment (start %s %s) (end %s %s) (width 0.1) (layer "%s") '
            '(net %d) (uuid "%s"))' % (x1, y1, x2, y2, layer, net_no, uid))


def _via(x, y, net_no, uid):
    return ('  (via (at %s %s) (size 0.45) (drill 0.2) (layers "F.Cu" "B.Cu") '
            '(net %d) (uuid "%s"))' % (x, y, net_no, uid))


def board():
    """30 x 20 mm, as the module docstring describes."""
    items = [
        _pad('TP1', 1.4, 9.5, 1, '/V', 'v-p1'),
        _pad('TP2', 28.6, 9.5, 1, '/V', 'v-p2'),
        _pad('TP3', 1.4, 4.5, 2, '/A', 'a-p1'),
        _pad('TP4', 3.5, 15.5, 2, '/A', 'a-p2'),
        _seg(1.4, 9.5, 0.9, 10, 'F.Cu', 1, 'esc-v1'),
        _via(0.9, 10, 1, 'esc-vv1'),
        _seg(28.6, 9.5, 29.1, 10, 'F.Cu', 1, 'esc-v2'),
        _via(29.1, 10, 1, 'esc-vv2'),
        _seg(0.9, 10, 1.45, 10.55, 'In1.Cu', 1, 'route-v1'),
        _seg(1.45, 10.55, 1.45, 11.9, 'In1.Cu', 1, 'route-v2'),
        _seg(1.45, 11.9, 29.1, 11.9, 'In1.Cu', 1, 'route-v3'),
        _seg(29.1, 11.9, 29.1, 10, 'In1.Cu', 1, 'route-v4'),
        _seg(1.4, 4.5, 0.9, 5, 'F.Cu', 2, 'esc-a1'),
        _via(0.9, 5, 2, 'esc-av1'),
        _seg(3.5, 15.5, 3.0, 15, 'F.Cu', 2, 'esc-a2'),
        _via(3.0, 15, 2, 'esc-av2'),
    ]
    head = ['(kicad_pcb (version 20241229) (generator "synth") '
            '(generator_version "9.0")',
            '  (general (thickness 1.6) (legacy_teardrops no))',
            '  (paper "A4")',
            '  (layers (0 "F.Cu" signal) (1 "In1.Cu" signal) (2 "In2.Cu" signal) '
            '(31 "B.Cu" signal) (37 "F.SilkS" user) (39 "F.Mask" user) '
            '(38 "B.Mask" user) (44 "Edge.Cuts" user))',
            '  (setup (pad_to_mask_clearance 0))',
            '  (net 0 "")', '  (net 1 "/V")', '  (net 2 "/A")']
    tail = ['  (gr_rect (start 0 0) (end 30 20) (layer "Edge.Cuts") '
            '(stroke (width 0.1) (type solid)) (fill none) (uuid "edge"))', ')']
    return '\n'.join(head + items + tail) + '\n'


def uuids(path, prefix):
    with open(path, encoding='utf-8') as fh:
        text = fh.read()
    return set(re.findall(r'\(uuid "(%s[^"]*)"\)' % prefix, text))


def escape_row():
    from kicad_parser import Segment, Via
    from rip_restore import via_escape_subset

    class _Pad:
        def __init__(self, x, y):
            self.global_x, self.global_y = x, y

    class _PCB:
        pads_by_net = {1: [_Pad(0.0, 0.0), _Pad(5.0, 0.0)]}

    to_via = Segment(start_x=0.0, start_y=0.0, end_x=0.5, end_y=0.5,
                     width=0.1, layer='F.Cu', net_id=1)
    bare = Segment(start_x=5.0, start_y=0.0, end_x=5.5, end_y=0.5,
                   width=0.1, layer='F.Cu', net_id=1)
    track = Segment(start_x=0.5, start_y=0.5, end_x=5.5, end_y=0.5,
                    width=0.1, layer='In1.Cu', net_id=1)
    via = Via(x=0.5, y=0.5, size=0.45, drill=0.2,
              layers=['F.Cu', 'B.Cu'], net_id=1)
    segs, vias = via_escape_subset(_PCB(), 1, [to_via, bare, track], [via])
    ok([id(s) for s in segs] == [id(to_via)] and [id(v) for v in vias] == [id(via)],
       'escape = the stub to a via and that via; a bare stub and the track are not',
       f'segs={len(segs)} vias={len(vias)}')


def connected(td, out, net):
    """check_connected's verdict; it exits 1 on an open net, so the exit is
    not the verdict -- its own summary line is, and a traceback is a broken
    test, not an open net."""
    c = subprocess.run([sys.executable, '-X', 'utf8', tool('check_connected.py'),
                        out, '--nets', net], capture_output=True, text=True,
                       cwd=td)
    text = c.stdout + c.stderr
    if 'Traceback' in text or not ('ALL NETS FULLY CONNECTED' in text
                                   or 'Connectivity issues' in text):
        raise AssertionError(f'BROKEN TEST: check_connected gave no verdict\n{text[-800:]}')
    return 'ALL NETS FULLY CONNECTED' in text, text[-400:]


def main():
    td = tempfile.mkdtemp(prefix='krt_rke_')
    try:
        src = os.path.join(td, 'esc.kicad_pcb')
        with open(src, 'w') as fh:
            fh.write(board())
        evidence(src, 'fixture board')
        out = os.path.join(td, 'out.kicad_pcb')
        env = dict(os.environ, KICAD_ESCAPE_STUB_RADIUS='0')
        r = run_check([sys.executable, '-X', 'utf8', tool('route.py'), src,
                       '--output', out, '--nets', '/A', '--layers', 'In1.Cu',
                       '--grid-step', '0.05', '--track-width', '0.1',
                       '--clearance', '0.1', '--via-size', '0.45',
                       '--via-drill', '0.2', '--board-edge-clearance', '0.5',
                       '--same-net-pad-clearance', '0.1'],
                      accept=True, cwd=td, env=env)
        log = r.stdout + r.stderr
        evidence(out, 'routed board')

        print('1. the rip happened')
        ok("PRE-EXISTING rip: '/V'" in log, '/V was ripped for /A (non-vacuity)',
           log[-600:])

        print('2. the escapes ship')
        before, after = uuids(src, 'esc-'), uuids(out, 'esc-')
        ok(len(before) == 8 and before <= after,
           f'every input stub and via ships ({len(before)} items)',
           f'missing {sorted(before - after)}')

        print('3. both nets connected')
        for net in ('/A', '/V'):
            c, tail = connected(td, out, net)
            ok(c, f'{net} is connected', tail)
        ok('Broken by this run' not in log, 'no net broken outside the scope',
           log[-600:])

        print('4. a bare stub is not an escape')
        escape_row()
    finally:
        shutil.rmtree(td, ignore_errors=True)
    if FAILS:
        print(f'FAIL: {len(FAILS)}: ' + '; '.join(FAILS))
        return 1
    print('ALL PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
