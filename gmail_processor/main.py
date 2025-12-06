import os
import io
import json
import base64
import argparse
from typing import Dict, Any, Optional, List
import asyncio

# Apify SDK imports
from apify import Actor
from apify_client import ApifyClient

# Google API imports
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# PDF processing imports
from pdfminer.high_level import extract_text_to_fp
from io import StringIO, BytesIO

# --- CONFIGURATION ---

# Default configuration values
DEFAULT_GMAIL_QUERY = 'subject:"Rate Confirmation for order #" has:attachment from:@scotlynn.com'
DEFAULT_MIME_TYPES = ['application/pdf']
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

# --- HELPER FUNCTIONS ---

def extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extracts plain text content from PDF file bytes using pdfminer.six."""
    output_string = StringIO()
    # Wrap bytes in a file-like object for pdfminer
    with BytesIO(pdf_bytes) as fin:
        # Use a high-level function for simple text extraction
        extract_text_to_fp(fin, output_string)
    return output_string.getvalue().strip()


def get_attachment_data(service: Any, user_id: str, msg_id: str, att_id: str) -> Optional[bytes]:
    """Fetches and decodes a specific attachment's binary data."""
    try:
        att = service.users().messages().attachments().get(
            userId=user_id, messageId=msg_id, id=att_id
        ).execute()

        # The data is base64url encoded
        data = att.get('data')
        if data:
            return base64.urlsafe_b64decode(data.encode('UTF-8'))
    except HttpError as error:
        Actor.log.error(f"Failed to fetch attachment {att_id}: {error}")
    return None

def find_mime_parts(parts: List[Dict[str, Any]], target_mimes: List[str]) -> List[Dict[str, Any]]:
    """Recursively search through message parts for target MIME types."""
    found_parts = []
    
    if not parts:
        return found_parts

    for part in parts:
        # Check current part
        if part.get('mimeType') in target_mimes and part.get('body', {}).get('attachmentId'):
            # Only include parts that have an attachment ID
            found_parts.append(part)
        
        # Check nested parts (e.g., in multipart messages)
        if 'parts' in part:
            found_parts.extend(find_mime_parts(part['parts'], target_mimes))
            
    return found_parts

# --- MAIN ACTOR LOGIC ---

