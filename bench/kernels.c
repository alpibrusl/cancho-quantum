/* The same state-vector kernels as src/gates.cho, written in C, to separate the language from the algorithm.
 *
 *     kernels naive|tuned h_layer|cx_chain|rz_layer N
 *
 * `naive` is the loop of src/gates.cho: visit every index, test the qubit's bit, act on the half that has it
 * clear. `tuned` visits only the pairs (no test, no skipped half). The state is interleaved re, im doubles,
 * as in src/state.cho; the whole process is timed from outside, as for qsim. Nothing is printed.
 */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef long long ll;

static void h_naive(double *st, int n, int q) {
    ll bit = 1LL << q, total = 1LL << n;
    double r = 1.0 / sqrt(2.0);
    for (ll i = 0; i < total; i++) {
        if ((i & bit) == 0) {
            double ar = st[2 * i], ai = st[2 * i + 1], br = st[2 * (i | bit)], bi = st[2 * (i | bit) + 1];
            st[2 * i] = (ar + br) * r;
            st[2 * i + 1] = (ai + bi) * r;
            st[2 * (i | bit)] = (ar - br) * r;
            st[2 * (i | bit) + 1] = (ai - bi) * r;
        }
    }
}

static void cx_naive(double *st, int n, int c, int t) {
    ll cb = 1LL << c, tb = 1LL << t, total = 1LL << n;
    for (ll i = 0; i < total; i++) {
        if ((i & cb) != 0 && (i & tb) == 0) {
            double ar = st[2 * i], ai = st[2 * i + 1];
            st[2 * i] = st[2 * (i | tb)];
            st[2 * i + 1] = st[2 * (i | tb) + 1];
            st[2 * (i | tb)] = ar;
            st[2 * (i | tb) + 1] = ai;
        }
    }
}

static void diag_naive(double *st, int n, int q, double p0r, double p0i, double p1r, double p1i) {
    ll bit = 1LL << q, total = 1LL << n;
    for (ll i = 0; i < total; i++) {
        double pr = (i & bit) == 0 ? p0r : p1r, pi_ = (i & bit) == 0 ? p0i : p1i;
        double ar = st[2 * i], ai = st[2 * i + 1];
        st[2 * i] = ar * pr - ai * pi_;
        st[2 * i + 1] = ar * pi_ + ai * pr;
    }
}

/* tuned: iterate the pairs directly */
static void h_tuned(double *st, int n, int q) {
    ll half = 1LL << (n - 1), low = (1LL << q) - 1, bit = 1LL << q;
    double r = 1.0 / sqrt(2.0);
    for (ll k = 0; k < half; k++) {
        ll i = ((k & ~low) << 1) | (k & low), j = i | bit;
        double ar = st[2 * i], ai = st[2 * i + 1], br = st[2 * j], bi = st[2 * j + 1];
        st[2 * i] = (ar + br) * r;
        st[2 * i + 1] = (ai + bi) * r;
        st[2 * j] = (ar - br) * r;
        st[2 * j + 1] = (ai - bi) * r;
    }
}

static void cx_tuned(double *st, int n, int c, int t) {
    ll quarter = 1LL << (n - 2), cb = 1LL << c, tb = 1LL << t;
    int lo = c < t ? c : t, hi = c < t ? t : c;
    ll mlo = (1LL << lo) - 1, mhi = (1LL << (hi - 1)) - 1;
    for (ll k = 0; k < quarter; k++) {
        ll x = (k & mlo) | ((k & ~mlo) << 1);
        ll i = (x & mhi) | ((x & ~mhi) << 1) | cb;
        ll j = i | tb;
        double ar = st[2 * i], ai = st[2 * i + 1];
        st[2 * i] = st[2 * j];
        st[2 * i + 1] = st[2 * j + 1];
        st[2 * j] = ar;
        st[2 * j + 1] = ai;
    }
}

int main(int argc, char **argv) {
    if (argc != 4 && argc != 5) return 2;
    int tuned = strcmp(argv[1], "tuned") == 0, n = atoi(argv[3]);
    double *st = calloc((size_t)2 << n, sizeof(double));
    st[0] = 1.0;
    const double PI = 3.141592653589793;
    if (strcmp(argv[2], "h_layer") == 0 || strcmp(argv[2], "rz_layer") == 0) {
        for (int q = 0; q < n; q++) tuned ? h_tuned(st, n, q) : h_naive(st, n, q);
    }
    if (strcmp(argv[2], "cx_chain") == 0) {
        tuned ? h_tuned(st, n, 0) : h_naive(st, n, 0);
        for (int q = 0; q < n - 1; q++) tuned ? cx_tuned(st, n, q, q + 1) : cx_naive(st, n, q, q + 1);
    }
    if (strcmp(argv[2], "rz_layer") == 0) {
        for (int q = 0; q < n; q++) {
            double half = PI * 1 / (q + 3) * 0.5, c = cos(half), s = sin(half);
            diag_naive(st, n, q, c, -s, c, s); /* a diagonal gate has no pair structure to tune */
        }
    }
    if (argc == 5) { /* `dump`: every amplitude, for the correctness check against qsim */
        for (ll i = 0; i < (1LL << n); i++) printf("%lld %.17g %.17g\n", i, st[2 * i], st[2 * i + 1]);
    }
    volatile double sink = st[1];
    (void)sink;
    free(st);
    return 0;
}
