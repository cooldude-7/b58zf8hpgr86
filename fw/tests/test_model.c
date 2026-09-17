/* The C torque model against the Python reference.
 *
 * Every row of fw/tests/data/golden.txt was produced by tqmodel in double
 * precision. This code runs in single precision on a microcontroller, so
 * the bar is 1e-4 relative, not equality. Anything worse than that means
 * the port diverged, and every tune built on the Python model would be
 * wrong on the engine.
 */
#include <math.h>
#include <stdio.h>
#include <string.h>

#include "model.h"
#include "tq_test.h"

#define TOL_REL 1.0e-4
#define TOL_ABS 1.0e-5

static int check_row(const char *name, int n, const double *a, double expect)
{
    tq_engine_t e = tq_engine_default();
    double got;

    if (!strcmp(name, "indicated_efficiency") && n == 0) {
        got = tq_indicated_efficiency(&e);
    } else if (!strcmp(name, "air_mass") && n == 3) {
        got = tq_air_mass((f32)a[0], (f32)a[1], (f32)a[2], &e);
    } else if (!strcmp(name, "ve_from_air") && n == 3) {
        got = tq_ve_from_air((f32)a[0], (f32)a[1], (f32)a[2], &e);
    } else if (!strcmp(name, "spark_efficiency") && n == 1) {
        got = tq_spark_efficiency((f32)a[0]);
    } else if (!strcmp(name, "lambda_efficiency") && n == 1) {
        got = tq_lambda_efficiency((f32)a[0]);
    } else if (!strcmp(name, "base_torque") && n == 2) {
        got = tq_base_torque((f32)a[0], (f32)a[1], &e);
    } else if (!strcmp(name, "friction_torque") && n == 2) {
        got = tq_friction_torque((f32)a[0], (f32)a[1], &e);
    } else if (!strcmp(name, "brake_torque") && n == 7) {
        got = tq_brake_torque((f32)a[0], (f32)a[1], (f32)a[2], (f32)a[3],
                              (f32)a[4], (f32)a[5], (f32)a[6], &e);
    } else if (!strcmp(name, "authority") && n == 7) {
        got = tq_authority((f32)a[0], (f32)a[1], (f32)a[2], (f32)a[3],
                           (f32)a[4], (f32)a[5], (f32)a[6], &e);
    } else if (!strcmp(name, "required_air") && n == 6) {
        got = tq_required_air((f32)a[0], (f32)a[1], (f32)a[2], (f32)a[3],
                              (f32)a[4], (f32)a[5], &e);
    } else {
        printf("  [FAIL] unknown golden row '%s' with %d args\n", name, n);
        return 1;
    }

    double scale = fabs(expect);
    double tol = TOL_ABS + TOL_REL * scale;
    tq_checks++;
    if (fabs(got - expect) > tol) {
        tq_fails++;
        printf("  [FAIL] %s(", name);
        for (int i = 0; i < n; i++) printf("%s%g", i ? ", " : "", a[i]);
        printf(") = %.9g, reference %.9g (off by %.3g)\n", got, expect,
               fabs(got - expect));
        return 1;
    }
    return 0;
}

int main(int argc, char **argv)
{
    const char *path = argc > 1 ? argv[1] : "fw/tests/data/golden.txt";
    FILE *f = fopen(path, "r");
    if (!f) {
        printf("cannot open golden file %s\n", path);
        return 2;
    }

    char line[512];
    int rows = 0;
    while (fgets(line, sizeof(line), f)) {
        if (line[0] == '#' || line[0] == '\n') continue;
        char name[64];
        int n;
        int pos = 0;
        if (sscanf(line, "%63s %d%n", name, &n, &pos) != 2) continue;
        double a[8], expect;
        for (int i = 0; i < n; i++) {
            int adv = 0;
            if (sscanf(line + pos, "%lf%n", &a[i], &adv) != 1) { n = -1; break; }
            pos += adv;
        }
        if (n < 0) continue;
        if (sscanf(line + pos, "%lf", &expect) != 1) continue;
        check_row(name, n, a, expect);
        rows++;
    }
    fclose(f);
    printf("  [ok]   %d rows checked against the Python reference\n", rows);

    /* A few properties that must hold regardless of the reference. */
    tq_engine_t e = tq_engine_default();

    TQ_CASE("spark efficiency is flat at MBT");
    TQ_NEAR((tq_spark_efficiency(1e-3f) - 1.0f) / 1e-3f, 0.0f, 1e-3,
            "slope at MBT");

    TQ_CASE("the inverse model round trips");
    for (f32 tgt = 50.0f; tgt <= 400.0f; tgt += 50.0f) {
        f32 air = tq_required_air(tgt, 3500.0f, 18.0f, 18.0f, 0.88f, 150.0f, &e);
        f32 made = tq_base_torque(air, 3500.0f, &e)
                   * tq_spark_efficiency(0.0f) * tq_lambda_efficiency(0.88f)
                   - tq_friction_torque(3500.0f, 150.0f, &e);
        TQ_NEAR(made, tgt, 0.05, "required_air -> brake torque at %.0f Nm", tgt);
    }
    TQ_PASS("inverse model round trips");

    TQ_CASE("air and VE invert each other");
    for (f32 ve = 0.2f; ve < 1.4f; ve += 0.2f) {
        f32 a = tq_air_mass(ve, 170.0f, 310.0f, &e);
        TQ_NEAR(tq_ve_from_air(a, 170.0f, 310.0f, &e), ve, 1e-5, "ve round trip");
    }
    TQ_PASS("VE round trips");

    TQ_CASE("no output is NaN for plausible inputs");
    for (f32 rpm = 500.0f; rpm < 8000.0f; rpm += 500.0f) {
        for (f32 mp = 20.0f; mp < 260.0f; mp += 20.0f) {
            f32 t = tq_brake_torque(0.9f, mp, 320.0f, rpm, 15.0f, 20.0f, 0.9f, &e);
            TQ_CHECK(isfinite(t), "brake_torque NaN at %.0f rpm %.0f kPa", rpm, mp);
        }
    }
    TQ_PASS("no NaN across the operating range");

    return tq_report("model");
}
