"""Guards against a capability being offered and never reached.

This is a regression test for a failure mode this project keeps hitting
rather than a style check. Three separate defects had the same shape: an
interface was declared, nothing was wired to it, and nothing failed --
because nothing calls a thing that nothing calls. `CMD_CHANNELS` sat in
proto.h for months with no handler. `hal_adc_read` exists and the control
path never reaches it, so every "measured" signal in the ECU is populated
only by tests. Eighteen tuner settings are collected from the user and
read by nobody.

The KNOWN_GAPS lists below are the current state of that debt, written
down. The test fails when a NEW dead interface appears, and it fails
again when a listed one is fixed but not removed from the list -- so the
list can only shrink, and it cannot quietly rot.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Protocol commands declared in proto.h with no case in proto.c.
KNOWN_UNHANDLED_COMMANDS = {
    "CMD_CHANNELS",   # live data streaming; the Pi dash and real-hardware
                      # gauges both need it. Tracked.
}

# HAL entry points the control path never calls.
KNOWN_UNCALLED_HAL = {
    "hal_adc_read",           # no sensor layer exists yet: nothing converts
                              # ADC counts into the ECU's measured signals
    "hal_can_send",           # no CAN layer yet
    "hal_can_recv",
    "hal_flash_read",         # calibration storage not wired
    "hal_flash_write",
    "hal_flash_erase",
    "hal_watchdog_force_reset",
    "hal_capture_overruns",   # counted, never read: a fault nobody sees

    # Nothing in fw/src registers the crank or cam interrupt callbacks --
    # only the test harnesses do. There is no target main() yet, but
    # ecu_init is the natural place and does not do it, so on real
    # hardware ecu_on_crank_edge would never be called at all.
    "hal_crank_set_callback",
    "hal_cam_set_callback",

    # There is no throttle controller. The ECU can only hal_throttle_disable()
    # for limp; nothing ever POSITIONS the throttle, so drive-by-wire is
    # not implemented.
    #
    # That leaves a latent fault waiting for the sensor layer. The Level 2
    # monitor's tracking check compares tps_cmd against tps_a
    # (fw/src/monitor.c:41), and NOTHING writes ecu_signals_t.tps_cmd --
    # it is zero from the memset in ecu_init onward. Today tps_a is also
    # always zero, so the two agree and the check passes. The moment a
    # sensor layer makes tps_a real while tps_cmd stays zero, the check
    # trips MON_F_TPS_TRACKING and limps the car to idle. Two gaps are
    # currently cancelling each other out.
    "hal_throttle_pwm",
}

# Tuner settings the UI collects that nothing consumes. The root cause is
# structural: cal.h carries tables and only tables, so no scalar setting
# can reach the ECU at all.
KNOWN_DEAD_SETTINGS = {
    "trigger_teeth", "trigger_missing", "trigger_gap_to_tdc_deg",
    "cam_edge_angle_deg", "cam_tolerance_deg",
    "dwell_ms", "soi_btdc_deg", "split_gap_deg",
    "inj_boost_v", "inj_peak_ma", "inj_peak_us", "inj_hold_ma",
    "inj_recharge_us",
    "hpfp_lobes", "hpfp_lobe_span_deg", "hpfp_first_lobe_deg",
    "msv_hold_us", "rail_volume_cc",
}


def _read(rel: str) -> str:
    return (REPO / rel).read_text()


def _sources(*dirs: str) -> str:
    out = []
    for d in dirs:
        for p in (REPO / d).rglob("*.c"):
            out.append(p.read_text())
        for p in (REPO / d).rglob("*.py"):
            out.append(p.read_text())
    return "\n".join(out)


def test_every_protocol_command_is_handled():
    header = _read("fw/include/proto.h")
    impl = _read("fw/src/proto.c")
    declared = set(re.findall(r"(CMD_[A-Z_]+)\s*=", header))
    unhandled = {c for c in declared if f"case {c}" not in impl}

    new = unhandled - KNOWN_UNHANDLED_COMMANDS
    assert not new, (
        f"new protocol command(s) declared with no handler: {sorted(new)}. "
        f"They will answer ST_BAD_CMD and the tuner will report an unknown "
        f"command."
    )
    fixed = KNOWN_UNHANDLED_COMMANDS - unhandled
    assert not fixed, (
        f"{sorted(fixed)} now has a handler. Remove it from "
        f"KNOWN_UNHANDLED_COMMANDS so the list keeps shrinking."
    )


def test_every_hal_entry_point_is_reached_by_the_control_path():
    hal = _read("fw/include/hal.h")
    # Declarations look like "ret name(args);" at the start of a line.
    decls = set(re.findall(r"^\w[\w \*]*?\b(hal_\w+)\s*\(", hal, re.M))
    body = _sources("fw/src", "fw/tools")
    uncalled = {d for d in decls if not re.search(rf"\b{d}\s*\(", body)}

    new = uncalled - KNOWN_UNCALLED_HAL
    assert not new, (
        f"new HAL entry point(s) that nothing in fw/src or fw/tools calls: "
        f"{sorted(new)}. A capability nothing reaches is a capability that "
        f"does not exist on real hardware."
    )
    fixed = KNOWN_UNCALLED_HAL - uncalled
    assert not fixed, (
        f"{sorted(fixed)} is now called. Remove it from KNOWN_UNCALLED_HAL."
    )


def test_every_tuner_setting_has_a_consumer():
    page = _read("tuner/ui/settings_page.py")
    fields = set(re.findall(r'^\s*"([a-z0-9_]+)":\s*\(', page, re.M))
    # tune.py only declares bounds and defaults, so it does not count as a
    # consumer; a setting is live when something outside it reads it.
    consumers = _sources("tqmodel") + "\n".join(
        p.read_text()
        for p in (REPO / "tuner").rglob("*.py")
        if p.name not in {"tune.py", "settings_page.py"}
    )
    dead = {f for f in fields if not re.search(rf'["\']{f}["\']|\b{f}\b', consumers)}

    new = dead - KNOWN_DEAD_SETTINGS
    assert not new, (
        f"new tuner setting(s) collected from the user and read by nothing: "
        f"{sorted(new)}. Either wire it up or do not ask for it."
    )
    fixed = KNOWN_DEAD_SETTINGS - dead
    assert not fixed, (
        f"{sorted(fixed)} now has a consumer. Remove it from "
        f"KNOWN_DEAD_SETTINGS."
    )


def test_the_known_gaps_are_documented_not_just_listed():
    """A bare allowlist rots. This one has to explain itself."""
    src = Path(__file__).read_text()
    for block in ("KNOWN_UNHANDLED_COMMANDS", "KNOWN_UNCALLED_HAL",
                  "KNOWN_DEAD_SETTINGS"):
        i = src.index(block)
        window = src[max(0, i - 400):i]
        assert "#" in window, f"{block} has no comment explaining why"
