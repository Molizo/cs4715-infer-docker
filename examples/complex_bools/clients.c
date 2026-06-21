#include <stdlib.h>
#include <stdbool.h>

void invert_number(int* p, bool boo);
void buggy_invert_number(int* p, bool boo);

void true_positive(bool invert) {
    int number = 10;
    buggy_invert_number(&number, invert);

    if (number != 10 && !invert) {
        int *p = NULL;
        *p = 42;
    }
}

void false_positive( bool invert) {
    int number = 10;
    buggy_invert_number(&number, invert);

    if (number != 10 && !invert) {
        int *p = NULL;
        *p = 42;
    }
}
