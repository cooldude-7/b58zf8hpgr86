#include "sensors.h"

#include <math.h>

static f32 absf(f32 v) { return v < 0.0f ? -v : v; }

/* Automotive sensors are 5 V ratiometric; this ADC reference is 3.3 V.
 * They therefore arrive through a divider, and every scale factor below
 * is expressed in ADC volts, not sensor volts.
 *
 * Getting this wrong is quiet and nasty rather than loud. Writing the
 * data-sheet scale directly makes full scale read 216 kPa on a 300 kPa
 * MAP sensor -- so the top third of the range is unreachable, AND the
 * plausibility ceiling can never be crossed, so a stuck-high sensor
 * reads as believable boost forever instead of faulting. */
#define V5_DIV (5.0f / 3.3f)

sens_config_t sensors_config_default(void)
{
    /* PROVISIONAL, like every other number that has not met a real
     * sensor. Each of these comes from a data sheet and then from a
     * two-point check against a known reference -- a pressure gauge, a
     * pot of boiling water -- because sensor tolerance is wide enough to
     * matter and a 5 kPa MAP offset is a fuelling error everywhere. */
    sens_config_t c;
    for (u32 i = 0; i < sizeof(c); i++) {
        ((u8 *)&c)[i] = 0;
    }
    c.vref = 3.3f;
    c.counts_full = 4095u;
    c.fault_s = 0.25f;

    /* Pedal and throttle position: ratiometric 0.5..4.5 V over 0..100 %.
     * The second of each pair is deliberately INVERTED on a real car, so
     * a shorted wire cannot make both read the same wrong thing -- that
     * is the entire point of having two. */
    for (u32 i = 0; i < 4; i++) {
        c.cfg[i].kind = SENS_LINEAR;
        c.cfg[i].scale = 25.0f * V5_DIV;
        c.cfg[i].offset = -12.5f;
        c.cfg[i].lo = -8.0f;
        c.cfg[i].hi = 108.0f;
        c.cfg[i].fallback = 0.0f;    /* a failed pedal means closed */
        c.cfg[i].tau_s = 0.010f;
    }

    /* MAP: 0.5..4.5 V over 20..300 kPa absolute. Fast, because the
     * manifold empties in tens of milliseconds and the fuel calculation
     * follows it. */
    c.cfg[HAL_ADC_MAP].kind = SENS_LINEAR;
    c.cfg[HAL_ADC_MAP].scale = 70.0f * V5_DIV;
    c.cfg[HAL_ADC_MAP].offset = -15.0f;
    c.cfg[HAL_ADC_MAP].lo = 10.0f;
    c.cfg[HAL_ADC_MAP].hi = 320.0f;
    c.cfg[HAL_ADC_MAP].fallback = 101.3f;   /* atmospheric: limp, not lean */
    c.cfg[HAL_ADC_MAP].tau_s = 0.005f;

    /* Intake air and coolant: NTC thermistors over a 2.2k pull-up.
     * Coolant is heavily filtered because it physically cannot change
     * quickly, so anything fast on that line is noise. */
    for (u32 k = 0; k < 2; k++) {
        hal_adc_t ch = (k == 0) ? HAL_ADC_IAT : HAL_ADC_CLT;
        c.cfg[ch].kind = SENS_NTC;
        c.cfg[ch].pullup_ohm = 2200.0f;
        c.cfg[ch].sh_a = 1.2874e-3f;
        c.cfg[ch].sh_b = 2.3573e-4f;
        c.cfg[ch].sh_c = 9.5027e-8f;
        c.cfg[ch].lo = 223.0f;               /* -50 C */
        c.cfg[ch].hi = 423.0f;               /* +150 C */
        c.cfg[ch].fallback = (k == 0) ? 298.0f : 363.0f;
        c.cfg[ch].tau_s = (k == 0) ? 0.5f : 2.0f;
    }
    /* A failed coolant sensor falls back to HOT, not cold. Cold would
     * command warmup enrichment forever and wash the bores. */

    /* Wideband lambda controller: 0..5 V linear over 0.68..1.36 lambda,
     * scaled for a 3.3 V input divider. */
    c.cfg[HAL_ADC_LAMBDA].kind = SENS_LINEAR;
    c.cfg[HAL_ADC_LAMBDA].scale = 0.136f * V5_DIV;
    c.cfg[HAL_ADC_LAMBDA].offset = 0.68f;
    c.cfg[HAL_ADC_LAMBDA].lo = 0.5f;
    c.cfg[HAL_ADC_LAMBDA].hi = 1.6f;
    c.cfg[HAL_ADC_LAMBDA].fallback = 1.0f;
    c.cfg[HAL_ADC_LAMBDA].tau_s = 0.020f;

    /* Fuel rail pressure, direct injection: 0.5..4.5 V over 0..20 MPa. */
    c.cfg[HAL_ADC_RAIL_PRESSURE].kind = SENS_LINEAR;
    c.cfg[HAL_ADC_RAIL_PRESSURE].scale = 5000.0f * V5_DIV;
    c.cfg[HAL_ADC_RAIL_PRESSURE].offset = -2500.0f;
    c.cfg[HAL_ADC_RAIL_PRESSURE].lo = -500.0f;
    c.cfg[HAL_ADC_RAIL_PRESSURE].hi = 21000.0f;
    c.cfg[HAL_ADC_RAIL_PRESSURE].fallback = 0.0f;
    c.cfg[HAL_ADC_RAIL_PRESSURE].tau_s = 0.010f;

    /* Battery, through a divider. */
    c.cfg[HAL_ADC_BATTERY].kind = SENS_LINEAR;
    c.cfg[HAL_ADC_BATTERY].scale = 6.0f;
    c.cfg[HAL_ADC_BATTERY].offset = 0.0f;
    c.cfg[HAL_ADC_BATTERY].lo = 4.0f;
    c.cfg[HAL_ADC_BATTERY].hi = 18.0f;
    c.cfg[HAL_ADC_BATTERY].fallback = 13.8f;
    c.cfg[HAL_ADC_BATTERY].tau_s = 0.100f;

    /* Oil pressure: 0.5..4.5 V over 0..1000 kPa. The cam phaser gate
     * reads this, and a phaser with no oil has no authority. */
    c.cfg[HAL_ADC_OIL_PRESSURE].kind = SENS_LINEAR;
    c.cfg[HAL_ADC_OIL_PRESSURE].scale = 250.0f * V5_DIV;
    c.cfg[HAL_ADC_OIL_PRESSURE].offset = -125.0f;
    c.cfg[HAL_ADC_OIL_PRESSURE].lo = -50.0f;
    c.cfg[HAL_ADC_OIL_PRESSURE].hi = 1100.0f;
    c.cfg[HAL_ADC_OIL_PRESSURE].fallback = 0.0f;   /* no oil: gate closed */
    c.cfg[HAL_ADC_OIL_PRESSURE].tau_s = 0.050f;

    /* Wastegate position feedback, 0..100 % of travel. */
    c.cfg[HAL_ADC_WASTEGATE_POS].kind = SENS_LINEAR;
    c.cfg[HAL_ADC_WASTEGATE_POS].scale = 25.0f * V5_DIV;
    c.cfg[HAL_ADC_WASTEGATE_POS].offset = -12.5f;
    c.cfg[HAL_ADC_WASTEGATE_POS].lo = -8.0f;
    c.cfg[HAL_ADC_WASTEGATE_POS].hi = 108.0f;
    c.cfg[HAL_ADC_WASTEGATE_POS].fallback = 100.0f;  /* fail wide open */
    c.cfg[HAL_ADC_WASTEGATE_POS].tau_s = 0.020f;

    /* Knock is NOT converted here. It needs its own high-rate sampling
     * window in the angle domain; one sample per millisecond off the
     * regular sequence is an alias, not a measurement. */
    c.cfg[HAL_ADC_KNOCK].kind = SENS_UNUSED;
    return c;
}

