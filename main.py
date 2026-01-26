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

load_dotenv()

# --- Configuration ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
PORT = int(os.getenv("PORT", 8000))

# Using the generic alias is often safer/more stable
MODEL = "gpt-4o-realtime-preview"

SYSTEM_MESSAGE = (
    "You are a helpful assistant named Riley. "
    "Speak fast, briefly, and clearly. Do not use markdown."
)

app = FastAPI()


@app.api_route("/incoming-call", methods=["GET", "POST"])
async def incoming_call(request: Request):
    response = VoiceResponse()
    response.say("Connecting to Riley.")
    response.pause(length=1)
    connect = Connect()
    connect.stream(url=f"wss://{request.url.hostname}/media-stream")
    response.append(connect)
    return HTMLResponse(content=str(response), media_type="application/xml")


@app.websocket("/media-stream")
async def media_stream(websocket: WebSocket):
    print("Client connected")
    await websocket.accept()

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
            print(">>> Connected to OpenAI. Initializing...")

            # 1. Initialize Session
            await openai_ws.send(json.dumps({
                "type": "session.update",
                "session": {
                    "modalities": ["text", "audio"],
                    "instructions": SYSTEM_MESSAGE,
                    "voice": "ash",
                    "input_audio_format": "g711_ulaw",
                    "output_audio_format": "g711_ulaw",
                    "turn_detection": {
                        "type": "server_vad",
                        "threshold": 0.5,  # Adjust sensitivity
                        "prefix_padding_ms": 300,
                        "silence_duration_ms": 500
                    }
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

                            # Force a Greeting
                            print(">>> Triggering Greeting...")
                            await openai_ws.send(json.dumps({
                                "type": "response.create",
                                "response": {
                                    "modalities": ["text", "audio"],
                                    "instructions": "Say 'Hello, I am ready!'"
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

                        elif response['type'] == 'response.audio_transcript.done':
                            print(f"AI: {response['transcript']}")

                        elif response['type'] == 'error':
                            print(f"!!! OpenAI Error: {response['error']['message']}")

                except Exception as e:
                    print(f"OpenAI Loop Error: {e}")

            await asyncio.gather(receive_from_twilio(), receive_from_openai())

    except websockets.exceptions.InvalidStatusCode as e:
        print(f"\n!!! CONNECTION FAILED: {e.status_code}")
        if e.status_code == 403:
            print(">>> CAUSE: Invalid API Key or Permissions.")
        elif e.status_code == 400:
            print(">>> CAUSE: Bad Request (Check model name or format).")
        elif e.status_code == 429:
            print(">>> CAUSE: Rate Limit or Insufficient Quota (Check Billing).")

    except Exception as e:
        print(f"\n!!! UNEXPECTED ERROR: {e}")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT)