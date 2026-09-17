/* Hardware abstraction layer.
 *
 * Every register touch in this project lives behind one of these calls.
 * The host build implements them in software so the whole control path
 * can be tested on a PC; the STM32H7 build implements them with timers,
 * DMA and CAN-FD. Nothing above this header knows which it is talking to.
 *
 * Rules:
 *   - No call here allocates.
 *   - No call here blocks, except hal_flash_write.
 *   - Callbacks run in interrupt context and must stay short.
 */
#ifndef TQ_HAL_H
#define TQ_HAL_H

#include "tq_types.h"

/* ---- time ------------------------------------------------------------ */
tq_time_t hal_now_us(void);

/* ---- crank and cam input capture ------------------------------------- */
/* Called from the input-capture ISR on every tooth edge, with the
 * hardware-latched timestamp of that edge. Latched, not read: software
 * timestamping at 7000 rpm loses several degrees to interrupt latency. */
typedef void (*hal_tooth_cb)(tq_time_t edge_us, void *ctx);

void hal_crank_set_callback(hal_tooth_cb cb, void *ctx);
void hal_cam_set_callback(hal_tooth_cb cb, void *ctx);

/* ---- scheduled outputs ----------------------------------------------- */
/* An output channel driven by a compare unit: the edge happens in
 * hardware at the requested time whether or not the CPU is busy. */
typedef enum {
    HAL_OUT_COIL_1 = 0, HAL_OUT_COIL_2, HAL_OUT_COIL_3, HAL_OUT_COIL_4,
    HAL_OUT_COIL_5, HAL_OUT_COIL_6, HAL_OUT_COIL_7, HAL_OUT_COIL_8,
    HAL_OUT_INJ_1, HAL_OUT_INJ_2, HAL_OUT_INJ_3, HAL_OUT_INJ_4,
    HAL_OUT_INJ_5, HAL_OUT_INJ_6, HAL_OUT_INJ_7, HAL_OUT_INJ_8,
    HAL_OUT_HPFP_MSV,
    HAL_OUT_COUNT
} hal_out_t;

/* Schedule a rising edge at `on_us` and a falling edge at `off_us`.
 * Re-arming a channel whose rising edge has not yet fired replaces it;
 * re-arming one already high only moves the falling edge, because
 * retracting a dwell that has started would misfire. Returns false if the
 * request is already in the past. */
bool hal_out_schedule(hal_out_t ch, tq_time_t on_us, tq_time_t off_us);
void hal_out_cancel(hal_out_t ch);
bool hal_out_is_active(hal_out_t ch);

/* ---- throttle -------------------------------------------------------- */
void hal_throttle_pwm(f32 duty);       /* -1..1, sign is direction */
void hal_throttle_disable(void);       /* H-bridge off: return spring wins */

/* ---- analogue -------------------------------------------------------- */
typedef enum {
    HAL_ADC_PEDAL_A = 0, HAL_ADC_PEDAL_B,
    HAL_ADC_TPS_A, HAL_ADC_TPS_B,
    HAL_ADC_MAP, HAL_ADC_IAT, HAL_ADC_CLT,
    HAL_ADC_LAMBDA, HAL_ADC_RAIL_PRESSURE, HAL_ADC_BATTERY,
    HAL_ADC_KNOCK,
    HAL_ADC_COUNT
} hal_adc_t;

/* Raw counts, already DMA'd into a buffer by the ADC. Scaling to physical
 * units is the sensor layer's job, not the HAL's. */
u16 hal_adc_read(hal_adc_t ch);

/* ---- CAN-FD ---------------------------------------------------------- */
typedef struct {
    u32 id;
    u8 len;
    u8 data[64];
} hal_can_frame_t;

bool hal_can_send(const hal_can_frame_t *f);
bool hal_can_recv(hal_can_frame_t *out);

/* ---- flash (calibration storage) ------------------------------------- */
bool hal_flash_read(u32 offset, void *dst, u32 len);
bool hal_flash_write(u32 offset, const void *src, u32 len);  /* blocks */
bool hal_flash_erase(u32 offset, u32 len);

/* ---- watchdog (Level 3) ---------------------------------------------- */
void hal_watchdog_kick(void);
void hal_watchdog_force_reset(void);

#endif /* TQ_HAL_H */
