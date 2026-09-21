/* ADC counts to physical units.
 *
 * Until this existed, every "measured" signal in the ECU was written by
 * a test and by nothing else: hal_adc_read() was declared and never
 * called, so on real hardware the torque model would have run on zeros
 * and the Level 2 monitor would have watched two pedals agreeing
 * perfectly at 0 % forever.
 *
 * Three jobs, and the third is the one that matters on a car:
 *
 *   1. Convert. Counts to volts to kPa, kelvin, lambda, percent.
 *   2. Filter. A raw ADC sample has noise a control loop should not see,
 *      and a first-order filter is enough as long as its time constant is
 *      chosen against what the signal actually does. MAP moves in
 *      milliseconds and coolant in minutes; one filter for both is wrong
 *      for one of them.
 *   3. Decide whether to believe it. A sensor that has failed is more
 *      dangerous than one that is merely noisy, because the control path
 *      cannot tell the difference between "the engine is cold" and "the
 *      coolant sensor is open circuit". Every channel carries a
 *      plausibility range and a fallback, and says which it is using.
 */
#ifndef TQ_SENSORS_H
#define TQ_SENSORS_H

#include "hal.h"
#include "tq_types.h"

typedef enum {
    SENS_LINEAR = 0,   /* value = scale * volts + offset */
    SENS_NTC,          /* thermistor over a pull-up, Steinhart-Hart */
    SENS_UNUSED
} sens_kind_t;

typedef struct {
    sens_kind_t kind;
    f32 scale, offset;      /* SENS_LINEAR */
    f32 pullup_ohm;         /* SENS_NTC */
    f32 sh_a, sh_b, sh_c;   /* SENS_NTC: Steinhart-Hart coefficients */

    /* Plausibility, in PHYSICAL units. A value outside this for longer
     * than fault_s means the sensor, not the engine. */
    f32 lo, hi;
    f32 fallback;           /* what to use while it is faulted */
    f32 tau_s;              /* filter time constant, 0 for none */
} sens_cfg_t;

typedef struct {
    f32 value;              /* filtered, in physical units */
    f32 raw;                /* converted but unfiltered */
    bool valid;             /* false = serving the fallback */
    f32 t_bad;              /* how long it has been implausible */
} sens_chan_t;

typedef struct {
    f32 vref;               /* ADC reference, volts */
    u16 counts_full;        /* full-scale reading, 4095 for 12-bit */
    f32 fault_s;            /* debounce before a channel is disbelieved */
    sens_cfg_t cfg[HAL_ADC_COUNT];
} sens_config_t;

typedef struct {
    sens_config_t cfg;
    sens_chan_t ch[HAL_ADC_COUNT];
    u16 fault_mask;         /* one bit per faulted channel */
} sensors_t;

sens_config_t sensors_config_default(void);
void sensors_init(sensors_t *s, const sens_config_t *cfg);

/* Read every channel from the HAL and update. Called from the 1 ms task:
 * the ADC is DMA'd at 1 kHz, so reading faster gains nothing and reading
 * slower makes the pedal feel laggy. */
void sensors_update(sensors_t *s, f32 dt_s);

f32 sensors_value(const sensors_t *s, hal_adc_t ch);
bool sensors_ok(const sensors_t *s, hal_adc_t ch);

/* The inverse: what ADC reading corresponds to this physical value.
 *
 * For tests and for a bench simulator, so a harness can say "the coolant
 * is at 90 C" and have the real conversion path run rather than reaching
 * past it to write the signal directly. A test that skips the conversion
 * is a test that cannot catch a wrong conversion. */
u16 sensors_counts_for(const sens_config_t *cfg, hal_adc_t ch, f32 value);

#endif /* TQ_SENSORS_H */
