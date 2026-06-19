#include <stdlib.h>

extern void copy(int* var1, int var2);

void var_stress() {
    int a = 1;
    int b = a + 2;
    int c = b * 3;
    int d = c - a;
    int e = d + b;
    int f = e * 2;
    int g = f / 3;
    int h = g + (a + b) + c;
    int i = h - d;
    int j = i + e;
    int k = j * 2 - f;
    int m = k + g + h;
    int n = m / (2 + a);
    int o = n + m + k;
    int p = o - n + j;
    int q = p * 2 + i;
    int r = q - o + h;
    int s = r + p - g;
    int t = s + q - f;
    int u = t + r - e;
    int v = u + s - d;
    int w = v + t - c;
    int x = w + u - b;
    int y = x + v - a;
    int z = y + w + x;

    int acc = z;
    int idx = 0;

    /*
    while (idx < 5) {
        int inner = acc + idx;
        acc = acc + inner - (idx * 2) + (idx + a);
        if ((idx - 2) == 0) {
            int shadow = acc + y;
            acc = shadow - inner + (idx + b);
        } else {
            int shadow = acc - x;
            acc = shadow + inner - (idx + c);
        };
        idx = idx + 1;
    };
    */

    int branchA=0;
    
    /*if (acc > 0) {
        int tmp = acc + d + e;
        branchA = tmp - f + g;
    }else {
        int tmp = acc - h - i;
        branchA = tmp + j - k;
    }*/
    
    copy(&branchA, v);

    int branchB=0;
    
    /*if (branchA < acc) {
        int tmp = branchA + v;
        branchB = tmp + acc;
    }else {
        int tmp = branchA - acc;
        branchB = tmp - acc;
    }*/

    int l = branchA / 2 + m;
    int branchC = branchB + l + n;
    int finalAcc = acc + branchA + branchB + branchC + o + p + q + r + s + t + u + v + w + x + y + z;

    if (finalAcc - (l / 2) < 0) {
        int *p = NULL;
        *p = 42;
    } 
}