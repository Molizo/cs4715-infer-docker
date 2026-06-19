#include <stdlib.h>

void broken_abs(int* p);

void false_negative() {
  int* x = (int*) malloc(sizeof(int));
  if (x) {
    // unknown call to x makes Pulse forget that x was allocated, in case it frees x
    broken_abs(x);
  }
} // no memory leak reported: false negative!

void false_positive(int *x) {
  broken_abs(x); // this should set x to abs(x) but is broken if -10 < x < 0
  if (*x < 0) {
    // unreachable
    int* p = NULL;
    *p = 42; // false positive reported here
  }
}
