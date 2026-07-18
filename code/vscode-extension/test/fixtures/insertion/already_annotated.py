# Variables that already have type annotations
# Test file to verify no duplicate annotations

annotated_int: int = 42
annotated_str: str = "hello"
annotated_list: list[int] = [1, 2, 3]
annotated_dict: dict[str, int] = {"a": 1}

# Mixed: some annotated, some not
mixed_annotated: bool = True
mixed_unannotated = 3.14

# Declaration without value
declared_only: str

# Complex annotation
complex_type: dict[str, list[int]] = {"nums": [1, 2, 3]}
