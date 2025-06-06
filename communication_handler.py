import json
import os
import uuid  # Add uuid import
from dotenv import load_dotenv
from fastapi import WebSocket
from fastapi.websockets import WebSocketState
from openai import AzureOpenAI
import base64
import asyncio
from azure.core.credentials import AzureKeyCredential
from azure.identity.aio import DefaultAzureCredential
from azure.communication.sms import SmsClient, SmsSendResult
from rtclient import (
    FunctionCallOutputItem,
    InputAudioBufferAppendMessage,
    InputAudioTranscription,
    InputTextContentPart,
    ItemCreateMessage,
    RTLowLevelClient,
    ResponseCreateMessage,
    ResponseCreateParams,
    ServerMessageType,
    ServerVAD,
    SessionUpdateMessage,
    SessionUpdateParams,
    UserMessageItem,
)

import logging
from aiologger import Logger

from verify_user import VerifyUser


logging.basicConfig(level=logging.INFO)
# logger = logging.getLogger(__name__)
logger = Logger.with_default_handlers()


load_dotenv()

AZURE_OPENAI_REALTIME_ENDPOINT = os.getenv("AZURE_OPENAI_REALTIME_ENDPOINT")
AZURE_OPENAI_REALTIME_SERVICE_KEY = os.getenv("AZURE_OPENAI_REALTIME_SERVICE_KEY")
AZURE_OPENAI_REALTIME_DEPLOYMENT_MODEL_NAME = os.getenv("AZURE_OPENAI_REALTIME_DEPLOYMENT_MODEL_NAME")

ACS_CONNECTION_STRING = os.getenv("ACS_CONNECTION_STRING")
ACS_SMS_CONNECTION_STRING = os.getenv("ACS_SMS_CONNECTION_STRING")

load_dotenv()

