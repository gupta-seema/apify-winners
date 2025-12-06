import asyncio
import os
import sys
import argparse
from contextlib import AsyncExitStack
from typing import Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from anthropic import AsyncAnthropic
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Initialize Anthropic Client
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
if not ANTHROPIC_API_KEY:
    print("WARNING: ANTHROPIC_API_KEY not found in environment.")
    # We don't exit here to allow import checks, but main() will fail if key is missing.

anthropic_client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

class MCPClient:
    def __init__(self, model_id: str):
        self.session: Optional[ClientSession] = None
        self.exit_stack = AsyncExitStack()
        self.model_id = model_id

    async def connect(self):
        """Connect to the Apify MCP server via npx."""
        print(f"Connecting to Apify MCP Server via npx...")
        
        command = "npx"
        args = ["-y", "@apify/actors-mcp-server"]
        
        env = os.environ.copy()
        params = StdioServerParameters(command=command, args=args, env=env)
        
        reader, writer = await self.exit_stack.enter_async_context(
            stdio_client(params)
        )

        self.session = await self.exit_stack.enter_async_context(
            ClientSession(reader, writer)
        )
        await self.session.initialize()

        tools = await self.session.list_tools()
        print(f"Connected to Apify! Found {len(tools.tools)} tools.")

    async def process_query(self, query: str):
        messages = [{"role": "user", "content": query}]

        # 1. Fetch available tools once
        mcp_tools = await self.session.list_tools()
        anthropic_tools = [{
            "name": t.name,
            "description": t.description,
            "input_schema": t.inputSchema
        } for t in mcp_tools.tools]

        print(f"\nProcessing query with model: {self.model_id}...")

        # 2. Tool Use Loop
        # We loop until the model decides to stop using tools (stop_reason != "tool_use")
        # or we hit a safety limit (e.g., 15 turns).
        MAX_TURNS = 15
        
        for turn in range(MAX_TURNS):
            try:
                # Call Claude with current history
                response = await anthropic_client.messages.create(
                    model=self.model_id,
                    max_tokens=2048,
                    messages=messages,
                    tools=anthropic_tools
                )
            except Exception as e:
                return f"Error calling Claude API: {e}"

            # Append the assistant's response (text + tool requests) to history
            messages.append({"role": "assistant", "content": response.content})

            # Check if we are done (no more tools needed)
            if response.stop_reason != "tool_use":
                # Extract and return final text
                final_text = []
                for block in response.content:
                    if block.type == "text":
                        final_text.append(block.text)
                return "\n".join(final_text)

            # --- If we are here, the model wants to use tools ---
            
            tool_results_content = []

            # Iterate through all blocks to find tool uses
            for block in response.content:
                if block.type == "tool_use":
                    tool_name = block.name
                    tool_args = block.input
                    tool_id = block.id

                    print(f"[Turn {turn+1}] Executing: {tool_name}")
                    # print(f"  Args: {tool_args}") # Uncomment for verbose debugging

                    try:
                        # Execute tool via MCP
                        result = await self.session.call_tool(tool_name, tool_args)
                        
                        # Format output
                        tool_output = "\n".join(
                            [c.text for c in result.content if c.type == "text"]
                        )
                        if not tool_output:
                            tool_output = "Tool executed successfully (no text output)."
                            
                    except Exception as e:
                        tool_output = f"Error executing tool: {str(e)}"
                        print(f"  Error: {tool_output}")

                    # Add result to the list of tool results for this turn
                    tool_results_content.append({
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": tool_output
                    })

            # Append all tool results as a single USER message
            messages.append({
                "role": "user",
                "content": tool_results_content
            })
            
            # The loop now repeats: Claude sees the results and decides what to do next

        return "Error: Maximum tool turns reached."

    async def chat_loop(self):
        print(f"MCP Client Started! Type 'quit' to exit.")
        while True:
            q = input("\nQuery: ").strip()
            if q.lower() in ('quit', 'exit'):
                break
            resp = await self.process_query(q)
            print(f"\nFinal Response:\n{resp}")

    async def cleanup(self):
        await self.exit_stack.aclose()

async def main():
    parser = argparse.ArgumentParser()
    # Default fallback to Opus 3.0 if Sonnet 3.5 (20240620) is unavailable
    parser.add_argument("--model", default="claude-sonnet-4-5", help="Anthropic Model ID")
    args = parser.parse_args()

    client = MCPClient(model_id=args.model)
    try:
        await client.connect()
        await client.chat_loop()
    finally:
        await client.cleanup()

if __name__ == "__main__":
    asyncio.run(main())