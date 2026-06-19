#include <stdlib.h>

void set_5(int *x) { 
  *x = 5; 
}

void abs_value(int *x) {
  if (*x < 0) {
    *x = -*x;
  }
}

void noop(int *x) { 
  (void)x; 
}

void positive_identity(int *x) {
  if (*x > 0) {
    /* Intentionally preserve *x. */
  }
}

void maybe_null(int **p) { 
  *p = NULL; 
}

void maybe_leak(int *x) { 
  free(x); 
}

void leak() {
  int *p = malloc(sizeof(int));
  if (p != NULL) {
    *p = 42;
  }
}

void buggy_abs(int *x) {
  if (*x < 0) {
    *x = -*x;
  } else if (*x < 10) {
    *x = -*x; // bug
  } else { // x >= 10
    // Do nothing; we have a positive number
  }
}

void buggy_abs_positive_guard(int *x) {
  if (*x < 0) {
    *x = -*x;
  } else if (*x < 10) {
    *x = -*x; // bug
  } else { // x >= 10
    // Do nothing; we have a positive number
  }
}

void discriminant(int a, int b, int c, int *disc) {
    *disc = b * b - 4 * a * c;
}

void num_roots(int a, int b, int c, int *roots) {
    int d = b * b - 4 * a * c;

    if (d > 0) {
        *roots = 2;
    } else if (d == 0) {
        *roots = 1;
    } else {
        *roots = 0;
    }
}

void num_roots_buggy(int a, int b, int c, int *roots) {
    int d = b * b - 4 * a * c;

    if (d > 0) {
        *roots = 2;
    } else if (d == 0) {
        *roots = 1;
    } else {
        // Bug: for small negative discriminants, incorrectly says one root.
        if (d >= -10) {
            *roots = 1;
        } else {
            *roots = 0;
        }
    }
}

void num_roots_buggy_intermediate_actions(int a, int b, int c, int *roots) {
    int d = b * b - 4 * a * c;

    if (d > 0) {
        *roots = 2;
    } else if (d == 0) {
        *roots = 1;
    } else {
        // Bug: for small negative discriminants, incorrectly says one root.
        if (d >= -10) {
            *roots = 1;
        } else {
            *roots = 0;
        }
    }
}
