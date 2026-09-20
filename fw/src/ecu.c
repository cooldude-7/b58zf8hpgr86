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
    van_config_t vcfg = vanos_config_default();
    vanos_init(&e->van, &vcfg);
    for (u8 i = 0; i < VAN_N_CAM; i++) {
        e->cam_target[i] = 0.0f;     /* park until a calibration says otherwise */
    }
    e->hpfp_sched = tq_hpfp_sched_default();
    tq_hpfp_init(&e->hpfp, e->hpfp_sched.lobes_per_cycle);
    /* A direct injector needs a current profile, not an on/off signal.
     * These are the driver's defaults; the tune overrides them. */
    e->inj_drive.boost_v = 65;
    e->inj_drive.peak_ma = 12000;
    e->inj_drive.peak_us = 400;
    e->inj_drive.hold_ma = 3500;
    e->inj_drive.recharge_us = 300;
    e->engine = tq_engine_default();
    e->injector = tq_injector_default();
    e->rev_limit = 7200.0f;
    e->overboost_kpa = 265.0f;
    e->max_cut_retard = 35.0f;
    e->engine_dwell_ms = 2.5f;
    e->split_gap_deg = 60.0f;
    e->sig.state = ECU_OFF;
    e->sig.lambda_target = 1.0f;
    e->sig.battery_v = 13.8f;
    e->sig.rail_kpa = 500.0f;
    e->sig.oil_kpa = 0.0f;
    e->sig.iat_k = 298.0f;
    e->sig.clt_k = 293.0f;
    e->sig.rail_target_kpa = 8000.0f;
    e->sig.soi_deg = 300.0f;
    e->sig.split_first = 0.0f;       /* single pulse until asked otherwise */
    e->sig.n_pulses = 1;
    for (u8 c = 0; c < e->sch.n_cyl; c++) {
        hal_inj_configure((hal_out_t)(HAL_OUT_INJ_1 + c), &e->inj_drive);
    }
}

void ecu_on_crank_edge(ecu_t *e, tq_time_t t)
{
    decoder_on_crank_edge(&e->dec, t);
    /* Re-arm immediately: waiting for the 1 ms task would put the arming
     * up to a millisecond late, which at 7000 rpm is 42 degrees. */
    sched_update(&e->sch, &e->dec, t);
    ecu_schedule_pump(e, t);
}

void ecu_schedule_pump(ecu_t *e, tq_time_t now_us)
{
    /* The pump valve is an angle-domain event like spark and injection,
     * not a PWM output: it has to close part way through a specific cam
     * lobe, so it needs phase just as much as the injectors do. */
    if (!e->hpfp.enabled || !decoder_has_phase(&e->dec)) {
        return;
    }
    if (hal_out_is_active(HAL_OUT_HPFP_MSV)) {
        return;
    }
    f32 now_angle = decoder_angle_at(&e->dec, now_us);
    f32 close_deg;
    /* The pump rides a triple cam on the EXHAUST camshaft (BMW's own
     * B46 text), and that camshaft is phased. So the pumping lobes move
     * with the phaser: advance the cam and every lobe arrives earlier by
     * the same amount. Aiming at a fixed angle would miss by up to half
     * a lobe span once VANOS starts working, which is a rail that does
     * not build pressure rather than an obvious fault. */
    tq_hpfp_sched_t sch = e->hpfp_sched;
    if (VAN_N_CAM > 1 && e->sig.cam_adv_valid[1]) {
        sch.first_lobe_deg = tq_wrap_deg(sch.first_lobe_deg - e->sig.cam_adv[1]);
    }
    if (!tq_hpfp_close_angle(&sch, e->hpfp.duty, now_angle, &close_deg)) {
        return;
    }
    f32 ahead = tq_wrap_deg(close_deg - now_angle);
    if (ahead > 60.0f) {
        return;                     /* not yet: arm it nearer the time */
    }
    tq_time_t at;
    if (!decoder_time_for_angle(&e->dec, now_us, close_deg, &at)) {
        return;
    }
    if (hal_out_schedule(HAL_OUT_HPFP_MSV, at,
                         at + e->hpfp_sched.valve_hold_us)) {
        e->sig.msv_events++;
    }
}

