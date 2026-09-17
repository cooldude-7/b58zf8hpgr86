/* Types and units, fixed once so no module has to guess.
 *
 * Single precision throughout: the M7 and the S32K3 both have a
 * single-precision FPU and no double unit, so a stray double turns a
 * one-cycle multiply into a library call inside a crank interrupt.
 * Anything that needs more range is scaled, not promoted.
 *
 * Units follow the Python reference exactly:
 *   angle   degrees BTDC, positive = advanced
 *   air     grams per cylinder per cycle
 *   fuel    grams
 *   torque  Nm
 *   press.  kPa absolute
 *   temp    kelvin
 *   time    microseconds (u32) for scheduling, seconds (f32) for physics
 */
#ifndef TQ_TYPES_H
#define TQ_TYPES_H

#include <stdbool.h>
#include <stdint.h>

typedef float f32;
typedef uint32_t u32;
typedef uint16_t u16;
typedef uint8_t u8;
typedef int32_t i32;
typedef int16_t i16;

#define TQ_MAX_CYL 8

/* One engine cycle. Everything angle-domain is modulo this. */
#define TQ_CYCLE_DEG 720.0f

/* A timestamp in microseconds since boot. Wraps every ~71 minutes, so
 * every comparison must be written as a signed difference, never as a
 * direct <. tq_after() is the only correct way to ask "is t past u". */
typedef u32 tq_time_t;

static inline bool tq_after(tq_time_t t, tq_time_t u)
{
    return (i32)(t - u) > 0;
}

static inline f32 tq_clampf(f32 v, f32 lo, f32 hi)
{
    return v < lo ? lo : (v > hi ? hi : v);
}

/* Angle arithmetic, always wrapped into [0, 720). */
static inline f32 tq_wrap_deg(f32 a)
{
    while (a >= TQ_CYCLE_DEG) a -= TQ_CYCLE_DEG;
    while (a < 0.0f) a += TQ_CYCLE_DEG;
    return a;
}

/* Shortest signed distance from a to b, in (-360, 360]. */
static inline f32 tq_angle_diff(f32 b, f32 a)
{
    f32 d = tq_wrap_deg(b - a);
    if (d > TQ_CYCLE_DEG * 0.5f) d -= TQ_CYCLE_DEG;
    return d;
}

#endif /* TQ_TYPES_H */
