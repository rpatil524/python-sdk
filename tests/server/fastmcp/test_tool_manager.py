import json
import logging

import pytest
from pydantic import BaseModel

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.fastmcp.tools import Tool, ToolManager
from mcp.server.fastmcp.utilities.func_metadata import ArgModelBase, FuncMetadata
from mcp.server.session import ServerSessionT
from mcp.shared.context import LifespanContextT, RequestT
from mcp.types import ToolAnnotations


class TestAddTools:
    def test_basic_function(self):
        """Test registering and running a basic function."""

        def add(a: int, b: int) -> int:
            """Add two numbers."""
            return a + b

        manager = ToolManager()
        manager.add_tool(add)

        tool = manager.get_tool("add")
        assert tool is not None
        assert tool.name == "add"
        assert tool.description == "Add two numbers."
        assert tool.is_async is False
        assert tool.parameters["properties"]["a"]["type"] == "integer"
        assert tool.parameters["properties"]["b"]["type"] == "integer"

    def test_init_with_tools(self, caplog):
        def add(a: int, b: int) -> int:
            return a + b

        class AddArguments(ArgModelBase):
            a: int
            b: int

        fn_metadata = FuncMetadata(arg_model=AddArguments)

        original_tool = Tool(
            name="add",
            title="Add Tool",
            description="Add two numbers.",
            fn=add,
            fn_metadata=fn_metadata,
            is_async=False,
            parameters=AddArguments.model_json_schema(),
            context_kwarg=None,
            annotations=None,
        )
        manager = ToolManager(tools=[original_tool])
        saved_tool = manager.get_tool("add")
        assert saved_tool == original_tool

        # warn on duplicate tools
        with caplog.at_level(logging.WARNING):
            manager = ToolManager(True, tools=[original_tool, original_tool])
            assert "Tool already exists: add" in caplog.text

    @pytest.mark.anyio
    async def test_async_function(self):
        """Test registering and running an async function."""

        async def fetch_data(url: str) -> str:
            """Fetch data from URL."""
            return f"Data from {url}"

        manager = ToolManager()
        manager.add_tool(fetch_data)

        tool = manager.get_tool("fetch_data")
        assert tool is not None
        assert tool.name == "fetch_data"
        assert tool.description == "Fetch data from URL."
        assert tool.is_async is True
        assert tool.parameters["properties"]["url"]["type"] == "string"

    def test_pydantic_model_function(self):
        """Test registering a function that takes a Pydantic model."""

        class UserInput(BaseModel):
            name: str
            age: int

        def create_user(user: UserInput, flag: bool) -> dict:
            """Create a new user."""
            return {"id": 1, **user.model_dump()}

        manager = ToolManager()
        manager.add_tool(create_user)

        tool = manager.get_tool("create_user")
        assert tool is not None
        assert tool.name == "create_user"
        assert tool.description == "Create a new user."
        assert tool.is_async is False
        assert "name" in tool.parameters["$defs"]["UserInput"]["properties"]
        assert "age" in tool.parameters["$defs"]["UserInput"]["properties"]
        assert "flag" in tool.parameters["properties"]

    def test_add_callable_object(self):
        """Test registering a callable object."""

        class MyTool:
            def __init__(self):
                self.__name__ = "MyTool"

            def __call__(self, x: int) -> int:
                return x * 2

        manager = ToolManager()
        tool = manager.add_tool(MyTool())
        assert tool.name == "MyTool"
        assert tool.is_async is False
        assert tool.parameters["properties"]["x"]["type"] == "integer"

    @pytest.mark.anyio
    async def test_add_async_callable_object(self):
        """Test registering an async callable object."""

        class MyAsyncTool:
            def __init__(self):
                self.__name__ = "MyAsyncTool"

            async def __call__(self, x: int) -> int:
                return x * 2

        manager = ToolManager()
        tool = manager.add_tool(MyAsyncTool())
        assert tool.name == "MyAsyncTool"
        assert tool.is_async is True
        assert tool.parameters["properties"]["x"]["type"] == "integer"

    def test_add_invalid_tool(self):
        manager = ToolManager()
        with pytest.raises(AttributeError):
            manager.add_tool(1)  # type: ignore

    def test_add_lambda(self):
        manager = ToolManager()
        tool = manager.add_tool(lambda x: x, name="my_tool")
        assert tool.name == "my_tool"

    def test_add_lambda_with_no_name(self):
        manager = ToolManager()
        with pytest.raises(ValueError, match="You must provide a name for lambda functions"):
            manager.add_tool(lambda x: x)

    def test_warn_on_duplicate_tools(self, caplog):
        """Test warning on duplicate tools."""

        def f(x: int) -> int:
            return x

        manager = ToolManager()
        manager.add_tool(f)
        with caplog.at_level(logging.WARNING):
            manager.add_tool(f)
            assert "Tool already exists: f" in caplog.text

    def test_disable_warn_on_duplicate_tools(self, caplog):
        """Test disabling warning on duplicate tools."""

        def f(x: int) -> int:
            return x

        manager = ToolManager()
        manager.add_tool(f)
        manager.warn_on_duplicate_tools = False
        with caplog.at_level(logging.WARNING):
            manager.add_tool(f)
            assert "Tool already exists: f" not in caplog.text


