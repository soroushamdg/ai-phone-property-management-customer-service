import os
import json
import asyncio
import websockets
import ssl
import certifi
from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import HTMLResponse
from dotenv import load_dotenv
from twilio.twiml.voice_response import VoiceResponse, Connect
import db
import knowledge_base

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
PORT = int(os.getenv("PORT", 8000))
MODEL = "gpt-4o-realtime-preview"
KNOWLEDGE_ENABLED = os.getenv("ENABLE_KNOWLEDGE_BASE", "false").lower() == "true"

app = FastAPI()

# Initialize knowledge base if enabled
if KNOWLEDGE_ENABLED:
    knowledge_base.initialize_knowledge_base()

# --- SYSTEM PROMPT ---
BASE_SYSTEM_MESSAGE = (
    "You are a proactive and efficient support assistant named Riley. "
    "Your goal is to resolve the user's issue as fast as possible. "
    "Do not wait for the user to lead. "
    "IMMEDIATELY ask for necessary information. "
    "If the user is new, your FIRST sentence must be to ask for their name. "
    "Keep your responses short (under 2 sentences) but drive the conversation forward. "
    "When the user indicates they are done or says goodbye, you MUST say a polite goodbye phrase "
    "like 'Have a great day!' and then immediately call the 'end_call' tool."
)

KNOWLEDGE_SYSTEM_MESSAGE = (
    "You are Riley, a knowledgeable property management assistant. "
    "You help people find rental properties in Montreal. "
    "You have access to a comprehensive database of properties with details about amenities, locations, and features. "
    "When users ask about properties, neighborhoods, amenities, or locations, use the search_properties tool to find relevant information. "
    "Be proactive in suggesting properties that match their needs. "
    "If the user is new, ask for their name first. "
    "Keep responses concise and helpful. "
    "When done, say goodbye and use the end_call tool."
)

TOOLS = [
    {
        "type": "function",
        "name": "end_call",
        "description": "Ends the call. Use this AFTER saying a polite goodbye to the user.",
        "parameters": {"type": "object", "properties": {}}
    },
    {
        "type": "function",
        "name": "register_user",
        "description": "Registers a new user name to the database.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "The user's full name"}
            },
            "required": ["name"]
        }
    },
    {
        "type": "function",
        "name": "create_ticket",
        "description": "Creates a support ticket for the user.",
        "parameters": {
            "type": "object",
            "properties": {
                "description": {"type": "string", "description": "Details of the issue or request"},
                "category": {
                    "type": "string",
                    "enum": ["issue", "request", "general"],
                    "description": "Category of the ticket"
                }
            },
            "required": ["description", "category"]
        }
    },
    {
        "type": "function",
        "name": "search_properties",
        "description": "Search properties by location, amenities, or features. Use this when users ask about available properties, neighborhoods, or specific features.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query about properties, locations, amenities, or features"}
            },
            "required": ["query"]
        }
    },
    {
        "type": "function",
        "name": "load_knowledge_base",
        "description": "Load the complete property knowledge base into your context. Use this when you need comprehensive information about Montreal rental properties to provide detailed answers or make proactive suggestions.",
        "parameters": {"type": "object", "properties": {}}
    }
]


@app.api_route("/incoming-call", methods=["GET", "POST"])
async def incoming_call(request: Request):
    form_data = await request.form()
    phone_number = form_data.get('From', 'Unknown')

    print(f"Incoming call from: {phone_number}")

    response = VoiceResponse()
    response.say("Connecting to Support.")
    response.pause(length=1)
    connect = Connect()

    # --- CRITICAL FIX: Send Phone via Stream Parameter ---
    stream = connect.stream(url=f"wss://{request.url.hostname}/media-stream")
    stream.parameter(name="customer_phone", value=phone_number)

    response.append(connect)
    return HTMLResponse(content=str(response), media_type="application/xml")


