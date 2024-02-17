import azure.functions as func
from gremlin_python.driver import client, serializer
import os
import logging
from psycopg2 import pool

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

@app.function_name("healthcheck")
@app.route(route="healthcheck",
           auth_level=func.AuthLevel.ANONYMOUS, 
           methods=['GET','POST'])
def healthcheck(req: func.HttpRequest) -> func.HttpResponse:
    # verify gremlin connection
    graph_client = client.Client('wss://docs-graph.gremlin.cosmosdb.azure.com:443/','g', 
                    username=f"/dbs/guidestone/colls/knowledge-graph", 
                    password=os.getenv("DOCS_GRAPH_KEY"),
                    message_serializer=serializer.GraphSONSerializersV2d0())
    
    # verify postgres connection
    postgreSQL_pool = pool.SimpleConnectionPool(1, int(os.getenv("PYTHON_THREADPOOL_THREAD_COUNT")), os.getenv("POSTGRES_CONN_STRING"))  
    conn = postgreSQL_pool.getconn()
    cursor = conn.cursor()
    postgreSQL_pool.putconn(conn)
    postgreSQL_pool.closeall()

    return func.HttpResponse(
        status_code=200
    )