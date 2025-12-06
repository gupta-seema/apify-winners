# token_generator.py
import os
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow
import json

# The SCOPE from your Apify Actor
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly'] 

def generate_credentials_json():
    """Performs the OAuth flow and prints the resulting JSON credentials."""
    
    # Get the directory where this script is located
    script_dir = Path(__file__).parent
    client_secret_path = script_dir / 'client_secret.json'
    
    # Check if the file exists
    if not client_secret_path.exists():
        print(f"Error: client_secret.json not found at {client_secret_path}")
        print(f"Please ensure client_secret.json is in the same directory as this script.")
        return
    
    # Load and validate the client secrets file
    try:
        with open(client_secret_path, 'r') as f:
            client_config = json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error: client_secret.json is not valid JSON: {e}")
        return
    except Exception as e:
        print(f"Error reading client_secret.json: {e}")
        return
    
    # Convert "web" format to "installed" format if needed
    # InstalledAppFlow expects "installed" key with specific OAuth URIs
    if "web" in client_config and "installed" not in client_config:
        print("Converting 'web' OAuth client to 'installed' format...")
        web_config = client_config.pop("web")
        
        # Create installed config with required fields
        # For installed apps, redirect_uris should include localhost variants
        redirect_uris = web_config.get("redirect_uris", [])
        if not redirect_uris or redirect_uris == ["http://localhost"]:
            # Use standard redirect URIs for installed apps
            redirect_uris = ["http://localhost"]
        
        client_config["installed"] = {
            "client_id": web_config.get("client_id"),
            "client_secret": web_config.get("client_secret"),
            "auth_uri": web_config.get("auth_uri", "https://accounts.google.com/o/oauth2/auth"),
            "token_uri": web_config.get("token_uri", "https://oauth2.googleapis.com/token"),
            "auth_provider_x509_cert_url": web_config.get("auth_provider_x509_cert_url", "https://www.googleapis.com/oauth2/v1/certs"),
            "redirect_uris": redirect_uris
        }
        
        # Validate required fields
        if not client_config["installed"].get("client_id") or not client_config["installed"].get("client_secret"):
            print("Error: client_id and client_secret are required in client_secret.json")
            return
    
    # Validate the format
    if "installed" not in client_config:
        print("Error: client_secret.json must contain either 'installed' or 'web' key.")
        print("Please download OAuth 2.0 credentials for 'Desktop app' from Google Cloud Console.")
        return
    
    # Debug: Print the config structure (without secrets)
    installed_config = client_config["installed"]
    print(f"Using OAuth client: {installed_config.get('client_id', 'N/A')[:20]}...")
    print(f"Redirect URIs: {installed_config.get('redirect_uris', [])}")
    
    # 1. Start the flow using from_client_config
    try:
        flow = InstalledAppFlow.from_client_config(
            client_config,
            scopes=SCOPES
        )
    except ValueError as e:
        print(f"\nError creating OAuth flow: {e}")
        print("\nTroubleshooting:")
        print("1. Ensure your OAuth client in Google Cloud Console is configured for 'Desktop app'")
        print("2. Make sure 'http://localhost' is added as an authorized redirect URI")
        print("3. Try downloading a new OAuth 2.0 client ID as 'Desktop app' type")
        print(f"\nCurrent config structure: {list(installed_config.keys())}")
        return
    
    # Use run_local_server for the Desktop App flow
    credentials = flow.run_local_server(
        port=0, # Choose a random available port
        access_type='offline', # MANDATORY: Ensures a refresh_token is returned
        prompt='consent' # MANDATORY: Forces the consent screen, ensuring a refresh_token
    )
    
    # 2. Get the required JSON string
    creds_json = credentials.to_json()
    
    # 3. Print the result
    print("\n\n#####################################################")
    print("COPY THIS ENTIRE JSON STRING (GMAIL_CREDENTIALS_JSON):")
    print("#####################################################\n")
    # This JSON string contains the refresh_token that Apify needs
    print(creds_json)

if __name__ == '__main__':
    # Setting this allows the use of HTTP for the local redirect
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1' 
    generate_credentials_json()