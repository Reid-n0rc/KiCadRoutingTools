#!/usr/bin/env python3
"""A dog-bone via deep under a BGA does not entomb its net (#472 widened).

A BGA exclusion zone blocks tracks and vias on EVERY layer of the part's pad
field; a route may cross it only inside the allowed-cell window around each
terminal (ENDPOINT_ALLOW_RADIUS_CELLS cells). #472 disables the zone when a
selected net has a BARE ball deep inside it. A ball with a dog-bone -- an
F.Cu stub to a through via beside the ball -- is not bare, so the zone stayed
on, and a net routed on an inner layer launched from a via the window could
not get out of: the main pass failed boxed in, and only the rescue (which
routes with no zones) joined it. The zone is now also disabled when a
selected net's ball copper ends deeper inside it than the window reaches.

The board: two 5x5 BGAs at 1.0 mm pitch, every ball dog-boned to a via, one
net joining the two centre balls, routed on In1.Cu only.

  1. centre balls: both zones are disabled, naming the reason, and the main
     pass routes the net (no rescue); the board grades connected and
     DRC-clean;
  2. control: the same net on two CORNER balls, whose vias sit inside the
     window -- both zones stay on and the main pass still routes it;
  3. the window is grid-aware: setup_bga_exclusion_zones with a window wider
     than the centre via's depth keeps both zones, and with no window keeps
     them as before.

    python3 tests/test_bga_dogbone_entombed_zone.py
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
from synth import dogbone_bga_board                             # noqa: E402

FAILS = []
NET = '/D0'


def ok(cond, msg, detail=''):
    print(f"  [{'ok' if cond else 'FAIL'}] {msg}"
          + (f': {detail}' if detail and not cond else ''))
    if not cond:
        FAILS.append(msg)


def route(td, tag, ball):
    src = os.path.join(td, f'{tag}.kicad_pcb')
    with open(src, 'w') as fh:
        fh.write(dogbone_bga_board(ball, NET))
    evidence(src, 'fixture board')
    out = os.path.join(td, f'{tag}_out.kicad_pcb')
    r = run_check([sys.executable, '-X', 'utf8', tool('route.py'), src,
                   '--output', out, '--nets', NET, '--layers', 'In1.Cu',
                   '--grid-step', '0.1', '--track-width', '0.1',
                   '--clearance', '0.1', '--via-size', '0.45', '--via-drill', '0.2'],
                  accept=True, cwd=td)
    evidence(out, 'routed board')
    return r.stdout + r.stderr, out


def main_pass_routed(log):
    """The main pass's own verdict on NET, before any rescue ladder."""
    m = re.search(r'\[1/1\] Routing ' + re.escape(NET) + r' .*?\n(.*?)(?:\n\n|Sync pcb_data)',
                  log, re.S)
    return bool(m) and 'SUCCESS:' in m.group(1)


def grade(td, out):
    c = subprocess.run([sys.executable, '-X', 'utf8', tool('check_connected.py'), out,
                        '--nets', NET], capture_output=True, text=True, cwd=td)
    d = subprocess.run([sys.executable, '-X', 'utf8', tool('check_drc.py'), out,
                        '--clearance', '0.1'], capture_output=True, text=True, cwd=td)
    return c, d


def main():
    td = tempfile.mkdtemp(prefix='krt_bdz_')
    try:
        print('1. centre balls: the dog-bone vias are entombed')
        log, out = route(td, 'centre', (2, 2))
        ok(log.count('zone DISABLED -- the fanout copper of 1 selected net(s) ends '
                     'inside it') == 2,
           'both zones are disabled for the entombed fanout copper',
           '\n'.join(l for l in log.splitlines() if 'zone' in l.lower())[:600])
        ok(main_pass_routed(log), 'the main pass routes the net', log[-1500:])
        ok('Rescuing ' + NET not in log, 'no rescue ladder was needed')
        c, d = grade(td, out)
        ok(c.returncode == 0 and 'ALL NETS FULLY CONNECTED' in c.stdout,
           'check_connected: the net is connected', c.stdout[-600:])
        ok(d.returncode == 0, 'check_drc is clean', d.stdout[-600:])

        print('2. control: corner balls, vias inside the window')
        log2, out2 = route(td, 'corner', (0, 0))
        ok('zone DISABLED' not in log2 and 'Auto-detected 2 BGA exclusion zone(s)' in log2,
           'both zones stay on (non-vacuity: the test reads a live zone)',
           '\n'.join(l for l in log2.splitlines() if 'zone' in l.lower())[:600])
        ok(main_pass_routed(log2), 'the main pass routes the corner net', log2[-1500:])

        print('3. the window decides')
        import io
        import contextlib
        from kicad_parser import parse_kicad_pcb
        from routing_common import setup_bga_exclusion_zones
        pcb = parse_kicad_pcb(os.path.join(td, 'centre.kicad_pcb'))
        nid = next(i for i, n in pcb.nets.items() if n.name == NET)
        for window, want, label in ((1.0, 0, 'a 1.0 mm window (centre via 1.7 mm deep)'),
                                    (1.8, 2, 'a 1.8 mm window'),
                                    (None, 2, 'no window (the old test)')):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                zones = setup_bga_exclusion_zones(pcb, None, None, selected_net_ids=[nid],
                                                  endpoint_window_mm=window)
            ok(len(zones) == want, f'{label}: {want} zone(s) kept', buf.getvalue()[-400:])
    finally:
        shutil.rmtree(td, ignore_errors=True)
    if FAILS:
        print(f'FAIL: {len(FAILS)}: ' + '; '.join(FAILS))
        return 1
    print('ALL PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
