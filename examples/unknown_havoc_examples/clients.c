#include <stdlib.h>

void set_5(int *x);
void abs_value(int *x);
void noop(int *x);
void positive_identity(int *x);
void maybe_null(int **p);
void maybe_leak(int *x);
void leak(void);
void buggy_abs(int *x);
void buggy_abs_positive_guard(int *x);
void discriminant(int a, int b, int c, int *disc);
void num_roots(int a, int b, int c, int *roots);
void num_roots_buggy(int a, int b, int c, int *roots);
void num_roots_buggy_intermediate_actions(int a, int b, int c, int *roots);

void expected_fp_set_5(int *x) {
  set_5(x);

  if (*x != 5) {
    int *p = NULL;
    *p = 42;
  }
}

void expected_fp_abs_value(int *x) {
  abs_value(x);

  if (*x < 0) {
    int *p = NULL;
    *p = 42;
  }
}

void expected_fp_noop(int *x) {
  *x = 7;

  noop(x);

  if (*x != 7) {
    int *p = NULL;
    *p = 42;
  }
}

void expected_fp_positive_identity(int *x) {
  if (*x > 0) {
    positive_identity(x);

    if (*x <= 0) {
      int *p = NULL;
      *p = 42;
    }
  }
}

void expected_fn_maybe_null(int **p) {
  int value = 10;
  *p = &value;

  maybe_null(p);

  **p = 42;
}

void expected_fn_maybe_leak_uaf(int *x) {
  maybe_leak(x);

  *x = 42;
}

void expected_fn_leak() { 
  leak(); 
}

void expected_fn_buggy_abs(int *x) {
  buggy_abs(x);

  if (*x < 0) {
    int *p = NULL;
    *p = 42;
  }
}

void expected_tp_buggy_abs_positive_guard(int *x) {
  if (*x > 0) {
    buggy_abs_positive_guard(x);

    if (*x < 0) {
      int *p = NULL;
      *p = 42;
    }
  }
}

void expected_fp_discriminant() {
    int a = 1, b = 2, c = 1;
    int disc;

    discriminant(a, b, c, &disc);

    // x^2 + 2x + 1 = 0
    // discriminant = 4 - 4 = 0

    if (disc != 0) {
        int *p = NULL;
        *p = 42;   // unreachable with real discriminant
    }
}

void expected_fp_num_roots() {
    int a = 1, b = 2, c = 1;
    int roots;

    num_roots(a, b, c, &roots);

    if (roots != 1) {
        int *p = NULL;
        *p = 42;   // unreachable
    }
}

void expected_tp_num_roots_buggy(int a, int b, int c) {
    int roots;

    num_roots_buggy(a, b, c, &roots);

    if (b * b - 4 * a * c < 0 && roots > 0) {
        int *p = NULL;
        *p = 42;   // real bug only in the buggy negative-discriminant region
    }
}

void expected_tp_num_roots_buggy_intermediate_actions(int a, int b, int c) {
    int roots;

    a = a + 69;
    b = b + 67;
    c = c + 420;

    num_roots_buggy_intermediate_actions(a, b, c, &roots);

    int temp = a;
    a = c * 2;
    c = temp / 2; // Should not matter; 4*a*c should stay the same

    if (b * b - 4 * a * c < 0 && roots > 0) {
        int *p = NULL;
        *p = 42;   // real bug only in the buggy negative-discriminant region
    }
}