async def main(gmail_query_override: Optional[str] = None, mime_types_override: Optional[List[str]] = None):
    """The main function of the Apify Actor."""
    async with Actor:
        Actor.log.info('Actor started.')

        # 1. Get Input and Configuration
        actor_input = await Actor.get_input() or {}
        
        # MANDATORY: The Gmail OAuth 2.0 credentials
        creds_json_str = actor_input.get('gmail_credentials.json')
        
        # Load local config file if it exists (for local testing)
        script_dir = os.path.dirname(os.path.abspath(__file__))
        local_creds_file = os.path.join(script_dir, 'gmail_credentials.json')
        local_config = None
        if os.path.exists(local_creds_file):
            try:
                with open(local_creds_file, 'r') as f:
                    local_config = json.load(f)
            except Exception as e:
                Actor.log.warning(f"Could not read local config file: {e}")
        
        # If not provided in Actor input, try to load from local file
        if not creds_json_str and local_config:
            # Handle both formats: direct JSON string or nested in GMAIL_CREDENTIALS_JSON key
            if 'GMAIL_CREDENTIALS_JSON' in local_config:
                creds_json_str = local_config['GMAIL_CREDENTIALS_JSON']
            elif 'token' in local_config:
                # Already in the correct format
                creds_json_str = json.dumps(local_config)
            else:
                Actor.log.error(f"Invalid format in {local_creds_file}. Expected 'GMAIL_CREDENTIALS_JSON' key or credentials object.")
                return
            if creds_json_str:
                Actor.log.info(f"Loaded credentials from local file: {local_creds_file}")
        
        if not creds_json_str:
            Actor.log.error("GMAIL_CREDENTIALS_JSON not provided in Actor input and local file not found or invalid.")
            return
            
        # OPTIONAL: The user-defined search query 
        # Priority: function parameter > command-line arg > actor input > local file > default
        gmail_query = (gmail_query_override or 
                      globals().get('GMAIL_QUERY_ARG') or 
                      actor_input.get('gmailQuery') or 
                      (local_config.get('gmailQuery') if local_config else None) or 
                      DEFAULT_GMAIL_QUERY)
        
        # OPTIONAL: The list of target MIME types
        # Priority: function parameter > command-line arg > actor input > local file > default
        target_mimes = (mime_types_override or 
                       globals().get('TARGET_MIME_TYPES_ARG') or 
                       actor_input.get('attachmentMimeTypes') or 
                       (local_config.get('attachmentMimeTypes') if local_config else None) or 
                       DEFAULT_MIME_TYPES)

        Actor.log.info(f"Using Search Query: '{gmail_query}'")
        Actor.log.info(f"Targeting MIME Types: {', '.join(target_mimes)}")

        # Load Credentials
        try:
            creds_data = json.loads(creds_json_str)
            
            # If client_id or client_secret are placeholders, load from client_secret.json
            if (creds_data.get('client_id', '').startswith('YOUR_CLIENT_ID') or 
                creds_data.get('client_secret', '').startswith('YOUR_CLIENT_SECRET')):
                Actor.log.info("Detected placeholder credentials. Loading from client_secret.json...")
                client_secret_file = os.path.join(script_dir, 'client_secret.json')
                if os.path.exists(client_secret_file):
                    try:
                        with open(client_secret_file, 'r') as f:
                            client_secret_data = json.load(f)
                        # Handle both "web" and "installed" formats
                        client_config = client_secret_data.get('installed') or client_secret_data.get('web', {})
                        creds_data['client_id'] = client_config.get('client_id')
                        creds_data['client_secret'] = client_config.get('client_secret')
                        Actor.log.info("Successfully loaded client_id and client_secret from client_secret.json")
                    except Exception as e:
                        Actor.log.warning(f"Could not load client_secret.json: {e}")
                else:
                    Actor.log.warning("client_secret.json not found. Token refresh may fail.")
            
            creds = Credentials.from_authorized_user_info(info=creds_data, scopes=SCOPES)
        except Exception as e:
            Actor.log.error(f"Error loading credentials: {e}")
            return

        # 2. Initialize Gmail Service
        try:
            service = build('gmail', 'v1', credentials=creds)
            user_id = 'me'
            Actor.log.info("Successfully initialized Gmail API service.")
        except Exception as e:
            Actor.log.error(f"Failed to build Gmail service: {e}")
            return

        # 3. Search for Emails
        # Gmail API returns messages in reverse chronological order (newest first) by default
        # But we'll fetch with a limit and handle pagination to ensure we get the most recent
        try:
            all_messages = []
            page_token = None
            max_results = 100  # Limit to most recent 100 emails by default
            
            while len(all_messages) < max_results:
                request_params = {
                    'userId': user_id,
                    'q': gmail_query,
                    'maxResults': min(500, max_results - len(all_messages))  # Gmail API max is 500 per page
                }
                
                if page_token:
                    request_params['pageToken'] = page_token
                
                response = service.users().messages().list(**request_params).execute()
                
                page_messages = response.get('messages', [])
                all_messages.extend(page_messages)
                
                # Check if there are more pages
                page_token = response.get('nextPageToken')
                if not page_token or len(all_messages) >= max_results:
                    break
            
            # Limit to the requested number
            messages = all_messages[:max_results]
            
            Actor.log.info(f"Found {len(messages)} matching email(s) (limited to most recent {max_results}).")
        except HttpError as error:
            Actor.log.error(f"Gmail search failed: {error}")
            return
        
        if not messages:
            Actor.log.info("No matching emails found. Exiting.")
            print("\n=== GMAIL PROCESSOR RESULTS ===")
            print("No matching emails found.")
            return
        
        # 4. Process Each Message
        all_results = []  # Collect results for output
        
        for msg_count, message in enumerate(messages, 1):
            msg_id = message['id']
            Actor.log.info(f"[{msg_count}/{len(messages)}] Processing message ID: {msg_id}")

            try:
                # Get the full message content
                msg = service.users().messages().get(
                    userId=user_id, id=msg_id, format='full'
                ).execute()
                
                # Extract basic metadata
                headers = {h['name']: h['value'] for h in msg['payload']['headers']}
                subject = headers.get('Subject', 'No Subject')
                date = headers.get('Date', 'No Date')
                
                # Get internal date (timestamp) for sorting - more reliable than Date header
                internal_date = msg.get('internalDate')
                if internal_date:
                    # Convert from milliseconds to seconds timestamp
                    timestamp = int(internal_date) / 1000
                else:
                    timestamp = 0
                
                # Recursively search for attachments
                all_parts = [msg['payload']] if 'parts' not in msg['payload'] else msg['payload']['parts']
                target_attachments = find_mime_parts(all_parts, target_mimes)

                attachment_content_text = None
                attachment_filename = None
                
                if target_attachments:
                    # We process only the first found target attachment
                    part = target_attachments[0]
                    filename = part.get('filename', 'untitled_attachment')
                    att_id = part['body']['attachmentId']
                    
                    Actor.log.info(f"  -> Found target attachment: {filename} (MIME: {part.get('mimeType')})")
                    
                    attachment_bytes = get_attachment_data(service, user_id, msg_id, att_id)
                    
                    if attachment_bytes and part.get('mimeType') == 'application/pdf':
                        # Handle PDF to Text
                        try:
                            attachment_content_text = extract_pdf_text(attachment_bytes)
                            attachment_filename = filename
                            Actor.log.info(f"  -> Successfully extracted text from PDF. Size: {len(attachment_content_text)} chars.")
                        except Exception as e:
                            Actor.log.warning(f"  -> Failed to extract text from PDF: {e}")
                            
                    elif attachment_bytes:
                        # Handle other binary types (if added to target_mimes)
                        # For simple LLM processing, we might base64 encode it or process it 
                        # using another library (e.g., python-docx for .docx files)
                        # For this example, we'll store the text of the message body if 
                        # we couldn't process the attachment.
                        attachment_filename = filename
                        attachment_content_text = f"Binary content of {filename} was not processed to text. Size: {len(attachment_bytes)} bytes."
                        Actor.log.warning(f"  -> Attachment type {part.get('mimeType')} not automatically converted to text.")


                # 5. Store Result in Apify Dataset
                if attachment_content_text:
                    record = {
                        "messageId": msg_id,
                        "subject": subject,
                        "date": date,
                        "timestamp": timestamp,  # For sorting
                        "attachmentName": attachment_filename,
                        "gmailQueryUsed": gmail_query,
                        "targetMimes": target_mimes,
                        # The full, extracted text content ready for the LLM
                        "attachmentContentText": attachment_content_text,
                        # This LLM-ready field contains the text for downstream processing
                    }
                    await Actor.push_data(record)
                    Actor.log.info(f"  -> Pushed data for message: {msg_id}")
                    all_results.append(record)  # Collect for output
                else:
                    Actor.log.warning(f"  -> No usable target attachment found or extraction failed for message {msg_id}. Skipping.")
                    # Still add basic info even without attachment
                    all_results.append({
                        "messageId": msg_id,
                        "subject": subject,
                        "date": date,
                        "timestamp": timestamp,  # For sorting
                        "status": "No target attachment found"
                    })

            except Exception as e:
                Actor.log.error(f"An unexpected error occurred processing message {msg_id}: {e}")

        Actor.log.info('Actor finished.')
        
        # Sort results by timestamp (newest first) to ensure most recent emails are shown first
        all_results.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
        
        # Print results summary for local execution
        import sys
        print("\n" + "="*60, flush=True)
        print("GMAIL PROCESSOR RESULTS", flush=True)
        print("="*60, flush=True)
        print(f"Query used: {gmail_query}", flush=True)
        print(f"Total emails processed: {len(messages)}", flush=True)
        print(f"Results with attachments: {len([r for r in all_results if 'attachmentContentText' in r])}", flush=True)
        print(f"Results sorted by date (newest first)", flush=True)
        print("\n" + "-"*60, flush=True)
        
        for idx, result in enumerate(all_results, 1):
            print(f"\n[{idx}] Email Result:", flush=True)
            print(f"  Subject: {result.get('subject', 'N/A')}", flush=True)
            print(f"  Date: {result.get('date', 'N/A')}", flush=True)
            print(f"  Message ID: {result.get('messageId', 'N/A')}", flush=True)
            if 'attachmentName' in result:
                print(f"  Attachment: {result.get('attachmentName', 'N/A')}", flush=True)
                content = result.get('attachmentContentText', '')
                if content:
                    # Show preview of content (first 200 chars)
                    preview = content[:200] + "..." if len(content) > 200 else content
                    print(f"  Content Preview: {preview}", flush=True)
                    print(f"  Full Content Length: {len(content)} characters", flush=True)
            elif 'status' in result:
                print(f"  Status: {result.get('status')}", flush=True)
            print("-"*60, flush=True)
        
        print(f"\nTotal results: {len(all_results)}", flush=True)
        print("="*60 + "\n", flush=True)
        sys.stdout.flush()  # Ensure all output is flushed

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Gmail Processor - Extract emails and attachments')
    parser.add_argument('--query', '-q', type=str, help='Gmail search query (e.g., "subject:invoice after:2024/01/01")')
    parser.add_argument('--mime-types', '-m', type=str, nargs='+', help='Target MIME types for attachments (default: application/pdf)')
    args = parser.parse_args()
    
    # Set global variable for query if provided via command line (for backward compatibility)
    if args.query:
        globals()['GMAIL_QUERY_ARG'] = args.query
    if args.mime_types:
        globals()['TARGET_MIME_TYPES_ARG'] = args.mime_types
    
    # Pass arguments directly to main function
    asyncio.run(main(gmail_query_override=args.query, mime_types_override=args.mime_types))