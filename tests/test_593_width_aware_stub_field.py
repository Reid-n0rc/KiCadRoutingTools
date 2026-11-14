#!/usr/bin/env python3
"""#593: an unrouted wide net's stub field is wider and dearer (opt-in).

The stub-proximity field tells a net being routed that another net still has
to leave from a stub end or a chip pad. It was the same for every net, so a
0.1 mm signal routed first kept from a 0.5 mm power net's pad only the room
another 0.1 mm signal would need. With KICAD_STUB_WIDTH_AWARE=1, a net
assigned a track at least KICAD_STUB_WIDTH_RATIO (2) times the run's width
gets its field over a radius grown by half its width, at a cost scaled by
(width / run width) ** KICAD_STUB_WIDTH_EXP (0.5), capped at 3x.

Rows:
  1. which nets are wide: a power width, a class width, the ratio, and none
     at all with the knob off;
  2. the field on the map, max composition: at a wide net's point the cost
     is the scaled one, it reaches past the plain radius, a plain net's
     point is as it was, and with the knob off the map is the plain map;
  3. the same per source in sum composition (the grouped stamp);
  4. splitflap_driver with its two supplies routed 0.5 mm wide: with the
     knob on every net is still routed and check_drc is clean.
"""
import importlib
import json
import os
import subprocess
import sys
import tempfile

TESTS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(TESTS)
sys.path.insert(0, os.path.join(REPO, 'py_router'))
sys.path.insert(0, os.path.join(REPO, 'rust_router'))
sys.path.insert(0, TESTS)
from run_utils import check, evidence  # noqa: E402

PY = [sys.executable, '-X', 'utf8']
FAILS = []
KNOBS = ('KICAD_STUB_WIDTH_AWARE', 'KICAD_STUB_WIDTH_RATIO', 'KICAD_STUB_WIDTH_EXP',
         'KICAD_PROXIMITY_SUM')


