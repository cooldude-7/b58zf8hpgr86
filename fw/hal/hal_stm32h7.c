/* STM32H7 HAL: the register-level implementation.
 *
 * NOT YET WRITTEN. This file exists so the shape of the port is visible
 * and the host build can be diffed against it, and so nobody is under
 * the impression that the firmware runs on hardware today. Each function
 * carries the peripheral it needs and the reason the obvious approach is
 * wrong, because those are the details that get lost between deciding
 * and doing.
 *
 * Build it with -DTQ_TARGET_STM32H7 once a toolchain and a board exist.
 */
#ifdef TQ_TARGET_STM32H7

#include "hal.h"

/* Peripheral plan, to be implemented against the reference manual:
 *
 * Time base        TIM2, 32-bit, 1 MHz from APB1. 32-bit matters: a
 *                  16-bit counter wraps every 65 ms, which is inside a
 *                  single crank revolution at idle.
 *
 * Crank capture    TIM5 CH1 input capture with the digital filter set
 *                  for the VR or Hall front end. The capture value is
 *                  the timestamp -- never read the counter in the ISR,
 *                  because interrupt latency under load is worth several
 *                  degrees at 7000 rpm.
 *
 * Cam capture      TIM5 CH2, same treatment.
 *
 * Coils, injectors TIM1 and TIM8 output compare in one-pulse-ish mode,
 *                  one channel per output, plus a software queue for the
 *                  channels that share a timer. The compare registers
 *                  are double buffered, which is what makes a late
 *                  revision safe.
 *
 * Throttle         TIM3 complementary PWM into the H-bridge, with the
 *                  brake-on-fault input wired to the monitor so the
 *                  hardware can open the bridge without software.
 *
 * ADC              ADC1 and ADC2 in dual regular simultaneous mode, DMA
 *                  into a double buffer, triggered from TIM6 at 1 kHz.
 *                  Pedal A and pedal B must be on DIFFERENT ADCs: two
 *                  channels on one ADC share a fault mode, which defeats
 *                  the point of having two.
 *
 * CAN-FD           FDCAN1 to the transmission, FDCAN2 to the tuner.
 *
 * Flash            The second bank, so calibration can be written while
 *                  running from the first.
 *
 * Watchdog         IWDG, kicked only by the diagnostic task and only
 *                  when the fast task has advanced.
 */

#error "STM32H7 HAL is not implemented yet -- see docs/ultracode-plan.md Phase D"

#endif /* TQ_TARGET_STM32H7 */
