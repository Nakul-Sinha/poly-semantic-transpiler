def is_prime(n: int) -> bool:
    if n < 2:
        return False
    i = 2
    while i * i <= n:
        if n % i == 0:
            return False
        i = i + 1
    return True


count = 0
for k in range(2, 30):
    if is_prime(k):
        count = count + 1
        print(k)
print(count)
