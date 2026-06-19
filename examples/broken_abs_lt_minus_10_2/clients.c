#include <stdlib.h>

extern void broken_abs_2(int* p);
extern void good_abs_2(int* p);

void false_positive_broken_abs_2(int *x) {
    broken_abs_2(x); // this should set x to abs(x) but is broken if -10 < x < 0
    if (*x < 0) {
      // unreachable
      int* p = NULL;
      *p = 42; // false positive reported here
    }
}

void false_positive_good_abs_2(int *x) {
    good_abs_2(x); // this should set x to abs(x)
    if (*x < 0) {
      // unreachable
      int* p = NULL;
      *p = 42; // no false positive reported here
    }
}


void fp2() {
    int x = -5;
    false_positive_broken_abs_2(&x);
    false_positive_good_abs_2(&x);
}