def gcd(a: int, b: int) -> int:
    while b != 0:
        t = b
        b = a % b
        a = t
    return a


def lcm(a: int, b: int) -> int:
    return a // gcd(a, b) * b


print(gcd(48, 36))
print(gcd(1071, 462))
print(lcm(4, 6))
