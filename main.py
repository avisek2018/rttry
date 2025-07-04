from multiprocessing import connection
import os
# import logging
import uuid
from urllib.parse import urlencode, urlparse, urlunparse
from dotenv import load_dotenv
from typing import List, Dict, Any, Optional
# from fastapi.logger import logger
from loguru import logger
from fastapi import (
    Body,
    FastAPI,
    Form,
    WebSocket,
    HTTPException,
    Request,
    status,
    APIRouter,
    Depends,
)
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, RedirectResponse
from azure.eventgrid import EventGridEvent, SystemEventNames
from azure.communication.callautomation import (
    MediaStreamingOptions,
    AudioFormat,
    MediaStreamingTransportType,
    MediaStreamingContentType,
    MediaStreamingAudioChannelType,
    CallAutomationClient,
    CallConnectionClient,
    PhoneNumberIdentifier,
    RecognizeInputType,
    MicrosoftTeamsUserIdentifier,
    CallInvite,
    RecognitionChoice,
    DtmfTone,
    TextSource,
)


from communication_handler import CommunicationHandler


load_dotenv()

app = FastAPI()
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

ACS_CONNECTION_STRING = os.getenv("ACS_CONNECTION_STRING")
acs_ca_client = CallAutomationClient.from_connection_string(ACS_CONNECTION_STRING)

# Callback events URI to handle callback events.
CALLBACK_URI_HOST = os.getenv("CALLBACK_URI_HOST")
CALLBACK_EVENTS_URI = CALLBACK_URI_HOST + "/api/callbacks"

#caller_id = None  # Define at the top level


@app.get("/")
async def root():
    return JSONResponse({"message": "Hello World!"})


@app.post("/api/incomingCall")
async def incoming_call_handler(request: Request):
    #global caller_id
    logger.info("incoming event data")
    for event_dict in await request.json():
        event = EventGridEvent.from_dict(event_dict)
        logger.info("Received Event Dict: ", {str(event_dict)})
        #logger.info("incoming event data --> %s", {event.data})
        if (
            event.event_type
            == SystemEventNames.EventGridSubscriptionValidationEventName
        ):
            logger.info("Validating subscription")
            validation_code = event.data["validationCode"]
            validation_response = {"validationResponse": validation_code}
            
            return JSONResponse(
                content=validation_response, status_code=status.HTTP_200_OK
            )
        elif event.event_type == "Microsoft.Communication.IncomingCall":
            if event.data["from"]["kind"] == "phoneNumber":
                caller_id = event.data["from"]["phoneNumber"]["value"]
            else:
                caller_id = event.data["from"]["rawId"]

            if event.event_type == "Microsoft.Communication.IncomingCall":
                logger.info("incoming event :", {event.event_type})
                if event.data["from"]["kind"] == "phoneNumber":
                    caller_id = event.data["from"]["phoneNumber"]["value"]
                else:
                    caller_id = event.data["from"]["rawId"]
            logger.info("Caller ID:", {caller_id})
            incoming_call_context = event.data["incomingCallContext"]
            guid = uuid.uuid4()
            logger.info("Incoming Call Context: ", {incoming_call_context})
            query_parameters = urlencode({"callerId": caller_id, "boo": "poop"})
            callback_uri = f"{CALLBACK_EVENTS_URI}/{guid}?{query_parameters}"

            parsed_url = urlparse(CALLBACK_EVENTS_URI)
            #websocket_url = urlunparse(("wss", parsed_url.netloc, "/ws", "", "", ""))
            websocket_url = urlunparse(("wss", parsed_url.netloc, "/ws", "", f"caller_id={caller_id}", ""))

       

            logger.info(f"callback url: {callback_uri}")
            logger.info(f"websocket url: {websocket_url}")

            try:
                # Answer the incoming call

                media_streaming_options = MediaStreamingOptions(
                    transport_url=websocket_url,
                    transport_type=MediaStreamingTransportType.WEBSOCKET,
                    content_type=MediaStreamingContentType.AUDIO,
                    audio_channel_type=MediaStreamingAudioChannelType.MIXED,
                    start_media_streaming=True,
                    enable_bidirectional=True,
                    audio_format=AudioFormat.PCM24_K_MONO,
                )

                logger.info("Incoming Call Context: ", {incoming_call_context})
                logger.info("Media Streaming Options: ", {media_streaming_options})

                answer_call_result = acs_ca_client.answer_call(
                    incoming_call_context=incoming_call_context,
                    operation_context="incomingCall",
                    callback_url=callback_uri,
                    media_streaming=media_streaming_options,
                )

            except Exception as e:
                logger.info("An error occurred:", {e})
                raise e

            logger.info(
                f"Answered call for connection id: {answer_call_result.call_connection_id}"
            )


