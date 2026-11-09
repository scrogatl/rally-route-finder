# BEGIN LICENSE HEADER
# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 Scott Rogers <scott@scottandrewrogers.com>
#
# Part of rally-route-finder. Licensed under the Apache License, Version 2.0;
# see the LICENSE and NOTICE files in the repository root.
# Redistributions must retain this notice and the NOTICE file.
#
# Commit history (date time tz | author <email> | commit | message):
#   2026-11-08 21:37:13 -0500 | Scott Rogers <scott@scottandrewrogers.com> | 3a05651 | Order routes for the finish instead of banking points early
#   2026-11-08 20:19:42 -0500 | Scott Rogers <scott@scottandrewrogers.com> | 2ee171a | GraphHopper drive times (--road-time-factor) and fitPace.py
# END LICENSE HEADER
"""Work backward from a rally's results to the planner's pace settings.

For each rider it takes the bonuses they were approved for (from the scoring
workbook), routes them the shortest way by road miles, and asks: how fast
did they ride, and how long did they stop, to cover that in the time they
had? Then it fits one --speed and --stop-minutes (and one
--road-time-factor) for the top riders and for the whole field, by least
squares:

    hours - gas stops = miles / speed + stops x stop minutes
    hours - gas stops = GraphHopper's drive time x factor + stops x stop minutes

Hours default to the whole rally (--hours, 10), since riders are assumed to
use all the time they have; a late penalty adds the middle of its window.
Miles default to GraphHopper's road miles along that shortest route. Give
each rider's real miles and hours in --actuals (a CSV with rider, miles,
hours; either may be blank) and those are used instead.

The submit and approve times in the workbook are when emails arrived, not
when the rider was at the bonus, so they aren't used.

    .venv/bin/python fitPace.py SNAFU_2026/results-2026.xlsx
    .venv/bin/python fitPace.py SNAFU_2026/results-2026.xlsx --actuals SNAFU_2026/actuals-2026.csv --top 10
    .venv/bin/python fitPace.py SNAFU_2026/results-2026.xlsx --write-actuals SNAFU_2026/actuals-2026.csv

The workbook layout is the snafu-rally-scoring one: a 'Bonus Master' tab
(code, points), a 'Combo Master' tab (combo, member), a 'Leader Board' tab
(rider, name, score, finish) and one tab per rider number with the bonus
code in column A and an X in column D when it was approved. Needs openpyxl.
"""
import argparse
import csv
import sys

import planRoute

# A rider needs at least this many bonuses on the map to be fitted
MIN_STOPS = 5


def read_workbook(path):
    """-> (points by code, combo codes, riders): riders is a list of dicts
    with rider, name, score, finish and the approved codes."""
    try:
        import openpyxl
    except ImportError:
        sys.exit("ERROR: fitPace.py needs openpyxl: .venv/bin/pip install openpyxl")
    try:
        book = openpyxl.load_workbook(path, data_only=True, read_only=True)
    except OSError as error:
        sys.exit(f"ERROR: can't read the results workbook: {error}")
    try:
        points = {str(row[0]).strip(): float(row[1] or 0)
                  for row in book['Bonus Master'].iter_rows(min_row=2, values_only=True) if row[0]}
        combos = {str(row[0]).strip() for row in book['Combo Master'].iter_rows(min_row=2, values_only=True)
                  if row[0]} if 'Combo Master' in book.sheetnames else set()
        riders = []
        for row in book['Leader Board'].iter_rows(min_row=2, values_only=True):
            if row[0] is None or str(int(row[0])) not in book.sheetnames:
                continue
            sheet = book[str(int(row[0]))]
            codes = [str(r[0]).strip() for r in sheet.iter_rows(min_row=2, values_only=True)
                     if len(r) > 3 and r[0] and r[3]]
            riders.append(dict(rider=int(row[0]), name=row[1], score=row[2] or 0, finish=row[3], codes=codes))
    except KeyError as error:
        sys.exit(f"ERROR: {path} has no {error} tab; is it a snafu-rally-scoring workbook?")
    return points, combos, riders


def read_actuals(path):
    """{rider: (miles or None, hours or None)} from a CSV with rider, miles, hours."""
    try:
        with open(path, newline='') as f:
            rows = list(csv.DictReader(f))
    except OSError as error:
        sys.exit(f"ERROR: can't read --actuals: {error}")
    actuals = {}
    for row in rows:
        try:
            value = lambda key: float(row[key]) if (row.get(key) or '').strip() else None
            actuals[int(row['rider'])] = (value('miles'), value('hours'))
        except (KeyError, ValueError):
            sys.exit(f"ERROR: --actuals needs rider, miles and hours columns with numbers; bad row: {row}")
    return actuals


def late_minutes(percent, late_penalty):
    """The middle of the late window a penalty of this percent off belongs to."""
    previous = 0
    for minutes, off in late_penalty:
        if abs(off - percent) < 1e-9:
            return (previous + minutes) / 2
        previous = minutes
    return previous


