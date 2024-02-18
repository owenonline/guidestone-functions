from typing import List
from gremlin_python.driver import client, serializer
import os
import logging
from psycopg2 import pool
from pydantic import BaseModel, Field
from enum import Enum
from langchain_openai import AzureChatOpenAI
from langchain.output_parsers import OutputFixingParser, PydanticOutputParser
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
from operator import itemgetter
import re
import json
from stemtopics import Topics

def clean_text(text: str) -> str:
    if text is None:
        return None
    return re.sub(r'\\\n *\\', '', text).replace("'", "").replace('"', '').replace("/","").replace(" ","_").strip().lower()

class GraphExpandRequest(BaseModel):
    topic: str = Field(description="The topic to expand the graph on")
    user_id: str = Field(description="The id of the user to get the graph for")

class LeafTopic(BaseModel):
    id: str = Field(description="the id of the node in the graph")
    topic: Topics = Field(description="the stem topic represented by this node in the graph")
    parents = []
    children = []

class TopicDependencies(BaseModel):
    dependencies: list[Topics] = Field(description="Topics that the user must already understand to understand the current topic. For example, to understand the topic 'fractions', the user must already understand the topic 'division'. Generate a full list of all of the topics IMMEDIATELY PRECEDING the current topic. For example, if the current topic is 'derivatives' you should include 'limits' in this list but NOT 'multiplication' since it is not a direct prerequisite for understanding derivatives.")

class Masteries(BaseModel):
    masteries: list[str] = Field(description="The list of all the sub-topics you have to learn as part of mastering this topic. These are NOT prerequisites, they are part of learning the topic at hand. For example, when learning limits, you have to learn one sided limits, two side limits, finding limits, limits at infinity, etc.")

def expand_graph(req_json: dict) -> None:
    graph_client = client.Client('wss://guidestone-gremlin.gremlin.cosmos.azure.com:443/','g', 
                    username=f"/dbs/guidestone/colls/knowledge-graph", 
                    password=os.getenv("KNOWLEDGE_GRAPH_KEY"),
                    message_serializer=serializer.GraphSONSerializersV2d0())
    
    postgreSQL_pool = pool.SimpleConnectionPool(1, int(os.getenv("PYTHON_THREADPOOL_THREAD_COUNT")), os.getenv("POSTGRES_CONN_STRING"))  
    conn = postgreSQL_pool.getconn()
    cursor = conn.cursor()

    gpt_4_llm = AzureChatOpenAI(deployment_name="gpt-4-turbo", api_version="2023-07-01-preview", model_name="gpt-4-1106-preview", temperature=0, max_retries=10)

    try:
        graph_expand_body = GraphExpandRequest(**req_json)
    except Exception as e:
        logging.error("Could not parse graph expansion request: " + str(e))

    # # chain to parse dependencies of a topic
    # dpe_parser = PydanticOutputParser(pydantic_object=TopicDependencies)
    # dpe_fixing_parser = OutputFixingParser.from_llm(parser=dpe_parser, llm=gpt_4_llm)

    # dependency_extraction_prompt = ChatPromptTemplate.from_messages(
    #     [
    #         ("system", "You are an agent that determines the immediate prerequisite knowledge of a topic. Return your answer in the following format: {format_instructions}"),
    #         ("user", "{current_topic}"),
    #     ]
    # )
    # dependency_extraction_chain = (
    #     {
    #         "format_instructions": itemgetter("format_instructions"),
    #         "current_topic": itemgetter("current_topic"),
    #     }
    #     | dependency_extraction_prompt
    #     | gpt_4_llm
    #     | dpe_fixing_parser
    # )

    # # prompts to determine if the current topic is already covered by anything currently included in the graph, to detect when
    # # connections should be made vs new nodes generated
    dependency_cover_prompt = ChatPromptTemplate.from_messages(
        [
            ("system", "Which one of the enum topics is the most similar to the user's topic? Return your answer in the following format: {format_instructions}"),
            ("user", "{current_topic}"),
        ]
    )

    # # get the user's baseline understanding topics
    # cursor.execute("SELECT base_knowledge FROM userData WHERE id = %s", (graph_expand_body.user_id,))
    # base_knowledge, = cursor.fetchone()

    # # get the root node id
    # root_node_callback = graph_client.submit(f"g.V().has('user_id', '{graph_expand_body.user_id}').has('label', 'start_node').values('id')")
    # root_node_id = root_node_callback.all().result()[0]

    # # get the leaf topics currently representing the frontier of the graph
    leaf_callback = graph_client.submit(f"g.V().has('user_id', '{graph_expand_body.user_id}').not(__.outE()).values('id', 'table_id')")
    leaf_result = leaf_callback.all().result()

    extant_nodes = []

    for node_id, table_id in zip(leaf_result[::2], leaf_result[1::2]):
        cursor.execute("SELECT topic FROM nodes WHERE id = %s", (table_id,))
        topic, = cursor.fetchone()
        extant_nodes.append((node_id, topic))

    available_nodes = [x[1] for x in extant_nodes]
    leaves_enum_dict = {k:k for k in available_nodes}
    available_leaves_enum = Enum('AvailableLeaves', leaves_enum_dict)
    class PickedLeaf(BaseModel):
        chosen_leaf: available_leaves_enum = Field(description="the most similar topic to the user's topic") # type: ignore

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
        "current_topic": graph_expand_body.topic,
    })

    # retreive extant node id and topic from extant nodes list
    old_node_id, topic = extant_nodes[[x[1] for x in extant_nodes].index(dependency_cover.chosen_leaf.value)]

    new_node_name = topic.title()
    new_node_id = clean_text(topic)

    # get the masteries
    masteries_parser = PydanticOutputParser(pydantic_object=Masteries)
    masteries_fixing_parser = OutputFixingParser.from_llm(parser=masteries_parser, llm=gpt_4_llm)
    masteries_creation_prompt = ChatPromptTemplate.from_messages(
        [
            ("system", "You are an agent that makes lesson plans, and your job is to take a topic and produce a list of sub-topics for it. Return your answer in the following format: {format_instructions}"),
            ("user", "Here is the topic I want you to make sub-topics for: {topic}")
        ]
    )
    masteries_creation_chain = (
        {
            "format_instructions": itemgetter("format_instructions"),
            "topic": itemgetter("topic")
        }
        | masteries_creation_prompt
        | gpt_4_llm
        | masteries_fixing_parser
    )
    masteries = masteries_creation_chain.invoke({
        "format_instructions": masteries_fixing_parser.get_format_instructions(),
        "topic": topic
    })

    insert_sql = """
    INSERT INTO Nodes (topic, learning_status, masteries, blurb, public_name)
    VALUES (%s, %s, %s, %s, %s) RETURNING id;
    """
    cursor.execute(insert_sql, (topic, [], json.dumps({mastery:False for mastery in masteries.masteries}), "You haven't started this node yet!", new_node_name))
    node_id = cursor.fetchone()[0]
    conn.commit()

    node_add_callback = graph_client.submit(f"g.addV('{new_node_id}').property('user_id','{graph_expand_body.user_id}').property('table_id','{node_id}').property('lesson_id','-1').property('status','unstarted').property('pk','pk')")
    node_add_result = node_add_callback.all().result()
    new_node_graph_id = node_add_result[0].id

    node_add_callback = graph_client.submit(f"g.addV('{old_node_id}').addE('prerequisite').to(g.V('{new_node_graph_id}'))")
    node_add_result = node_add_callback.all().result()