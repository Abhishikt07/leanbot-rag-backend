"""
Demo Scheduler Module: Handles Google Calendar/Meet creation and Email Confirmation.
This script is completely decoupled from the core RAG logic.

PREREQUISITES:
1. Google Cloud Project with Calendar API enabled.
2. Download a Service Account JSON key as 'credentials.json' in the same directory.
3. Configure EMAIL_HOST and EMAIL_PASSWORD (or use environment variables).
"""
import logging
import datetime
import time
import os
from typing import Optional
from google.oauth2 import service_account
from googleapiclient.discovery import build
from email.mime.text import MIMEText
import smtplib
from smtplib import SMTPAuthenticationError

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- CONFIGURATION (Use environment variables for production security) ---
SCOPES = ['https://www.googleapis.com/auth/calendar']
SERVICE_ACCOUNT_FILE = "credentials.json"
# Example of Company Email/Password (NEVER hardcode passwords in production)
COMPANY_EMAIL = os.getenv("COMPANY_EMAIL", "sales@yourcompany.com") 
COMPANY_EMAIL_PASSWORD = os.getenv("COMPANY_EMAIL_PASSWORD", "your_app_password_here")
INTERNAL_TEAM_EMAIL = os.getenv("INTERNAL_TEAM_EMAIL", "sales-team@yourcompany.com")
# --- END CONFIGURATION ---

# --- HELPER 1: EMAIL SENDER ---

def send_confirmation_email(to_email: str, demo_type: str, meet_link: Optional[str], recipient_name: str) -> bool:
    """Sends confirmation email to the user and a notification to the internal team."""
    
    # 1. Email Body Construction
    body = f"""
    Hello {recipient_name},

    Your {demo_type} demo with Leanext Consulting has been successfully scheduled!
    
    ⏰ **Date and Time**: We have tentatively set aside time and will follow up with a confirmed slot shortly.
    
    🔗 **Google Meet Link**: {meet_link or 'Link will be sent in a follow-up email.'}
    
    A consultant will reach out to you within 24 hours to confirm the exact time and agenda.

    Regards,
    The Leanext Consulting Demo Team
    """

    msg = MIMEText(body)
    msg["Subject"] = f"✅ Confirmation: Your {demo_type} Demo is Booked!"
    msg["From"] = COMPANY_EMAIL
    msg["To"] = to_email
    
    # Send a copy to the internal team as well
    msg_internal = MIMEText(f"A new lead has booked a demo:\nName: {recipient_name}\nEmail: {to_email}\nType: {demo_type}\nMeet Link: {meet_link}")
    msg_internal["Subject"] = f"🔔 NEW DEMO BOOKING: {demo_type}"
    msg_internal["From"] = COMPANY_EMAIL
    msg_internal["To"] = INTERNAL_TEAM_EMAIL

    # 2. Sending Logic
    try:
        # Use secure TLS connection
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(COMPANY_EMAIL, COMPANY_EMAIL_PASSWORD)
            
            # Send to user
            server.send_message(msg)
            logging.info(f"Confirmation email sent to user: {to_email}")
            
            # Send to internal team
            server.send_message(msg_internal)
            logging.info(f"Notification email sent to internal team: {INTERNAL_TEAM_EMAIL}")
        return True
    except SMTPAuthenticationError:
        logging.error("Email authentication failed. Check COMPANY_EMAIL and COMPANY_EMAIL_PASSWORD (App Password needed).")
        return False
    except Exception as e:
        logging.error(f"Failed to send confirmation email: {e}")
        return False


# --- HELPER 2: CALENDAR SCHEDULER ---

def create_google_meet_event(name: str, email: str, demo_type: str) -> Optional[str]:
    """Creates a Google Calendar event and returns the Meet link."""
    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        logging.error(f"Google Calendar credentials file not found: {SERVICE_ACCOUNT_FILE}. Skipping scheduling.")
        return None
    
    # Tentatively schedule 2 hours from now, lasting 60 minutes
    now = datetime.datetime.utcnow()
    start_time = now + datetime.timedelta(hours=2)
    end_time = start_time + datetime.timedelta(minutes=60)
    
    try:
        # Load credentials from service account file
        credentials = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=SCOPES
        )
        service = build('calendar', 'v3', credentials=credentials)

        event = {
            'summary': f'Leanext Demo: {demo_type} with {name}',
            'description': f'Automatic demo booking from the chatbot for the topic: {demo_type}.',
            'start': {'dateTime': start_time.isoformat() + 'Z'},
            'end': {'dateTime': end_time.isoformat() + 'Z'},
            'conferenceData': {'createRequest': {'requestId': f"{name}-{int(time.time())}", 'conferenceSolutionKey': {'type': 'hangoutsMeet'}}},
            'attendees': [
                {'email': email},
                {'email': INTERNAL_TEAM_EMAIL} # Invite the internal team directly
            ],
            'sendUpdates': 'all' # Send notification emails to attendees
        }

        # Insert the event into the primary calendar
        event = service.events().insert(
            calendarId='primary', 
            body=event, 
            conferenceDataVersion=1 # Must be 1 to create the Meet link
        ).execute()

        meet_link = event.get('hangoutLink')
        return meet_link
    except Exception as e:
        logging.error(f"Google Calendar event creation failed: {e}")
        return None

# --- CORE FUNCTION: Public Interface ---

def schedule_demo_meeting(name: str, email: str, demo_type: str) -> Optional[str]:
    """
    Creates a Google Calendar event + Meet link, sends confirmation email, and returns the link.
    This is the function called by the FastAPI backend.
    """
    if not email:
        logging.warning("Cannot schedule demo: Email is missing.")
        return None
        
    logging.info(f"Starting scheduling process for {name} ({demo_type}).")
    
    # 1. Create Google Meet/Calendar Event
    meet_link = create_google_meet_event(name, email, demo_type)
    
    if not meet_link:
        # Fallback if Meet creation fails: continue to send email without link
        logging.warning("Meet link generation failed. Proceeding with email confirmation (without link).")

    # 2. Send Email Confirmation
    email_success = send_confirmation_email(email, demo_type, meet_link, name)
    
    if not email_success:
        logging.error(f"Failed to send email for {name}. Manual follow-up needed.")
        
    return meet_link

if __name__ == '__main__':
    # Example usage for testing this script directly
    logging.info("--- Testing Demo Scheduler ---")
    test_meet_link = schedule_demo_meeting("Test User", "test@example.com", "ERP")
    logging.info(f"Test Run Completed. Meet Link: {test_meet_link}")