from gremlin_python.driver import client, serializer
import os
import logging
from psycopg2 import pool
from pydantic import BaseModel
from azure.storage.blob import BlobServiceClient

class GraphStructureRequest(BaseModel):
    user_id: int

class NodeDetailRequest(BaseModel):
    node_id: str

class GraphError(Exception):
    pass

def get_graph_structure(req_json: dict) -> dict[str, any]:
    graph_client = client.Client('wss://guidestone-gremlin.gremlin.cosmos.azure.com:443/','g', 
                    username=f"/dbs/guidestone/colls/knowledge-graph", 
                    password=os.getenv("KNOWLEDGE_GRAPH_KEY"),
                    message_serializer=serializer.GraphSONSerializersV2d0())
    
    postgreSQL_pool = pool.SimpleConnectionPool(1, int(os.getenv("PYTHON_THREADPOOL_THREAD_COUNT")), os.getenv("POSTGRES_CONN_STRING"))  
    conn = postgreSQL_pool.getconn()
    cursor = conn.cursor()

    try:
        get_graph_body = GraphStructureRequest(**req_json)
    except Exception as e:
        logging.error("Could not parse get graph structure request: " + str(e))

    node_id_callback = graph_client.submit(f"g.V().has('user_id', '{get_graph_body.user_id}').values('id', 'table_id').fold()")
    node_table_ids = node_id_callback.all().result()[0]

    # base_ids_callback = graph_client.submit(f"g.V().hasLabel('start_node').has('user_id', '{get_graph_body.user_id}').out().values('id').fold()")
    # base_ids = base_ids_callback.all().result()[0]

    edges = []
    nodes = []
    node_names = {}
    for node_id, table_id in zip(node_table_ids[::2], node_table_ids[1::2]):
        # building a list of just node ids
        nodes.append(node_id)

        # building a list of edges
        edge_callback = graph_client.submit(f"g.V('{node_id}').outE().inV().values('id').fold()")
        edge_results = edge_callback.all().result()[0]
        edges.extend([(node_id, edge) for edge in edge_results])

        # building a dictionary of names
        cursor.execute("SELECT public_name FROM nodes WHERE id = %s", (table_id,))
        public_name, = cursor.fetchone()
        node_names[node_id] = public_name

    return {
        "nodes": nodes,
        # "bases": base_ids,
        "edges": edges,
        "names": node_names
    }

def get_node_details(req_json: dict) -> dict[str, any]:
    graph_client = client.Client('wss://guidestone-gremlin.gremlin.cosmos.azure.com:443/','g', 
                    username=f"/dbs/guidestone/colls/knowledge-graph", 
                    password=os.getenv("KNOWLEDGE_GRAPH_KEY"),
                    message_serializer=serializer.GraphSONSerializersV2d0())
    
    postgreSQL_pool = pool.SimpleConnectionPool(1, int(os.getenv("PYTHON_THREADPOOL_THREAD_COUNT")), os.getenv("POSTGRES_CONN_STRING"))  
    conn = postgreSQL_pool.getconn()
    cursor = conn.cursor()

    try:
        node_details_body = NodeDetailRequest(**req_json)
    except Exception as e:
        logging.error("Could not parse node details request: " + str(e))

    node_details_callback = graph_client.submit(f"g.V('{node_details_body.node_id}').valueMap()")
    node_details_results = node_details_callback.all().result()[0]

    logging.info(node_details_results)

    # get the lesson info
    if node_details_results['lesson_id'][0] != '-1':
        cursor.execute("SELECT lesson_description, video_id, quiz FROM lessons WHERE id = %s", (node_details_results['lesson_id'][0],))
        lesson_description, video_id, quiz = cursor.fetchone()
    else:
        lesson_description, video_id, quiz = None, None, None

    # get node info 
    cursor.execute("SELECT public_name, learning_status, masteries, blurb FROM nodes WHERE id = %s", (node_details_results['table_id'][0],))
    public_name, learning_status, masteries, blurb = cursor.fetchone()

    if video_id is None:
        video_url = None
    else:
        blob_service_client = BlobServiceClient.from_connection_string(os.getenv("AzureWebJobsStorage"))
        container_client = blob_service_client.get_container_client("videos")
        blob_client = container_client.get_blob_client(video_id)
        video_url = blob_client.url

    if not quiz is None:
        quiz = {question: (quiz[question]['choices'], quiz[question]['correct_index']) for question in quiz.keys()}

    if masteries == {}:
        masteries = None

    if learning_status == []:
        learning_status = None
    else:
        learning_status = learning_status[-1]

    return {
        "lesson_description": lesson_description,
        "node_name": public_name,
        "video_url": video_url,
        "quiz": quiz,
        "masteries": masteries,
        "blurb": blurb,
        "learning_status": learning_status
    }


