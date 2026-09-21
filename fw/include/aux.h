/* The unglamorous outputs that turn an engine into a car.
 *
 * None of this is clever and all of it is necessary. One of them is a
 * safety function rather than a convenience: the fuel pump must stop
 * promptly when the engine loses sync, because a pump running into a
 * broken line after a crash is exactly the failure that rule prevents.
 */
#ifndef TQ_AUX_H
#define TQ_AUX_H

#include "tq_types.h"

typedef struct {
    f32 prime_s;             /* pump run at key-on, to fill the rail */
    f32 pump_sync_grace_s;   /* how long sync may be absent before cutting */

    f32 fan_on_k, fan_off_k; /* hysteresis, or it chatters at the threshold */
    f32 fan_runon_s;         /* after shutdown on a hot engine */

    f32 tacho_pulses_per_rev; /* what the cluster expects */
} aux_config_t;

typedef struct {
    bool pump, fan, mil;
    f32 tacho_hz;
    f32 prime_t;
    f32 nosync_t;
    f32 runon_t;
    bool primed;
} aux_t;

typedef struct {
    f32 dt;
    f32 rpm;
    f32 clt_k;
    bool has_sync;
    bool running;
    bool faulted;            /* anything worth lighting the lamp for */
} aux_in_t;

aux_config_t aux_config_default(void);
void aux_init(aux_t *a);
void aux_update(aux_t *a, const aux_config_t *cfg, const aux_in_t *in);

#endif /* TQ_AUX_H */
