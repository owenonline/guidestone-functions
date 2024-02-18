import cv2
from scipy.interpolate import CubicSpline
from concurrent.futures import ThreadPoolExecutor, as_completed
import numpy as np
import requests
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
from azure.storage.blob import BlobServiceClient
import json
from skimage.metrics import structural_similarity as compare_ssim

class AfterLessonReport(BaseModel):
    teaching_effectiveness_report: str = Field(description="A report on the effectiveness of the teaching in the video. This should be a summary of the impact the video had on the user, and should be based on the attention scores and the pause and rewind data. Be sure to include briefly what the video was about, what teaching techniques contributed to that, and which subtracted. Make recommendations for the future and summarize your predictions about the student's learning style")
    learning_state: str = Field(description="A summary of the user's learning state. This should include what topics they have mastered, what topics they have struggled with, and what topics they are currently learning. This should be based more heavily on the quiz data. Be sure to include what topics you think the user might have missed, and what topics they might have been confused about.")

def score_user(node_id, quiz_data, attn_score, masteries):
    graph_client = client.Client('wss://guidestone-gremlin.gremlin.cosmos.azure.com:443/','g', 
                    username=f"/dbs/guidestone/colls/knowledge-graph", 
                    password=os.getenv("KNOWLEDGE_GRAPH_KEY"),
                    message_serializer=serializer.GraphSONSerializersV2d0())
    
    gpt_4_llm = AzureChatOpenAI(deployment_name="gpt-4-turbo", api_version="2023-07-01-preview", model_name="gpt-4-1106-preview", temperature=0, max_retries=10)

    
    postgreSQL_pool = pool.SimpleConnectionPool(1, int(os.getenv("PYTHON_THREADPOOL_THREAD_COUNT")), os.getenv("POSTGRES_CONN_STRING"))  
    conn = postgreSQL_pool.getconn()
    cursor = conn.cursor()

    # get video
    table_id_callback = graph_client.submit(f"g.V('{node_id}').values('table_id')")
    table_id = table_id_callback.all().result()[0]
    cursor.execute("SELECT video_id FROM nodes WHERE id = %s", (table_id,))
    video_id, = cursor.fetchone()

    quiz_data = []

    for count, question in enumerate(quiz_data):
        choices_str = " | ".join(question["choices"])
        quiz_data.append(f"{count+1}. Question: {question['question']}, Choices: {choices_str}, Correct Answer: {question['choices'][question['correct_index']]}")

    quiz_data_str = "\n".join(quiz_data)

    grading_prompt_template = ChatPromptTemplate(
        [
            ("system", """You are a helpful, critiquing (but ultimately friendly) evaluator evaluating someone's performance on watching a video about and then answering questions on a topic. The topic is: {topic_name} You have been passed the following information about how engaged they were by the video:

They got an attention score of {attention_score} on a scale from 0 to 1, with 1 being perfect attention and 0 being no attention.

Some important things that you can point out based on this information is what information you think the person watching the video might have missed based on their attention score. This can be validated by the quiz that the user took after watching the video. In fact, you should take more relevance from this quiz than the attention score. Here are the questions, choices, and answers they selected:

{quiz_data_str}

If the user missed a question, a new video is going to be created going over what they missed, so keep in mind what you think is a gap in the user's understanding. You are also going to need to generate a summary of the user's progress, so also be thinking of a summary of their performance.

Then, finally, you are going to need to evaluate the teaching received from the video, focusing on the impact it had specifically on the person watching it. Based on the attention scores, and the following pause and rewind data, think about the following questions:

1. Is the pace good or does it need to slow down to better accommodate the viewer?
2. What kind of scenes did this user prefer? Do they like to see a list of formulas on the screen? Prefer detailed animations? Like blocks of text? Predict what their learning style might be.
3. What kind of narration style did the user prefer? Did they like to hear a lot of anecdoates? Did they prefer to stick to the facts? Or did they want to have more time to think out solutions on their own? Predict what their learning style might be.

Number of rewinds per second: {rewind_per_sec}
Avg number of second before the student rewound again: {sec_b4_rewind}
             
previously, they had mastered these topics: {mastered_topics}
and struggled with these: {struggled_topics}
             
and the state of their learning was: {learning_state}
             
Output your response following this template: {formatting_instructions}
""")
        ]
    )

    dpe_parser = PydanticOutputParser(pydantic_object=AfterLessonReport)
    dpe_fixing_parser = OutputFixingParser.from_llm(parser=dpe_parser, llm=gpt_4_llm)

    grade_chain = (
        {
            "topic_name": itemgetter("topic_name"),
            "attention_score": itemgetter,
            "quiz_data_str": itemgetter("quiz_data_str"),
            "rewind_per_sec": itemgetter("rewind_per_sec"),
            "sec_b4_rewind": itemgetter("sec_b4_rewind"),
            "mastered_topics": itemgetter("mastered_topics"),
            "struggled_topics": itemgetter("struggled_topics"),
            "learning_state": itemgetter("learning_state"),
            "formatting_instructions": itemgetter("formatting_instructions")
        }
        | grading_prompt_template
        | gpt_4_llm
        | dpe_fixing_parser
    )

    after_lesson_report: AfterLessonReport = grade_chain.invoke({
        "topic_name": video_id,
        "attention_score": attn_score,
        "quiz_data_str": quiz_data_str,
        "rewind_per_sec": 0,
        "sec_b4_rewind": 0,
        "mastered_topics": masteries.mastered_topics,
        "struggled_topics": masteries.struggled_topics,
        "learning_state": masteries.learning_state,
        "formatting_instructions": dpe_fixing_parser.get_format_instructions()
    })

    graph_client.submit(f"g.V('{node_id}').property('status', 'graded')")

    # cursor.execute("INSERT INTO nodes (node_id, teaching_effectiveness_report, learning_state) VALUES (%s, %s, %s)", (node_id, after_lesson_report.teaching_effectiveness_report, after_lesson_report.learning_state))