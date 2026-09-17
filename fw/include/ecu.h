/* The ECU: task structure and the order things happen in.
 *
 * Four rates, chosen by what the physics demands rather than by taste:
 *
 *   crank ISR   every tooth      decode, then re-arm spark and injection.
 *                                Nothing slow may ever run here.
 *   fast task   1 ms             torque structure, spark, the Level 2
 *                                monitor. Fast enough that the driver
 *                                cannot feel the delay.
 *   slow task   10 ms            air path, throttle control, fuel
 *                                trims, pump target.
 *   diag task   100 ms           faults, logging, CAN housekeeping.
 *
 * The fast task runs the monitor AFTER the torque structure, so it judges
 * what was actually commanded, and the monitor's verdict is applied
 * before any of it reaches an actuator.
 */
#ifndef TQ_ECU_H
#define TQ_ECU_H

#include "decoder.h"
#include "fuel.h"
#include "model.h"
#include "monitor.h"
#include "sched.h"

typedef enum {
    ECU_OFF = 0,
    ECU_CRANKING,
    ECU_RUNNING,
    ECU_LIMP,
    ECU_STOPPING
} ecu_state_t;

typedef struct {
    /* measured */
    f32 rpm, map_kpa, iat_k, clt_k, battery_v, rail_kpa, lambda_meas;
    f32 pedal_a, pedal_b, tps_a, tps_b;
    /* commanded */
    f32 tps_cmd, spark_deg, mbt_deg, knock_limit_deg, lambda_target;
    /* direct injection */
    f32 rail_target_kpa, soi_deg, split_first;   /* split: fraction in pulse 1 */
    u8 n_pulses;
    u32 msv_events;
    bool boost_low;                              /* injector supply sagging */
    f32 torque_request, torque_estimate, torque_authority;
    f32 air_g, ve;
    u32 pw_us;
    /* state */
    ecu_state_t state;
    u32 fast_cycles, slow_cycles;
} ecu_signals_t;

typedef struct {
    decoder_t dec;
    sched_t sch;
    tq_monitor_t mon;
    tq_hpfp_t hpfp;
    tq_hpfp_sched_t hpfp_sched;
    hal_inj_drive_t inj_drive;
    tq_engine_t engine;
    tq_injector_t injector;
    ecu_signals_t sig;
    f32 rev_limit;
    f32 overboost_kpa;
    f32 max_cut_retard;
    f32 engine_dwell_ms;
    f32 split_gap_deg;       /* crank degrees between split injection pulses */
    bool fuel_cut;
    bool spark_cut;
} ecu_t;

void ecu_init(ecu_t *e);

/* Called from the crank input-capture ISR. Keep it short. */
void ecu_on_crank_edge(ecu_t *e, tq_time_t t);
void ecu_on_cam_edge(ecu_t *e, tq_time_t t);

void ecu_schedule_pump(ecu_t *e, tq_time_t now_us);
void ecu_fast_task(ecu_t *e, f32 dt_s);     /* 1 ms */
void ecu_slow_task(ecu_t *e, f32 dt_s);     /* 10 ms */
void ecu_diag_task(ecu_t *e, f32 dt_s);     /* 100 ms */

#endif /* TQ_ECU_H */
