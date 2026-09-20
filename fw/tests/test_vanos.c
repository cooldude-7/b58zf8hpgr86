/* VANOS control against a simulated integrating plant.
 *
 * The plant is the thing that makes this controller unusual: oil valve
 * duty sets the cam's VELOCITY, not its position, and the duty that holds
 * the cam still is neither zero nor known. Every test here exists because
 * getting one of those two facts wrong produces a loop that looks fine in
 * a diagram and hunts, sticks or false-faults on an engine.
 */
#include <math.h>

#include "hal_host.h"
#include "tq_test.h"
#include "vanos.h"

typedef struct {
    f32 pos;            /* true cam advance, crank degrees */
    f32 null_true;      /* the duty that actually holds it still */
    f32 kv;             /* crank deg/s per unit duty away from null */
    f32 lo, hi;         /* mechanical travel */
    f32 dir;            /* +1 advances when energized, -1 retards */
    bool seized;        /* the cam cannot move at all */
} plant_t;

static void plant_step(plant_t *p, f32 duty, f32 dt)
{
    if (p->seized) return;
    /* De-energized means the locking pin holds it, not that it drifts. */
    if (duty <= 0.001f) return;
    f32 rate = p->dir * p->kv * (duty - p->null_true);
    p->pos += rate * dt;
    p->pos = tq_clampf(p->pos, p->lo, p->hi);
}

typedef struct {
    vanos_t van;
    plant_t plant;
    van_inputs_t in;
    tq_time_t t;
} rig_t;

static void rig_init_dir(rig_t *r, f32 null_true, f32 lo, f32 hi, f32 dir)
{
    van_config_t cfg = vanos_config_default();
    vanos_init(&r->van, &cfg);
    r->plant.pos = 0.0f;
    r->plant.null_true = null_true;
    r->plant.kv = cfg.kv_deg_s;
    r->plant.lo = lo;
    r->plant.hi = hi;
    r->plant.seized = false;
    r->plant.dir = dir;
    r->t = 1000000u;

    for (u8 i = 0; i < VAN_N_CAM; i++) {
        r->in.target_deg[i] = 0.0f;
        r->in.null_sched[i] = cfg.null_seed;
        r->in.meas_valid[i] = false;
        r->in.meas_deg[i] = 0.0f;
        r->in.meas_age_us[i] = 0;
        r->in.adv_min[i] = lo;
        r->in.adv_max[i] = hi;
        r->in.travel_dir[i] = dir;
    }
    r->in.dt = 0.010f;                  /* the 10 ms task */
    r->in.rpm = 1500.0f;
    r->in.oil_kpa = 300.0f;
    r->in.oil_k = 273.0f + 90.0f;
    r->in.running = true;
}

static void rig_init(rig_t *r, f32 null_true, f32 lo, f32 hi)
{
    rig_init_dir(r, null_true, lo, hi, 1.0f);
}

/* One 10 ms tick: measure, control, let the plant move. */
static void tick(rig_t *r, bool measure)
{
    r->t += 10000u;
    r->in.now_us = r->t;
    r->in.meas_valid[0] = measure;
    r->in.meas_deg[0] = r->plant.pos;
    r->in.meas_age_us[0] = 0;
    vanos_update(&r->van, &r->in);
    plant_step(&r->plant, r->van.cam[0].duty, r->in.dt);
}

static void run(rig_t *r, int ticks) { for (int i = 0; i < ticks; i++) tick(r, true); }

