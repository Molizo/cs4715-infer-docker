#include <stdlib.h>

void unknown(int* p); // third-party code that does [*p = 5]
                      // Infer doesn't have access to that code

void false_negative() {
  int* x = (int*) malloc(sizeof(int));
  if (x) {
    // unknown call to x makes Pulse forget that x was allocated, in case it frees x
    unknown(x);
  }
} // no memory leak reported: false negative!

void false_positive(int *x) {
  unknown(x); // this sets *x to 5
  if (*x != 5) {
    // unreachable
    int* p = NULL;
    *p = 42; // false positive reported here
  }
}
