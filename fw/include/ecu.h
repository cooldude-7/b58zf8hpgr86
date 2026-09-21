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
#include "enrich.h"
#include "lambda.h"
#include "sensors.h"
#include "throttle.h"
#include "torque.h"
#include "vanos.h"

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
    f32 oil_kpa;
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
    /* cam phasing. cam_adv is the MEASURED advance in crank degrees;
     * cam_adv_valid says whether it means anything, because a phaser
     * loop must not integrate against a frozen number. vanos_fault is
     * reported, never acted on here: a cam that cannot find its target
     * is not a reason to stop fuelling the engine. */
    f32 enrich_mult;         /* cranking x after-start x warmup x accel */
    f32 lambda_trim;         /* long term x short term */
    bool decel_cut;
    bool lambda_closed;
    f32 map_target_kpa;      /* what the torque path asked the air for */
    f32 idle_target_rpm;
    u16 sensor_faults;
    f32 cam_adv[VAN_N_CAM];
    bool cam_adv_valid[VAN_N_CAM];
    u8 vanos_fault[VAN_N_CAM];
    /* state */
    ecu_state_t state;
    u32 fast_cycles, slow_cycles;
} ecu_signals_t;

typedef struct {
    decoder_t dec;
    sched_t sch;
    tq_monitor_t mon;
    vanos_t van;
    sensors_t sens;
    tq_coord_t coord;
    tq_coord_config_t coord_cfg;
    throttle_t thr;
    thr_config_t thr_cfg;
    enrich_t enr;
    enr_config_t enr_cfg;
    lambda_t lam;
    lam_config_t lam_cfg;
    f32 cam_target[VAN_N_CAM];   /* commanded advance; a cal table later */
    tq_hpfp_t hpfp;
    tq_hpfp_sched_t hpfp_sched;
    hal_inj_drive_t inj_drive;
    tq_engine_t engine;
    tq_injector_t injector;
    tq_dwell_t dwell;
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
void ecu_on_cam_edge(ecu_t *e, u8 cam, tq_time_t t, bool rising);

void ecu_schedule_pump(ecu_t *e, tq_time_t now_us);
void ecu_fast_task(ecu_t *e, f32 dt_s);     /* 1 ms */
void ecu_slow_task(ecu_t *e, f32 dt_s);     /* 10 ms */
void ecu_diag_task(ecu_t *e, f32 dt_s);     /* 100 ms */

#endif /* TQ_ECU_H */