class TestCallTools:
    @pytest.mark.anyio
    async def test_call_tool(self):
        def add(a: int, b: int) -> int:
            """Add two numbers."""
            return a + b

        manager = ToolManager()
        manager.add_tool(add)
        result = await manager.call_tool("add", {"a": 1, "b": 2})
        assert result == 3

    @pytest.mark.anyio
    async def test_call_async_tool(self):
        async def double(n: int) -> int:
            """Double a number."""
            return n * 2

        manager = ToolManager()
        manager.add_tool(double)
        result = await manager.call_tool("double", {"n": 5})
        assert result == 10

    @pytest.mark.anyio
    async def test_call_object_tool(self):
        class MyTool:
            def __init__(self):
                self.__name__ = "MyTool"

            def __call__(self, x: int) -> int:
                return x * 2

        manager = ToolManager()
        tool = manager.add_tool(MyTool())
        result = await tool.run({"x": 5})
        assert result == 10

    @pytest.mark.anyio
    async def test_call_async_object_tool(self):
        class MyAsyncTool:
            def __init__(self):
                self.__name__ = "MyAsyncTool"

            async def __call__(self, x: int) -> int:
                return x * 2

        manager = ToolManager()
        tool = manager.add_tool(MyAsyncTool())
        result = await tool.run({"x": 5})
        assert result == 10

    @pytest.mark.anyio
    async def test_call_tool_with_default_args(self):
        def add(a: int, b: int = 1) -> int:
            """Add two numbers."""
            return a + b

        manager = ToolManager()
        manager.add_tool(add)
        result = await manager.call_tool("add", {"a": 1})
        assert result == 2

    @pytest.mark.anyio
    async def test_call_tool_with_missing_args(self):
        def add(a: int, b: int) -> int:
            """Add two numbers."""
            return a + b

        manager = ToolManager()
        manager.add_tool(add)
        with pytest.raises(ToolError):
            await manager.call_tool("add", {"a": 1})

    @pytest.mark.anyio
    async def test_call_unknown_tool(self):
        manager = ToolManager()
        with pytest.raises(ToolError):
            await manager.call_tool("unknown", {"a": 1})

    @pytest.mark.anyio
    async def test_call_tool_with_list_int_input(self):
        def sum_vals(vals: list[int]) -> int:
            return sum(vals)

        manager = ToolManager()
        manager.add_tool(sum_vals)
        # Try both with plain list and with JSON list
        result = await manager.call_tool("sum_vals", {"vals": "[1, 2, 3]"})
        assert result == 6
        result = await manager.call_tool("sum_vals", {"vals": [1, 2, 3]})
        assert result == 6

    @pytest.mark.anyio
    async def test_call_tool_with_list_str_or_str_input(self):
        def concat_strs(vals: list[str] | str) -> str:
            return vals if isinstance(vals, str) else "".join(vals)

        manager = ToolManager()
        manager.add_tool(concat_strs)
        # Try both with plain python object and with JSON list
        result = await manager.call_tool("concat_strs", {"vals": ["a", "b", "c"]})
        assert result == "abc"
        result = await manager.call_tool("concat_strs", {"vals": '["a", "b", "c"]'})
        assert result == "abc"
        result = await manager.call_tool("concat_strs", {"vals": "a"})
        assert result == "a"
        result = await manager.call_tool("concat_strs", {"vals": '"a"'})
        assert result == '"a"'

    @pytest.mark.anyio
    async def test_call_tool_with_complex_model(self):
        class MyShrimpTank(BaseModel):
            class Shrimp(BaseModel):
                name: str

            shrimp: list[Shrimp]
            x: None

        def name_shrimp(tank: MyShrimpTank, ctx: Context) -> list[str]:
            return [x.name for x in tank.shrimp]

        manager = ToolManager()
        manager.add_tool(name_shrimp)
        result = await manager.call_tool(
            "name_shrimp",
            {"tank": {"x": None, "shrimp": [{"name": "rex"}, {"name": "gertrude"}]}},
        )
        assert result == ["rex", "gertrude"]
        result = await manager.call_tool(
            "name_shrimp",
            {"tank": '{"x": null, "shrimp": [{"name": "rex"}, {"name": "gertrude"}]}'},
        )
        assert result == ["rex", "gertrude"]


