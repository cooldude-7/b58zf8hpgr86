/* STM32H7 register definitions, for only the peripherals this HAL uses.
 *
 * Hand-written rather than pulling in ST's CMSIS pack, because the pack
 * is large, vendored, and would still have to be trusted. This is small
 * enough to check against the reference manual by eye.
 *
 * HOW FAR TO TRUST THIS FILE: the offsets are transcribed from the
 * RM0433 register maps. They have NOT been checked against silicon,
 * because no board exists. The _Static_asserts below catch a field
 * accidentally inserted or removed -- they do NOT prove any offset is
 * right, since they only check these numbers against themselves. The
 * first thing to do with a real board is read a known register (say
 * TIM2_ARR after writing it) and confirm the struct lines up.
 *
 * The word at 0x50 in the advanced-control timers is reserved and must
 * be declared, or everything from CCMR3 onwards lands one word early.
 */
#ifndef TQ_STM32H7_REGS_H
#define TQ_STM32H7_REGS_H

#include "tq_types.h"

typedef struct {
    volatile u32 CR1;        /* 0x00 */
    volatile u32 CR2;        /* 0x04 */
    volatile u32 SMCR;       /* 0x08 */
    volatile u32 DIER;       /* 0x0C */
    volatile u32 SR;         /* 0x10 */
    volatile u32 EGR;        /* 0x14 */
    volatile u32 CCMR1;      /* 0x18 */
    volatile u32 CCMR2;      /* 0x1C */
    volatile u32 CCER;       /* 0x20 */
    volatile u32 CNT;        /* 0x24 */
    volatile u32 PSC;        /* 0x28 */
    volatile u32 ARR;        /* 0x2C */
    volatile u32 RCR;        /* 0x30 */
    volatile u32 CCR[4];     /* 0x34..0x40 */
    volatile u32 BDTR;       /* 0x44 */
    volatile u32 DCR;        /* 0x48 */
    volatile u32 DMAR;       /* 0x4C */
    volatile u32 RESERVED0;  /* 0x50 -- present, and easy to forget */
    volatile u32 CCMR3;      /* 0x54 */
    volatile u32 CCR5;       /* 0x58 */
    volatile u32 CCR6;       /* 0x5C */
    volatile u32 AF1;        /* 0x60 */
    volatile u32 AF2;        /* 0x64 */
    volatile u32 TISEL;      /* 0x68 */
} tim_t;

_Static_assert(sizeof(u32) == 4, "u32 must be 32 bits");
#define TQ_OFF(f) ((u32)(unsigned long)&(((tim_t *)0)->f))
_Static_assert(TQ_OFF(CCER)  == 0x20u, "CCER offset");
_Static_assert(TQ_OFF(CNT)   == 0x24u, "CNT offset");
_Static_assert(TQ_OFF(CCR[0]) == 0x34u, "CCR1 offset");
_Static_assert(TQ_OFF(BDTR)  == 0x44u, "BDTR offset");
_Static_assert(TQ_OFF(CCMR3) == 0x54u, "CCMR3 offset -- the 0x50 hole");
_Static_assert(TQ_OFF(TISEL) == 0x68u, "TISEL offset");
_Static_assert(sizeof(tim_t) == 0x6Cu, "tim_t size");

/* Bits used here, named rather than spelled as magic numbers. */
#define TIM_CR1_CEN      (1u << 0)
#define TIM_CR1_ARPE     (1u << 7)
#define TIM_EGR_UG       (1u << 0)
#define TIM_SR_CCIF(ch)  (1u << (1u + (ch)))
#define TIM_SR_CCOF(ch)  (1u << (9u + (ch)))   /* overcapture */
#define TIM_DIER_CCIE(ch) (1u << (1u + (ch)))
#define TIM_CCER_CCE(ch) (1u << (4u * (ch)))

/* Output compare modes, in the CCMRx output-mode field for a channel. */
#define TIM_OCM_FROZEN     0x0u
#define TIM_OCM_ACTIVE     0x1u        /* force high on match */
#define TIM_OCM_INACTIVE   0x2u        /* force low on match */
#define TIM_OCM_FORCE_LOW  0x4u        /* force low NOW, no match needed */
#define TIM_OCM_FORCE_HIGH 0x5u

/* Peripheral bases. Substitutable so the scheduling logic can be run on a
 * PC against plain memory: the target build resolves these to constants,
 * the host test build points them at a buffer. Nothing else in the HAL
 * needs to know which it is. */
#ifdef TQ_REGS_MOCK
#define TQ_N_TIM 6
extern tim_t tq_mock_tim[TQ_N_TIM];
#define TQ_TIM(i) (&tq_mock_tim[i])
#else
#define TQ_TIM1  ((tim_t *)0x40010000u)
#define TQ_TIM2  ((tim_t *)0x40000000u)
#define TQ_TIM3  ((tim_t *)0x40000400u)
#define TQ_TIM4  ((tim_t *)0x40000800u)
#define TQ_TIM5  ((tim_t *)0x40000C00u)
#define TQ_TIM8  ((tim_t *)0x40010400u)
#endif

#endif /* TQ_STM32H7_REGS_H */
