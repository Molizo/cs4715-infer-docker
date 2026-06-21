#include <stdlib.h>
#include <stdbool.h>

extern void impure(int *n);

void detect_impure() {
  int n = 10;

  impure(&n);

  if (n > 0) {
    int *p = NULL;
    *p = 42;
  }
}
