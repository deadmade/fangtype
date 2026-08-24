"""Integration smoke test: drive the real fangtype-server over stdio via the client."""

from __future__ import annotations

from benchmark.lsp_client.client import FangtypeLspClient
from benchmark.lsp_client.label_parse import scrape_inlay_type


async def test_inlay_hints_roundtrip(tmp_path) -> None:
    """Start the real server, didOpen a file, and get an inlay hint back over stdio."""
    src = "def f():\n    x = 42\n    return x\n"
    case = tmp_path / "case.py"
    case.write_text(src)
    uri = case.as_uri()

    client = FangtypeLspClient(engine="jedi", root_uri=tmp_path.as_uri())
    await client.start()
    try:
        await client.open_document(uri, src)
        hints = await client.inlay_hints(uri)
    finally:
        await client.stop()

    assert hints, "expected at least one inlay hint"
    scraped = [scrape_inlay_type(h.label) for h in hints]
    assert any(s == "int" for s in scraped), f"expected an int hint, got {scraped}"


async def test_insert_types_in_file_roundtrip(tmp_path) -> None:
    """Smoke check bulk-insert request still works over real stdio (WP5 dropped other caller)."""
    src = "def f():\n    x = 42\n    return x\n"
    case = tmp_path / "case.py"
    case.write_text(src)
    uri = case.as_uri()

    client = FangtypeLspClient(engine="jedi", root_uri=tmp_path.as_uri())
    await client.start()
    try:
        await client.open_document(uri, src)
        response = await client.insert_types_in_file(uri)
    finally:
        await client.stop()

    success = response.get("success") if isinstance(response, dict) else response.success
    assert success
