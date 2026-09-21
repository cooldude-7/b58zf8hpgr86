/* Closed-loop fuel, and the difference between reacting and learning. */
#include "lambda.h"
#include "tq_test.h"

static lam_in_t base(f32 meas, f32 target)
{
    lam_in_t in;
    in.dt = 0.010f;
    in.lambda_meas = meas;
    in.lambda_target = target;
    in.rpm = 2000.0f;
    in.load_kpa = 80.0f;
    in.clt_k = 363.0f;
    in.sensor_ok = true;
    in.inhibit = false;
    return in;
}

static void run(lambda_t *l, const lam_config_t *c, lam_in_t *in, int n)
{
    for (int i = 0; i < n; i++) lambda_update(l, c, in);
}

int main(void)
{
    lam_config_t cfg = lam_config_default();

    TQ_CASE("a lean engine gets more fuel");
    {
        lambda_t l; lambda_init(&l, &cfg);
        lam_in_t in = base(1.08f, 1.00f);       /* 8 % lean */
        run(&l, &cfg, &in, 200);
        TQ_CHECK(l.closed, "the loop never closed");
        TQ_CHECK(l.total > 1.02f,
                 "a lean engine was corrected by only %.3f", (double)l.total);
        TQ_PASS("feedback in the right direction");
    }

    TQ_CASE("a rich engine gets less fuel");
    {
        lambda_t l; lambda_init(&l, &cfg);
        lam_in_t in = base(0.92f, 1.00f);
        run(&l, &cfg, &in, 200);
        TQ_CHECK(l.total < 0.98f,
                 "a rich engine was corrected by only %.3f", (double)l.total);
        TQ_PASS("and in the other direction");
    }

    TQ_CASE("a persistent error is LEARNED, not re-corrected forever");
    {
        /* The whole point of the long term trim: an injector 5 % small
         * should stop being rediscovered every time the engine visits
         * this region. */
        lambda_t l; lambda_init(&l, &cfg);
        lam_in_t in = base(1.05f, 1.00f);
        run(&l, &cfg, &in, 6000);               /* a minute of it */
        f32 learned = l.long_trim[l.cell_l][l.cell_r];
        TQ_CHECK(learned > 1.01f,
                 "the long term trim learned nothing (%.4f)", (double)learned);
        TQ_PASS("the correction is remembered");
    }

    TQ_CASE("the trim is authority-limited, not unbounded");
    {
        /* A sensor reporting nonsense must not be able to command any
         * fuelling it likes. A 60 % correction is a fault, not a tune. */
        lambda_t l; lambda_init(&l, &cfg);
        lam_in_t in = base(1.60f, 1.00f);
        run(&l, &cfg, &in, 20000);
        TQ_CHECK(l.total <= 1.0f + cfg.total_max + 1e-4f,
                 "trim ran to %.3f, past its total authority of %.3f",
                 (double)l.total, (double)(1.0f + cfg.total_max));
        TQ_PASS("bounded");
    }

    TQ_CASE("a failed sensor opens the loop");
    {
        lambda_t l; lambda_init(&l, &cfg);
        lam_in_t in = base(1.08f, 1.00f);
        in.sensor_ok = false;
        run(&l, &cfg, &in, 500);
        TQ_CHECK(!l.closed, "ran closed loop on a failed sensor");
        TQ_PASS("no feedback from a sensor that is not reporting");
    }

    TQ_CASE("a cold engine runs open loop");
    {
        /* The sensor is not at temperature and its reading means
         * nothing, and the engine is deliberately rich anyway. */
        lambda_t l; lambda_init(&l, &cfg);
        lam_in_t in = base(1.08f, 1.00f);
        in.clt_k = 300.0f;
        run(&l, &cfg, &in, 500);
        TQ_CHECK(!l.closed, "closed the loop on a cold engine");
        TQ_PASS("warm up first");
    }

    TQ_CASE("a deliberately rich target is not trimmed back to stoich");
    {
        /* Full-load enrichment is the calibration protecting the engine.
         * A feedback loop chasing lambda 1.0 there would undo it, and
         * the failure mode is a melted piston rather than a rough idle. */
        lambda_t l; lambda_init(&l, &cfg);
        lam_in_t in = base(0.85f, 0.85f);
        run(&l, &cfg, &in, 500);
        TQ_CHECK(!l.closed, "closed the loop against a rich target");
        TQ_PASS("protection is not an error to correct");
    }

    TQ_CASE("a transient is not learned from");
    {
        lambda_t l; lambda_init(&l, &cfg);
        lam_in_t in = base(1.20f, 1.00f);
        in.inhibit = true;                       /* accel enrichment active */
        run(&l, &cfg, &in, 1000);
        TQ_CHECK(!l.closed, "trimmed during a transient");
        TQ_NEAR(l.long_trim[l.cell_l][l.cell_r], 1.0f, 1e-4f,
                "learned from a mixture that was off target on purpose");
        TQ_PASS("does not fight a deliberate correction");
    }

    TQ_CASE("entering a new region waits for the exhaust to catch up");
    {
        /* The gas in the pipe is still from the old operating point.
         * Integrating against it corrects the new cell for the old
         * cell's error. */
        lambda_t l; lambda_init(&l, &cfg);
        lam_in_t in = base(1.00f, 1.00f);
        run(&l, &cfg, &in, 500);
        TQ_CHECK(l.closed, "precondition");
        in.rpm = 5000.0f;                        /* a different cell */
        lambda_update(&l, &cfg, &in);
        TQ_CHECK(!l.closed,
                 "started trimming the instant the operating point moved");
        run(&l, &cfg, &in, 200);
        TQ_CHECK(l.closed, "never resumed after settling");
        TQ_PASS("transport delay respected");
    }

    TQ_CASE("each region learns its own trim");
    {
        lambda_t l; lambda_init(&l, &cfg);
        lam_in_t low = base(1.06f, 1.00f);
        low.rpm = 1000.0f; low.load_kpa = 30.0f;
        run(&l, &cfg, &low, 6000);
        u8 lr = l.cell_r, ll = l.cell_l;

        lam_in_t high = base(1.00f, 1.00f);
        high.rpm = 5000.0f; high.load_kpa = 200.0f;
        run(&l, &cfg, &high, 6000);

        TQ_CHECK(l.cell_r != lr || l.cell_l != ll, "the cells did not differ");
        TQ_CHECK(l.long_trim[ll][lr] > l.long_trim[l.cell_l][l.cell_r] + 0.005f,
                 "a lean region and a correct one learned the same trim "
                 "(%.4f vs %.4f)", (double)l.long_trim[ll][lr],
                 (double)l.long_trim[l.cell_l][l.cell_r]);
        TQ_PASS("the map is learned, not one number");
    }

    return tq_report("lambda");
}
