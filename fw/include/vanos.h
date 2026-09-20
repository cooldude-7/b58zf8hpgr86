/* Cam phaser (VANOS) closed-loop control.
 *
 * The plant is an INTEGRATOR. An oil control valve does not command where
 * the cam sits; it commands which way and how fast the cam travels. Feed
 * it a position error through a proportional gain and the closed loop is
 * already first order and settles with no steady-state error -- provided
 * the duty that holds the cam still is known exactly. It is not, it
 * drifts with oil temperature and pressure and cam torque, so it is
 * scheduled and then learned.
 *
 * So the holding duty is an integrator on position error. Two rules that
 * look reasonable and are not: learning "while the error is small" can
 * never start, because the error only goes small once the holding duty
 * is already right; and learning "only while the cam is stationary"
 * deadlocks, because a badly wrong estimate drives the cam to a rail
 * where the locking pin holds it still and the gate then refuses to
 * learn exactly when the estimate is worst. Integrate always, clamp, and
 * stop integrating into a rail.
 *
 * What this module deliberately does NOT do:
 *   - It never writes the ECU state machine. A phaser has no business
 *     deciding the engine is in limp: ECU_LIMP would switch off the high
 *     pressure pump (see ecu_slow_task) and a cam that cannot find its
 *     target is not a reason to stop fuelling.
 *   - It never feeds the Level 2 monitor a de-rated torque ceiling.
 *     Shrinking the monitor's permissible torque while the torque
 *     estimate is unchanged trips it within its debounce, and the limp
 *     it raises latches until the key is cycled. That is an
 *     engine-disabling reaction dressed up as a mild one.
 * It reports a fault and parks. Deciding what that means is the ECU's.
 */
#ifndef TQ_VANOS_H
#define TQ_VANOS_H

#include "hal.h"
#include "tq_types.h"

#define VAN_N_CAM HAL_CAM_COUNT

typedef enum {
    VAN_OFF = 0,        /* gated out: de-energized, parked on the lock pin */
    VAN_CLOSED_LOOP,
    VAN_FAULT           /* parked, and refusing to try again this key cycle */
} van_state_t;

enum {
    VAN_F_NONE = 0,
    VAN_F_NOT_REACHED = 1,   /* commanded, oil present, did not arrive */
    VAN_F_RUNAWAY = 2        /* moved the opposite way to the command */
};

typedef struct {
    /* Plant gain: crank degrees per second per unit of duty away from the
     * holding duty. Measured on a bench, not guessed -- this one is a
     * placeholder sized so the loop is slow rather than lively. */
    f32 kv_deg_s;
    f32 kp;                  /* duty per crank degree of error */
    /* Damping on the rate. On a pure integrator with a clean measurement
     * P alone is already first order, so this buys nothing and costs
     * bandwidth: closed-loop tau is (1 + kv*kd)/(kv*kp). It exists only
     * because this measurement is averaged over a cam pattern and
     * therefore lags, and lag plus high gain oscillates. Default zero. */
    f32 kd;

    /* Integral gain on position error, in duty per (crank degree second).
     * This is what finds the holding duty. Sized against kp for a damping
     * ratio near 1: the closed loop is lambda^2 + kv*kp*lambda + kv*ki. */
    f32 ki;
    f32 null_seed;           /* holding duty before anything is learned */
    f32 stationary_dps;      /* |rate| under this counts as "not moving" */

    /* Gates. A phaser has no authority without oil. */
    f32 min_oil_kpa;
    f32 min_oil_k;
    f32 min_rpm;
    u32 stale_limit_us;      /* a measurement older than this is no use */

    f32 fault_err_deg;       /* commanded but not reached, by this much... */
    f32 fault_time_s;        /* ...for this long */
} van_config_t;

van_config_t vanos_config_default(void);

typedef struct {
    van_state_t state;
    u8 fault;
    f32 target_deg;          /* clamped command, crank degrees */
    f32 meas_deg;
    f32 rate_deg_s;
    f32 null_duty;           /* the learned holding duty */
    f32 duty;                /* what was commanded this tick */
    f32 t_err;               /* how long the error has been unacceptable */
    bool have_meas;
    tq_time_t last_stamp;
} van_cam_t;

typedef struct {
    van_config_t cfg;
    van_cam_t cam[VAN_N_CAM];
} vanos_t;

typedef struct {
    f32 dt;
    f32 rpm;
    f32 oil_kpa;
    f32 oil_k;
    bool running;

    f32 target_deg[VAN_N_CAM];   /* what the calibration wants */
    f32 null_sched[VAN_N_CAM];   /* scheduled holding duty, before learning */

    bool meas_valid[VAN_N_CAM];
    f32 meas_deg[VAN_N_CAM];
    u32 meas_age_us[VAN_N_CAM];

    /* Mechanical travel, signed, from the decoder's cam patterns. Intake
     * runs 0..+N and exhaust -N..0, so these are not symmetric. */
    f32 adv_min[VAN_N_CAM];
    f32 adv_max[VAN_N_CAM];

    /* Which way energizing the valve moves this cam: +1 if duty above the
     * holding duty ADVANCES it, -1 if it RETARDS it.
     *
     * This is not a sign convention, it is the hardware. Both BMW cams
     * energize to move AWAY FROM PARK, but they park at opposite ends:
     * the intake parks fully retarded and advances, the exhaust parks
     * fully advanced and retards. Assume one sign for both and the
     * exhaust loop drives the valve to zero, the locking pin holds the
     * cam, and it never moves again. */
    f32 travel_dir[VAN_N_CAM];

    tq_time_t now_us;
} van_inputs_t;

void vanos_init(vanos_t *v, const van_config_t *cfg);
void vanos_update(vanos_t *v, const van_inputs_t *in);

/* True when this cam's position is currently trustworthy enough to act
 * on. A cam that has never been measured reads false, which callers must
 * treat as "no information", not as "faulty". */
bool vanos_position_known(const vanos_t *v, u8 cam);

#endif /* TQ_VANOS_H */
