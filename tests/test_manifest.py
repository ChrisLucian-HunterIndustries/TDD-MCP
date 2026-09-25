import asyncio

from approvaltests import Options, verify_as_json
from approvaltests.namer.templated_custom_namer import TemplatedCustomNamer

from tdd_mcp.server import mcp


def test_tools_manifest():
    """The JSON manifest a consuming MCP client reads via `tools/list`."""
    tools = asyncio.run(mcp.list_tools())
    manifest = [tool.model_dump(mode="json", exclude_none=True) for tool in tools]

    namer = TemplatedCustomNamer(
        "{test_source_directory}/manifest.{approved_or_received}.{file_extension}"
    )
    verify_as_json(manifest, options=Options().with_namer(namer))
