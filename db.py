import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

# Initialize Supabase
url: str = os.getenv("SUPABASE_URL")
key: str = os.getenv("SUPABASE_KEY")

if not url or not key:
    raise ValueError("Missing SUPABASE_URL or SUPABASE_KEY in .env")

supabase: Client = create_client(url, key)


def get_contact(phone_number: str):
    """Check if a number exists in contacts."""
    response = supabase.table("contacts").select("*").eq("phone_number", phone_number).execute()
    return response.data[0] if response.data else None


def create_contact(name: str, phone_number: str):
    """Register a new user."""
    data = {"name": name, "phone_number": phone_number}
    response = supabase.table("contacts").insert(data).execute()
    return response.data[0] if response.data else None


def get_tickets(contact_id: str, limit=5):
    """Fetch recent tickets for a contact."""
    response = supabase.table("tickets").select("*") \
        .eq("contact_id", contact_id) \
        .order("created_at", desc=True) \
        .limit(limit) \
        .execute()
    return response.data


def create_ticket(contact_id: str, description: str, category: str):
    """Create a new ticket."""
    valid_categories = ['issue', 'request', 'general']
    if category not in valid_categories:
        category = 'general'

    data = {
        "contact_id": contact_id,
        "description": description,
        "category": category,
        "status": "to_do"
    }
    response = supabase.table("tickets").insert(data).execute()
    return response.data[0] if response.data else None