void sensors_init(sensors_t *s, const sens_config_t *cfg)
{
    for (u32 i = 0; i < sizeof(*s); i++) {
        ((u8 *)s)[i] = 0;
    }
    s->cfg = *cfg;
    for (u32 i = 0; i < HAL_ADC_COUNT; i++) {
        /* Start at the fallback rather than at zero. Zero kelvin and zero
         * kPa are not neutral values -- the first tick would run the
         * torque model on them. */
        s->ch[i].value = cfg->cfg[i].fallback;
        s->ch[i].raw = cfg->cfg[i].fallback;
        s->ch[i].valid = true;
    }
}

static f32 counts_to_volts(const sens_config_t *c, u16 counts)
{
    if (c->counts_full == 0u) return 0.0f;
    return (f32)counts * c->vref / (f32)c->counts_full;
}

/* Thermistor over a pull-up to vref: the divider gives the resistance,
 * and Steinhart-Hart gives the temperature. Guarded at both ends, since
 * an open circuit reads vref and a short reads zero, and both would
 * otherwise divide by zero or take the log of a negative. */
static f32 ntc_kelvin(const sens_cfg_t *c, f32 v, f32 vref)
{
    /* An impossible divider reading must return an IMPLAUSIBLE
     * temperature, not the fallback. Returning the fallback here would
     * hand the plausibility check a believable number, so a shorted or
     * open sensor would read as a healthy engine at the fallback
     * temperature forever and never raise a fault -- the fallback
     * silently becoming the measurement. Point it out of range in the
     * direction the physics implies and let the check do its job. */
    f32 head = vref - v;
    if (head <= 0.001f) {
        return c->lo - 100.0f;      /* open circuit: infinite R, "freezing" */
    }
    if (v <= 0.001f) {
        return c->hi + 100.0f;      /* short to ground: zero R, "glowing" */
    }
    f32 r = c->pullup_ohm * v / head;
    if (r <= 1.0f) {
        return c->hi + 100.0f;
    }
    f32 ln_r = logf(r);
    f32 inv_t = c->sh_a + c->sh_b * ln_r + c->sh_c * ln_r * ln_r * ln_r;
    if (absf(inv_t) < 1e-9f) {
        return c->lo - 100.0f;
    }
    return 1.0f / inv_t;
}

