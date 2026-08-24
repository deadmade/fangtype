# Error case scenarios
# These may not have type hints or may cause errors

# Unknown function (no type info)
unknown_result = some_undefined_function()

# Import that may not exist

# Attribute access on unknown
obj_attr = unknown_object.attribute

# Complex expression with unknown
complex_unknown = unknown_func() + another_unknown()
