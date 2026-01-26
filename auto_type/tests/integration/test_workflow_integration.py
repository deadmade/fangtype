import pytest

from auto_type.inference import JediInferenceEngine
from auto_type.insertion import (
    CodeLocation,
    InsertionTarget,
    TargetType,
    UnifiedInsertionEngine,
)


@pytest.mark.asyncio
async def test_full_pipeline_inference_to_insertion(tmp_path):
    # 1. Setup real file
    source_file = tmp_path / "test.py"
    source_file.write_text("def add(a, b): return a + b\nx = add(1, 2)")

    # 2. Use real engines
    inference = JediInferenceEngine()
    insertion = UnifiedInsertionEngine()

    # 3. Infer
    # Note: Using str(source_file) as path so Jedi can find it
    await inference.infer_types(source_file.read_text(), str(source_file))

    # 4. Verify Inference
    # (Assuming inference works, x should be int)
    vars = await inference.infer_variable_types(source_file.read_text())
    # Note: Depending on Jedi version and environment, it might infer 'int' or exact value.
    # We check if 'x' is in vars.
    assert "x" in vars
    assert vars["x"] == "int"

    # 5. Insert using unified API
    target = InsertionTarget(
        target_type=TargetType.VARIABLE_SIMPLE,
        location=CodeLocation(line=2, column=0),  # x is on line 2
        type_annotation=vars["x"],
        name="x",
    )
    result = insertion.insert([target], source_file.read_text())

    # 6. Verify Code Transformation
    assert result.success is True
    assert "x: int = add(1, 2)" in result.modified_source
