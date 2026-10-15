"""A tiny calculator module providing basic arithmetic functions.

Functions:
    add(a, b): Return the sum of a and b.
    subtract(a, b): Return the difference of a and b (a - b).
    multiply(a, b): Return the product of a and b.
    divide(a, b): Return the quotient of a and b (a / b); raises ValueError if b is 0.
"""


def add(a, b):
    """Return the sum of a and b."""
    return a + b


def subtract(a, b):
    """Return the result of subtracting b from a."""
    return a - b


def multiply(a, b):
    """Return the product of a and b."""
    return a * b


def divide(a, b):
    """Return the result of dividing a by b.

    Raises:
        ValueError: If b is zero.
    """
    if b == 0:
        raise ValueError("Cannot divide by zero.")
    return a / b


if __name__ == "__main__":
    # Simple examples of how to call the functions
    print(add(2, 3))        # 5
    print(subtract(10, 4))  # 6
    print(add(1.5, 2.25))   # 3.75
    print(subtract(3, 7))   # -4
