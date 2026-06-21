#include <stdlib.h>
#include <stdbool.h>

extern void write_false(bool *flag);

void expected_fp_write_false_bool() {
  bool flag = true;

  write_false(&flag);

  if (flag) {
    int *p = NULL;
    *p = 42;
  }
}
