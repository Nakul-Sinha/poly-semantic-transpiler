def sum_squares(xs: list[int]) -> int:
    total = 0
    for x in xs:
        if x % 2 == 0:
            total = total + x * x
    return total


nums = [1, 2, 3, 4, 5, 6]
print(sum_squares(nums))
nums.append(8)
print(sum_squares(nums), len(nums))
