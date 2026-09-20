"""TQ-101: the labs must be failable at the start and passable at the end.

A course whose labs pass before the student does anything teaches
nothing. A course whose labs cannot be passed at all is worse. Both
halves are checked here, by solving each lab the way the lecture says
to and confirming the marker agrees.
"""
import numpy as np
import pytest

from conftest import TEST_PLANT_SEED

from tuner.core import course
from tuner.core.sim_ecu import SimulatedECU
from tuner.core.tune import default_tune


@pytest.fixture
def student(qapp):
    t = course.student_tune()
    s = SimulatedECU(t, seed=TEST_PLANT_SEED)
    return t, s


# ---- the starting position ------------------------------------------------
def test_the_course_tune_validates(student):
    t, _ = student
    t.validate()


def test_every_lab_fails_at_the_start(student):
    t, s = student
    for lab in course.LABS:
        r = lab.run(t, s)
        assert not r.passed, f"{lab.title} passed before any work was done"
        assert r.findings or lab.key == "shift", \
            f"{lab.title} failed with nothing to act on"


def test_findings_name_an_operating_point(student):
    t, s = student
    r = course.LABS_BY_KEY["ve"].run(t, s)
    f = r.findings[0]
    assert f.rpm > 0 and f.load > 0
    assert "%" in f.detail
    assert "rpm" in str(f)


# ---- each lab, solved the way the lecture says --------------------------
def test_lab_1_passes_once_ve_matches_the_plant(student):
    """The lecture's method: multiply each cell by measured over target.
    Done across the grid, that is the same as setting the table to the
    plant's surface, which is what a real calibration converges on."""
    t, s = student
    ve = t.tables["ve"]
    for j, mp in enumerate(ve.y):
        for i, rpm in enumerate(ve.x):
            ve.values[j, i] = s.plant_ve(float(rpm), float(mp))
    r = course.LABS_BY_KEY["ve"].run(t, s)
    assert r.passed, r.summary


def test_lab_1_still_fails_if_only_the_breakpoints_are_fixed(student):
    """The marker samples off the breakpoints on purpose. Fixing four
    cells you happened to visit should not pass."""
    t, s = student
    ve = t.tables["ve"]
    ve.values[0, 0] = s.plant_ve(float(ve.x[0]), float(ve.y[0]))
    assert not course.LABS_BY_KEY["ve"].run(t, s).passed


def test_lab_2_passes_once_mbt_matches(student):
    t, s = student
    mbt = t.tables["mbt"]
    for j, mp in enumerate(mbt.y):
        for i, rpm in enumerate(mbt.x):
            mbt.values[j, i] = s.plant_mbt(float(rpm), float(mp))
    r = course.LABS_BY_KEY["mbt"].run(t, s)
    assert r.passed, r.summary


def test_lab_3_fails_hard_when_past_the_limit(student):
    t, s = student
    knock = t.tables["knock"]
    for j, mp in enumerate(knock.y):
        for i, rpm in enumerate(knock.x):
            knock.values[j, i] = s.plant_knock_limit(float(rpm), float(mp)) + 5.0
    r = course.LABS_BY_KEY["knock"].run(t, s)
    assert not r.passed
    assert "UNSAFE" in r.summary


def test_lab_3_fails_when_needlessly_conservative(student):
    """Retarding everything to be safe is not a calibration."""
    t, s = student
    knock = t.tables["knock"]
    for j, mp in enumerate(knock.y):
        for i, rpm in enumerate(knock.x):
            knock.values[j, i] = s.plant_knock_limit(float(rpm), float(mp)) - 20.0
    r = course.LABS_BY_KEY["knock"].run(t, s)
    assert not r.passed
    assert "UNSAFE" not in r.summary
    assert "conservative" in r.summary


def test_lab_3_passes_with_a_sensible_margin(student):
    t, s = student
    knock = t.tables["knock"]
    for j, mp in enumerate(knock.y):
        for i, rpm in enumerate(knock.x):
            knock.values[j, i] = s.plant_knock_limit(float(rpm), float(mp)) - 3.0
    r = course.LABS_BY_KEY["knock"].run(t, s)
    assert r.passed, r.summary


