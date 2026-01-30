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

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
PORT = int(os.getenv("PORT", 8000))
MODEL = "gpt-4o-realtime-preview"

app = FastAPI()

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

            full_system_prompt = BASE_SYSTEM_MESSAGE + "\n\nCONTEXT:\n" + context_instruction

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
            nonlocal contact_id
            try:
                async for message in openai_ws:
                    response = json.loads(message)

                    if response['type'] == 'response.audio.delta' and stream_sid:
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
                            # Wait 3 seconds for the "Goodbye" audio to finish playing
                            await asyncio.sleep(3)
                            await websocket.close()
                            return

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