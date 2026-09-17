#include "ecu.h"

#include "hal.h"

void ecu_init(ecu_t *e)
{
    for (u32 i = 0; i < sizeof(*e); i++) {
        ((u8 *)e)[i] = 0;
    }
    dec_config_t cfg = decoder_config_b48();
    decoder_init(&e->dec, &cfg);
    sched_init(&e->sch, 4);
    sched_set_tdc(&e->sch, 0, 0.0f);       /* inline four, 1-3-4-2 */
    sched_set_tdc(&e->sch, 1, 180.0f);
    sched_set_tdc(&e->sch, 2, 360.0f);
    sched_set_tdc(&e->sch, 3, 540.0f);
    tq_monitor_reset(&e->mon);
    tq_hpfp_init(&e->hpfp, 3.0f);
    e->engine = tq_engine_default();
    e->injector = tq_injector_default();
    e->rev_limit = 7200.0f;
    e->overboost_kpa = 265.0f;
    e->max_cut_retard = 35.0f;
    e->sig.state = ECU_OFF;
    e->sig.lambda_target = 1.0f;
    e->sig.battery_v = 13.8f;
    e->sig.rail_kpa = 500.0f;
    e->sig.iat_k = 298.0f;
    e->sig.clt_k = 293.0f;
}

void ecu_on_crank_edge(ecu_t *e, tq_time_t t)
{
    decoder_on_crank_edge(&e->dec, t);
    /* Re-arm immediately: waiting for the 1 ms task would put the arming
     * up to a millisecond late, which at 7000 rpm is 42 degrees. */
    sched_update(&e->sch, &e->dec, t);
}

void ecu_on_cam_edge(ecu_t *e, tq_time_t t)
{
    decoder_on_cam_edge(&e->dec, t);
}

static void apply_cuts(ecu_t *e)
{
    /* Fuel is the fast cut and the safe one. Spark is only ever cut with
     * fuel already off, because cutting spark alone pumps raw fuel into
     * the exhaust and lights it there. */
    sched_enable_fuel(&e->sch, !e->fuel_cut);
    sched_enable_spark(&e->sch, !(e->spark_cut && e->fuel_cut));
}

void ecu_fast_task(ecu_t *e, f32 dt_s)
{
    ecu_signals_t *s = &e->sig;
    s->fast_cycles++;
    s->rpm = decoder_rpm(&e->dec);

    /* ---- state machine ------------------------------------------------ */
    if (!decoder_has_phase(&e->dec)) {
        s->state = (s->rpm > 50.0f) ? ECU_CRANKING : ECU_OFF;
    } else if (e->mon.limp >= MON_IDLE_ONLY) {
        s->state = ECU_LIMP;
    } else {
        s->state = (s->rpm > 400.0f) ? ECU_RUNNING : ECU_CRANKING;
    }

    /* ---- torque structure --------------------------------------------- */
    s->air_g = tq_air_mass(s->ve, s->map_kpa, s->iat_k + 15.0f, &e->engine);
    f32 spark = s->spark_deg;
    if (spark > s->knock_limit_deg) {
        spark = s->knock_limit_deg;       /* the knock limit is not advisory */
    }
    if (spark < s->mbt_deg - e->max_cut_retard) {
        spark = s->mbt_deg - e->max_cut_retard;
    }
    s->spark_deg = spark;

    s->torque_estimate = tq_brake_torque(s->ve, s->map_kpa, s->iat_k + 15.0f,
                                         s->rpm, spark, s->mbt_deg,
                                         s->lambda_meas, &e->engine);
    s->torque_authority = tq_authority(s->ve, s->map_kpa, s->iat_k + 15.0f,
                                       s->rpm, spark, s->mbt_deg,
                                       s->lambda_meas, &e->engine);

    /* ---- fuel ---------------------------------------------------------- */
    f32 fuel_g = tq_fuel_mass(s->air_g, s->lambda_target, &e->engine);
    s->pw_us = tq_pulse_width_us(fuel_g, s->rail_kpa, s->map_kpa,
                                 s->battery_v, &e->injector);

    /* ---- hard limits --------------------------------------------------- */
    e->fuel_cut = (s->rpm > e->rev_limit) || (s->map_kpa > e->overboost_kpa);
    e->spark_cut = false;

    /* ---- Level 2 ------------------------------------------------------- */
    /* Run last, on what was actually commanded, and let its verdict
     * override everything above. */
    mon_inputs_t in;
    in.dt = dt_s;
    in.pedal_a = s->pedal_a;
    in.pedal_b = s->pedal_b;
    in.tps_a = s->tps_a;
    in.tps_b = s->tps_b;
    in.tps_cmd = s->tps_cmd;
    in.torque = s->torque_estimate;
    in.rpm = s->rpm;
    in.max_torque = s->torque_request > 1.0f ? s->torque_request : 400.0f;
    in.rev_limit = e->rev_limit;
    in.map_kpa = s->map_kpa;
    in.overboost_kpa = e->overboost_kpa;
    mon_limp_t limp = tq_monitor_update(&e->mon, &in);

    if (limp == MON_SHUTDOWN) {
        e->fuel_cut = true;
        hal_throttle_disable();
    } else if (limp >= MON_IDLE_ONLY) {
        hal_throttle_disable();
    }

    apply_cuts(e);

    /* ---- hand the scheduler its numbers -------------------------------- */
    for (u8 c = 0; c < e->sch.n_cyl; c++) {
        sched_set_spark(&e->sch, c, spark, 2500);
        sched_set_injection(&e->sch, c, 300.0f, e->fuel_cut ? 0u : s->pw_us);
    }
}

void ecu_slow_task(ecu_t *e, f32 dt_s)
{
    ecu_signals_t *s = &e->sig;
    s->slow_cycles++;

    /* The pump only runs with the engine turning: spinning it against a
     * closed system with no injection is how a rail gets broken. */
    e->hpfp.enabled = (s->state == ECU_RUNNING || s->state == ECU_CRANKING);
    f32 demand = tq_fuel_mass(s->air_g, s->lambda_target, &e->engine)
                 * (f32)e->engine.n_cyl;
    tq_hpfp_update(&e->hpfp, dt_s, s->rail_kpa, demand);

    decoder_check_timeout(&e->dec, hal_now_us());
    if (!decoder_has_phase(&e->dec)) {
        sched_all_off(&e->sch);
    }
}

void ecu_diag_task(ecu_t *e, f32 dt_s)
{
    (void)dt_s;
    /* Level 3: the watchdog is only kicked while the fast task is
     * demonstrably still running. A fast task that has stopped is the
     * failure the watchdog exists for, and kicking unconditionally here
     * would hide exactly that. */
    static u32 last_fast;
    if (e->sig.fast_cycles != last_fast) {
        last_fast = e->sig.fast_cycles;
        hal_watchdog_kick();
    }
}
