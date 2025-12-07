import asyncio
import os
import sys
import argparse
import subprocess
import shutil
import json
from contextlib import AsyncExitStack
from typing import Optional

# MCP & AI Imports
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from anthropic import AsyncAnthropic
from dotenv import load_dotenv

# Apify Imports
try:
    from apify_client import ApifyClient
except ImportError:
    print("Error: 'apify-client' is missing. Install it with: pip install apify-client")
    sys.exit(1)

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
if not ANTHROPIC_API_KEY:
    print("WARNING: ANTHROPIC_API_KEY not found.")
    
anthropic_client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

class MCPClient:
    def __init__(self, model_id: str):
        self.session: Optional[ClientSession] = None
        self.exit_stack = AsyncExitStack()
        self.model_id = model_id
        self.messages = [] 
        self.system_prompt = """You are an expert AI developer with access to Apify tools.

YOUR GOAL: Solve the user's problem using Apify Actors.

STRATEGY:
1. FIRST, use 'search-actors' to find an existing solution.
2. IF a good Actor exists, use 'call-actor'.
3. IF NO suitable Actor exists, you must BUILD one using 'build_apify_actor'.

WHEN BUILDING AN ACTOR:
- You will be asked to provide the Python code for 'main.py'.
- The code MUST use the Apify SDK ('from apify import Actor').
- It MUST be a complete, runnable script.
- The tool will automatically handle 'actor.json' configuration and publishing.
- IMMEDIATELY after building, use 'call-actor' to run your new creation using the ID returned.
"""

    async def connect(self):
        print(f"Connecting to Apify MCP Server via npx...")
        command = "npx"
        args = ["-y", "@apify/actors-mcp-server"]
        env = os.environ.copy()
        
        params = StdioServerParameters(command=command, args=args, env=env)
        reader, writer = await self.exit_stack.enter_async_context(stdio_client(params))
        self.session = await self.exit_stack.enter_async_context(ClientSession(reader, writer))
        await self.session.initialize()
        print(f"Connected to Apify!")

    async def create_gmail_draft(self, to: str, subject: str, body: str) -> str:
        """Local tool to create a Gmail draft via main.py"""
        script_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        gmail_main = os.path.join(script_dir, 'gmail_processor', 'main.py')
        
        cmd = [sys.executable, gmail_main, '--mode', 'draft', '--to', to, '--subject', subject, '--body', body]
        try:
            process = subprocess.run(cmd, capture_output=True, text=True, cwd=script_dir)
            return f"Draft output: {process.stdout} {process.stderr}" if process.returncode == 0 else f"Error: {process.stderr}"
        except Exception as e:
            return f"Error executing draft script: {e}"

    async def build_apify_actor(self, actor_name: str, python_code: str) -> str:
        """
        Local tool to create, configure, deploy, and publish a new Apify Actor.
        """
        base_dir = os.path.dirname(os.path.abspath(__file__))
        actors_dir = os.path.join(base_dir, "generated_actors")
        actor_path = os.path.join(actors_dir, actor_name)
        
        os.makedirs(actors_dir, exist_ok=True)
        
        print(f"\n[Builder] Creating new Actor '{actor_name}'...")

        try:
            # 1. Clean up previous attempts
            if os.path.exists(actor_path):
                shutil.rmtree(actor_path)

            # 2. Initialize new Actor using Apify CLI
            # 'python-start' template is standard for Python Actors
            cmd_create = ["apify", "create", actor_name, "--template", "python-start"]
            proc_create = subprocess.run(cmd_create, cwd=actors_dir, capture_output=True, text=True)
            
            if proc_create.returncode != 0:
                return f"Failed to run 'apify create': {proc_create.stderr}"

            # 3. Inject Categories & Metadata into local actor.json
            # We do this locally first so 'apify push' sends it up.
            actor_json_path = os.path.join(actor_path, ".actor", "actor.json")
            if not os.path.exists(actor_json_path):
                actor_json_path = os.path.join(actor_path, "actor.json")
            
            if os.path.exists(actor_json_path):
                try:
                    with open(actor_json_path, 'r') as f:
                        config = json.load(f)
                    
                    # Standard API-compatible category
                    config['categories'] = ["DEVELOPER_TOOLS"] 
                    config['title'] = actor_name.replace('-', ' ').title()
                    config['description'] = "Auto-generated custom actor."
                    
                    with open(actor_json_path, 'w') as f:
                        json.dump(config, f, indent=4)
                    print(f"[Builder] Configured actor.json with required metadata.")
                except Exception as e:
                    print(f"[Builder] Warning: Could not update actor.json: {e}")

            # 4. Overwrite main.py with LLM code
            main_py_path = os.path.join(actor_path, "src", "main.py")
            os.makedirs(os.path.dirname(main_py_path), exist_ok=True)
            with open(main_py_path, "w") as f:
                f.write(python_code)

            # 5. Push (Deploy) to Apify
            print(f"[Builder] Deploying code to Apify...")
            cmd_push = ["apify", "push"]
            # Pipe 'yes' just in case
            proc_push = subprocess.run(cmd_push, cwd=actor_path, capture_output=True, text=True, input="y\n")
            
            if proc_push.returncode != 0:
                return f"Failed to push actor: {proc_push.stderr}"
            
            # 6. Make Public via API
            token = os.getenv("APIFY_TOKEN")
            final_actor_id = f"unknown/{actor_name}"
            
            if token:
                try:
                    client_api = ApifyClient(token)
                    me = client_api.user().get()
                    username = me.get('username')
                    final_actor_id = f"{username}/{actor_name}"
                    
                    print(f"[Builder] Setting {final_actor_id} to PUBLIC...")
                    
                    # We pass the category again explicitly to satisfy the 'isPublic' validation
                    client_api.actor(final_actor_id).update(
                        is_public=True,
                        title=actor_name.replace('-', ' ').title(),
                        description="Auto-generated by MCP Client AI.",
                        categories=["DEVELOPER_TOOLS"], # Use safe, standard category
                        seo_title=actor_name.replace('-', ' ').title(),
                        seo_description="Auto-generated by MCP Client AI."
                    )
                    print(f"[Builder] Success! Actor is now PUBLIC.")
                except Exception as e:
                    # Even if public switch fails, we return the ID so the user can still run it privately
                    print(f"[Builder] Warning: Failed to set public visibility: {e}")
            
            return f"Actor built and deployed! ID: {final_actor_id}. You can now run it using the 'call-actor' tool."

        except Exception as e:
            return f"Builder Exception: {str(e)}"

    async def process_query(self, query: str):
        self.messages.append({"role": "user", "content": query})

        # 1. Fetch Remote Tools
        mcp_tools = await self.session.list_tools()
        
        # 2. Define Local Tools
        local_tools = [
            {
                "name": "create_gmail_draft",
                "description": "Create a new email draft in Gmail.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "to": {"type": "string"},
                        "subject": {"type": "string"},
                        "body": {"type": "string"}
                    },
                    "required": ["to", "subject", "body"]
                }
            },
            {
                "name": "build_apify_actor",
                "description": "Build and deploy a NEW Apify Actor using Python code. Use this when no existing Actor matches the user's needs.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "actor_name": {"type": "string", "description": "A unique kebab-case name (e.g. 'my-scraper')"},
                        "python_code": {"type": "string", "description": "The complete Python source code for src/main.py. Must import Apify Actor."}
                    },
                    "required": ["actor_name", "python_code"]
                }
            }
        ]

        all_tools = []
        for t in mcp_tools.tools:
            all_tools.append({
                "name": t.name,
                "description": t.description,
                "input_schema": t.inputSchema
            })
        all_tools.extend(local_tools)

        print(f"\nThinking...")

        MAX_TURNS = 15
        for turn in range(MAX_TURNS):
            response = await anthropic_client.messages.create(
                model=self.model_id,
                max_tokens=4096,
                system=self.system_prompt,
                messages=self.messages,
                tools=all_tools
            )

            self.messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason != "tool_use":
                text_content = next((b.text for b in response.content if b.type == "text"), "")
                return text_content

            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    t_name = block.name
                    t_args = block.input
                    t_id = block.id
                    print(f"[Executing Tool: {t_name}]")

                    try:
                        if t_name == "create_gmail_draft":
                            res_text = await self.create_gmail_draft(**t_args)
                        elif t_name == "build_apify_actor":
                            res_text = await self.build_apify_actor(**t_args)
                        else:
                            res = await self.session.call_tool(t_name, t_args)
                            res_text = "\n".join([c.text for c in res.content if c.type == "text"])
                    except Exception as e:
                        res_text = f"Error: {str(e)}"

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": t_id,
                        "content": res_text
                    })

            self.messages.append({"role": "user", "content": tool_results})

        return "Error: Maximum turns reached."

    async def execute_gmail_cli(self, query):
        script_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        gmail_main = os.path.join(script_dir, 'gmail_processor', 'main.py')
        real_query = query.split(":", 1)[1].strip()
        
        print("Executing Gmail Search...")
        cmd = [sys.executable, gmail_main, '--mode', 'search', '--query', real_query]
        res = subprocess.run(cmd, capture_output=True, text=True, cwd=script_dir)
        output = res.stdout + "\n" + res.stderr
        print(output)
        
        self.messages.append({
            "role": "user", 
            "content": f"I ran a tool to search Gmail. Output:\n{output}\nUse this for context."
        })
        self.messages.append({"role": "assistant", "content": "Understood."})

    async def chat_loop(self):
        print(f"MCP Client Started! Type 'quit' to exit.")
        while True:
            q = input("\nQuery: ").strip()
            if q.lower() in ('quit', 'exit'):
                break
            
            if q.lower().startswith("gmail:"):
                await self.execute_gmail_cli(q)
            else:
                resp = await self.process_query(q)
                print(f"\nFinal Response:\n{resp}")

    async def cleanup(self):
        await self.exit_stack.aclose()

async def main():
    parser = argparse.ArgumentParser()
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