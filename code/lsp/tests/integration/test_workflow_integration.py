from fangtype.inference.jedi.engine import JediInferenceEngine
from fangtype.insertion import (
    CodeLocation,
    InsertionEngine,
    InsertionTarget,
    TargetType,
)
from fangtype.utils.settings import Settings


def test_full_pipeline_inference_to_insertion(tmp_path):
    # 1. Setup real file
    source_file = tmp_path / "test.py"
    source_file.write_text("def add(a, b): return a + b\nx = add(1, 2)")

    # 2. Use real engines
    inference = JediInferenceEngine(Settings())
    insertion = InsertionEngine()

    # 3. Infer — pass str(source_file) as path so Jedi can find it
    result = inference.infer_types(source_file.read_text(), str(source_file))

    # 4. Verify Inference — x should be int
    vars = {
        name: info.type_str
        for name, info in result.scope_tree.root.variables.items()
        if info.type_str != "Unknown"
    }
    # Note: Jedi may infer 'int' or the exact value depending on version/environment.
    assert "x" in vars
    assert vars["x"] == "int"

    # 5. Insert using unified API
    target = InsertionTarget(
        target_type=TargetType.VARIABLE_SIMPLE,
        location=CodeLocation(line=2, column=0),  # x is on line 2
        type_annotation=vars["x"],
        name="x",
    )
    insertion_result = insertion.insert([target], source_file.read_text())

    # 6. Verify Code Transformation
    assert insertion_result.success is True
    assert "x: int = add(1, 2)" in insertion_result.modified_source
