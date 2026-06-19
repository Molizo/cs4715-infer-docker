#include <stdlib.h>

void broken_abs_2(int* p) {
    if (*p <= -10) {
        *p = -*p;
    } else if (*p < 0) {
        /* Buggy area */
    } else {
        *p = *p;
    }
}

void good_abs_2(int* p) {
    if (*p < 0) {
        *p = -*p;
    } else {
        *p = *p;
    }
}