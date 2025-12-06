import os
import json
import argparse
from typing import Dict, Any, Optional
import asyncio
import sys

# Apify SDK imports
from apify import Actor
from apify_client import ApifyClient

# Retell AI SDK imports
try:
    from retell import Retell
except ImportError:
    Retell = None
    print("Warning: retell-sdk not installed. Install with: pip install retell-sdk")

# --- CONFIGURATION ---

# Default configuration values
DEFAULT_AGENT_ID = None  # Must be provided
DEFAULT_FROM_NUMBER = None  # Must be provided
DEFAULT_TO_NUMBER = None  # Must be provided

# --- HELPER FUNCTIONS ---

def load_retell_config(script_dir: str) -> Dict[str, Any]:
    """Load Retell configuration from local file."""
    config_file = os.path.join(script_dir, 'retell_config.json')
    if os.path.exists(config_file):
        try:
            with open(config_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            Actor.log.warning(f"Could not read retell_config.json: {e}")
    return {}

# --- MAIN ACTOR LOGIC ---

async def main(
    from_number_override: Optional[str] = None,
    to_number_override: Optional[str] = None,
    agent_id_override: Optional[str] = None,
    dynamic_variables_override: Optional[Dict[str, str]] = None
):
    """The main function of the Apify Actor for making Retell phone calls."""
    async with Actor:
        Actor.log.info('Retell Phone Call Actor started.')

        # 1. Get Input and Configuration
        actor_input = await Actor.get_input() or {}
        
        # Load local config file if it exists (for local testing)
        script_dir = os.path.dirname(os.path.abspath(__file__))
        local_config = load_retell_config(script_dir)
        
        # Get API key - priority: environment > local config > actor input
        api_key = (
            os.getenv("RETELL_API_KEY") or 
            local_config.get("api_key") or 
            actor_input.get("retell_api_key")
        )
        
        if not api_key:
            error_msg = "RETELL_API_KEY not provided. Set it in environment, retell_config.json, or actor input."
            Actor.log.error(error_msg)
            print(f"\n=== ERROR ===")
            print(error_msg)
            print("=" * 60 + "\n")
            return
        
        # Get phone call parameters
        # Priority: function parameter > command-line arg > actor input > local file > default
        from_number = (
            from_number_override or
            globals().get('FROM_NUMBER_ARG') or
            actor_input.get('from_number') or
            local_config.get('from_number') or
            DEFAULT_FROM_NUMBER
        )
        
        to_number = (
            to_number_override or
            globals().get('TO_NUMBER_ARG') or
            actor_input.get('to_number') or
            local_config.get('to_number') or
            DEFAULT_TO_NUMBER
        )
        
        agent_id = (
            agent_id_override or
            globals().get('AGENT_ID_ARG') or
            actor_input.get('agent_id') or
            local_config.get('agent_id') or
            DEFAULT_AGENT_ID
        )
        
        # Get dynamic variables
        dynamic_variables = (
            dynamic_variables_override or
            globals().get('DYNAMIC_VARIABLES_ARG') or
            actor_input.get('retell_llm_dynamic_variables') or
            local_config.get('retell_llm_dynamic_variables') or
            {}
        )
        
        # Validate required parameters
        if not from_number:
            error_msg = "from_number is required. Provide via --from-number, actor input, or retell_config.json"
            Actor.log.error(error_msg)
            print(f"\n=== ERROR ===")
            print(error_msg)
            print("=" * 60 + "\n")
            return
        
        if not to_number:
            error_msg = "to_number is required. Provide via --to-number, actor input, or retell_config.json"
            Actor.log.error(error_msg)
            print(f"\n=== ERROR ===")
            print(error_msg)
            print("=" * 60 + "\n")
            return
        
        if not agent_id:
            error_msg = "agent_id is required. Provide via --agent-id, actor input, or retell_config.json"
            Actor.log.error(error_msg)
            print(f"\n=== ERROR ===")
            print(error_msg)
            print("=" * 60 + "\n")
            return
        
        Actor.log.info(f"Making phone call:")
        Actor.log.info(f"  From: {from_number}")
        Actor.log.info(f"  To: {to_number}")
        Actor.log.info(f"  Agent ID: {agent_id}")
        if dynamic_variables:
            Actor.log.info(f"  Dynamic Variables: {dynamic_variables}")
        
        # 2. Initialize Retell Client
        if not Retell:
            error_msg = "retell-sdk not installed. Install with: pip install retell-sdk"
            Actor.log.error(error_msg)
            print(f"\n=== ERROR ===")
            print(error_msg)
            print("=" * 60 + "\n")
            return
        
        try:
            client = Retell(api_key=api_key)
        except Exception as e:
            error_msg = f"Failed to initialize Retell client: {e}"
            Actor.log.error(error_msg)
            print(f"\n=== ERROR ===")
            print(error_msg)
            print("=" * 60 + "\n")
            return
        
        # 3. Create Phone Call
        try:
            call_params = {
                "from_number": from_number,
                "to_number": to_number,
                "agent_id": agent_id,
            }
            
            # Add optional parameters
            if dynamic_variables:
                call_params["retell_llm_dynamic_variables"] = dynamic_variables
            
            # Add other optional parameters from actor input
            optional_params = [
                "custom_sip_headers",
                "data_storage_setting",
                "opt_in_signed_url",
            ]
            for param in optional_params:
                if param in actor_input:
                    call_params[param] = actor_input[param]
            
            Actor.log.info("Creating phone call via Retell API...")
            # Retell SDK - call the API (handles both sync and async)
            try:
                # Try async first
                phone_call_response = await client.call.create_phone_call(call_params)
            except TypeError:
                # If it's sync, run in executor
                loop = asyncio.get_event_loop()
                phone_call_response = await loop.run_in_executor(
                    None, 
                    lambda: client.call.create_phone_call(call_params)
                )
            
            # Extract call information
            call_id = phone_call_response.get("call_id")
            call_status = phone_call_response.get("call_status")
            agent_name = phone_call_response.get("agent_name")
            
            Actor.log.info(f"Phone call created successfully!")
            Actor.log.info(f"  Call ID: {call_id}")
            Actor.log.info(f"  Status: {call_status}")
            Actor.log.info(f"  Agent: {agent_name}")
            
            # Store result
            result = {
                "call_id": call_id,
                "call_status": call_status,
                "from_number": from_number,
                "to_number": to_number,
                "agent_id": agent_id,
                "agent_name": agent_name,
                "call_type": phone_call_response.get("call_type"),
                "direction": phone_call_response.get("direction"),
                "metadata": phone_call_response.get("metadata", {}),
            }
            
            await Actor.push_data(result)
            
            # Print results summary for local execution
            print("\n" + "=" * 60, flush=True)
            print("RETELL PHONE CALL RESULTS", flush=True)
            print("=" * 60, flush=True)
            print(f"Call ID: {call_id}", flush=True)
            print(f"Status: {call_status}", flush=True)
            print(f"From: {from_number}", flush=True)
            print(f"To: {to_number}", flush=True)
            print(f"Agent ID: {agent_id}", flush=True)
            if agent_name:
                print(f"Agent Name: {agent_name}", flush=True)
            if dynamic_variables:
                print(f"Dynamic Variables: {json.dumps(dynamic_variables, indent=2)}", flush=True)
            print("\nNote: Call is now in progress.", flush=True)
            print("Use Retell API or dashboard to check call status and get transcript.", flush=True)
            print("=" * 60 + "\n", flush=True)
            sys.stdout.flush()
            
        except Exception as e:
            error_msg = f"Failed to create phone call: {e}"
            Actor.log.error(error_msg)
            import traceback
            Actor.log.error(traceback.format_exc())
            print(f"\n=== ERROR ===")
            print(error_msg)
            print(traceback.format_exc())
            print("=" * 60 + "\n")
            return
        
        Actor.log.info('Retell Phone Call Actor finished.')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Retell Phone Call Processor - Make phone calls via Retell AI')
    parser.add_argument('--from-number', '-f', type=str, help='Phone number to call from (e.g., +14157774444)')
    parser.add_argument('--to-number', '-t', type=str, help='Phone number to call to (e.g., +12137774445)')
    parser.add_argument('--agent-id', '-a', type=str, help='Retell agent ID')
    parser.add_argument('--dynamic-variables', '-d', type=str, help='Dynamic variables as JSON string (e.g., \'{"customer_name":"John"}\')')
    args = parser.parse_args()
    
    # Set global variables for backward compatibility
    if args.from_number:
        globals()['FROM_NUMBER_ARG'] = args.from_number
    if args.to_number:
        globals()['TO_NUMBER_ARG'] = args.to_number
    if args.agent_id:
        globals()['AGENT_ID_ARG'] = args.agent_id
    if args.dynamic_variables:
        try:
            globals()['DYNAMIC_VARIABLES_ARG'] = json.loads(args.dynamic_variables)
        except json.JSONDecodeError:
            print(f"Error: Invalid JSON in --dynamic-variables: {args.dynamic_variables}")
            sys.exit(1)
    
    # Parse dynamic variables if provided
    dynamic_vars = None
    if args.dynamic_variables:
        try:
            dynamic_vars = json.loads(args.dynamic_variables)
        except json.JSONDecodeError:
            print(f"Error: Invalid JSON in --dynamic-variables: {args.dynamic_variables}")
            sys.exit(1)
    
    # Pass arguments directly to main function
    asyncio.run(main(
        from_number_override=args.from_number,
        to_number_override=args.to_number,
        agent_id_override=args.agent_id,
        dynamic_variables_override=dynamic_vars
    ))

