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
import copy
import re

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
    cursor = conn.cursor()
    postgreSQL_pool.putconn(conn)
    postgreSQL_pool.closeall()

    return func.HttpResponse(
        status_code=200
    )

class GradeLevel(Enum):
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
    grade_level: GradeLevel = Field(description="The grade level of the user")
    interests: list[str] = Field(description="The interests of the user")

@app.function_name("createUser")
@app.route(route="createuser",
           auth_level=func.AuthLevel.ANONYMOUS, 
           methods=['POST'])
def createUser(req: func.HttpRequest) -> func.HttpResponse:
    postgreSQL_pool = pool.SimpleConnectionPool(1, int(os.getenv("PYTHON_THREADPOOL_THREAD_COUNT")), os.getenv("POSTGRES_CONN_STRING"))  
    conn = postgreSQL_pool.getconn()
    cursor = conn.cursor()

    try:
        create_user_body = UserCreateRequest.model_validate(req.get_json())
    except Exception as e:
        logging.error("Could not parse user creation request: " + str(e))

    try:
        name = create_user_body.name
        email = create_user_body.email
        profile_pic_url = create_user_body.profile_pic_url
        grade_level = create_user_body.grade_level.value
        interests = create_user_body.interests

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

# makes text safe for insertion into gremlin graph
def clean_text(text: str) -> str:
    if text is None:
        return None
    return re.sub(r'\\\n *\\', '', text).replace("'", "").replace('"', '').replace("/","").replace(" ","").strip().lower()

class GraphExpandRequest(BaseModel):
    topic: str = Field(description="The topic to expand the graph on")

class LeafTopic(BaseModel):
    id: str = Field(description="the id of the node in the graph")
    topic: str = Field(description="the natural language and very brief description of what the topic is")

class TopicDependencies(BaseModel):
    dependencies: list[str] = Field(description="Topics that the user must already understand to understand the current topic. For example, to understand the topic 'fractions', the user must already understand the topic 'division'. Generate a full list of all of the topics IMMEDIATELY PRECEDING the current topic. For example, if the current topic is 'derivatives' you should include 'limits' in this list but NOT 'multiplication' since it is not a direct prerequisite for understanding derivatives.")

@app.function_name("expandGraph")
@app.route(route="expandGraph",
           auth_level=func.AuthLevel.ANONYMOUS, 
           methods=['POST'])