def shortest_route(planner, stops):
    """The stops in the order with the fewest road miles from Rally HQ and
    back: cheapest insertion and 2-opt (the planner's), then moving single
    stops while that helps."""
    planner.required, planner.lead = frozenset(stops), []
    route = planner.combo_seed(())
    miles = planner.route_miles(route)
    improved = True
    while improved:
        improved = False
        for i in range(len(route)):
            rest = route[:i] + route[i + 1:]
            for j in range(len(route)):
                if j == i:
                    continue
                candidate = rest[:j] + [route[i]] + rest[j:]
                candidate_miles = planner.route_miles(candidate)
                if candidate_miles < miles - 1e-9:
                    route, miles, improved = candidate, candidate_miles, True
                    break
            if improved:
                break
    return route, miles


def fit(rows, time_key, stop_minutes=None):
    """Least squares for hours - gas = time_key x a + stops x s, with s >= 0,
    or with s fixed at stop_minutes. Returns (a, s in minutes, root mean
    square error in minutes)."""
    if stop_minutes is not None:
        s = stop_minutes / 60
        a = (sum(r[time_key] * (r['net_hours'] - r['stops'] * s) for r in rows)
             / sum(r[time_key] ** 2 for r in rows))
        error = (sum((r['net_hours'] - r[time_key] * a - r['stops'] * s) ** 2 for r in rows) / len(rows)) ** 0.5
        return a, stop_minutes, error * 60
    xx = sum(r[time_key] ** 2 for r in rows)
    xn = sum(r[time_key] * r['stops'] for r in rows)
    nn = sum(r['stops'] ** 2 for r in rows)
    xy = sum(r[time_key] * r['net_hours'] for r in rows)
    ny = sum(r['stops'] * r['net_hours'] for r in rows)
    det = xx * nn - xn * xn
    a, s = ((xy * nn - xn * ny) / det, (xx * ny - xn * xy) / det) if abs(det) > 1e-12 else (xy / xx, 0)
    if s < 0:
        a, s = xy / xx, 0.0
    error = (sum((r['net_hours'] - r[time_key] * a - r['stops'] * s) ** 2 for r in rows) / len(rows)) ** 0.5
    return a, s * 60, error * 60


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('workbook', help='the scoring workbook (.xlsx, snafu-rally-scoring layout)')
    parser.add_argument('--bonuses', default='bonus-lat-lon-points.csv', help='the bonus file (default %(default)s)')
    parser.add_argument('--road-miles', default=planRoute.ROAD_MILES_CSV,
                        help='GraphHopper road miles and times table (default %(default)s)')
    parser.add_argument('--actuals', metavar='CSV', help="riders' real miles and hours: rider, miles, hours")
    parser.add_argument('--write-actuals', metavar='CSV',
                        help='write a blank --actuals file listing every rider, to fill in, and stop')
    parser.add_argument('--hours', type=float, default=planRoute.DEFAULT_HOURS,
                        help='hours each rider is taken to have ridden when --actuals has none (default %(default)g)')
    parser.add_argument('--late-penalty', type=planRoute.parse_late_penalty, default=planRoute.LATE_PENALTY,
                        help='the late penalty tiers, MINUTES:PERCENT, to turn a penalty into minutes late '
                             '(default 15:25,30:50)')
    parser.add_argument('--gas-miles', type=float, default=175, help='a gas stop every this many miles (default 175)')
    parser.add_argument('--gas-minutes', type=float, default=10, help='minutes per gas stop (default 10)')
    parser.add_argument('--stop-minutes', type=float,
                        help='fix the minutes per stop and fit only the speed and factor; with every rider at '
                             'the same hours the split between speed and stops is loose, so this steadies it')
    parser.add_argument('--top', type=int, default=10, help='also fit the top this many finishers (default 10)')
    parser.add_argument('--csv', metavar='FILE', help='write the per-rider table to this CSV')
    args = parser.parse_args()

    points, combos, riders = read_workbook(args.workbook)
    if args.write_actuals:
        with open(args.write_actuals, 'w', newline='') as f:
            out = csv.writer(f)
            out.writerow(['rider', 'name', 'miles', 'hours'])
            for r in sorted(riders, key=lambda r: r['rider']):
                out.writerow([r['rider'], r['name'], '', ''])
        print(f"Wrote {args.write_actuals}: fill in miles and hours (blank keeps the estimate)")
        return
    actuals = read_actuals(args.actuals) if args.actuals else {}

    hq, bonuses = planRoute.load_bonuses(args.bonuses)
    # Hours ignored, no stops, legs or gas: route hours are just road miles / 60
    planner = planRoute.Planner(hq, bonuses, 10000, 60, 0, planRoute.DEFAULT_ROAD_FACTOR, (), 0, 0,
                                use_hours=False, road_miles=planRoute.load_road_miles(args.road_miles))
    minutes = planRoute.load_road_miles(args.road_miles, 'minutes')
    keys = [planRoute.coordinate_key(place) for place in planner.places]
    index = {place['code']: i for i, place in enumerate(planner.places)}

    rows, unknown = [], set()
    for r in riders:
        on_map = [index[c] for c in dict.fromkeys(r['codes']) if c in index]
        unknown.update(c for c in r['codes'] if c not in index and c not in combos and points.get(c, 0) >= 0)
        if len(on_map) < MIN_STOPS:
            continue
        route, road_miles = shortest_route(planner, on_map)
        stops = [0] + route + [0]
        gh_hours = sum(minutes.get((keys[a], keys[b]), 0) for a, b in zip(stops, stops[1:])) / 60
        miles, hours = actuals.get(r['rider'], (None, None))
        penalty = min([points[c] for c in r['codes'] if points.get(c, 0) < 0], default=0)
        late = late_minutes(-penalty, args.late_penalty) if penalty else 0
        if hours is None:
            hours = args.hours + late / 60
        if miles is None:
            miles = road_miles
        gas = int(miles // args.gas_miles) * args.gas_minutes / 60 if args.gas_miles else 0
        # GraphHopper's time scaled to the rider's miles, when they're known
        gh_hours *= miles / road_miles
        rows.append(dict(rider=r['rider'], name=r['name'], score=r['score'], finish=r['finish'],
                         stops=len(on_map), miles=miles, road_miles=road_miles, hours=hours, late=late,
                         gas=gas, net_hours=hours - gas, gh_hours=gh_hours,
                         actual_miles=r['rider'] in actuals and actuals[r['rider']][0] is not None,
                         actual_hours=r['rider'] in actuals and actuals[r['rider']][1] is not None))
    if not rows:
        sys.exit(f"ERROR: no rider has {MIN_STOPS} or more bonuses from {args.bonuses}")
    rows.sort(key=lambda r: (r['finish'] or 999, r['rider']))

    if unknown:
        print(f"Not on the map, so not counted as stops: {', '.join(sorted(unknown))}\n")
    groups = [(f"Top {args.top}", [r for r in rows if r['finish'] and r['finish'] <= args.top]), ("All riders", rows)]
    fits = []
    for label, group in groups:
        if len(group) < 2:
            continue
        a, stop, error = fit(group, 'miles', args.stop_minutes)
        factor, gh_stop, gh_error = fit(group, 'gh_hours', args.stop_minutes)
        fits.append((label, len(group), 1 / a, stop, error, factor, gh_stop, gh_error))

    print(f"{'Fin':>3} {'Rider':>5}  {'Name':<22} {'Score':>7} {'Stops':>5} {'Miles':>6} {'Hours':>5} "
          f"{'MPH':>5} {'GH x':>5}   (MPH and GH x at the top-group stop minutes)")
    stop_hours = fits[0][3] / 60 if fits else 0
    gh_stop_hours = fits[0][6] / 60 if fits else 0
    for r in rows:
        moving = r['net_hours'] - r['stops'] * stop_hours
        r['mph'] = r['miles'] / moving if moving > 0 else float('inf')
        r['gh_factor'] = (r['net_hours'] - r['stops'] * gh_stop_hours) / r['gh_hours']
        flags = ('' if r['actual_miles'] else ' ~mi') + ('' if r['actual_hours'] else ' ~h') + \
                (f" +{r['late']:g} min late" if r['late'] else '')
        print(f"{r['finish'] or '':>3} {r['rider']:>5}  {str(r['name'])[:22]:<22} {r['score']:>7,.0f} {r['stops']:>5} "
              f"{r['miles']:>6.0f} {r['hours']:>5.2f} {r['mph']:>5.1f} {r['gh_factor']:>5.2f} {flags}")
    print("\n~mi: GraphHopper road miles along the shortest route through the rider's bonuses; "
          "~h: hours assumed (--hours)\n")

    for label, n, speed, stop, error, factor, gh_stop, gh_error in fits:
        print(f"{label} ({n} riders):")
        print(f"  --speed {speed:.0f} --stop-minutes {stop:.1f} --leg-minutes 0   "
              f"(off by {error:.0f} min a rider, root mean square)")
        print(f"  --road-miles {args.road_miles} --road-time-factor {factor:.2f} --stop-minutes {gh_stop:.1f} "
              f"--leg-minutes 0   (off by {gh_error:.0f} min)")
    if args.csv:
        with open(args.csv, 'w', newline='') as f:
            fields = ['finish', 'rider', 'name', 'score', 'stops', 'miles', 'road_miles', 'hours', 'late', 'gas',
                      'gh_hours', 'mph', 'gh_factor', 'actual_miles', 'actual_hours']
            out = csv.DictWriter(f, fields, extrasaction='ignore')
            out.writeheader()
            out.writerows(rows)


if __name__ == '__main__':
    main()
