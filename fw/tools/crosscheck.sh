#!/bin/sh
# Cross-compile the firmware for the real target and check the two things
# a host build cannot: that the target HAL compiles at all, and that the
# "single precision everywhere" rule actually holds.
#
# The second one is not a style check. The M7 and the S32K3 have a
# single-precision FPU and no double unit, so one stray double turns a
# one-cycle multiply into a library call -- and the place that happens is
# inside a crank interrupt at 7000 rpm. Building against an FPU that has
# no double support makes the compiler emit a call to __aeabi_d* instead,
# which is something a script can see.
#
# Exits non-zero on failure. Skips cleanly when no cross compiler exists,
# so a contributor without one is not blocked.
set -e

CC=arm-none-eabi-gcc
if ! command -v "$CC" >/dev/null 2>&1; then
    echo "crosscheck: $CC not installed, skipping"
    exit 0
fi

ROOT=$(cd "$(dirname "$0")/.." && pwd)
OUT=$(mktemp -d)
trap 'rm -rf "$OUT"' EXIT

FLAGS="-mcpu=cortex-m7 -mfpu=fpv5-sp-d16 -mfloat-abi=hard -mthumb
       -std=c11 -Wall -Wextra -Werror -O2
       -I$ROOT/include -I$ROOT/hal"

echo "crosscheck: building the control path for cortex-m7"
for f in "$ROOT"/src/*.c "$ROOT"/hal/oc_core.c; do
    $CC -c $FLAGS "$f" -o "$OUT/$(basename "$f" .c).o"
done

echo "crosscheck: building the STM32H7 HAL"
$CC -c $FLAGS -DTQ_TARGET_STM32H7 "$ROOT/hal/hal_stm32h7.c" -o "$OUT/hal_stm32h7.o"

echo "crosscheck: looking for double-precision arithmetic"
if arm-none-eabi-nm "$OUT"/*.o | grep -E '__aeabi_d|__(add|sub|mul|div)df3|__truncdfsf2' ; then
    echo "crosscheck: FAILED -- the above are double-precision runtime calls."
    echo "            Find the stray double; there is no double FPU on this part."
    exit 1
fi

echo "crosscheck: ok ($(ls "$OUT"/*.o | wc -l) objects, no double-precision calls)"
