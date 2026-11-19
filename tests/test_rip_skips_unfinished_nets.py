#!/usr/bin/env python3
"""Pre-existing rip candidacy takes finished routes only, not fanout copper.

route.py registers small unprotected pre-existing nets as main-pass rip
candidates, custody-backed: a ripped victim is rerouted this run or its copper
restored. A net whose copper does not join its pads -- the dog-bone stubs and
vias a fanout step left on a bus nobody has routed yet -- cannot be rerouted
to what it was. Ripping one only freed the run to ROUTE it: the victim then
went through the own-requirement retry, the rescue and the terminal
escalation as if it had been asked for, and a run of a few nets worked on
dozens of nets outside its --nets. Such nets are now left out of candidacy,
with a line saying so; --rip-existing-nets naming one still allows it.

The board: two 5x5 BGAs at 0.8 mm pitch, every ball dog-boned, every ball's
net joining the same ball of the other part (an unrouted bus), routed on
In1.Cu for the centre ball's net only. One bus net, /B41, is also routed
(an In2.Cu track joins its vias), so it is a finished route.

  1. the open bus nets are left out of candidacy and the finished one stays
     a candidate;
  2. no open bus net is ripped, and none is worked on by any later ladder
     (own-requirement retry, rescue, terminal escalation);
  3. every input via and stub of the bus ships unchanged (uuid set), and the
     selected net is connected;
  4. --rip-existing-nets naming an open bus net makes it a candidate again
     (the override holds).

    python3 tests/test_rip_skips_unfinished_nets.py
"""
import os
import re
import shutil
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
LEFT_OUT = re.compile(r'^(\d+) pre-existing net\(s\) left out of rip candidacy', re.M)
REGISTERED = re.compile(r'^(\d+) unprotected pre-existing net\(s\) registered', re.M)
WORKED = re.compile(r"(?:PRE-EXISTING rip: '|Rescuing |terminal escalation: "
                    r"|own-requirement retry: )(/[^' ]+)")


def ok(cond, msg, detail=''):
    print(f"  [{'ok' if cond else 'FAIL'}] {msg}"
          + (f': {detail}' if detail and not cond else ''))
    if not cond:
        FAILS.append(msg)


def route(td, tag, extra=()):
    src = os.path.join(td, 'bus.kicad_pcb')
    if not os.path.exists(src):
        with open(src, 'w') as fh:
            fh.write(dogbone_bga_board((2, 2), NET, pitch=0.8, paired=True,
                                       finished=[(4, 1)]))
    evidence(src, 'fixture board')
    out = os.path.join(td, f'{tag}.kicad_pcb')
    r = run_check([sys.executable, '-X', 'utf8', tool('route.py'), src,
                   '--output', out, '--nets', NET, '--layers', 'In1.Cu',
                   '--grid-step', '0.1', '--track-width', '0.1',
                   '--clearance', '0.1', '--via-size', '0.45', '--via-drill', '0.2',
                   *extra], accept=True, cwd=td)
    evidence(out, 'routed board')
    return r.stdout + r.stderr, src, out


def bus_uuids(path):
    with open(path, encoding='utf-8') as fh:
        text = fh.read()
    return set(re.findall(r'\((?:segment|via) [^\n]*\(uuid "(bga-\d+)"\)', text))


def main():
    td = tempfile.mkdtemp(prefix='krt_rsu_')
    try:
        print('1. candidacy')
        log, src, out = route(td, 'out')
        m, g = LEFT_OUT.search(log), REGISTERED.search(log)
        ok(m and int(m.group(1)) == 23, 'the 23 open bus nets are left out',
           m and m.group(0))
        ok(g and int(g.group(1)) == 1, 'the finished bus net stays a candidate',
           g and g.group(0))

        print('2. nothing outside --nets is worked on')
        worked = sorted(set(WORKED.findall(log)) - {NET})
        ok(not worked, 'no rip, retry, rescue or escalation of another net',
           ', '.join(worked[:8]))
        ok('ROUTE FAILED' in log or 'FAILED: Could not find route' in log,
           'the main pass did fail on the net (non-vacuity: a rip ladder ran)')

        print('3. the bus copper ships unchanged')
        before, after = bus_uuids(src), bus_uuids(out)
        ok(len(before) > 100 and before <= after,
           f'every input stub and via is in the output ({len(before)} items)',
           f'missing {len(before - after)}')
        c = run_check([sys.executable, '-X', 'utf8', tool('check_connected.py'), out,
                       '--nets', NET], accept=True, cwd=td)
        ok('ALL NETS FULLY CONNECTED' in c.stdout, f'{NET} is connected',
           c.stdout[-400:])

        print('4. the override')
        log4, _, _ = route(td, 'named', ('--rip-existing-nets', '/B21'))
        m4 = LEFT_OUT.search(log4)
        ok(m4 and int(m4.group(1)) == 22, 'a named open net is not left out',
           m4 and m4.group(0))
    finally:
        shutil.rmtree(td, ignore_errors=True)
    if FAILS:
        print(f'FAIL: {len(FAILS)}: ' + '; '.join(FAILS))
        return 1
    print('ALL PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
