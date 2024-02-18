import shutil
from typing import List
from gremlin_python.driver import client, serializer
import os
import logging
from psycopg2 import pool
from pydantic import BaseModel, Field
from langchain_openai import AzureChatOpenAI
from azure.storage.blob import BlobServiceClient
from langchain.output_parsers import OutputFixingParser, PydanticOutputParser
from langchain.prompts import ChatPromptTemplate
from operator import itemgetter
from concurrent.futures import ThreadPoolExecutor, as_completed
from lesson.video import VideoGeneratorAgent
from lesson.audio import create_audio
import re
import json
import uuid
from moviepy.editor import VideoFileClip, concatenate_videoclips, AudioFileClip
from azure.storage.blob import BlobServiceClient

class LessonCreateRequest(BaseModel):
    node_id: str = Field(description="The id of the node in the graph that needs a new lesson")
    user_id: str

class QuizQuestion(BaseModel):
    question: str = Field(description="The question that the answers in the choices list belong to")
    choices: list[str] = Field(description="The list of answer choices the student has to choose from")
    correct_index: int = Field(description="The index (starting from 0) of the answer in the answer_choices list that is the correct answer")

class Scene(BaseModel):
    visuals: str = Field(description="Describe the visuals you want to have on screen for this scene. Use basic shapes to describe the motion and animation you want to see, and if motion needs to follow a specific equation, include that equation here. Similarly, if you want to display an example problem or equaiton on the screen, include all of that text here exactly as you want it written.")
    audio: str = Field(description="Describe the information you want covered in the voiceover to this scene. This should not be a full script, but it should include any specific information exactly as you want it told. For example, if you want a specific practice problem to be explained, you need to include the full text of the problem. If you want to explain more general information, however, then you can give a more high level overview.")

class LessonPlan(BaseModel):
    notes: str = Field(description="Describe how you want to teach this video. Include things like how you want to approach building intuitive understanding, problem solving ability, and interest with your students")
    scenes: list[Scene] = Field(description="The specific content (what you want spoken and on screen) for each scene of the video. Make sure the visuals and audio for each scene together, and that the video as a whole has a compelling and cohesive narrative flow.")
    quiz: list[QuizQuestion] = Field(description="The quiz to go at the end of this video lesson to assess the student's understanding. You should have questions covering the whole range of topics you will be covering in the lesson, and a mix of computational and conceptual questions that are sure to draw out misunderstandings.")
    lesson_description: str = Field(description="Summarize what the lesson is going to be about and why. Be sure to emphasize why you're covering certain topics. For example \"Since you've struggled with x approach to y, today we're going to be covering another method and tying it in to your understanding\" is the style of writing you aim for.")

class Quiz(BaseModel):
    questions: list[QuizQuestion]

