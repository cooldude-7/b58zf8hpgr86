/* A test framework small enough to read in one sitting. */
#ifndef TQ_TEST_H
#define TQ_TEST_H

#include <math.h>
#include <stdio.h>
#include <stdlib.h>

static int tq_fails;
static int tq_checks;
static const char *tq_case = "";

#define TQ_CASE(name) (tq_case = (name))

#define TQ_CHECK(cond, ...)                                                   \
    do {                                                                      \
        tq_checks++;                                                          \
        if (!(cond)) {                                                        \
            tq_fails++;                                                       \
            printf("  [FAIL] %s: ", tq_case);                                 \
            printf(__VA_ARGS__);                                              \
            printf("\n         at %s:%d: %s\n", __FILE__, __LINE__, #cond);   \
        }                                                                     \
    } while (0)

#define TQ_NEAR(a, b, tol, ...)                                               \
    do {                                                                      \
        tq_checks++;                                                          \
        double _d = fabs((double)(a) - (double)(b));                          \
        if (!(_d <= (tol))) {                                                 \
            tq_fails++;                                                       \
            printf("  [FAIL] %s: ", tq_case);                                 \
            printf(__VA_ARGS__);                                              \
            printf("\n         %s = %g, expected %g +/- %g (off by %g)\n",    \
                   #a, (double)(a), (double)(b), (double)(tol), _d);          \
            printf("         at %s:%d\n", __FILE__, __LINE__);                \
        }                                                                     \
    } while (0)

#define TQ_PASS(name)                                                         \
    do {                                                                      \
        printf("  [ok]   %s\n", (name));                                      \
    } while (0)

static inline int tq_report(const char *suite)
{
    printf("%s: %d checks, %d failed\n", suite, tq_checks, tq_fails);
    return tq_fails ? 1 : 0;
}

#endif /* TQ_TEST_H */