@app.websocket("/media-stream")
async def media_stream(websocket: WebSocket):
    await websocket.accept()

    openai_url = f"wss://api.openai.com/v1/realtime?model={MODEL}"
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "OpenAI-Beta": "realtime=v1",
    }
    ssl_context = ssl.create_default_context(cafile=certifi.where())

    async with websockets.connect(openai_url, additional_headers=headers, ssl=ssl_context) as openai_ws:
        print(">>> Connected to OpenAI.")

        # --- SESSION STATE ---
        stream_sid = None
        call_phone_number = None
        contact_id = None
        end_call_requested = False
        goodbye_response_id = None
        goodbye_audio_playing = False

        async def initialize_ai_session():
            nonlocal contact_id

            print(f">>> Looking up contact for: {call_phone_number}")
            contact = db.get_contact(call_phone_number)

            context_instruction = ""
            greeting = ""

            if contact:
                contact_id = contact['id']
                tickets = db.get_tickets(contact_id)
                ticket_summary = "\n".join([f"- [{t['status']}] {t['category']}: {t['description']}" for t in tickets])

                context_instruction = (
                    f"You are speaking with {contact['name']}. "
                    f"They have {len(tickets)} recent tickets:\n{ticket_summary}\n"
                    "Ask if they are calling about an existing ticket or a new issue."
                )
                greeting = f"Hello {contact['name']}! I see you have {len(tickets)} tickets. How can I help?"
            else:
                context_instruction = (
                    "This is a NEW caller. You do not know their name. "
                    "Politely welcome them and ask for their name to register them."
                )
                greeting = "Hello, this is Riley Support. I don't have your number saved. What is your full name?"

            # Choose system message based on knowledge base setting
            base_message = KNOWLEDGE_SYSTEM_MESSAGE if KNOWLEDGE_ENABLED else BASE_SYSTEM_MESSAGE
            
            full_system_prompt = base_message + "\n\nCONTEXT:\n" + context_instruction

            # Configure OpenAI
            await openai_ws.send(json.dumps({
                "type": "session.update",
                "session": {
                    "modalities": ["text", "audio"],
                    "instructions": full_system_prompt,
                    "voice": "alloy",
                    "input_audio_format": "g711_ulaw",
                    "output_audio_format": "g711_ulaw",
                    "turn_detection": {
                        "type": "server_vad",
                        "threshold": 0.5,
                        "prefix_padding_ms": 300,
                        "silence_duration_ms": 200,
                        "create_response": True
                    },
                    "tools": TOOLS,
                    "tool_choice": "auto"
                }
            }))

            # Trigger Greeting
            await openai_ws.send(json.dumps({
                "type": "response.create",
                "response": {
                    "modalities": ["text", "audio"],
                    "instructions": f"Say exactly: '{greeting}'"
                }
            }))

        # --- Twilio Listener ---
        async def receive_from_twilio():
            nonlocal stream_sid, call_phone_number
            try:
                async for message in websocket.iter_text():
                    data = json.loads(message)

                    if data['event'] == 'start':
                        stream_sid = data['start']['streamSid']
                        custom_params = data['start'].get('customParameters', {})
                        call_phone_number = custom_params.get('customer_phone')

                        print(f"--- Captured Phone: {call_phone_number} ---")

                        if call_phone_number:
                            await initialize_ai_session()
                        else:
                            print("!!! ERROR: Phone number missing.")

                    elif data['event'] == 'media':
                        if call_phone_number:
                            await openai_ws.send(json.dumps({
                                "type": "input_audio_buffer.append",
                                "audio": data['media']['payload']
                            }))

            except Exception as e:
                print(f"Twilio Error: {e}")

        # --- OpenAI Listener ---
        async def receive_from_openai():
            nonlocal contact_id, end_call_requested, goodbye_response_id, goodbye_audio_playing
            try:
                async for message in openai_ws:
                    response = json.loads(message)

                    if response['type'] == 'response.created':
                        if end_call_requested:
                            goodbye_response_id = response['response']['id']
                            print(f">>> Goodbye response started: {goodbye_response_id}")
                            goodbye_audio_playing = True

                    elif response['type'] == 'response.done':
                        if goodbye_response_id and response['response']['id'] == goodbye_response_id:
                            print(">>> Goodbye response finished, ending call.")
                            await asyncio.sleep(0.5)  # Brief pause for audio to flush
                            await websocket.close()
                            return

                    elif response['type'] == 'response.audio.delta' and stream_sid:
                        await websocket.send_json({
                            "event": "media", "streamSid": stream_sid, "media": {"payload": response['delta']}
                        })

                    elif response['type'] == 'input_audio_buffer.speech_started':
                        if stream_sid: await websocket.send_json({"event": "clear", "streamSid": stream_sid})
                        await openai_ws.send(json.dumps({"type": "response.cancel"}))

                    # --- TOOL LOGIC ---
                    elif response['type'] == 'response.function_call_arguments.done':
                        print(f"Tool Call: {response['name']}")
                        args = json.loads(response['arguments'])
                        tool_output = None

                        if response['name'] == 'end_call':
                            print(">>> Ending Call Requested.")
                            end_call_requested = True
                            # Don't end call immediately - wait for goodbye to finish
                            tool_output = "Call will end after goodbye message."

                        elif response['name'] == 'register_user':
                            if call_phone_number and args.get('name'):
                                new_contact = db.create_contact(args['name'], call_phone_number)
                                if new_contact:
                                    contact_id = new_contact['id']
                                    tool_output = f"User {args['name']} registered."
                                else:
                                    tool_output = "DB Error."
                            else:
                                tool_output = "Error: Missing data."

                        elif response['name'] == 'create_ticket':
                            if contact_id:
                                ticket = db.create_ticket(contact_id, args['description'], args['category'])
                                tool_output = f"Ticket created. ID: {ticket['id']}"
                            else:
                                tool_output = "Error: User not found."

                        elif response['name'] == 'search_properties':
                            if KNOWLEDGE_ENABLED:
                                search_result = knowledge_base.search_properties(args['query'])
                                if 'error' in search_result:
                                    tool_output = f"Property search unavailable: {search_result['error']}"
                                else:
                                    # Format search results for user
                                    results_text = []
                                    for result in search_result['results'][:3]:  # Top 3 results
                                        results_text.append(f"• {result['text'][:200]}...")
                                    tool_output = f"Found {search_result['total_found']} properties:\n" + "\n".join(results_text)
                            else:
                                tool_output = "Property search is not available."

                        elif response['name'] == 'load_knowledge_base':
                            if KNOWLEDGE_ENABLED:
                                all_knowledge = knowledge_base.get_all_knowledge()
                                tool_output = all_knowledge
                            else:
                                tool_output = "Knowledge base is not available."

                        if tool_output:
                            print(f">>> Tool Output: {tool_output}")
                            await openai_ws.send(json.dumps({
                                "type": "conversation.item.create",
                                "item": {
                                    "type": "function_call_output",
                                    "call_id": response['call_id'],
                                    "output": tool_output
                                }
                            }))
                            await openai_ws.send(json.dumps({"type": "response.create"}))

            except Exception as e:
                print(f"OpenAI Loop Crash: {e}")

        await asyncio.gather(receive_from_twilio(), receive_from_openai())


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT)