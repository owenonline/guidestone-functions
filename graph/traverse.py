from typing import List
from gremlin_python.driver import client, serializer
import os
import logging
from psycopg2 import pool
from pydantic import BaseModel, Field
from enum import Enum, auto
from azure.storage.queue import QueueClient, TextBase64EncodePolicy, TextBase64DecodePolicy
from langchain_openai import AzureChatOpenAI
from langchain.output_parsers import OutputFixingParser, PydanticOutputParser
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
from operator import itemgetter
import re
import json

def send_update_message(node_id, user_id):
    with QueueClient.from_connection_string(conn_str=os.environ['AzureWebJobsStorage'], 
                                            queue_name="lesson-regenerate",
                                            message_encode_policy = TextBase64EncodePolicy(),
                                            message_decode_policy = TextBase64DecodePolicy()) as queue_client:
        queue_client.send_message(json.dumps({"node_id": node_id, "user_id": user_id}))

def traverse_graph(user_id: str) -> list[str]:
    graph_client = client.Client('wss://guidestone-gremlin.gremlin.cosmos.azure.com:443/','g', 
                    username=f"/dbs/guidestone/colls/knowledge-graph", 
                    password=os.getenv("KNOWLEDGE_GRAPH_KEY"),
                    message_serializer=serializer.GraphSONSerializersV2d0())
    
    def update_node_status(node_id):
        # Fetch the node and its status
        cb = graph_client.submit(f"g.V('{node_id}').values('status')")
        node_status = cb.all().result()[0]

        if node_status in ['ready', 'scoring', 'regen', 'firstgen']:
            # Do not search children
            return
        elif node_status == 'completed':
            # Progress to children
            child_id_callback = graph_client.submit(f"g.V('{node_id}').out().id()")
            child_ids = child_id_callback.all().result()

            for child_id in child_ids:
                update_node_status(child_id)
        elif node_status == 'graded':
            # Send out a message to update the level content
            send_update_message(node_id, user_id)
        elif node_status == 'unstarted':
            # Check if all incoming nodes are 'completed'
            invals_callback = graph_client.submit(f"g.V('{node_id}').in().values('status')")
            invals = invals_callback.all().result()
            if all(status == 'completed' for status in invals):
                # Update status to 'firstgen' and send out a message
                graph_client.submit(f"g.V('{node_id}').property('status', 'firstgen')")
                send_update_message(node_id, user_id)
    
    gc_callback = graph_client.submit(f"g.V().hasLabel('start_node').has('user_id', '{user_id}').values('id')")
    root_node_id = gc_callback.all().result()[0]
    update_node_status(root_node_id)

    