void ecu_on_cam_edge(ecu_t *e, u8 cam, tq_time_t t, bool rising)
{
    decoder_on_cam_edge(&e->dec, cam, t, rising);
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

    /* A sagging boost rail means the injectors are not opening properly
     * and the fuelling number above is fiction. */
    s->boost_low = hal_inj_boost_voltage() < (u16)(e->inj_drive.boost_v * 8 / 10);

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
    u32 total_pw = e->fuel_cut ? 0u : s->pw_us;
    for (u8 c = 0; c < e->sch.n_cyl; c++) {
        sched_set_spark(&e->sch, c, spark, (u32)(e->engine_dwell_ms * 1000.0f));
        if (s->n_pulses >= 2 && s->split_first > 0.01f && total_pw > 0) {
            /* Split the charge: a pilot early for mixing, the rest
             * behind it. The gap has to clear the injector's recharge
             * time or the second pulse will not open properly. */
            sched_pulse_t p[2];
            p[0].soi_deg = s->soi_deg;
            p[0].pw_us = (u32)((f32)total_pw * s->split_first);
            p[1].soi_deg = s->soi_deg - e->split_gap_deg;
            p[1].pw_us = total_pw - p[0].pw_us;
            if (!sched_set_pulses(&e->sch, c, p, 2)) {
                sched_set_injection(&e->sch, c, s->soi_deg, total_pw);
            }
        } else {
            sched_set_injection(&e->sch, c, s->soi_deg, total_pw);
        }
    }
}

void ecu_slow_task(ecu_t *e, f32 dt_s)
{
    ecu_signals_t *s = &e->sig;
    s->slow_cycles++;

    /* The pump only runs with the engine turning: spinning it against a
     * closed system with no injection is how a rail gets broken. */
    e->hpfp.enabled = (s->state == ECU_RUNNING || s->state == ECU_CRANKING);
    e->hpfp.target_kpa = s->rail_target_kpa;
    f32 demand = tq_fuel_mass(s->air_g, s->lambda_target, &e->engine)
                 * (f32)e->engine.n_cyl;
    tq_hpfp_update(&e->hpfp, dt_s, s->rail_kpa, demand);

    /* ---- cam phasing --------------------------------------------------- */
    tq_time_t now = hal_now_us();
    van_inputs_t vi;
    vi.dt = dt_s;
    vi.rpm = s->rpm;
    vi.oil_kpa = s->oil_kpa;
    /* Oil temperature is not measured. Coolant is the usual stand-in and
     * it is optimistic on a cold start, when the oil is still thick and
     * the phaser has least authority -- which is why the gate is on the
     * conservative side. A real oil temperature sensor or model replaces
     * this. */
    vi.oil_k = s->clt_k;
    vi.running = (s->state == ECU_RUNNING);
    vi.now_us = now;
    for (u8 i = 0; i < VAN_N_CAM; i++) {
        const dec_cam_pattern_t *cp = &e->dec.cfg.cam[i];
        f32 adv = 0.0f;
        u32 age = 0;
        bool ok = decoder_cam_advance(&e->dec, i, now, &adv, &age);
        vi.meas_valid[i] = ok;
        vi.meas_deg[i] = adv;
        vi.meas_age_us[i] = age;
        vi.target_deg[i] = e->cam_target[i];
        vi.null_sched[i] = 0.0f;
        vi.adv_min[i] = cp->adv_min_deg;
        vi.adv_max[i] = cp->adv_max_deg;
        /* Park sits at zero advance, so whichever end of the travel is
         * further from zero is the end the cam energizes towards. */
        vi.travel_dir[i] = (cp->adv_max_deg + cp->adv_min_deg >= 0.0f)
                         ? 1.0f : -1.0f;
        s->cam_adv[i] = adv;
        s->cam_adv_valid[i] = ok;
    }
    vanos_update(&e->van, &vi);
    for (u8 i = 0; i < VAN_N_CAM; i++) {
        s->vanos_fault[i] = e->van.cam[i].fault;
    }

    decoder_check_timeout(&e->dec, now);
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