void sensors_update(sensors_t *s, f32 dt_s)
{
    for (u32 i = 0; i < HAL_ADC_COUNT; i++) {
        const sens_cfg_t *c = &s->cfg.cfg[i];
        sens_chan_t *ch = &s->ch[i];
        if (c->kind == SENS_UNUSED) {
            continue;
        }

        f32 v = counts_to_volts(&s->cfg, hal_adc_read((hal_adc_t)i));
        f32 phys = (c->kind == SENS_NTC)
                 ? ntc_kelvin(c, v, s->cfg.vref)
                 : c->scale * v + c->offset;
        ch->raw = phys;

        /* Plausibility, debounced. A single sample outside the range is
         * a spike; a quarter second outside it is a wiring fault. */
        bool bad = (phys < c->lo) || (phys > c->hi);
        ch->t_bad = bad ? ch->t_bad + dt_s : 0.0f;
        bool faulted = ch->t_bad > s->cfg.fault_s;

        if (faulted) {
            ch->valid = false;
            ch->value = c->fallback;
            s->fault_mask |= (u16)(1u << i);
            continue;
        }
        /* Recovering from a fault clears the bit: a sensor that comes
         * back is believed again, unlike a jumped timing chain. A loose
         * connector that reseats itself is a real and common thing. */
        ch->valid = true;
        s->fault_mask &= (u16)~(1u << i);

        if (c->tau_s > 1e-6f && dt_s > 0.0f) {
            f32 k = dt_s / c->tau_s;
            if (k > 1.0f) k = 1.0f;
            ch->value += (phys - ch->value) * k;
        } else {
            ch->value = phys;
        }
    }
}

f32 sensors_value(const sensors_t *s, hal_adc_t ch)
{
    return ch < HAL_ADC_COUNT ? s->ch[ch].value : 0.0f;
}

bool sensors_ok(const sensors_t *s, hal_adc_t ch)
{
    return ch < HAL_ADC_COUNT && s->ch[ch].valid;
}

u16 sensors_counts_for(const sens_config_t *cfg, hal_adc_t ch, f32 value)
{
    if (ch >= HAL_ADC_COUNT) return 0u;
    const sens_cfg_t *c = &cfg->cfg[ch];
    f32 v;

    if (c->kind == SENS_NTC) {
        /* Invert Steinhart-Hart for resistance, then the divider for
         * voltage. The polynomial is cubic in ln(R), so rather than the
         * closed form, iterate -- this is a bench helper, not an ISR. */
        f32 target = 1.0f / ((value > 1.0f) ? value : 1.0f);
        f32 ln_r = 9.0f;                     /* ~8 kohm, a sane start */
        for (u32 it = 0; it < 40u; it++) {
            f32 f = c->sh_a + c->sh_b * ln_r + c->sh_c * ln_r * ln_r * ln_r
                  - target;
            f32 df = c->sh_b + 3.0f * c->sh_c * ln_r * ln_r;
            if (absf(df) < 1e-12f) break;
            f32 step = f / df;
            ln_r -= step;
            if (absf(step) < 1e-7f) break;
        }
        f32 r = expf(ln_r);
        v = cfg->vref * r / (r + c->pullup_ohm);
    } else {
        if (absf(c->scale) < 1e-9f) return 0u;
        v = (value - c->offset) / c->scale;
    }

    f32 counts = v * (f32)cfg->counts_full / cfg->vref;
    if (counts < 0.0f) counts = 0.0f;
    if (counts > (f32)cfg->counts_full) counts = (f32)cfg->counts_full;
    return (u16)(counts + 0.5f);
}
