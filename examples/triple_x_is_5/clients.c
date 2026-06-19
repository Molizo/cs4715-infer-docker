#include <stdlib.h>

void unknown1(int* p) {
  *p = 5;
}

void unknown2(int* p); // third-party code that does [*p = 5]
                      // Infer doesn't have access to that code

void unknown3(int* p) {
  *p = 5;
}

void false_negative() {
  int* x = (int*) malloc(sizeof(int));
  if (x) {
    unknown1(x);
    // unknown call to x makes Pulse forget that x was allocated, in case it frees x
    unknown2(x);
    unknown3(x);
  }
} // no memory leak reported: false negative!

void false_positive(int *x) {
  unknown1(x); // this sets *x to 5
  unknown2(x); // this sets *x to 5
  //unknown3(x); // this sets *x to 5
  if (*x != 5) {
    // unreachable
    int* p = NULL;
    *p = 42; // false positive reported here
  }
}
