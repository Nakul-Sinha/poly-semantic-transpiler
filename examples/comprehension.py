# Uses list comprehensions -> each becomes a validated LLM semantic hole (JS/Python).
xs = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
evens = [x for x in xs if x % 2 == 0]
squares = [x * x for x in xs]
odd_squares = [x * x for x in xs if x % 2 == 1]
print(evens)
print(squares)
print(odd_squares)