class CommunicationHandler:
    voice_name = None or "alloy"
    target_phone_number = os.getenv("TARGET_PHONE_NUMBER")
    # Read system_prompt from the file.
    system_prompt_path = os.path.join(os.path.dirname(__file__), "system_prompt.txt")
    try:
        with open(system_prompt_path, "r", encoding="utf-8") as f:
            system_prompt = f.read()
    except Exception as e:
        system_prompt = ""
        logging.warning(f"Could not read system_prompt.txt: {e}")

    caller_id = None  # Define at the top level

    def __init__(self, websocket: WebSocket, caller_id) -> None:
        self.rt_client = None
        self.active_websocket = websocket
        self.caller_id = caller_id
        return

    async def start_conversation_async(self) -> None:
        self.rt_client = RTLowLevelClient(
            url=AZURE_OPENAI_REALTIME_ENDPOINT,
            key_credential=AzureKeyCredential(AZURE_OPENAI_REALTIME_SERVICE_KEY),
            azure_deployment=AZURE_OPENAI_REALTIME_DEPLOYMENT_MODEL_NAME,
        )
        try:
            await self.rt_client.connect()
        except Exception as e:
            print(f"Failed to connect to Azure OpenAI Realtime Service: {e}")
            raise e

        functions = [
            {
                "type": "function",
                "name": "validate_user",
                "description": "Validate user based on the phone no",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "ph_no": {
                            "type": "string",
                            "description": "The phone number from which the user is calling.",
                        },
                    },
                    "required": ["ph_no"], 
                },
            },
        ]

        session_update_message = {
            "type": "session.update",
            "session": {
                "voice": "alloy",
                "instructions": self.system_prompt,
                "input_audio_format": "pcm16",
                "input_audio_transcription": {"model": "whisper-1"},
                "turn_detection": {
                    "threshold": 0.6,
                    "silence_duration_ms": 300,
                    "prefix_padding_ms": 200,
                    "type": "server_vad",
                },
                "tools": functions,
            },
        }

        session_update_message_payload = SessionUpdateMessage(**session_update_message)
        await self.rt_client.send(session_update_message_payload)

        # Generate initial call_id that will be used for the entire conversation
        self.conversation_call_id = str(uuid.uuid4())

        content_part = InputTextContentPart(
            text="Greet the caller with a message – Please give me a couple of seconds so we can verify your details. I will then be able to assist you with your request.",
        )
        initial_conversation_item = ItemCreateMessage(
            item=UserMessageItem(content=[content_part]),
            call_id=self.conversation_call_id  # Use the stored conversation_call_id
        )

        await self.rt_client.send(message=initial_conversation_item)
        # NOTE: Need to call this to tell OpenAI to start the conversation and say something first to the user
        await self.rt_client.send(ResponseCreateMessage())

        asyncio.create_task(self.receive_messages_async())
        return

    async def send_message_async(self, message: str) -> None:
        try:
            if self.active_websocket.client_state == WebSocketState.CONNECTED:
                await self.active_websocket.send_text(message)
        except Exception as e:
            logger.error(f"Send Message - Failed to send message: {e}")
            raise e

    async def receive_messages_async(self) -> None:
        try:
            while not self.rt_client.closed:
                message: ServerMessageType = await self.rt_client.recv()

                if message is None or self.rt_client.ws.closed:
                    continue
                
                match message.type:
                    case "session.created":
                        print("Session Created Message")
                        print(f"Session Id: {message.session.id}")
                        pass
                    case "error":
                        print(f"Error: {message.error}")
                        pass
                    case "input_audio_buffer.cleared":
                        print("Input Audio Buffer Cleared Message")
                        pass
                    case "input_audio_buffer.speech_started":
                        print(
                            f"Voice activity detection started at {message.audio_start_ms} [ms]"
                        )
                        await self.stop_audio_async()
                        pass
                    case "input_audio_buffer.speech_stopped":
                        pass
                    case "conversation.item.input_audio_transcription.completed":
                        print(f"User:-- {message.transcript}")
                    case "conversation.item.input_audio_transcription.failed":
                        print(f"Error: {message.error}")
                    case "response.done":
                        print("Response Done Message")
                        print(f"  Response Id: {message.response.id}")

                        if message.response.status_details:
                            print(
                                f"Status Details: {message.response.status_details.model_dump_json()}"
                            )
                    case "response.audio_transcript.done":
                        print(f"AI:-- {message.transcript}")
                    case "response.audio.delta":
                        await self.receive_audio(message.delta)
                        pass
                    case "function_call":
                        print(f"Function Call Message: {message}")
                        # Store the original call_id from the function call
                        call_id = message.call_id
                        pass
                    case "response.function_call_arguments.done":
                        print(f"Message: {message}")
                        function_name = message.name
                        args = json.loads(message.arguments)
                        # Use the call_id from the original function call
                        call_id = message.call_id

                        print(f"Function args: {message.arguments}")

                        if function_name == "validate_user":
                            # Handle the function call to get results
                            logger.info(f"Function Call Name: {function_name}")
                            try:
                                #query = args["query"]
                                # Use the phone number from the handler (self.target_phone_number)
                                is_verified = await VerifyUser.verify_user(self.caller_id)
                                logger.info(f"User Verified? {is_verified}")
                                if not is_verified:
                                    await self.rt_client.ws.send_json(
                                        {
                                            "type": "conversation.item.create",
                                            "item": {
                                                "type": "function_call_output",
                                                "output": "Sorry, I couldn't verify your phone number.",
                                                "call_id": call_id  # Use original call_id
                                            }
                                        }
                                    )
                                else:
                                    await self.rt_client.ws.send_json(
                                        {
                                            "type": "conversation.item.create",
                                            "item": {
                                                "type": "function_call_output",
                                                "output": "I failed to veeify you based on your ph no.",
                                                "call_id": call_id  # Use original call_id
                                            }
                                        }
                                    )
                                    continue


                                await self.rt_client.ws.send_json(
                                    {
                                        "type": "conversation.item.create",
                                        "item": {
                                            "type": "function_call_output",
                                            "output": "For whom you need the back up care for",
                                           # "output": f"Here is a recipe for you: {recipe_name}",
                                            "call_id": call_id  # Use original call_id
                                        }
                                    }
                                )

                                await self.rt_client.ws.send_json(
                                    {
                                        "type": "response.create",
                                        "response": {
                                            "modalities": ["text", "audio"],
                                            "instructions": f"Respond to the user that you are able to validate and proceed with the next set of questions."
                                        }
                                    }
                                )
                            except Exception as e:
                                logger.error(f"Error in Response: {e}")
                                await self.rt_client.ws.send_json(
                                    {
                                        "type": "conversation.item.create",
                                        "item": {
                                            "type": "function_call_output",
                                            "output": "Sorry, I encountered an error while searching for the topic.",
                                            "call_id": call_id  # Use original call_id
                                        }
                                    }
                                )
                        elif function_name == "send_result":
                            url = args["url"]
                            await self.send_sms(url)
                            pass

                        elif function_name == "transfer_to_agent":
                            # await self.tranfer_call(...)
                            pass

                        logger.info(f"Function Call Arguments: {message.arguments}")
                        print(f"Function Call Arguments: {message.arguments}")
                        pass
                    case _:
                        pass
        except Exception as e:
            logger.error(f"Error in receive_messages_async: {e}")
            if not isinstance(e, asyncio.CancelledError):
                raise e

    async def receive_audio(self, data_payload) -> None:
        try:
            data_payload = {
                "Kind": "AudioData",
                "AudioData": {"Data": data_payload},
                "StopAudio": None,
            }

            # Serialize the server streaming data
            serialized_data = json.dumps(data_payload)
            await self.send_message_async(serialized_data)

        except Exception as e:
            print(e)

    async def send_audio_async(self, audio_data: str) -> None:
        await self.rt_client.send(
            message=InputAudioBufferAppendMessage(
                type="input_audio_buffer.append", audio=audio_data, _is_azure=True
            )
        )

    async def stop_audio_async(self) -> None:
        try:
            stop_audio_data = {"Kind": "StopAudio", "AudioData": None, "StopAudio": {}}
            json_data = json.dumps(stop_audio_data)
            await self.send_message_async(json_data)
        except Exception as e:
            # print(f"Stop Audio - Failed to send message: {e}")
            logger.error(f"Stop Audio - Failed to send message: {e}")
            raise e
        return

    async def send_sms(self, message: str) -> None:
        try:
            sms_client = SmsClient.from_connection_string(ACS_SMS_CONNECTION_STRING)
            sms_response_list: list[SmsSendResult] = sms_client.send(
                from_=os.getenv("ACS_SMS_FROM_PHONE_NUMBER"),
                to=[self.target_phone_number],
                message=f"Hello from RecipeFinder! Here's the recipe you requested:\n\n{message}",
            )

            for sms_response in sms_response_list:
                if sms_response.successful is True:
                    logger.info(f"SMS sent: {sms_response}")
                else:
                    logger.error(f"Failed to send SMS: {sms_response}")

        except Exception as e:
            logger.error(f"Failed to send SMS: {e}")
            raise e
