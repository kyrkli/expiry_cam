#!/usr/bin/env python3
"""Discharge test report: battery_log.csv -> runtime and a new SOC_TABLE for hw/battery.py.

    python3 scanner/tools/discharge_report.py battery_log.csv        (on the PC)
    venv/bin/python -m tools.discharge_report battery_log.csv        (on the scanner)

With BATTERY_LOG = True in config.py the scanner appends one line per minute to
battery_log.csv (see hw/battery.py), every time it runs. So the file may also hold lines from
before the charge or from switching it on again later: the test is the longest run without
a pause, and only that run is used.
With a steady load (the scanner idle all the time) the used charge grows linearly with
time, so 100 % = the first line of the run and 0 % = its last one (our safe cut-off, not
empty cells). Only the standard library is used, so it runs on the PC too.
"""
import csv
import sys

WARN_V = 7.0          # BATTERY_WARN_V in config.py: how much time is left after the warning?
CUTOFF_V = 6.6        # BATTERY_CUTOFF_V: a finished test ends close to it
FULL_V = 8.2          # a test that starts lower did not start with a full battery
GAP_S = 5 * 60        # a longer pause between lines = the scanner was off or restarted


def voltage_at(rows, t):
    """Voltage at time t, linear between the two nearest lines."""
    for (t1, v1), (t2, v2) in zip(rows, rows[1:]):
        if t1 <= t <= t2:
            return v1 if t2 == t1 else v1 + (v2 - v1) * (t - t1) / (t2 - t1)
    return rows[-1][1]


def hours(seconds):
    return f"{int(seconds // 3600)} h {int(seconds % 3600 // 60):02d} min"


def main(path):
    with open(path, newline="") as f:
        lines = [(float(r["unix"]), float(r["voltage"])) for r in csv.DictReader(f)
                 if r.get("unix") and r.get("voltage")]
    if not lines:
        sys.exit("the file has no lines")

    # Split at pauses (scanner off), the longest run is the test
    runs, run = [], [lines[0]]
    for prev, cur in zip(lines, lines[1:]):
        if cur[0] - prev[0] > GAP_S:
            runs.append(run)
            run = []
        run.append(cur)
    runs.append(run)
    rows = max(runs, key=lambda r: r[-1][0] - r[0][0])
    if len(runs) > 1:
        print(f"{len(runs)} runs in the file (the scanner was switched off in between), "
              f"using the longest one")
    if len(rows) < 30:
        sys.exit(f"the longest run has only {len(rows)} lines: the test needs to run until "
                 f"the automatic shutdown")

    t0, t_end = rows[0][0], rows[-1][0]
    total = t_end - t0
    print(f"Lines:   {len(rows)}")
    print(f"Runtime: {hours(total)}  ({rows[0][1]:.2f} V -> {rows[-1][1]:.2f} V)")
    if rows[0][1] < FULL_V:
        print(f"WARNING: the run starts at {rows[0][1]:.2f} V — the battery was not full, "
              f"the runtime is too short")
    if rows[-1][1] > CUTOFF_V + 0.1:
        print(f"WARNING: the run ends at {rows[-1][1]:.2f} V, not at the cut-off "
              f"({CUTOFF_V} V) — the test was stopped before the automatic shutdown")

    warn_t = next((t for t, v in rows if v < WARN_V), None)
    if warn_t is not None:
        left = t_end - warn_t
        print(f"Low battery warning ({WARN_V} V) came {hours(left)} before the shutdown "
              f"({100 * left / total:.0f} % of the runtime)")

    # Voltage at every 10 % of the used charge; keep it falling, battery.py needs that
    table, last_v = [], None
    for pct in range(100, -1, -10):
        v = round(voltage_at(rows, t0 + (1 - pct / 100) * total), 2)
        if last_v is not None and v >= last_v:
            v = round(last_v - 0.01, 2)
        table.append((v, pct))
        last_v = v

    print(f"For a warning at about 10 % left: BATTERY_WARN_V = {table[-2][0]:.2f} in config.py")

    print("\nPut this into scanner/hw/battery.py:\n")
    print("SOC_TABLE = [")
    for i in range(0, len(table), 4):
        print("    " + " ".join(f"({v:.2f}, {p})," for v, p in table[i:i + 4]))
    print("]")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
