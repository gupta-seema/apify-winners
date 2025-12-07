import os
import json
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow

# The SCOPE from your Apify Actor (includes compose now)
SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.compose'
]

def generate_credentials_json():
    """Performs the OAuth flow and updates gmail_credentials.json automatically."""
    
    # Get the directory where this script is located
    script_dir = Path(__file__).parent
    client_secret_path = script_dir / 'client_secret.json'
    gmail_creds_path = script_dir / 'gmail_credentials.json'
    
    # Check if client_secret exists
    if not client_secret_path.exists():
        print(f"Error: client_secret.json not found at {client_secret_path}")
        return
    
    # Load and validate client secrets
    try:
        with open(client_secret_path, 'r') as f:
            client_config = json.load(f)
    except Exception as e:
        print(f"Error reading client_secret.json: {e}")
        return
    
    # Convert "web" format to "installed" format if needed
    if "web" in client_config and "installed" not in client_config:
        print("Converting 'web' OAuth client to 'installed' format...")
        web_config = client_config.pop("web")
        redirect_uris = web_config.get("redirect_uris", [])
        if not redirect_uris or redirect_uris == ["http://localhost"]:
            redirect_uris = ["http://localhost"]
        
        client_config["installed"] = {
            "client_id": web_config.get("client_id"),
            "client_secret": web_config.get("client_secret"),
            "auth_uri": web_config.get("auth_uri", "https://accounts.google.com/o/oauth2/auth"),
            "token_uri": web_config.get("token_uri", "https://oauth2.googleapis.com/token"),
            "auth_provider_x509_cert_url": web_config.get("auth_provider_x509_cert_url", "https://www.googleapis.com/oauth2/v1/certs"),
            "redirect_uris": redirect_uris
        }

    if "installed" not in client_config:
        print("Error: Invalid client_secret.json format.")
        return
    
    print("Starting OAuth flow...")
    
    # 1. Start the flow
    try:
        flow = InstalledAppFlow.from_client_config(client_config, scopes=SCOPES)
        credentials = flow.run_local_server(
            port=0,
            access_type='offline',
            prompt='consent'
        )
    except Exception as e:
        print(f"Error during OAuth flow: {e}")
        return
    
    # 2. Get the new credentials string
    new_creds_json_string = credentials.to_json()
    
    # 3. Update gmail_credentials.json
    current_data = {}
    
    # Read existing file to preserve other settings (like gmailQuery)
    if gmail_creds_path.exists():
        try:
            with open(gmail_creds_path, 'r') as f:
                current_data = json.load(f)
        except Exception as e:
            print(f"Warning: Could not read existing gmail_credentials.json ({e}). Creating new file.")

    # Update the credentials key
    current_data["GMAIL_CREDENTIALS_JSON"] = new_creds_json_string
    
    # Ensure default fields exist if it's a new file
    if "gmailQuery" not in current_data:
        current_data["gmailQuery"] = "subject:invoice after:2024/01/01"
    if "attachmentMimeTypes" not in current_data:
        current_data["attachmentMimeTypes"] = ["application/pdf"]

    # Write back to file
    try:
        with open(gmail_creds_path, 'w') as f:
            json.dump(current_data, f, indent=2)
        
        print("\nSUCCESS!")
        print(f"Updated credentials in: {gmail_creds_path}")
        print("You can now run your client.")
        
    except Exception as e:
        print(f"Error writing to file: {e}")

if __name__ == '__main__':
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1' 
    generate_credentials_json()