from typing import List
import typing
import azure.functions as func
from gremlin_python.driver import client, serializer
import os
import logging
from psycopg2 import pool
import json
from grader.grade import score_user
from grader.metrics import calculate_attention
from graph.api import get_graph_structure, get_node_details
from graph.expand import expand_graph
from graph.traverse import traverse_graph
from lesson.create import create_lesson
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
            body=json.dumps({"user_id": user_id})
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
        body=json.dumps(exchange_token(req.get_json()))
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
@app.queue_output(arg_name='queue', 
                  queue_name='node-updated',
                  connection="AzureWebJobsStorage")
def expandGraph(req: func.HttpRequest, queue: func.Out[str]) -> func.HttpResponse:
    req_json: dict = req.get_json()
    expand_graph(req_json)

    # queue.set(req_json['user_id'])
    
    return func.HttpResponse(
        status_code=200
    )

@app.function_name("traverseGraph")
@app.queue_trigger(arg_name='queuein', 
                  queue_name='node-updated',
                  connection="AzureWebJobsStorage")
def traverseGraph(queuein: func.QueueMessage, context) -> None:
    traverse_graph(queuein.get_body().decode("utf-8"))
    
@app.function_name("createLesson")
@app.queue_trigger(arg_name='queuemessage', 
                  queue_name='lesson-regenerate',
                  connection="AzureWebJobsStorage")
def createLesson(queuemessage: func.QueueMessage, context) -> None:
    create_lesson(queuemessage.get_json())

@app.function_name("lessonDone")
@app.route(route="lessonDone",
           auth_level=func.AuthLevel.ANONYMOUS, 
           methods=['POST'])
@app.queue_output(arg_name='queue', 
                  queue_name='quiz-taken',
                  connection="AzureWebJobsStorage")
def lessonDone(req: func.HttpRequest, queue: func.Out[str]) -> func.HttpResponse:
    graph_client = client.Client('wss://guidestone-gremlin.gremlin.cosmos.azure.com:443/','g', 
                    username=f"/dbs/guidestone/colls/knowledge-graph", 
                    password=os.getenv("KNOWLEDGE_GRAPH_KEY"),
                    message_serializer=serializer.GraphSONSerializersV2d0())
    
    postgreSQL_pool = pool.SimpleConnectionPool(1, int(os.getenv("PYTHON_THREADPOOL_THREAD_COUNT")), os.getenv("POSTGRES_CONN_STRING"))  
    conn = postgreSQL_pool.getconn()
    cursor = conn.cursor()

    req_json = req.get_json()

    attention_score = calculate_attention(req_json['vision_points'], req_json['node_id'])
    
    queue.set(json.dumps({"user_id": req_json['user_id'], "node_id": req_json['node_id'], "attention_score": attention_score, "quiz_data": req_json["quiz_data"]}))

    # mark node status as grading
    graph_client.submit(f"g.V('{req_json['node_id']}').property('status', 'scoring')")

    return func.HttpResponse(
        status_code=200
    )

@app.function_name("gradeQuiz")
@app.queue_trigger(arg_name='queuein', 
                  queue_name='quiz-taken',
                  connection="AzureWebJobsStorage")
@app.queue_output(arg_name='queueout', 
                  queue_name='node-updated',
                  connection="AzureWebJobsStorage")
def gradeQuiz(queuein: func.QueueMessage, queueout: func.Out[str], context) -> None:
    req_json = json.loads(queuein.get_body().decode("utf-8"))
    graph_client = client.Client('wss://guidestone-gremlin.gremlin.cosmos.azure.com:443/','g', 
                    username=f"/dbs/guidestone/colls/knowledge-graph", 
                    password=os.getenv("KNOWLEDGE_GRAPH_KEY"),
                    message_serializer=serializer.GraphSONSerializersV2d0())
    
    postgreSQL_pool = pool.SimpleConnectionPool(1, int(os.getenv("PYTHON_THREADPOOL_THREAD_COUNT")), os.getenv("POSTGRES_CONN_STRING"))  
    conn = postgreSQL_pool.getconn()
    cursor = conn.cursor()

    # get learning statuses and masteries
    tid_callback = graph_client.submit(f"g.V('{req_json['node_id']}').values('table_id')")
    table_id = tid_callback.all().result()[0]
    cursor.execute("SELECT learning_status, masteries FROM nodes WHERE id=%s", (table_id,))
    learning_status, masteries = cursor.fetchone()

    score_user(req_json['node_id'], req_json['quiz_data'], req_json['attention_score'], masteries)

    queueout.set(req_json['user_id'])