def create_lesson(req_json: dict) -> None:
    graph_client = client.Client('wss://guidestone-gremlin.gremlin.cosmos.azure.com:443/','g', 
                    username=f"/dbs/guidestone/colls/knowledge-graph", 
                    password=os.getenv("KNOWLEDGE_GRAPH_KEY"),
                    message_serializer=serializer.GraphSONSerializersV2d0())
    
    postgreSQL_pool = pool.SimpleConnectionPool(1, int(os.getenv("PYTHON_THREADPOOL_THREAD_COUNT")), os.getenv("POSTGRES_CONN_STRING"))  
    conn = postgreSQL_pool.getconn()
    cursor = conn.cursor()

    gpt_4_llm = AzureChatOpenAI(deployment_name="gpt-4-turbo", api_version="2023-07-01-preview", model_name="gpt-4-1106-preview", temperature=0, max_retries=10)

    try:
        data = LessonCreateRequest(**req_json)
    except Exception as e:
        logging.error("Could not parse create_lesson request: " + str(e))
    
    # get records from learning style database
    cursor.execute("SELECT learning_record FROM learning_records WHERE user_id=%s", (data.user_id,))
    learning_records = cursor.fetchall()

    # get records from node id
    # g = traversal().withRemote(DriverRemoteConnection('wss://guidestone-gremlin.gremlin.cosmos.azure.com:443/','g', 
    #                                                   username=f"/dbs/guidestone/colls/knowledge-graph", 
    #                                                   password=os.getenv("KNOWLEDGE_GRAPH_KEY")))
    tid_callback = graph_client.submit(f"g.V().has('id', '{data.node_id}').values('table_id')")
    table_id = tid_callback.all().result()[0]
    logging.info(table_id)
    cursor.execute("SELECT learning_status, topic, masteries FROM nodes WHERE id=%s", (table_id,))
    learning_status, topic, masteries = cursor.fetchone()

    lp_parser = PydanticOutputParser(pydantic_object=LessonPlan)
    lp_fixing_parser = OutputFixingParser.from_llm(parser=lp_parser, llm=gpt_4_llm)

    lesson_plan_prompt = ChatPromptTemplate.from_messages(
        [
            ("system", "You are a tutor in charge of creating a lesson plan for a video lesson on the topic of {topic}. You are paid hundreds of thousands of dollars to provide the best education you can to your pupil, so you make sure to tune the lesson to maximize his learning style. You must output your lesson plan in the following format: {output_format}"),
            ("assistant", "I have tried a number of different learning styles with this student and kept record of how they impacted their learning. Here are those records:\n{learning_style_records}\nWith this in mind, I can generate a lesson plan uniquely tailored for my student! We are learning about {topic}, and my student has mastered {mastered_topics} but is still struggling with {unmastered_topics}. {learning_status}\nTime to generate my lesson plan!")
        ]
    )
    lesson_plan_chain = (
        {
            "topic": itemgetter("topic"),
            "output_format": itemgetter("topic"),
            "learning_style_records": itemgetter("learning_style_records"),
            "mastered_topics": itemgetter("mastered_topics"),
            "unmastered_topics": itemgetter("unmastered_topics"),
            "learning_status": itemgetter("learning_status")
        }
        | lesson_plan_prompt
        | gpt_4_llm
        | lp_fixing_parser
    )

    if learning_status == []:
        learning_status_arg = ""
    else:
        learning_status_arg = learning_status[-1]

    lesson_plan = lesson_plan_chain.invoke({
            "topic": topic,
            "output_format": lp_fixing_parser.get_format_instructions(),
            "learning_style_records": "\n".join(learning_records),
            "mastered_topics": " and ".join(topic for topic in masteries if masteries[topic]),
            "unmastered_topics": " and ".join(topic for topic in masteries if not masteries[topic]),
            "learning_status": learning_status_arg
        })

    video_generator = VideoGeneratorAgent()

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = []
        for i, scene in enumerate(lesson_plan.scenes):

            if os.path.exists(f"scenes") and os.path.isdir(f"scenes"):
                shutil.rmtree(f"scenes")

            os.mkdir(f"scenes")
            folder = os.path.join(os.getcwd(),f"scenes/")
            futures.append(executor.submit(video_generator, scene.visuals, folder, i))
            futures.append(executor.submit(create_audio, scene.audio, scene.visuals, folder, i))

        for future in as_completed(futures):
            future.result()

    blobname = str(uuid.uuid4())
    videos = [f"scenes/animation_{i}.mp4" for i in range(len(lesson_plan.scenes))]
    audios = [f"scenes/voiceover_{i}.mp3" for i in range(len(lesson_plan.scenes))]

    combine_audio_video_and_upload(videos, audios, f"{blobname}.mp4")

    quiz = {}
    for question, choices, correct_index in lesson_plan.quiz:
        quiz[question] = {
            "choices": choices,
            "correct_index": correct_index
        }

    cursor.execute("INSERT INTO lessons (lesson_description, video_id, quiz) VALUES (%s, %s, %s) RETURNING id", (lesson_plan.lesson_description, f"{blobname}.mp4", json.dumps(quiz)))
    lesson_id = cursor.fetchone()[0]
    conn.commit()

    lidcb = graph_client.submit(f"g.V('{data.node_id}').property('lesson_id', '{lesson_id}')")
    lidcb.all().result()
    tbncb = graph_client.submit(f"g.V('{data.node_id}').values('table_id')")
    table_id = tbncb.all().result()[0]

    cursor.execute("SELECT lesson_ids FROM nodes WHERE id = %s", (table_id))
    lesson_ids = cursor.fetchone()[0]
    if lesson_ids is None:
        lesson_ids = [lesson_id]
    else:
        lesson_ids.append(lesson_id)
    cursor.execute("UPDATE nodes SET lesson_ids = %s WHERE id = %s", (lesson_ids, table_id))
    conn.commit()

def combine_audio_video_and_upload(video_files, audio_files, output_filename):
    combined_clips = []

    # Combine each video with its corresponding audio
    for video_path, audio_path in zip(video_files, audio_files):
        video = VideoFileClip(video_path)
        audio = AudioFileClip(audio_path)
        # Set the audio of the video clip
        video = video.set_audio(audio)
        combined_clips.append(video)

    # Concatenate the combined clips into one video
    final_clip = concatenate_videoclips(combined_clips)
    final_clip_path = f"/tmp/{output_filename}"
    final_clip.write_videofile(final_clip_path, codec="libx264")

    # Upload the final video to Azure Blob Storage
    blob_service_client = BlobServiceClient.from_connection_string(os.getenv("AzureWebJobsStorage"))
    blob_client = blob_service_client.get_blob_client(container="videos", blob=output_filename)
    
    with open(final_clip_path, "rb") as data:
        blob_client.upload_blob(data, overwrite=True)

    print(f"Uploaded {output_filename} to Azure Blob Storage.")
    