def test_lab_4_passes_with_a_sensible_mixture_strategy(student):
    t, s = student
    lam = t.tables["lambda"]
    for j, mp in enumerate(lam.y):
        for i in range(lam.n_x):
            if mp <= 95.0:
                lam.values[j, i] = 1.00
            elif mp >= 170.0:
                lam.values[j, i] = 0.86
            else:
                k = (float(mp) - 95.0) / 75.0
                lam.values[j, i] = 1.00 - 0.14 * k
    r = course.LABS_BY_KEY["lambda"].run(t, s)
    assert r.passed, r.summary


def test_lab_5_passes_with_a_correct_coordinator(student):
    """A reference coordinator that does the four things the lab asks."""
    t, s = student

    class Reference:
        HOLD, RAMP = 0.20, 0.15

        def new_controller(self):
            return {"phase": "idle", "t": 0.0, "target": 0.0, "entry": 0.0}

        def start_shift(self, st, target, current):
            st.update(phase="cutting", t=0.0, target=target, entry=current)

        def update(self, st, dt, driver, mbt):
            if st["phase"] == "idle":
                return mbt, driver, driver
            st["t"] += dt
            entry = max(st["entry"], 1.0)
            want = max(st["target"], 0.0)
            frac = min(max(want / entry, 0.05), 1.0)
            deg = ((1.0 - frac) / 1.096e-3) ** (1.0 / 1.8)
            if st["t"] < self.HOLD:
                spark, tq = mbt - deg, want
            elif st["t"] < self.HOLD + self.RAMP:
                k = (st["t"] - self.HOLD) / self.RAMP
                spark, tq = mbt - deg * (1.0 - k), want + (driver - want) * k
            else:
                st["phase"] = "idle"
                return mbt, driver, driver
            return spark, driver, tq        # air held at the driver's request

    s.coord = Reference()
    r = course.LABS_BY_KEY["shift"].run(t, s)
    assert r.passed, f"{r.summary}: {[str(f) for f in r.findings]}"


def test_lab_5_catches_a_coordinator_that_chases_air(student):
    t, s = student

    class Chaser:
        def new_controller(self):
            return {}

        def start_shift(self, st, target, current):
            st["on"] = True

        def update(self, st, dt, driver, mbt):
            if not st.get("on"):
                return mbt, driver, driver
            return mbt - 20.0, driver * 2.0, driver * 0.35

    s.coord = Chaser()
    r = course.LABS_BY_KEY["shift"].run(t, s)
    assert not r.passed
    assert any("air-chase" in f.detail for f in r.findings)


def test_lab_5_survives_a_coordinator_that_raises(student):
    t, s = student

    class Broken:
        def new_controller(self):
            return {}

        def start_shift(self, *a):
            pass

        def update(self, *a):
            raise RuntimeError("student bug")

    s.coord = Broken()
    r = course.LABS_BY_KEY["shift"].run(t, s)
    assert not r.passed
    assert "student bug" in r.summary


def test_lab_6_passes_with_a_sensible_di_strategy(student):
    t, s = student
    rail, soi, split = (t.tables["rail_target"], t.tables["soi"],
                        t.tables["inj_split"])
    for j, mp in enumerate(rail.y):
        for i, rpm in enumerate(rail.x):
            rail.values[j, i] = np.clip(5000.0 + 70.0 * (float(mp) - 30.0),
                                        5000.0, 20000.0)
            soi.values[j, i] = 300.0 + 0.004 * float(rpm)
            split.values[j, i] = 0.30 if (mp > 170.0 and rpm > 4000.0) else 0.0
    r = course.LABS_BY_KEY["di"].run(t, s)
    assert r.passed, f"{r.summary}: {[str(f) for f in r.findings][:4]}"


