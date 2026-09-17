/* Test hooks for the host HAL. Only tests include this. */
#ifndef HAL_HOST_H
#define HAL_HOST_H

#include "hal.h"

#define HAL_HOST_MAX_EVENTS 4096

typedef struct {
    hal_out_t ch;
    bool rising;
    tq_time_t t;
} hal_event_t;

extern hal_event_t hal_host_events[HAL_HOST_MAX_EVENTS];
extern u32 hal_host_event_count;

void hal_host_reset(void);
void hal_host_advance_to(tq_time_t t);
void hal_host_crank_edge(tq_time_t t);
void hal_host_cam_edge(tq_time_t t);
void hal_host_set_adc(hal_adc_t ch, u16 counts);
f32 hal_host_throttle(void);
bool hal_host_throttle_enabled(void);
u32 hal_host_watchdog_kicks(void);
bool hal_host_watchdog_tripped(void);
void hal_host_set_boost_voltage(u16 v);
const hal_inj_drive_t *hal_host_inj_drive(hal_out_t ch);

#endif
