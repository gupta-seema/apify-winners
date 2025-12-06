import asyncio
import os
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Define the connection parameters
# We use 'npx' to download and run the Node.js server on the fly
server_params = StdioServerParameters(
    command="npx",
    args=["-y", "@apify/actors-mcp-server"],
    env={
        "PATH": os.environ["PATH"],  # distinct from the OS environment
        "APIFY_TOKEN": "apify_api_LOH89K1VJKFnY02AY5aQwruxbMVh2R1Zh9VV"
    }
)

async def run():
    # Connect via stdio
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # 1. Initialize the connection
            await session.initialize()
            
            # 2. List available tools (Verification)
            tools = await session.list_tools()
            print(f"Connected! Found {len(tools.tools)} tools.")
            
            # Example: Print the first tool's name
            if tools.tools:
                print(f"First tool: {tools.tools}")

            # 3. (Optional) Call a tool
            # result = await session.call_tool("search-actors", arguments={"query": "instagram"})
            # print(result)

if __name__ == "__main__":
    asyncio.run(run())