def ok(cond, msg):
    print(f"  [{'ok' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILS.append(msg)


def knobs(**env):
    """Set the knobs for THIS process and re-read them."""
    import env_knobs
    for k in KNOBS:
        os.environ.pop(k, None)
    os.environ.update({k: str(v) for k, v in env.items()})
    env_knobs.refresh()


def config(**kw):
    from routing_config import GridRouteConfig
    return GridRouteConfig(grid_step=0.1, clearance=0.1, track_width=0.1,
                           layers=['F.Cu', 'B.Cu'], stub_proximity_radius=2.0,
                           stub_proximity_cost=0.2, **kw)


def which_nets():
    print("1. which nets are wide")
    import obstacle_costs as oc
    knobs(KICAD_STUB_WIDTH_AWARE=1)
    cfg = config(power_net_widths={5: 0.5, 6: 0.15})
    cfg.net_track_widths = {7: 0.3}
    got = oc.wide_stub_nets(cfg, [5, 6, 7, 8])
    ok(sorted(got) == [5, 7], f"a 0.5 mm supply and a 0.3 mm class, not 0.15 or the default: {sorted(got)}")
    ok(abs(got[5][0] - 0.25) < 1e-9 and abs(got[5][1] - 5 ** 0.5) < 1e-9,
       f"the supply: half its width more radius, sqrt(5) the cost: {got[5]}")
    knobs(KICAD_STUB_WIDTH_AWARE=1, KICAD_STUB_WIDTH_EXP=3)
    ok(oc.wide_stub_nets(cfg, [5])[5][1] == oc.STUB_WIDTH_COST_CAP, "the cost scale is capped at 3x")
    knobs(KICAD_STUB_WIDTH_AWARE=1, KICAD_STUB_WIDTH_RATIO=6)
    ok(oc.wide_stub_nets(cfg, [5, 7]) == {}, "a ratio of 6 leaves both out")
    knobs()
    ok(oc.wide_stub_nets(cfg, [5, 7]) == {}, "and with the knob off no net is wide")


def stamp(env, sum_mode=False):
    """The stub map after apply_stub_proximity for a wide net 5 at (10, 10)
    and a plain net 8 at (30, 10); returns cost(x, y)."""
    import connectivity
    import net_queries
    import obstacle_costs as oc
    from grid_router import GridObstacleMap
    if sum_mode:
        env = dict(env, KICAD_PROXIMITY_SUM=1)
    knobs(**env)
    importlib.reload(oc)
    pts = {5: [(10.0, 10.0, 'F.Cu')], 8: [(30.0, 10.0, 'F.Cu')]}
    keep = (connectivity.get_stub_endpoints, net_queries.get_chip_pad_positions)
    connectivity.get_stub_endpoints = lambda pcb, ids: [p for n in ids for p in pts.get(n, [])]
    net_queries.get_chip_pad_positions = lambda pcb, ids, min_pads=4: []
    try:
        cfg = config(power_net_widths={5: 0.5})
        obs = GridObstacleMap(2)
        oc.apply_stub_proximity(obs, None, [5, 8], pts[5] + pts[8], cfg)
    finally:
        connectivity.get_stub_endpoints, net_queries.get_chip_pad_positions = keep
    return (lambda x, y: obs.get_stub_proximity_cost(int(round(x / 0.1)), int(round(y / 0.1)))), cfg


def the_field(sum_mode):
    tag = 'sum' if sum_mode else 'max'
    print(f"{3 if sum_mode else 2}. the field on the map, {tag} composition")
    off, cfg = stamp({}, sum_mode)
    on, _ = stamp({'KICAD_STUB_WIDTH_AWARE': 1}, sum_mode)
    full = cfg.cell_cost(cfg.stub_proximity_cost)
    ok(off(10, 10) == off(30, 10) == full, f"off: both nets' points cost the stub cost ({full})")
    ok(abs(on(10, 10) - int(full * 5 ** 0.5)) <= 1,
       f"on: the wide net's point costs sqrt(5) of it: {on(10, 10)}")
    ok(on(30, 10) == off(30, 10) and on(31, 10) == off(31, 10),
       "the plain net's field is what it was")
    ok(off(12.1, 10) == 0 and on(12.1, 10) > 0 and on(12.4, 10) == 0,
       f"the wide field reaches 2.25 mm, past the plain 2.0: {on(12.1, 10)}")
    ok(on(11, 10) > off(11, 10), "and is dearer along the way")
    knobs()


def the_board(td):
    print("4. splitflap_driver, its supplies 0.5 mm wide, the knob on")
    src = os.path.join(REPO, 'kicad_files', 'splitflap_driver.kicad_pcb')
    board, out = os.path.join(td, 'in.kicad_pcb'), os.path.join(td, 'out.kicad_pcb')
    summary = os.path.join(td, 'out.json')
    check(PY + [os.path.join(REPO, 'py_router', 'copy_board.py'),
                evidence(src, 'the board'), board], accept=True)
    env = {k: v for k, v in os.environ.items() if k not in KNOBS}
    env['KICAD_STUB_WIDTH_AWARE'] = '1'
    check(PY + [os.path.join(REPO, 'py_router', 'route.py'), board, out,
                '--power-nets', '+3V3', '+12V', '--power-nets-widths', '0.5', '0.5',
                '--json-out', summary], accept=True, timeout=1800, env=env)
    with open(evidence(summary, 'the summary'), encoding='utf-8') as fh:
        doc = json.load(fh)
    ok(not (doc.get('failed_single') or []) and not (doc.get('failed_multipoint') or [])
       and len(doc.get('routed_single') or []) > 70,
       f"every net is routed: {len(doc.get('routed_single') or [])} routed, "
       f"{doc.get('failed_single')} failed")
    g = check(PY + [os.path.join(REPO, 'py_router', 'check_drc.py'),
                    evidence(out, 'the routed board')], accept=True)
    ok('NO DRC VIOLATIONS FOUND' in (g.stdout or ''), "check_drc is clean")


def main():
    which_nets()
    the_field(False)
    the_field(True)
    knobs()
    with tempfile.TemporaryDirectory() as td:
        the_board(td)
    if FAILS:
        print(f"\nFAILED ({len(FAILS)}):")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("\nALL PASSED")
    return 0


if __name__ == '__main__':
    sys.exit(main())
