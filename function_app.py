import azure.functions as func
from gremlin_python.driver import client, serializer
import os
import logging
from psycopg2 import pool
from pydantic import BaseModel, Field, ValidationError, root_validator
from enum import Enum

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

class gradeLevel(Enum):
    KINDERGARTEN = "K"
    FIRST_GRADE = "1"
    SECOND_GRADE = "2"
    THIRD_GRADE = "3"
    FOURTH_GRADE = "4"
    FIFTH_GRADE = "5"
    SIXTH_GRADE = "6"
    SEVENTH_GRADE = "7"
    EIGHTH_GRADE = "8"
    NINTH_GRADE = "9"
    TENTH_GRADE = "10"
    ELEVENTH_GRADE = "11"
    TWELFTH_GRADE = "12"
    COLLEGE = "College"

class UserCreateRequest(BaseModel):
    name: str = Field(description="The name of the user")
    email: str = Field(description="The email of the user")
    profile_pic_url: str = Field(description="The profile picture of the user")
    grade_level: gradeLevel = Field(description="The grade level of the user")
    interests: list[str] = Field(description="The interests of the user")

@app.function_name("createUser")
@app.route(route="createuser",
           auth_level=func.AuthLevel.ANONYMOUS, 
           methods=['POST'])
def createUser(req: func.HttpRequest) -> func.HttpResponse:
    # connect to postgres
    postgreSQL_pool = pool.SimpleConnectionPool(1, int(os.getenv("PYTHON_THREADPOOL_THREAD_COUNT")), os.getenv("POSTGRES_CONN_STRING"))  
    conn = postgreSQL_pool.getconn()
    cursor = conn.cursor()

    try:
        webhook_body = UserCreateRequest.model_validate(req.get_json())
    except ValueError as e:
        logging.error("taskId is invalid OR body is not valid json: " + str(e))

    try:
        name = webhook_body.name
        email = webhook_body.email
        profile_pic_url = webhook_body.profile_pic_url
        grade_level = webhook_body.grade_level.value
        interests = webhook_body.interests

        insert_sql = """
        INSERT INTO userData (name, email, profile_picture_url, grade_level, interests)
        VALUES (%s, %s, %s, %s, %s)
        """
        cursor.execute(insert_sql, (name, email, profile_pic_url, grade_level, interests))

        conn.commit()

    except Exception as e:
        logging.error("Error while inserting into database: " + str(e))

        conn.rollback()
        return func.HttpResponse(
            "Failed to create user",
            status_code=500
        )

    postgreSQL_pool.putconn(conn)
    postgreSQL_pool.closeall()

    return func.HttpResponse(
        status_code=200
    )