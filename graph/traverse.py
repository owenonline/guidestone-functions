from typing import List
from gremlin_python.process.anonymous_traversal import traversal
from gremlin_python.driver.driver_remote_connection import DriverRemoteConnection
import os
import logging
from psycopg2 import pool
from pydantic import BaseModel, Field
from enum import Enum
from azure.storage.queue import QueueClient, TextBase64EncodePolicy, TextBase64DecodePolicy
from langchain_openai import AzureChatOpenAI
from langchain.output_parsers import OutputFixingParser, PydanticOutputParser
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
from operator import itemgetter
import re
import json

def send_update_message(node_id):
    with QueueClient.from_connection_string(conn_str=os.environ['AzureWebJobsStorage'], 
                                            queue_name="lesson-regenerate",
                                            message_encode_policy = TextBase64EncodePolicy(),
                                            message_decode_policy = TextBase64DecodePolicy()) as queue_client:
        queue_client.send_message(json.dumps({"node_id": node_id}))

def traverse_graph(user_id: str) -> list[str]:
    g = traversal().withRemote(DriverRemoteConnection('wss://guidestone-gremlin.gremlin.cosmos.azure.com:443/','g', 
                                                      username=f"/dbs/guidestone/colls/knowledge-graph", 
                                                      password=os.getenv("KNOWLEDGE_GRAPH_KEY")))
    
    def update_node_status(node_id):
        # Fetch the node and its status
        node_status = g.V(node_id).values('status').next()

        if node_status in ['ready', 'scoring', 'regen', 'firstgen']:
            # Do not search children
            return
        elif node_status == 'completed':
            # Progress to children
            for child_id in g.V(node_id).out().id().toList():
                update_node_status(child_id)
        elif node_status == 'graded':
            # Send out a message to update the level content
            send_update_message(node_id)
        elif node_status == 'unstarted':
            # Check if all incoming nodes are 'completed'
            if all(status == 'completed' for status in g.V(node_id).in_().values('status').toList()):
                # Update status to 'firstgen' and send out a message
                g.V(node_id).property('status', 'firstgen').next()
                send_update_message(node_id)
    
    root_node_id = g.V().hasLabel('start_node').has('user_id', user_id).values('id').next()
    update_node_status(root_node_id)

    