class TestToolSchema:
    @pytest.mark.anyio
    async def test_context_arg_excluded_from_schema(self):
        def something(a: int, ctx: Context) -> int:
            return a

        manager = ToolManager()
        tool = manager.add_tool(something)
        assert "ctx" not in json.dumps(tool.parameters)
        assert "Context" not in json.dumps(tool.parameters)
        assert "ctx" not in tool.fn_metadata.arg_model.model_fields


class TestContextHandling:
    """Test context handling in the tool manager."""

    def test_context_parameter_detection(self):
        """Test that context parameters are properly detected in
        Tool.from_function()."""

        def tool_with_context(x: int, ctx: Context) -> str:
            return str(x)

        manager = ToolManager()
        tool = manager.add_tool(tool_with_context)
        assert tool.context_kwarg == "ctx"

        def tool_without_context(x: int) -> str:
            return str(x)

        tool = manager.add_tool(tool_without_context)
        assert tool.context_kwarg is None

        def tool_with_parametrized_context(x: int, ctx: Context[ServerSessionT, LifespanContextT, RequestT]) -> str:
            return str(x)

        tool = manager.add_tool(tool_with_parametrized_context)
        assert tool.context_kwarg == "ctx"

    @pytest.mark.anyio
    async def test_context_injection(self):
        """Test that context is properly injected during tool execution."""

        def tool_with_context(x: int, ctx: Context) -> str:
            assert isinstance(ctx, Context)
            return str(x)

        manager = ToolManager()
        manager.add_tool(tool_with_context)

        mcp = FastMCP()
        ctx = mcp.get_context()
        result = await manager.call_tool("tool_with_context", {"x": 42}, context=ctx)
        assert result == "42"

    @pytest.mark.anyio
    async def test_context_injection_async(self):
        """Test that context is properly injected in async tools."""

        async def async_tool(x: int, ctx: Context) -> str:
            assert isinstance(ctx, Context)
            return str(x)

        manager = ToolManager()
        manager.add_tool(async_tool)

        mcp = FastMCP()
        ctx = mcp.get_context()
        result = await manager.call_tool("async_tool", {"x": 42}, context=ctx)
        assert result == "42"

    @pytest.mark.anyio
    async def test_context_optional(self):
        """Test that context is optional when calling tools."""

        def tool_with_context(x: int, ctx: Context | None = None) -> str:
            return str(x)

        manager = ToolManager()
        manager.add_tool(tool_with_context)
        # Should not raise an error when context is not provided
        result = await manager.call_tool("tool_with_context", {"x": 42})
        assert result == "42"

    @pytest.mark.anyio
    async def test_context_error_handling(self):
        """Test error handling when context injection fails."""

        def tool_with_context(x: int, ctx: Context) -> str:
            raise ValueError("Test error")

        manager = ToolManager()
        manager.add_tool(tool_with_context)

        mcp = FastMCP()
        ctx = mcp.get_context()
        with pytest.raises(ToolError, match="Error executing tool tool_with_context"):
            await manager.call_tool("tool_with_context", {"x": 42}, context=ctx)


class TestToolAnnotations:
    def test_tool_annotations(self):
        """Test that tool annotations are correctly added to tools."""

        def read_data(path: str) -> str:
            """Read data from a file."""
            return f"Data from {path}"

        annotations = ToolAnnotations(
            title="File Reader",
            readOnlyHint=True,
            openWorldHint=False,
        )

        manager = ToolManager()
        tool = manager.add_tool(read_data, annotations=annotations)

        assert tool.annotations is not None
        assert tool.annotations.title == "File Reader"
        assert tool.annotations.readOnlyHint is True
        assert tool.annotations.openWorldHint is False

    @pytest.mark.anyio
    async def test_tool_annotations_in_fastmcp(self):
        """Test that tool annotations are included in MCPTool conversion."""

        app = FastMCP()

        @app.tool(annotations=ToolAnnotations(title="Echo Tool", readOnlyHint=True))
        def echo(message: str) -> str:
            """Echo a message back."""
            return message

        tools = await app.list_tools()
        assert len(tools) == 1
        assert tools[0].annotations is not None
        assert tools[0].annotations.title == "Echo Tool"
        assert tools[0].annotations.readOnlyHint is True
