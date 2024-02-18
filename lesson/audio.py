import ast
import operator
from typing import Annotated, Dict, List, Optional, Sequence, Type, TypedDict
import azure.functions as func
from psycopg2 import pool
import requests
from pydantic import BaseModel, Field, ValidationError, root_validator, validator, ConfigDict
from enum import Enum
from langchain_openai import AzureChatOpenAI
from langchain_core.runnables import RunnableLambda
from langchain_core.messages import BaseMessage, ToolMessage, HumanMessage
from langchain.agents.output_parsers.openai_tools import OpenAIToolsAgentOutputParser
from langchain.tools.render import format_tool_to_openai_tool
from langchain.agents.format_scratchpad.openai_tools import format_to_openai_tool_messages
from langchain.output_parsers import OutputFixingParser, PydanticOutputParser
from langchain.prompts import ChatPromptTemplate
from langchain.schema import StrOutputParser
from langchain.tools import BaseTool
import shutil
from langchain.callbacks.manager import (
    AsyncCallbackManagerForToolRun,
    CallbackManagerForToolRun,
)
from operator import itemgetter
import re
import json
import os
import subprocess
from ansi2html import Ansi2HTMLConverter
from langchain.agents import AgentExecutor

from langchain.callbacks.manager import (
    AsyncCallbackManagerForToolRun,
    CallbackManagerForToolRun,
)
from langgraph.prebuilt import ToolExecutor, ToolInvocation
from langgraph.graph import StateGraph, END
from langgraph.pregel import Pregel
from azure.storage.blob import BlobServiceClient, BlobClient, ContainerClient
from langchain.load.dump import dumps
from langchain.load.load import loads
from langchain.schema import StrOutputParser

from langchain_openai import AzureChatOpenAI
from langchain.output_parsers import OutputFixingParser, PydanticOutputParser
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
from operator import itemgetter
from gremlin_python.process.anonymous_traversal import traversal
from gremlin_python.driver.driver_remote_connection import DriverRemoteConnection
from langchain.schema import StrOutputParser
from concurrent.futures import ThreadPoolExecutor, as_completed
from lesson.video import VideoGeneratorAgent
import os

class Script(BaseModel):
    txt: str

def create_audio(prompt: str, visuals: str, folder: str, i: int):
    gpt_4_llm = AzureChatOpenAI(deployment_name="gpt-4-turbo", api_version="2023-07-01-preview", model_name="gpt-4-1106-preview", temperature=0, max_retries=10)

    s_parser = PydanticOutputParser(pydantic_object=Script)
    lp_fixing_parser = OutputFixingParser.from_llm(parser=s_parser, llm=gpt_4_llm)

    script_writing_prompt = ChatPromptTemplate.from_messages(
        [
            ('system', "Your job is to write a script for a scene of an educational video based on the information below. Your script must contain nothing but the words that are going to be spoken. Anything else will mess up the recording session."),
            ('user', "This is an overview of what the script needs to contain: {prompt}. While your script is being recited, this will be on stage, so keep that in mind: {visuals}")
        ]
    )
    script_writing_chain = (
        {
            "prompt": itemgetter("prompt"),
            "visuals": itemgetter("visuals"),
        }
        | script_writing_prompt
        | gpt_4_llm
        | lp_fixing_parser
    )

    script = script_writing_chain.invoke({
        "prompt": prompt,
        "visuals": visuals
    })

    response = requests.post("https://api.elevenlabs.io/v1/text-to-speech/fJE3lSefh7YI494JMYYz", json={
        "text": script.txt,
        "voice_settings": {
            "similarity_boost": 0.75,
            "stability": 0.5,
        }
    }, headers={
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
        "xi-api-key": os.getenv("ELEVEN_LABS_API_KEY")
    })

    with open(os.path.join(folder, f"voiceover_{i}.mp3"), 'wb') as f:
        for chunk in response.iter_content(chunk_size=1024):
            if chunk:
                f.write(chunk)

    return os.path.join(folder, "voiceover.mp3")