# ---- the whole course ----------------------------------------------------
def test_the_course_can_be_completed(student):
    """Every lab passing at once, on one tune. If the labs contradicted
    each other this is where it would show."""
    t, s = student
    for j, mp in enumerate(t.tables["ve"].y):
        for i, rpm in enumerate(t.tables["ve"].x):
            r_, m_ = float(rpm), float(mp)
            t.tables["ve"].values[j, i] = s.plant_ve(r_, m_)
            t.tables["mbt"].values[j, i] = s.plant_mbt(r_, m_)
            t.tables["knock"].values[j, i] = s.plant_knock_limit(r_, m_) - 3.0
            t.tables["lambda"].values[j, i] = (
                1.00 if m_ <= 95.0 else 0.86 if m_ >= 170.0
                else 1.00 - 0.14 * (m_ - 95.0) / 75.0)
            t.tables["rail_target"].values[j, i] = np.clip(
                5000.0 + 70.0 * (m_ - 30.0), 5000.0, 20000.0)
            t.tables["soi"].values[j, i] = 300.0 + 0.004 * r_
            t.tables["inj_split"].values[j, i] = (
                0.30 if (m_ > 170.0 and r_ > 4000.0) else 0.0)
    t.validate()
    failed = [lab.title for lab in course.LABS
              if lab.key != "shift" and not lab.run(t, s).passed]
    assert not failed, f"still failing: {failed}"


def test_a_completed_tune_is_still_a_legal_tune(student):
    """Passing the labs must not require values the ECU would refuse."""
    t, s = student
    for j, mp in enumerate(t.tables["ve"].y):
        for i, rpm in enumerate(t.tables["ve"].x):
            t.tables["ve"].values[j, i] = s.plant_ve(float(rpm), float(mp))
    t.validate()
    s.connect_ecu()
    try:
        s.write_table("ve", t.tables["ve"].values)
    finally:
        s.disconnect_ecu()


# ---- the page in the app -------------------------------------------------
def test_loading_the_course_tune_does_not_close_the_course_page(qapp):
    """_replace_tune closes every tab. The button that loads the tune
    lives on the Course page, so without care the page vanishes the
    moment it is used."""
    from tuner.ui.main_window import MainWindow

    w = MainWindow(default_tune(), persist_layout=False)
    try:
        w.conn = w.sim
        w.conn.connect_ecu()
        w._on_conn_state(True)
        w.open_key("course")
        assert "course" in w.editors
        w._load_course_tune()
        assert "course" in w.editors, "the Course page closed itself"
        assert w.tune.name.startswith("TQ-101")
    finally:
        w.conn.disconnect_ecu()
        w.tune.mark_saved()
        w.close()


def test_the_page_marks_and_reports(qapp):
    from tuner.ui.main_window import MainWindow

    w = MainWindow(course.student_tune(), persist_layout=False)
    try:
        w.conn = w.sim
        w.conn.connect_ecu()
        w._on_conn_state(True)
        w.open_key("course")
        page = w.editors["course"]
        page.check_all()
        assert "0 of 6" in page.l_overall.text()
        page.list.setCurrentRow(0)
        assert "NOT YET" in page.out.toHtml()
        assert page.bar.value() < 100
    finally:
        w.conn.disconnect_ecu()
        w.tune.mark_saved()
        w.close()


# ---- the plant is per-installation, and every one of them is tunable ----
def test_the_same_seed_is_the_same_engine(qapp):
    t = course.student_tune()
    a, b = SimulatedECU(t, seed=12345), SimulatedECU(t, seed=12345)
    c = SimulatedECU(t, seed=999)
    for rpm, mp in ((1200, 40), (3000, 100), (6000, 200)):
        assert a.plant_ve(rpm, mp) == b.plant_ve(rpm, mp)
        assert a.plant_mbt(rpm, mp) == b.plant_mbt(rpm, mp)
        assert a.plant_knock_limit(rpm, mp) == b.plant_knock_limit(rpm, mp)
    assert a.plant_ve(3000, 100) != c.plant_ve(3000, 100)


def test_the_seed_survives_a_restart(qapp):
    """Closing the application mid-lab and coming back to a different
    engine would throw the work away, so the seed is kept, not minted per
    session."""
    from tuner.core.sim_ecu import plant_seed

    assert plant_seed() == plant_seed()
    assert SimulatedECU(course.student_tune()).seed == plant_seed()


