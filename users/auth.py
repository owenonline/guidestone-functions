from typing import List
import azure.functions as func
from gremlin_python.driver import client, serializer
import os
import logging
from psycopg2 import pool
from pydantic import BaseModel, Field, ValidationError, root_validator, validator
from enum import Enum
from langchain_openai import AzureChatOpenAI
from langchain.output_parsers import OutputFixingParser, PydanticOutputParser
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
from operator import itemgetter

import requests
from graph.api import get_graph_structure, get_node_details
import re
import json

class TokenExchangeRequest(BaseModel):
    code: str
    redirect_uri: str

def exchange_token(request_json: dict) -> str:
    try:
        req_json = TokenExchangeRequest(**request_json)
    except:
        logging.error("Could not parse token exchange request: " + str(e))

    token_endpoint = 'https://www.googleapis.com/oauth2/v4/token'
    payload = {
        'code': req_json.code,
        'client_id': os.getenv("GOOGLE_CLIENT_ID"),
        'client_secret': os.getenv("GOOGLE_CLIENT_SECRET"),
        'redirect_uri': req_json.redirect_uri,
        'grant_type': 'authorization_code',
    }
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
    }

    response = requests.post(token_endpoint, data=payload, headers=headers)
    response.raise_for_status()
    return response['access_token']