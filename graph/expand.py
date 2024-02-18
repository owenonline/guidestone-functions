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

def clean_text(text: str) -> str:
    if text is None:
        return None
    return re.sub(r'\\\n *\\', '', text).replace("'", "").replace('"', '').replace("/","").replace(" ","_").strip().lower()

class GraphExpandRequest(BaseModel):
    topic: str = Field(description="The topic to expand the graph on")
    user_id: str = Field(description="The id of the user to get the graph for")

class LeafTopic(BaseModel):
    id: str = Field(description="the id of the node in the graph")
    topic: str = Field(description="the natural language and very brief description of what the topic is")

class TopicDependencies(BaseModel):
    dependencies: list[str] = Field(description="Topics that the user must already understand to understand the current topic. For example, to understand the topic 'fractions', the user must already understand the topic 'division'. Generate a full list of all of the topics IMMEDIATELY PRECEDING the current topic. For example, if the current topic is 'derivatives' you should include 'limits' in this list but NOT 'multiplication' since it is not a direct prerequisite for understanding derivatives.")

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

    # chain to parse dependencies of a topic
    dpe_parser = PydanticOutputParser(pydantic_object=TopicDependencies)
    dpe_fixing_parser = OutputFixingParser.from_llm(parser=dpe_parser, llm=gpt_4_llm)

    dependency_extraction_prompt = ChatPromptTemplate.from_messages(
        [
            ("system", "You are an agent that determines the immediate prerequisite knowledge of a topic. Return your answer in the following format: {format_instructions}"),
            ("user", "{current_topic}, which unlocks {parent_topics}"),
        ]
    )
    dependency_extraction_chain = (
        {
            "format_instructions": itemgetter("format_instructions"),
            "parent_topics": itemgetter("parent_topics"),
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

    # get the leaf topics currently representing the frontier of the graph
    leaf_callback = graph_client.submit(f"g.V().has('user_id', '{graph_expand_body.user_id}').not(__.outE()).values('id', 'table_id')")
    leaf_result = leaf_callback.all().result()

    logging.info(leaf_result)

    leaf_topics: dict[str, LeafTopic] = {}
    for node_id, table_id in zip(leaf_result[::2], leaf_result[1::2]):
        logging.info(f"Found leaf node {node_id} with table id {table_id}")
        cursor.execute("SELECT topic FROM nodes WHERE id = %s", (table_id,))
        topic, = cursor.fetchone()
        leaf_topics[topic] = LeafTopic(id=node_id, topic=topic)

    logging.info(f"Leaf nodes at the start of process: {leaf_topics}")

    def expand_graph_recursive(topic, available_leaf_topics, parent_topics, depth=0):
        current_connections: list[LeafTopic] = []

        if depth > 10:
            raise ValueError("Recursion depth exceeded")

        # get prerequisites of current topic
        logging.info(f"parent topic: {parent_topics}")
        topic_dependencies: TopicDependencies = dependency_extraction_chain.invoke({
            "format_instructions": dpe_fixing_parser.get_format_instructions(),
            "parent_topics": parent_topics,
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
                logging.info(depth*"\t" + f"Connection found for dependency {dependency}: {dependency_cover.chosen_leaf.value}")
                current_connections.append(available_leaf_topics[dependency_cover.chosen_leaf.value])
            # otherwise, recurse on this topic to generate a new leaf node
            else:
                logging.info(depth*"\t" + f"No connection found for dependency {dependency}: recurring")
                expanded_parents = parent_topics + [dependency]
                logging.info(depth*"\t" + f"expanded parents: {expanded_parents}")
                new_leaf, available_leaf_topics = expand_graph_recursive(dependency, available_leaf_topics, expanded_parents, depth=depth+1)
                available_leaf_topics = {**available_leaf_topics, dependency:new_leaf}
                current_connections.append(new_leaf)

        ## create this node in the graph ##
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
        new_node_id_confirmed = node_add_result[0]['id']

        # add all the requisite edges
        for node in current_connections:
            edge_add_callback = graph_client.submit(f"g.V('{node.id}').addE('prerequisite').to(g.V('{new_node_id_confirmed}'))")
            _ = edge_add_callback.all().result()

        # create node object
        new_node = LeafTopic(id=new_node_id_confirmed, topic=topic)

        return new_node, available_leaf_topics

    expand_graph_recursive(graph_expand_body.topic, leaf_topics, [graph_expand_body.topic])