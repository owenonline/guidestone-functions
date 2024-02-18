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

def calculate_attention(points, node_id):
    graph_client = client.Client('wss://guidestone-gremlin.gremlin.cosmos.azure.com:443/','g', 
                    username=f"/dbs/guidestone/colls/knowledge-graph", 
                    password=os.getenv("KNOWLEDGE_GRAPH_KEY"),
                    message_serializer=serializer.GraphSONSerializersV2d0())
    
    postgreSQL_pool = pool.SimpleConnectionPool(1, int(os.getenv("PYTHON_THREADPOOL_THREAD_COUNT")), os.getenv("POSTGRES_CONN_STRING"))  
    conn = postgreSQL_pool.getconn()
    cursor = conn.cursor()

    # get video
    table_id_callback = graph_client.submit(f"g.V('{node_id}').values('table_id')")
    table_id = table_id_callback.all().result()[0]
    cursor.execute("SELECT video_id FROM nodes WHERE id = %s", (table_id,))
    video_id, = cursor.fetchone()

    blob_service_client = BlobServiceClient.from_connection_string(os.getenv("AzureWebJobsStorage"))
    container_client = blob_service_client.get_container_client("videos")
    blob_client = container_client.get_blob_client(video_id)
    stream = blob_client.download_blob()
    video_bytes = stream.readall()

    temp_video_path = 'temp_video.mp4'
    with open(temp_video_path, 'wb') as temp_video_file:
        temp_video_file.write(video_bytes)

    # smoothen motion
    times = [point['time'] for point in points]
    x_coords = [point['x'] for point in points]
    y_coords = [point['y'] for point in points]

    cs_x = CubicSpline(times, x_coords)
    cs_y = CubicSpline(times, y_coords)

    smooth_times = np.linspace(min(times), max(times), 100)

    smooth_x = cs_x(smooth_times)
    smooth_y = cs_y(smooth_times)

    smooth_points = [{"x": x, "y": y, "time": t} for x, y, t in zip(smooth_x, smooth_y, smooth_times)]

    # get the frames
    frames = []
    cap = cv2.VideoCapture("temp_video.mp4")
    fps = cap.get(cv2.CAP_PROP_FPS)  # Get frames per second of the video

    for timestamp in [timestamps['time'] for timestamps in smooth_points]:
        cap.set(cv2.CAP_PROP_POS_MSEC, timestamp*1000)
        ret, frame = cap.read()
        if ret:
            frames.append(frame)
        else:
            print(f"Frame for timestamp {timestamp} not found.")

    cap.release()

    ssim_values = []
    position_differences = []

    for i in range(len(frames) - 1):
        frame1 = frames[i]
        frame2 = frames[i + 1]
        
        # Convert frames to grayscale for SSIM calculation
        gray1 = cv2.cvtColor(frame1, cv2.COLOR_BGR2GRAY)
        gray2 = cv2.cvtColor(frame2, cv2.COLOR_BGR2GRAY)
        
        # Calculate SSIM between two consecutive frames
        ssim, _ = compare_ssim(gray1, gray2, full=True)
        ssim_values.append(ssim)
        
        # Calculate difference in position between coordinates of two consecutive frames
        coord1 = (smooth_points[i]['x'], smooth_points[i]['y'])
        coord2 = (smooth_points[i + 1]['x'], smooth_points[i + 1]['y'])
        position_diff = np.sqrt((coord2[0] - coord1[0]) ** 2 + (coord2[1] - coord1[1]) ** 2)
        position_differences.append(position_diff)

    ssim_derivatives = np.diff(ssim_values)
    position_derivatives = np.diff(position_differences)

    correlation_coefficient = np.corrcoef(ssim_derivatives, position_derivatives)[0, 1]
    attention_score = abs(correlation_coefficient)

    return attention_score

def calculate_pace(rewinds, node_id):
    graph_client = client.Client('wss://guidestone-gremlin.gremlin.cosmos.azure.com:443/','g', 
                    username=f"/dbs/guidestone/colls/knowledge-graph", 
                    password=os.getenv("KNOWLEDGE_GRAPH_KEY"),
                    message_serializer=serializer.GraphSONSerializersV2d0())
    
    postgreSQL_pool = pool.SimpleConnectionPool(1, int(os.getenv("PYTHON_THREADPOOL_THREAD_COUNT")), os.getenv("POSTGRES_CONN_STRING"))  
    conn = postgreSQL_pool.getconn()
    cursor = conn.cursor()

    # get video
    table_id_callback = graph_client.submit(f"g.V('{node_id}').values('table_id')")
    table_id = table_id_callback.all().result()[0]
    cursor.execute("SELECT video_id FROM nodes WHERE id = %s", (table_id,))
    video_id, = cursor.fetchone()

    blob_service_client = BlobServiceClient.from_connection_string(os.getenv("AzureWebJobsStorage"))
    container_client = blob_service_client.get_container_client("videos")
    blob_client = container_client.get_blob_client(video_id)
    stream = blob_client.download_blob()
    video_bytes = stream.readall()

    temp_video_path = 'temp_video.mp4'
    with open(temp_video_path, 'wb') as temp_video_file:
        temp_video_file.write(video_bytes)

    cap = cv2.VideoCapture(temp_video_path)

    fps = cap.get(cv2.CAP_PROP_FPS)
    
    # Get the total number of frames in the video
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    
    # Calculate the duration of the video in seconds
    duration_seconds = frame_count / fps

    rewinds_per_second = len(rewinds) / duration_seconds

    secs_between_rewinds = [rewinds[i+1]['from'] - rewinds[i]['from'] for i in range(len(rewinds)-1)]
    # Calculate the average of these differences
    average_secs_between_rewinds = sum(secs_between_rewinds) / len(secs_between_rewinds)

    return rewinds_per_second, average_secs_between_rewinds

