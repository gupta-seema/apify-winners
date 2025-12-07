import os
import json
import base64
import argparse
from typing import Dict, Any, Optional, List
import asyncio
from email.mime.text import MIMEText

# Apify SDK imports
from apify import Actor

# Google API imports
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# PDF processing imports
from pdfminer.high_level import extract_text_to_fp
from io import StringIO, BytesIO

# --- CONFIGURATION ---
DEFAULT_GMAIL_QUERY = 'subject:"Rate Confirmation" has:attachment'
DEFAULT_MIME_TYPES = ['application/pdf']
SCOPES = ['https://www.googleapis.com/auth/gmail.compose', 'https://www.googleapis.com/auth/gmail.readonly']

# --- HELPER FUNCTIONS ---

def extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extracts plain text content from PDF file bytes using pdfminer.six."""
    output_string = StringIO()
    with BytesIO(pdf_bytes) as fin:
        extract_text_to_fp(fin, output_string)
    return output_string.getvalue().strip()

def get_attachment_data(service: Any, user_id: str, msg_id: str, att_id: str) -> Optional[bytes]:
    """Fetches and decodes a specific attachment's binary data."""
    try:
        att = service.users().messages().attachments().get(
            userId=user_id, messageId=msg_id, id=att_id
        ).execute()
        data = att.get('data')
        if data:
            return base64.urlsafe_b64decode(data.encode('UTF-8'))
    except HttpError as error:
        print(f"Failed to fetch attachment {att_id}: {error}")
    return None

def find_mime_parts(parts: List[Dict[str, Any]], target_mimes: List[str]) -> List[Dict[str, Any]]:
    """Recursively search through message parts for target MIME types."""
    found_parts = []
    if not parts:
        return found_parts
    for part in parts:
        if part.get('mimeType') in target_mimes and part.get('body', {}).get('attachmentId'):
            found_parts.append(part)
        if 'parts' in part:
            found_parts.extend(find_mime_parts(part['parts'], target_mimes))
    return found_parts

def create_draft(service, user_id, to, subject, body):
    """Creates a draft email."""
    try:
        message = MIMEText(body)
        message['to'] = to
        message['subject'] = subject
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        
        draft_body = {'message': {'raw': raw}}
        draft = service.users().drafts().create(userId=user_id, body=draft_body).execute()
        
        print(f"Draft created successfully! Id: {draft['id']}")
        return draft
    except HttpError as error:
        print(f"An error occurred creating draft: {error}")
        return None

def get_credentials(actor_input):
    """Loads credentials from input or local file."""
    creds_json_str = actor_input.get('gmail_credentials.json')
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    local_creds_file = os.path.join(script_dir, 'gmail_credentials.json')
    
    if not creds_json_str and os.path.exists(local_creds_file):
        try:
            with open(local_creds_file, 'r') as f:
                local_config = json.load(f)
                if 'GMAIL_CREDENTIALS_JSON' in local_config:
                    creds_json_str = local_config['GMAIL_CREDENTIALS_JSON']
                elif 'token' in local_config:
                    creds_json_str = json.dumps(local_config)
        except Exception as e:
            print(f"Warning: Could not read local config: {e}")

    if not creds_json_str:
        return None

    try:
        creds_data = json.loads(creds_json_str)
        # Handle client_secret.json fallback for placeholders
        if creds_data.get('client_id', '').startswith('YOUR_CLIENT'):
            client_secret_file = os.path.join(script_dir, 'client_secret.json')
            if os.path.exists(client_secret_file):
                with open(client_secret_file, 'r') as f:
                    secrets = json.load(f)
                    config = secrets.get('installed') or secrets.get('web', {})
                    creds_data['client_id'] = config.get('client_id')
                    creds_data['client_secret'] = config.get('client_secret')
        
        return Credentials.from_authorized_user_info(info=creds_data, scopes=SCOPES)
    except Exception as e:
        print(f"Error parsing credentials: {e}")
        return None

async def main(args):
    """Main execution function."""
    async with Actor:
        actor_input = await Actor.get_input() or {}
        creds = get_credentials(actor_input)
        
        if not creds:
            print("Error: No valid credentials found.")
            return

        try:
            service = build('gmail', 'v1', credentials=creds)
        except Exception as e:
            print(f"Error initializing Gmail service: {e}")
            return

        # --- MODE: DRAFT ---
        if args.mode == 'draft':
            if not args.to or not args.subject or not args.body:
                print("Error: --to, --subject, and --body are required for draft mode.")
                return
            print(f"Creating draft to {args.to}...")
            create_draft(service, 'me', args.to, args.subject, args.body)
            return

        # --- MODE: SEARCH (Default) ---
        gmail_query = args.query or actor_input.get('gmailQuery') or DEFAULT_GMAIL_QUERY
        target_mimes = args.mime_types or actor_input.get('attachmentMimeTypes') or DEFAULT_MIME_TYPES

        print(f"Searching: {gmail_query}")
        
        try:
            results = service.users().messages().list(userId='me', q=gmail_query, maxResults=5).execute()
            messages = results.get('messages', [])
            
            if not messages:
                print("No emails found.")
                return

            print(f"Found {len(messages)} emails. Processing...")
            
            for msg_meta in messages:
                msg = service.users().messages().get(userId='me', id=msg_meta['id'], format='full').execute()
                
                # Basic Headers
                headers = {h['name']: h['value'] for h in msg['payload']['headers']}
                subject = headers.get('Subject', '(No Subject)')
                date = headers.get('Date', '')
                
                print(f"\n--- Email: {subject} ---")
                print(f"Date: {date}")
                
                # Find Attachments
                parts = [msg['payload']] if 'parts' not in msg['payload'] else msg['payload']['parts']
                attachments = find_mime_parts(parts, target_mimes)
                
                if attachments:
                    att = attachments[0] # Process first
                    fname = att.get('filename', 'untitled')
                    print(f"Found Attachment: {fname}")
                    
                    data = get_attachment_data(service, 'me', msg_meta['id'], att['body']['attachmentId'])
                    if data and att.get('mimeType') == 'application/pdf':
                        text = extract_pdf_text(data)
                        print(f"PDF CONTENT START:\n{text[:500]}...\nPDF CONTENT END")
                        # Push to Apify Dataset for MCP to read
                        await Actor.push_data({
                            "subject": subject,
                            "filename": fname,
                            "content": text
                        })
                else:
                    print("No target attachments found.")
                    
        except HttpError as error:
            print(f"Gmail API Error: {error}")

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['search', 'draft'], default='search', help='Operation mode')
    parser.add_argument('--query', type=str, help='Gmail search query')
    parser.add_argument('--mime-types', nargs='+', help='Mime types')
    
    # Draft args
    parser.add_argument('--to', type=str, help='Recipient email')
    parser.add_argument('--subject', type=str, help='Email subject')
    parser.add_argument('--body', type=str, help='Email body')

    args = parser.parse_args()
    asyncio.run(main(args))