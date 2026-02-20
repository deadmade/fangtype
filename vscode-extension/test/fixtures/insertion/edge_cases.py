# Edge case scenarios for insertion testing

# Comments with assignments (should not be annotated)
# x = 5  <- this is a comment, not code

# String containing assignment syntax
message = "x = 5 is the assignment"

# Multi-line string
multiline = """
This is a
multi-line string
with x = 5 inside
"""

# Variable reassignment
counter = 0
counter = counter + 1

# Multiple assignments on one line (tuple unpacking)
# Note: This may require special handling
# a, b = 1, 2

# Chained assignment
# chain_a = chain_b = 10

# Expression results
sum_result = 1 + 2 + 3
concat_result = "hello" + " " + "world"
bool_expr = True and False

# Built-in function calls
length = len([1, 2, 3])
string_upper = "hello".upper()
list_sorted = sorted([3, 1, 2])

# Comprehensions
list_comp = [x * 2 for x in range(5)]
dict_comp = {str(i): i for i in range(3)}
set_comp = {x for x in [1, 2, 2, 3]}

# Conditional expression
ternary = "yes" if True else "no"

# Lambda (result type)
func = lambda x: x * 2