def expandGraph(req: func.HttpRequest) -> func.HttpResponse:
    graph_client = client.Client('wss://guidestone-gremlin.gremlin.cosmos.azure.com:443/','g', 
                    username=f"/dbs/guidestone/colls/knowledge-graph", 
                    password=os.getenv("KNOWLEDGE_GRAPH_KEY"),
                    message_serializer=serializer.GraphSONSerializersV2d0())

    try:
        graph_expand_body = GraphExpandRequest(**req.get_json())
    except Exception as e:
        logging.error("Could not parse graph expansion request: " + str(e))

    # get current leaf nodes
    leaf_callback = graph_client.submit("g.V().not(__.outE()).project('id', 'topic').by('id').by('topic').fold()")
    leaf_result = leaf_callback.all().result()[0]
    logging.info(leaf_result)
    leaf_topics: dict[str, LeafTopic] = {lr['topic']:LeafTopic(id=lr['id'], topic=lr['topic']) for lr in leaf_result}

    gpt_4_llm = AzureChatOpenAI(deployment_name="gpt-4-turbo", api_version="2023-07-01-preview", model_name="gpt-4-1106-preview", temperature=0, max_retries=10)

    # code to parse the immediate dependencies of a current topic
    dpe_parser = PydanticOutputParser(pydantic_object=TopicDependencies)
    dpe_fixing_parser = OutputFixingParser.from_llm(parser=dpe_parser, llm=gpt_4_llm)

    dependency_extraction_prompt = ChatPromptTemplate.from_messages(
        [
            ("system", "You are an agent that determines the immediate prerequisite knowledge of a topic. Return your answer in the following format: {format_instructions}"),
            ("user", "{current_topic}"),
        ]
    )
    dependency_extraction_chain = (
        {
            "format_instructions": itemgetter("format_instructions"),
            "current_topic": itemgetter("current_topic"),
        }
        | dependency_extraction_prompt
        | gpt_4_llm
        | dpe_fixing_parser
    )

    # prompts to determine if the current topic is already covered by anything currently included in the graph, to detect when
    # connections should be made vs new nodes generated
    dependency_cover_prompt = ChatPromptTemplate.from_messages(
        [
            ("system", "You are an agent that determines whether or not any of the user's already understood topics imply understanding the topic the user specifies below. Return your answer in the following format: {format_instructions}"),
            ("user", "I currently understand these topics: \n{currently_understood_topics}\nHere is the topic I'm specifying: {current_topic}"),
        ]
    )

    def expand_graph_recursive(topic, available_leaf_topics, depth=0):
        current_connections: list[LeafTopic] = []

        if depth > 10:
            raise ValueError("Recursion depth exceeded")

        topic_dependencies: TopicDependencies = dependency_extraction_chain.invoke({
            "format_instructions": dpe_fixing_parser.get_format_instructions(),
            "current_topic": topic
        })
        topic_dependencies = topic_dependencies.dependencies

        logging.info(depth*"\t" + f"Expanding {topic} with dependencies {topic_dependencies}")

        for dependency in topic_dependencies:
            # dynamically create pydantic template to enforce model selecting from available leaves
            leaves_enum_dict = {k:k for k in available_leaf_topics.keys()}
            leaves_enum_none = {**leaves_enum_dict, "NONE":"NONE"}
            available_leaves_enum = Enum('AvailableLeaves', leaves_enum_none)
            class PickedLeaf(BaseModel):
                chosen_leaf: available_leaves_enum = Field(description="Which of the given understood topics implies understanding the current topic. For example, if the current topic is 'limits' and one of the understood topics is 'derivatives', you should select 'derivatives' since understanding derivatives implies understanding limits. However, if none of the currently understood topics imply understanding the current topic, select NONE") # type: ignore

            # determine if any of the understood topics cover the current dependency
            dpc_parser = PydanticOutputParser(pydantic_object=PickedLeaf)
            dpc_fixing_parser = OutputFixingParser.from_llm(parser=dpc_parser, llm=gpt_4_llm)
            dependency_cover_chain = (
                {
                    "format_instructions": itemgetter("format_instructions"),
                    "currently_understood_topics": itemgetter("currently_understood_topics"),
                    "current_topic": itemgetter("current_topic"),
                }
                | dependency_cover_prompt
                | gpt_4_llm
                | dpc_fixing_parser
            )
            dependency_cover: PickedLeaf = dependency_cover_chain.invoke({
                "format_instructions": dpc_fixing_parser.get_format_instructions(),
                "currently_understood_topics": "\n- ".join(available_leaf_topics.keys()),
                "current_topic": dependency
            })

            # if the model determines that one of the existing leaf nodes accounts for this topic, mark it
            # as a prerequisite for the current topic 
            if dependency_cover.chosen_leaf.value != "NONE":
                current_connections.append(available_leaf_topics[dependency_cover.chosen_leaf.value])
            # otherwise, recurse on this topic to generate a new leaf node
            else:
                new_leaf, available_leaf_topics = expand_graph_recursive(dependency, available_leaf_topics, depth=depth+1)
                available_leaf_topics = {**available_leaf_topics, dependency:new_leaf}
                current_connections.append(new_leaf)

        # create this node in the graph
        new_node_id = clean_text(topic)
        node_add_callback = graph_client.submit(f"g.addV('{new_node_id}').property('id','{new_node_id}').property('topic','{topic}').property('status','unstarted').property('pk','pk')")
        node_add_result = node_add_callback.all().result()
        new_node_id_confirmed = node_add_result[0]['id']

        # add all the requisite edges
        for node in current_connections:
            edge_add_callback = graph_client.submit(f"g.V('{node.id}').addE('prerequisite').to(g.V('{new_node_id_confirmed}'))")
            _ = edge_add_callback.all().result()

        # create node object
        new_node = LeafTopic(id=new_node_id_confirmed, topic=topic)

        return new_node, available_leaf_topics
    
    expand_graph_recursive(graph_expand_body.topic, leaf_topics)

    return func.HttpResponse(
        status_code=200
    )