@app.post("/api/callbacks/{contextId}")
async def handle_callback_with_context(contextId: str, request: Request):
    for event in await request.json():
        # Parsing callback events
        global call_connection_id
        event_data = event["data"]
        call_connection_id = event_data["callConnectionId"]
        logger.info(
            f"Received Event:-> {event['type']}, Correlation Id:-> {event_data['correlationId']}, CallConnectionId:-> {call_connection_id}"
        )
        if event["type"] == "Microsoft.Communication.CallConnected":
            call_connection_properties = acs_ca_client.get_call_connection(
                call_connection_id
            ).get_call_properties()
            media_streaming_subscription = (
                call_connection_properties.media_streaming_subscription
            )

            logger.info(
                f"MediaStreamingSubscription:--> {media_streaming_subscription}"
            )
            logger.info(
                f"Received CallConnected event for connection id: {call_connection_id}"
            )
            logger.info(f"CORRELATION ID:--> { event_data['correlationId'] }")
            logger.info(f"CALL CONNECTION ID:--> {event_data['callConnectionId']}")
        elif event["type"] == "Microsoft.Communication.MediaStreamingStarted":
            logger.info(
                f"Media streaming content type:--> {event_data['mediaStreamingUpdate']['contentType']}"
            )
            logger.info(
                f"Media streaming status:--> {event_data['mediaStreamingUpdate']['mediaStreamingStatus']}"
            )
            logger.info(
                f"Media streaming status details:--> {event_data['mediaStreamingUpdate']['mediaStreamingStatusDetails']}"
            )
        elif event["type"] == "Microsoft.Communication.MediaStreamingStopped":
            logger.info(
                f"Media streaming content type:--> {event_data['mediaStreamingUpdate']['contentType']}"
            )
            logger.info(
                f"Media streaming status:--> {event_data['mediaStreamingUpdate']['mediaStreamingStatus']}"
            )
            logger.info(
                f"Media streaming status details:--> {event_data['mediaStreamingUpdate']['mediaStreamingStatusDetails']}"
            )
        elif event["type"] == "Microsoft.Communication.MediaStreamingFailed":
            logger.info(
                f"Code:->{event_data['resultInformation']['code']}, Subcode:-> {event_data['resultInformation']['subCode']}"
            )
            logger.info(f"Message:->{event_data['resultInformation']['message']}")
        elif event["type"] == "Microsoft.Communication.CallDisconnected":
            pass


# WebSocket
@app.websocket("/ws")
async def ws(websocket: WebSocket, caller_id: Optional[str] = None):
    logger.info("WebSocket connection trying to get established")
    await websocket.accept()
    #caller_id = websocket.query_params.get("caller_id")
    logger.info("WebSocket connection established")
    logger.info(f"Caller ID from WebSocket: {caller_id}")
    service = CommunicationHandler(websocket=websocket, caller_id=caller_id)
    await service.start_conversation_async()
    
    while True:
        try:
            # Receive data from the client
            data = await websocket.receive_json()
            #logger.info(f"Received data from client: {data}")
            kind = data["kind"]
            if kind == "AudioData":
                audio_data = data["audioData"]["data"]
                # Send the audio data to the CallAutomationHandler
                await service.send_audio_async(audio_data)
        except Exception as e:
            print(f"WebSocket connection closed: {e}")
            break

