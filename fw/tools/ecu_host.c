/* The firmware, running on a PC, speaking the tuner protocol on stdin
 * and stdout.
 *
 * This is what lets the tuner be tested against the real C protocol code
 * rather than against a Python imitation of it. The bytes on the pipe
 * are the bytes that will be on the wire.
 *
 *   ecu_host <layout-file>
 *
 * The layout file stands in for the calibration a real ECU would have
 * been flashed with.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "cal.h"
#include "proto.h"

static int load_layout(cal_t *c, const char *path)
{
    FILE *f = fopen(path, "r");
    if (!f) {
        fprintf(stderr, "ecu_host: cannot open %s\n", path);
        return -1;
    }
    char line[8192];
    cal_table_t *cur = 0;
    u8 row = 0;
    while (fgets(line, sizeof(line), f)) {
        if (!strncmp(line, "table ", 6)) {
            if (c->n_tables >= CAL_MAX_TABLES) break;
            cur = &c->t[c->n_tables++];
            memset(cur, 0, sizeof(*cur));
            int nx, ny;
            double lo, hi;
            char key[64];
            if (sscanf(line + 6, "%63s %d %d %lf %lf", key, &nx, &ny, &lo, &hi) != 5) {
                fclose(f); return -1;
            }
            /* memcpy of a measured length rather than strncpy: the key
             * buffer is deliberately short and a silent truncation would
             * make two tables collide. */
            size_t klen = strlen(key);
            if (klen >= CAL_NAME_LEN) {
                fprintf(stderr, "ecu_host: table key '%s' is too long\n", key);
                fclose(f); return -1;
            }
            memcpy(cur->key, key, klen);
            cur->key[klen] = '\0';
            cur->n_x = (u8)nx; cur->n_y = (u8)ny;
            cur->lo = (f32)lo; cur->hi = (f32)hi;
            row = 0;
        } else if (cur && !strncmp(line, "x ", 2)) {
            char *p = line + 2;
            for (u8 i = 0; i < cur->n_x; i++) cur->x[i] = (f32)strtod(p, &p);
        } else if (cur && !strncmp(line, "y ", 2)) {
            char *p = line + 2;
            for (u8 j = 0; j < cur->n_y; j++) cur->y[j] = (f32)strtod(p, &p);
        } else if (cur && !strncmp(line, "v ", 2)) {
            if (row >= cur->n_y) continue;
            char *p = line + 2;
            for (u8 i = 0; i < cur->n_x; i++) cur->v[row][i] = (f32)strtod(p, &p);
            row++;
        }
    }
    fclose(f);
    return 0;
}

int main(int argc, char **argv)
{
    if (argc < 2) {
        fprintf(stderr, "usage: ecu_host <layout-file>\n");
        return 2;
    }
    static cal_t ram, flash;
    cal_init(&ram);
    if (load_layout(&ram, argv[1]) != 0) {
        return 2;
    }
    flash = ram;

    static proto_t p;
    proto_init(&p, &ram, &flash);

    /* Unbuffered: a tuner waiting on a reply that is sitting in a stdio
     * buffer looks exactly like an ECU that has crashed. */
    setvbuf(stdin, NULL, _IONBF, 0);
    setvbuf(stdout, NULL, _IONBF, 0);

    static u8 out[PROTO_MAX_PAYLOAD + 64];
    int ch;
    while ((ch = fgetc(stdin)) != EOF) {
        u8 b = (u8)ch;
        u32 n = proto_feed(&p, &b, 1, out, sizeof(out));
        if (n) {
            fwrite(out, 1, n, stdout);
            fflush(stdout);
        }
    }
    return 0;
}