int main(void)
{
    TQ_CASE("the cam reaches its target from park");
    {
        rig_t r; rig_init(&r, 0.42f, -8.0f, 70.0f);
        r.in.target_deg[0] = 40.0f;
        run(&r, 400);                   /* 4 seconds */
        TQ_NEAR(r.plant.pos, 40.0f, 2.0f, "cam did not arrive");
        TQ_CHECK(r.van.cam[0].state == VAN_CLOSED_LOOP, "not in closed loop");
        TQ_CHECK(r.van.cam[0].fault == VAN_F_NONE, "faulted on a healthy run");
        TQ_PASS("converges on an integrating plant");
    }

    TQ_CASE("the holding duty is learned, from a seed that is wrong");
    {
        /* The whole reason the learner gates on "is the cam moving"
         * rather than "is the error small". The seed here is 0.50 and the
         * truth is 0.30; a learner that waits for a small error never
         * gets one, because the error is only small once it has already
         * learned. */
        rig_t r; rig_init(&r, 0.30f, -8.0f, 70.0f);
        r.in.target_deg[0] = 30.0f;
        run(&r, 800);
        TQ_NEAR(r.van.cam[0].null_duty, 0.30f, 0.05f,
                "holding duty never converged");
        TQ_NEAR(r.plant.pos, 30.0f, 1.5f, "position drifted off target");
        TQ_PASS("learns the holding duty while the cam is stationary");
    }

    TQ_CASE("an exhaust cam, whose travel is negative, also converges");
    {
        /* An exhaust cam parks fully ADVANCED and retards from there, so
         * energizing it moves the advance negative. */
        rig_t r; rig_init_dir(&r, 0.55f, -60.0f, 8.0f, -1.0f);
        r.in.target_deg[0] = -45.0f;
        run(&r, 500);
        TQ_NEAR(r.plant.pos, -45.0f, 2.0f, "exhaust cam did not arrive");
        TQ_PASS("handles negative travel");
    }

    TQ_CASE("a target outside the mechanical travel is clamped, not chased");
    {
        rig_t r; rig_init(&r, 0.42f, -8.0f, 70.0f);
        r.in.target_deg[0] = 200.0f;          /* nonsense from calibration */
        run(&r, 400);
        TQ_CHECK(r.van.cam[0].target_deg <= 70.0f + 0.01f,
                 "target %.1f was not clamped", (double)r.van.cam[0].target_deg);
        TQ_CHECK(r.van.cam[0].fault == VAN_F_NONE,
                 "faulted while pinned on its own stop");
        TQ_PASS("clamps to travel, and a stop is not a fault");
    }

    TQ_CASE("no oil pressure means de-energized, not a fault");
    {
        rig_t r; rig_init(&r, 0.42f, -8.0f, 70.0f);
        r.in.target_deg[0] = 40.0f;
        r.in.oil_kpa = 50.0f;                 /* cranking, no pressure yet */
        run(&r, 400);
        TQ_CHECK(r.van.cam[0].state == VAN_OFF, "tried to control with no oil");
        TQ_NEAR(r.van.cam[0].duty, 0.0f, 0.001f, "left the valve energized");
        TQ_CHECK(r.van.cam[0].fault == VAN_F_NONE,
                 "raised a fault for an absent gate");
        TQ_PASS("parks when it has no authority");
    }

    TQ_CASE("the learned duty survives a gate-out");
    {
        rig_t r; rig_init(&r, 0.30f, -8.0f, 70.0f);
        r.in.target_deg[0] = 30.0f;
        run(&r, 800);
        f32 learned = r.van.cam[0].null_duty;
        r.in.oil_kpa = 50.0f;                 /* lose oil */
        run(&r, 200);
        TQ_NEAR(r.van.cam[0].null_duty, learned, 0.001f,
                "threw away the learned holding duty when gated out");
        TQ_PASS("keeps what it learned");
    }

    TQ_CASE("a stale measurement is not acted on");
    {
        /* An integrating plant driven from a frozen measurement winds
         * itself into its stop. The decoder refuses to serve a stale cam
         * position; this is the other half of that contract. */
        rig_t r; rig_init(&r, 0.42f, -8.0f, 70.0f);
        r.in.target_deg[0] = 40.0f;
        run(&r, 200);
        for (int i = 0; i < 100; i++) {
            r.t += 10000u;
            r.in.now_us = r.t;
            r.in.meas_valid[0] = true;
            r.in.meas_deg[0] = r.plant.pos;
            r.in.meas_age_us[0] = 900000u;    /* nearly a second old */
            vanos_update(&r.van, &r.in);
            plant_step(&r.plant, r.van.cam[0].duty, r.in.dt);
        }
        TQ_CHECK(r.van.cam[0].state == VAN_OFF,
                 "acted on a stale cam position (state %d)",
                 r.van.cam[0].state);
        TQ_PASS("refuses to integrate against a frozen measurement");
    }

    TQ_CASE("a cam that is commanded but cannot move raises a fault");
    {
        rig_t r; rig_init(&r, 0.42f, -8.0f, 70.0f);
        r.in.target_deg[0] = 50.0f;
        r.plant.seized = true;
        run(&r, 600);
        TQ_CHECK(r.van.cam[0].state == VAN_FAULT, "no fault on a seized cam");
        TQ_CHECK(r.van.cam[0].fault == VAN_F_NOT_REACHED,
                 "wrong fault code %u", r.van.cam[0].fault);
        TQ_NEAR(r.van.cam[0].duty, 0.0f, 0.001f,
                "kept driving oil at a cam it had given up on");
        TQ_PASS("faults and parks when the cam will not move");
    }

    TQ_CASE("a faulted cam stays parked");
    {
        rig_t r; rig_init(&r, 0.42f, -8.0f, 70.0f);
        r.in.target_deg[0] = 50.0f;
        r.plant.seized = true;
        run(&r, 600);
        TQ_CHECK(r.van.cam[0].state == VAN_FAULT, "precondition");
        r.plant.seized = false;               /* it frees itself */
        run(&r, 400);
        TQ_CHECK(r.van.cam[0].state == VAN_FAULT,
                 "un-faulted itself mid-drive");
        TQ_NEAR(r.plant.pos, 0.0f, 0.5f, "moved while faulted");
        TQ_PASS("a phaser fault does not clear itself under way");
    }

    return tq_report("vanos");
}
