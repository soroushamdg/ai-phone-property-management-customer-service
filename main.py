import os
import json
import asyncio
import glob
import websockets
import ssl
import certifi
from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import HTMLResponse
from dotenv import load_dotenv
from twilio.twiml.voice_response import VoiceResponse, Connect

load_dotenv()

# --- Configuration ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
PORT = int(os.getenv("PORT", 8000))
MODEL = "gpt-4o-realtime-preview"

SYSTEM_MESSAGE = (
    "You are a helpful assistant named Riley. "
    "Speak fast, briefly, and clearly. "
    "Start with Bonjour/Hi"
    "When the user says goodbye or indicates they are finished, "
    "you MUST say a polite goodbye and then immediately call the 'end_call' tool."
)

app = FastAPI()


# --- HELPER: Load Markdown Files ---
def load_knowledge_base():
    kb_content = "\n\n# KNOWLEDGE BASE:\n"
    if not os.path.exists("knowledge_base"):
        os.makedirs("knowledge_base")
        return kb_content + "(No knowledge base files found.)"
    files = glob.glob("knowledge_base/*.md")
    for file_path in files:
        with open(file_path, "r") as f:
            kb_content += f"\n--- SOURCE: {os.path.basename(file_path)} ---\n"
            kb_content += f.read()
    return kb_content


@app.api_route("/incoming-call", methods=["GET", "POST"])
async def incoming_call(request: Request):
    response = VoiceResponse()
    response.say("Waiting for riley to pickup.")
    response.pause(length=1)
    connect = Connect()
    connect.stream(url=f"wss://{request.url.hostname}/media-stream")
    response.append(connect)
    return HTMLResponse(content=str(response), media_type="application/xml")


@app.websocket("/media-stream")
async def media_stream(websocket: WebSocket):
    print("Client connected")
    await websocket.accept()

    knowledge_base_text = load_knowledge_base()
    full_system_prompt = SYSTEM_MESSAGE + knowledge_base_text

    openai_url = f"wss://api.openai.com/v1/realtime?model={MODEL}"
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "OpenAI-Beta": "realtime=v1",
    }
    ssl_context = ssl.create_default_context(cafile=certifi.where())

    try:
        async with websockets.connect(
                openai_url,
                additional_headers=headers,
                ssl=ssl_context
        ) as openai_ws:
            print(">>> Connected to OpenAI.")

            # 1. Initialize Session with Tool Definition
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
                    # --- NEW: Define the Tool ---
                    "tools": [
                        {
                            "type": "function",
                            "name": "end_call",
                            "description": "Ends the phone call. Use this when the user says goodbye, bye, or indicates they are done.",
                            "parameters": {
                                "type": "object",
                                "properties": {}
                            }
                        }
                    ],
                    "tool_choice": "auto"
                }
            }))

            stream_sid = None

            # --- Task A: Twilio -> OpenAI ---
            async def receive_from_twilio():
                nonlocal stream_sid
                try:
                    async for message in websocket.iter_text():
                        data = json.loads(message)

                        if data['event'] == 'media':
                            await openai_ws.send(json.dumps({
                                "type": "input_audio_buffer.append",
                                "audio": data['media']['payload']
                            }))

                        elif data['event'] == 'start':
                            stream_sid = data['start']['streamSid']
                            print(f"--- Stream Started: {stream_sid} ---")
                            # Trigger Greeting
                            await openai_ws.send(json.dumps({
                                "type": "response.create",
                                "response": {
                                    "modalities": ["text", "audio"],
                                    "instructions": "Say 'Hello! How can I help you today?'"
                                }
                            }))

                except Exception as e:
                    print(f"Twilio Error: {e}")

            # --- Task B: OpenAI -> Twilio ---
            async def receive_from_openai():
                try:
                    async for message in openai_ws:
                        response = json.loads(message)

                        if response['type'] == 'response.audio.delta' and stream_sid:
                            await websocket.send_json({
                                "event": "media",
                                "streamSid": stream_sid,
                                "media": {"payload": response['delta']}
                            })

                        elif response['type'] == 'input_audio_buffer.speech_started':
                            print(">>> INTERRUPT: Clearing buffer...")
                            if stream_sid:
                                await websocket.send_json({"event": "clear", "streamSid": stream_sid})
                            await openai_ws.send(json.dumps({"type": "response.cancel"}))

                        # --- NEW: Handle Function Calls (Hangup) ---
                        elif response['type'] == 'response.function_call_arguments.done':
                            if response['name'] == 'end_call':
                                print(">>> AI REQUESTED HANGUP")
                                # Wait 2 seconds for the AI's "Goodbye" audio to finish playing on the phone
                                print(">>> Waiting for audio to finish...")
                                await asyncio.sleep(2)
                                print(">>> Hanging up now.")
                                await websocket.close()
                                return  # Exit the loop

                        elif response['type'] == 'response.audio_transcript.done':
                            print(f"AI: {response['transcript']}")

                        elif response['type'] == 'error':
                            print(f"!!! OpenAI Error: {response['error']['message']}")

                except Exception as e:
                    print(f"OpenAI Loop Error: {e}")

            await asyncio.gather(receive_from_twilio(), receive_from_openai())

    except Exception as e:
        print(f"\n!!! ERROR: {e}")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT)