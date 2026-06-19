#include <stdlib.h>

extern void identity(int* x);

void loop1() {
    int pos = 0;
    int neg = 0;

    int lim = 0;
    identity(&lim);

    for (int i = 0; i < lim; ++i) {
        int tmp = 1;
        if (tmp < 0) {
            pos++;
        } else { 
            neg++;
        }
    }
    
	if (pos < neg) {
		int *p = NULL;
        *p = 42;
	}
}