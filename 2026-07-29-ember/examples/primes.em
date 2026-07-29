// Trial-division primality test + a count of primes below n -- exercises
// nested control flow (while containing an if containing a return),
// `%`, and `&&`.
fn is_prime(n) {
    if (n < 2) {
        return 0;
    }
    let i = 2;
    while (i * i <= n) {
        if (n % i == 0) {
            return 0;
        }
        i = i + 1;
    }
    return 1;
}

fn count_primes_below(n) {
    let count = 0;
    let i = 2;
    while (i < n) {
        if (is_prime(i)) {
            count = count + 1;
        }
        i = i + 1;
    }
    return count;
}