@pytest.mark.parametrize("seed", [1, 7, 42, 1234, 99991, 2 ** 31 - 2])
def test_every_seed_is_a_tunable_engine(qapp, seed):
    """Different is not enough: each seed has to be an engine somebody can
    actually calibrate. The shipped course tune must fail against it, and
    the plant's own surfaces must pass -- otherwise a student somewhere
    gets a lab that cannot be started or cannot be finished."""
    t = course.student_tune()
    s = SimulatedECU(t, seed=seed)

    assert not course.LABS_BY_KEY["ve"].run(t, s).passed, "starts already solved"

    ve = t.tables["ve"]
    for j, mp in enumerate(ve.y):
        for i, rpm in enumerate(ve.x):
            v = s.plant_ve(float(rpm), float(mp))
            assert 0.30 < v < 1.45, (seed, rpm, mp, v)     # a plausible engine
            ve.values[j, i] = v
    assert course.LABS_BY_KEY["ve"].run(t, s).passed, (seed, "cannot be solved")

    mbt = t.tables["mbt"]
    for j, mp in enumerate(mbt.y):
        for i, rpm in enumerate(mbt.x):
            d = s.plant_mbt(float(rpm), float(mp))
            assert 0.0 < d < 45.0, (seed, rpm, mp, d)
            mbt.values[j, i] = d
    assert course.LABS_BY_KEY["mbt"].run(t, s).passed, (seed, "cannot be solved")


# ---- the marker's answer reaches the table ------------------------------
def test_findings_carry_a_signed_comparable_error(student):
    """Every lab signs its error the same way -- positive means the cell
    is too high -- or the table cannot draw a direction."""
    t, s = student
    ve = t.tables["ve"]
    ve.values[:] = ve.values * 1.20                  # 20% too much airflow
    r = course.LABS_BY_KEY["ve"].run(t, s)
    assert not r.passed
    assert all(f.error > 0 for f in r.findings), "too high must read positive"
    assert all(f.tol > 0 for f in r.findings)

    ve.values[:] = ve.values / 1.44                  # now well under
    r = course.LABS_BY_KEY["ve"].run(t, s)
    assert all(f.error < 0 for f in r.findings), "too low must read negative"


def test_commanding_past_the_knock_limit_is_flagged_unsafe(student):
    """Too much advance is a different class of wrong from too little, and
    the table shows it differently."""
    t, s = student
    knock = t.tables["knock"]
    for j, mp in enumerate(knock.y):
        for i, rpm in enumerate(knock.x):
            knock.values[j, i] = s.plant_knock_limit(float(rpm), float(mp)) + 6.0
    r = course.LABS_BY_KEY["knock"].run(t, s)
    assert not r.passed
    assert any(f.unsafe for f in r.findings)
    assert all(f.error > 0 for f in r.findings if f.unsafe)


def test_marking_puts_the_findings_on_the_table(qapp):
    """The point of the whole change: the marker's answer belongs on the
    grid the student is looking at, not only in a list beside it."""
    from tuner.ui.main_window import MainWindow

    win = MainWindow(course.student_tune(), persist_layout=False)
    win.open_item("course", "course", "Labs and progress")
    win.editors["course"].check_all()

    ed = win.editors["ve"]
    assert ed.findings, "a failing lab must mark the table"
    for (j, i), (error, sev, unsafe) in ed.findings.items():
        assert 0 <= j < ed.table.n_y and 0 <= i < ed.table.n_x
        assert error != 0.0 and sev > 0.0

    # solving it clears them, so the table stops showing finished work
    ve = win.tune.tables["ve"]
    for j, mp in enumerate(ve.y):
        for i, rpm in enumerate(ve.x):
            ve.values[j, i] = win.sim.plant_ve(float(rpm), float(mp))
    win.editors["course"].check_all()
    assert not ed.findings
    win.tune.mark_saved()      # or close() sits on the unsaved-work prompt
    win.close()
