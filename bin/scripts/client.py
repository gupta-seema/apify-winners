import asyncio
import os
import sys
import argparse
import subprocess
import json
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
        # Check if query is Gmail-related
        gmail_keywords = ['email', 'gmail', 'inbox', 'message', 'mail', 'inbox', 'attachment', 'pdf', 'invoice']
        is_gmail_query = any(keyword in query.lower() for keyword in gmail_keywords)
        
        # If it's a Gmail query, add context about Gmail processor capability
        if is_gmail_query:
            system_context = """You can help users search Gmail by generating Gmail search queries. 
If the user wants to search Gmail, you should:
1. Generate an appropriate Gmail search query using Gmail search syntax
2. Mention that the query can be executed using the Gmail processor

Gmail search syntax examples:
- subject:"text" - search in subject
- from:email@example.com - search by sender
- has:attachment - emails with attachments
- after:YYYY/MM/DD - emails after date
- before:YYYY/MM/DD - emails before date
- is:unread - unread emails
- Combine with spaces: subject:invoice after:2024/01/01"""
            messages = [{"role": "system", "content": system_context}, {"role": "user", "content": query}]
        else:
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

    async def generate_gmail_query(self, user_request: str) -> str:
        """Use LLM to generate a Gmail search query from natural language request."""
        prompt = f"""Convert the following user request into a Gmail search query.

User request: {user_request}

Generate a Gmail search query that would find emails matching this request. 
Use Gmail search syntax like:
- subject:"text" for subject searches (use quotes for phrases)
- from:email@example.com for sender
- has:attachment for emails with attachments
- after:YYYY/MM/DD for date filters
- before:YYYY/MM/DD for date filters
- is:unread, is:read for read status
- Combine multiple criteria with spaces

IMPORTANT: 
- If the subject contains spaces, wrap it in quotes: subject:"Rate Confirmation"
- Return ONLY the Gmail search query string, nothing else
- No explanation, no markdown, no code blocks
- Just the raw query string

Example: If user says "find invoices from last month", return: subject:invoice after:2024/11/01 before:2024/12/01
Example: If user says "emails with Rate Confirmation", return: subject:"Rate Confirmation"

Gmail query:"""
        
        try:
            response = await anthropic_client.messages.create(
                model=self.model_id,
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}]
            )
            
            # Extract the query from response
            query = ""
            for block in response.content:
                if block.type == "text":
                    query = block.text.strip()
                    # Remove markdown code blocks if present
                    if query.startswith("```"):
                        lines = query.split("\n")
                        query = "\n".join([l for l in lines if not l.strip().startswith("```")]).strip()
                    # Remove any outer quotes (but keep quotes inside the query)
                    if query.startswith('"') and query.endswith('"'):
                        query = query[1:-1]
                    elif query.startswith("'") and query.endswith("'"):
                        query = query[1:-1]
                    break
            
            return query
        except Exception as e:
            return f"Error generating query: {e}"

    async def execute_gmail_processor(self, gmail_query: str, mime_types: Optional[list] = None) -> str:
        """Execute the Gmail processor with the given query."""
        script_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        gmail_main = os.path.join(script_dir, 'gmail_processor', 'main.py')
        
        if not os.path.exists(gmail_main):
            return f"Error: Gmail processor not found at {gmail_main}"
        
        # Build command
        cmd = [sys.executable, gmail_main, '--query', gmail_query]
        if mime_types:
            cmd.extend(['--mime-types'] + mime_types)
        
        try:
            # Run subprocess and capture both stdout and stderr
            # Use Popen for better control over output streams
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=script_dir,
                env=os.environ.copy(),
                bufsize=1  # Line buffered
            )
            
            # Wait for process to complete and get output
            stdout, stderr = process.communicate()
            returncode = process.returncode
            
            # Combine stdout and stderr - Actor logs go to stderr, print() goes to stdout
            # We want both to see the full output
            output_parts = []
            
            # Add stderr first (contains Actor logs)
            if stderr and stderr.strip():
                output_parts.append(stderr)
            
            # Add stdout (contains the formatted results)
            if stdout and stdout.strip():
                output_parts.append(stdout)
            
            output = "\n".join(output_parts)
            
            if returncode == 0:
                # Return the full output (which now includes formatted results)
                if output.strip():
                    return output
                else:
                    return "Gmail processor executed successfully (no output)."
            else:
                return f"Gmail processor error (exit code {returncode}):\n{output}"
        except Exception as e:
            import traceback
            return f"Error executing Gmail processor: {e}\n{traceback.format_exc()}"

    async def generate_phone_call_params(self, user_request: str) -> Dict[str, Any]:
        """Use LLM to generate phone call parameters from natural language request."""
        prompt = f"""Convert the following user request into phone call parameters for Retell AI.

User request: {user_request}

Extract the following information:
1. from_number - The phone number to call from (must be a valid phone number with country code, e.g., +14157774444)
2. to_number - The phone number to call to (must be a valid phone number with country code, e.g., +12137774445)
3. agent_id - The Retell agent ID to use for the call
4. dynamic_variables (optional) - Any context or variables to pass to the agent (as JSON object)

Return ONLY a valid JSON object with these fields. No explanation, no markdown, just the JSON.

Example: If user says "call +12137774445 from +14157774444 using agent abc123", return:
{{"from_number": "+14157774444", "to_number": "+12137774445", "agent_id": "abc123"}}

Example: If user says "call John at +12137774445 with customer name John Doe", return:
{{"from_number": "+14157774444", "to_number": "+12137774445", "agent_id": "abc123", "dynamic_variables": {{"customer_name": "John Doe"}}}}

Phone call parameters (JSON only):"""
        
        try:
            response = await anthropic_client.messages.create(
                model=self.model_id,
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}]
            )
            
            # Extract the JSON from response
            json_str = ""
            for block in response.content:
                if block.type == "text":
                    json_str = block.text.strip()
                    # Remove markdown code blocks if present
                    if json_str.startswith("```"):
                        lines = json_str.split("\n")
                        json_str = "\n".join([l for l in lines if not l.strip().startswith("```")]).strip()
                    # Remove any outer quotes
                    if json_str.startswith('"') and json_str.endswith('"'):
                        json_str = json_str[1:-1]
                    break
            
            # Parse JSON
            try:
                params = json.loads(json_str)
                return params
            except json.JSONDecodeError as e:
                return {"error": f"Invalid JSON response: {e}", "raw": json_str}
        except Exception as e:
            return {"error": f"Error generating phone call parameters: {e}"}

    async def execute_retell_processor(self, from_number: str, to_number: str, agent_id: str, dynamic_variables: Optional[Dict] = None) -> str:
        """Execute the Retell phone call processor with the given parameters."""
        script_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        retell_main = os.path.join(script_dir, 'retell_processor', 'main.py')
        
        if not os.path.exists(retell_main):
            return f"Error: Retell processor not found at {retell_main}"
        
        # Build command
        cmd = [sys.executable, retell_main, '--from-number', from_number, '--to-number', to_number, '--agent-id', agent_id]
        
        if dynamic_variables:
            cmd.extend(['--dynamic-variables', json.dumps(dynamic_variables)])
        
        try:
            # Run subprocess and capture both stdout and stderr
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=script_dir,
                env=os.environ.copy(),
                bufsize=1
            )
            
            # Wait for process to complete and get output
            stdout, stderr = process.communicate()
            returncode = process.returncode
            
            # Combine stdout and stderr
            output_parts = []
            if stderr and stderr.strip():
                output_parts.append(stderr)
            if stdout and stdout.strip():
                output_parts.append(stdout)
            
            output = "\n".join(output_parts)
            
            if returncode == 0:
                if output.strip():
                    return output
                else:
                    return "Retell phone call processor executed successfully (no output)."
            else:
                return f"Retell processor error (exit code {returncode}):\n{output}"
        except Exception as e:
            import traceback
            return f"Error executing Retell processor: {e}\n{traceback.format_exc()}"

    async def chat_loop(self):
        print(f"MCP Client Started! Type 'quit' to exit.")
        print("Special commands:")
        print("  - 'gmail: <your request>' - Generate and execute Gmail query")
        print("  - 'retell: <your request>' or 'call: <your request>' - Generate and make phone call")
        print("  - 'quit' or 'exit' - Exit the client")
        while True:
            q = input("\nQuery: ").strip()
            if q.lower() in ('quit', 'exit'):
                break
            
            # Check if it's a Gmail request
            if q.lower().startswith('gmail:'):
                user_request = q[6:].strip()  # Remove 'gmail:' prefix
                print(f"\nGenerating Gmail query for: {user_request}")
                gmail_query = await self.generate_gmail_query(user_request)
                print(f"Generated query: {gmail_query}")
                
                if not gmail_query.startswith("Error"):
                    print("\nExecuting Gmail processor...")
                    result = await self.execute_gmail_processor(gmail_query)
                    if result:
                        print(f"\n{result}")
                    else:
                        print("\nGmail processor completed but returned no output.")
                else:
                    print(f"\n{gmail_query}")
            # Check if it's a Retell phone call request
            elif q.lower().startswith('retell:') or q.lower().startswith('call:'):
                prefix_len = 7 if q.lower().startswith('retell:') else 5
                user_request = q[prefix_len:].strip()  # Remove prefix
                print(f"\nGenerating phone call parameters for: {user_request}")
                call_params = await self.generate_phone_call_params(user_request)
                
                if "error" in call_params:
                    print(f"\nError: {call_params.get('error', 'Unknown error')}")
                    if "raw" in call_params:
                        print(f"Raw response: {call_params['raw']}")
                else:
                    from_num = call_params.get("from_number")
                    to_num = call_params.get("to_number")
                    agent_id = call_params.get("agent_id")
                    dynamic_vars = call_params.get("dynamic_variables")
                    
                    print(f"Generated parameters:")
                    print(f"  From: {from_num}")
                    print(f"  To: {to_num}")
                    print(f"  Agent ID: {agent_id}")
                    if dynamic_vars:
                        print(f"  Dynamic Variables: {json.dumps(dynamic_vars, indent=2)}")
                    
                    if not from_num or not to_num or not agent_id:
                        print("\nError: Missing required parameters (from_number, to_number, or agent_id)")
                    else:
                        print("\nExecuting Retell phone call processor...")
                        result = await self.execute_retell_processor(from_num, to_num, agent_id, dynamic_vars)
                        if result:
                            print(f"\n{result}")
                        else:
                            print("\nRetell processor completed but returned no output.")
            else:
                resp = await self.process_query(q)
                print(f"\nFinal Response:\n{resp}")

    async def cleanup(self):
        await self.exit_stack.aclose()

async def main():
    parser = argparse.ArgumentParser()
    # Default fallback to Opus 3.0 if Sonnet 3.5 (20240620) is unavailable
    parser.add_argument("--model", default=os.getenv("ANTHROPIC_MODEL"), help="Anthropic Model ID")
    args = parser.parse_args()

    client = MCPClient(model_id=args.model)
    try:
        await client.connect()
        await client.chat_loop()
    finally:
        await client.cleanup()

if __name__ == "__main__":
    asyncio.run(main())