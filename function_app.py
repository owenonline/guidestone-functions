from typing import List
import typing
import azure.functions as func
from gremlin_python.driver import client, serializer
import os
import logging
from psycopg2 import pool
import json
from graph.api import get_graph_structure, get_node_details
from graph.expand import expand_graph
from users.auth import exchange_token
from users.new import create_new_user

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

@app.function_name("healthcheck")
@app.route(route="healthcheck",
           auth_level=func.AuthLevel.ANONYMOUS, 
           methods=['GET','POST'])
def healthcheck(req: func.HttpRequest) -> func.HttpResponse:
    # verify gremlin connection
    graph_client = client.Client('wss://guidestone-gremlin.gremlin.cosmos.azure.com:443/','g', 
                    username=f"/dbs/guidestone/colls/knowledge-graph", 
                    password=os.getenv("KNOWLEDGE_GRAPH_KEY"),
                    message_serializer=serializer.GraphSONSerializersV2d0())
    
    # verify postgres connection
    postgreSQL_pool = pool.SimpleConnectionPool(1, int(os.getenv("PYTHON_THREADPOOL_THREAD_COUNT")), os.getenv("POSTGRES_CONN_STRING"))  
    conn = postgreSQL_pool.getconn()
    postgreSQL_pool.putconn(conn)
    postgreSQL_pool.closeall()

    return func.HttpResponse(
        status_code=200
    )

@app.function_name("createUser")
@app.route(route="createUser",
           auth_level=func.AuthLevel.ANONYMOUS, 
           methods=['POST'])
def createUser(req: func.HttpRequest) -> func.HttpResponse:
    try:
        user_id = create_new_user(req.get_json())
        return func.HttpResponse(
            status_code=200,
            body={ "user_id": user_id}
        )
    except Exception as e:
        logging.exception(e)
        return func.HttpResponse(
            status_code=500
        )

@app.function_name("exchangeToken")
@app.route(route="exchangeToken",
           auth_level=func.AuthLevel.ANONYMOUS, 
           methods=['POST'])
def exchangeToken(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse(
        status_code=200,
        body={
            "access_token": exchange_token(req.get_json())
        }
    )

@app.function_name("getGraphStructure")
@app.route(route="getGraphStructure",
           auth_level=func.AuthLevel.ANONYMOUS, 
           methods=['POST'])
def getGraphStructure(req: func.HttpRequest) -> func.HttpResponse:
    graph_structure = get_graph_structure(req.get_json())

    return func.HttpResponse(
        status_code=200,
        body=json.dumps(graph_structure)
    )

@app.function_name("getNodeDetails")
@app.route(route="getNodeDetails",
           auth_level=func.AuthLevel.ANONYMOUS, 
           methods=['POST'])
def getNodeDetails(req: func.HttpRequest) -> func.HttpResponse:
    node_details = get_node_details(req.get_json())

    return func.HttpResponse(
        status_code=200,
        body=json.dumps(node_details)
    )

@app.function_name("expandGraph")
@app.route(route="expandGraph",
           auth_level=func.AuthLevel.ANONYMOUS, 
           methods=['POST'])
def expandGraph(req: func.HttpRequest) -> func.HttpResponse:
    expand_graph(req.get_json())
    
    return func.HttpResponse(
        status_code=200
    )

# @app.function_name("traverseGraph")
# @app.queue_trigger(arg_name='queuein', 
#                   queue_name='node-updated',
#                   connection="AzureWebJobsStorage")
# @app.queue_output(arg_name='queueout', 
#                   queue_name='actions',
#                   connection="AzureWebJobsStorage")
# def traverseGraph(queuein: func.QueueMessage, queueout: func.Out[typing.List[str]], context) -> None:
    
    
#     try:
#         node_id = queuein.get_json()
#     except ValueError as e:
#         logging.error(f"Queue message is not valid: {queuein.get_body().decode('utf-8')}")
#         return
    
    # get the records in the learning style database
    
# @app.function_name("createLesson")
# @app.queue_trigger(arg_name='queuemessage', 
#                   queue_name='actions',
#                   connection="AzureWebJobsStorage")
# def createLesson(queuemessage: func.QueueMessage, context) -> None:
#     graph_client = client.Client('wss://guidestone-gremlin.gremlin.cosmos.azure.com:443/','g', 
#                     username=f"/dbs/guidestone/colls/knowledge-graph", 
#                     password=os.getenv("KNOWLEDGE_GRAPH_KEY"),
#                     message_serializer=serializer.GraphSONSerializersV2d0())
    
#     postgreSQL_pool = pool.SimpleConnectionPool(1, int(os.getenv("PYTHON_THREADPOOL_THREAD_COUNT")), os.getenv("POSTGRES_CONN_STRING"))  
#     conn = postgreSQL_pool.getconn()
#     cursor = conn.cursor()
    
#     try:
#         data = LessonCreateRequest(**queuemessage.get_json()) # all the data in here is verified to be valid and will not cause errors
#     except ValidationError as e:
#         logging.exception(e)
#         logging.error(f"Invalid queue message: {queuemessage.get_json()}")
#         return
#     except ValueError as e:
#         logging.error(f"Queue message is not valid: {queuemessage.get_body().decode('utf-8')}")
#         return
    
#     # get the records in the learning style database
#     # TODO: Implement learning style database

