import ast
import logging
import operator
from typing import Annotated, Dict, List, Optional, Sequence, Type, TypedDict
import azure.functions as func
from psycopg2 import pool
from pydantic import BaseModel, Field, ValidationError, root_validator, validator, ConfigDict
from enum import Enum
from langchain_openai import AzureChatOpenAI
from langchain_core.runnables import RunnableLambda
from langchain_core.messages import BaseMessage, ToolMessage, HumanMessage
from langchain.agents.output_parsers.openai_tools import OpenAIToolsAgentOutputParser
from langchain.tools.render import format_tool_to_openai_tool
from langchain.agents.format_scratchpad.openai_tools import format_to_openai_tool_messages
from langchain.output_parsers import OutputFixingParser, PydanticOutputParser
from langchain.prompts import ChatPromptTemplate
from langchain.schema import StrOutputParser
from langchain.tools import BaseTool
import shutil
from langchain.callbacks.manager import (
    AsyncCallbackManagerForToolRun,
    CallbackManagerForToolRun,
)
from operator import itemgetter
import re
import json
import os
import subprocess
from ansi2html import Ansi2HTMLConverter
from langchain.agents import AgentExecutor

from langchain.callbacks.manager import (
    AsyncCallbackManagerForToolRun,
    CallbackManagerForToolRun,
)
from langgraph.prebuilt import ToolExecutor, ToolInvocation
from langgraph.graph import StateGraph, END
from langgraph.pregel import Pregel
from azure.storage.blob import BlobServiceClient, BlobClient, ContainerClient
from langchain.load.dump import dumps
from langchain.load.load import loads
import random
class CodeGenerateSchema(BaseModel):
    manim_code: str = Field(description="Manim code that generates the visuals for the scene. Treat this field as the equivalent to a .py file; it must be NOTHING BUT Python code and be able to be executed with manim -pql scene.py <class_name> AS-IS.")
    class_name: str = Field(description="The Manim scene class to use when running the manim -pql scene.py <class_name> command to render the video")
    desired_visual: str = Field(description="The exact input the user gave you describing the visual they want you to create")

    @root_validator
    def is_valid_code(cls, v):
        try:
            parsed_module = ast.parse(v['manim_code'])
            class_names = [node.name for node in ast.walk(parsed_module) if isinstance(node, ast.ClassDef)]
            if not any([v['class_name'] in name for name in class_names]):
                raise ValueError("Target render class not found in code!")
        except SyntaxError:
            raise ValueError("Code is not valid Python")
        return v
    
class CodeIssue(BaseModel):
    issue: str = Field(description="""A description of what issue with your animation this code will cause. Only report issues that fall into the below categories. Because you want to make sure the developer knows what to fix, you report what the actual issue is in the animation (e.g. the end of the pendulum moves at a different rate from the spring, causing the two to separate) instead of the category
                       - issues that cause the animation to be choppy
                       - issues that cause elements to move out of the video and be cut off or not visible
                       - issues that cause elements to incorrectly overlap
                       - issues that cause animations to render off-center in the video
                       - issues that cause elements that should move as 1 component to move at different speeds or in different directions
                       - instances where movement that should be determined by physical equations is not determined by those equations (e.g., a pendulum that doesn't move according to the pendulum equation)
                       - issues that cause latex code will render as plain text with markup visible
                       - issues that cause elements to render larger or smaller than they should be for comfortable viewing
                       - issues where an animation is too long or short to voice over (e.g., a pendulum swinging for an entire minute or only once) UNLESS THE USER SPECIFICALLY REQUESTS IT""")
    code: str = Field(description="The code that causes the issue")

class CodeCorrectnessReport(BaseModel):
    issues: List[CodeIssue] = Field(description="A list of issues with the code the developer wrote that will cause the animation to differ from your desired visual. You only care about the issues listed in the issue field of the CodeIssue model. You are very excited for those issues to be cleared up so you can show your eager students your new video!")

class ThingLearned(BaseModel):
    goal: str = Field(description="What you were trying to do with this specific piece of code (e.g. make a spring and weight visually move together, or represent a spring visually). DO NOT just state the animation goal given by the user here; this field is for more specific goals")
    original_code: str = Field(description="The code you initially wrote to try to achieve the goal")
    issue: str = Field(description="The issue you encountered with that code")
    final_code: str = Field(description="The code that fixed the issue")
    explanation: str = Field(description="A 1 sentence explanation of why the final code fixed the issue")

class Reflection(BaseModel):
    things_learned: List[ThingLearned] = Field(description="A list of things you learned about writing Manim code from the process of writing the user's code. Be sure to include all the minsconceptions you had so that you can remeber this information and avoid them in the future. DO NOT include issues that you didn't solve.")

class CodeCreateState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], operator.add]
    memory: str
    desired_visual: str
    gen_num: str

class VideoGenerate(BaseTool):
    name = "RenderVideo"
    description = "Attempts to render the provided code into a video file and provides the stdout and stderr of the render process. This tool returns the stderr of the command line so you can tell what went wrong; if it generated correctly there won't be output. However, it will be automatically sent to your client for their review, and they'll reach out to you with feedback"
    args_schema: Type[BaseModel] = CodeGenerateSchema
    conv = Ansi2HTMLConverter()

    model_config = ConfigDict(from_attributes=True)

    def _run(self, manim_code: str, class_name: str, desired_visual: str, run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
        """generate a video synchronously."""

        # get rid of old generation stuff
        if os.path.isfile("scene.py"):
            os.remove("scene.py")
        if os.path.isdir("media"):
            shutil.rmtree("media")

        # write the code to a file
        with open("scene.py", "w") as scene:
            scene.write(manim_code)

        stdout, stderr = subprocess.Popen(f"manim -pql scene.py {class_name}", stderr=subprocess.PIPE, stdout=subprocess.PIPE, shell=True).communicate()
        stdout_decoded = stdout.decode('utf-8')
        stderr_decoded = stderr.decode('utf-8')

        stdout_html = self.conv.convert(stdout_decoded)
        stderr_html = self.conv.convert(stderr_decoded)

        return stdout_html, stderr_html, manim_code, desired_visual
        
    def _arun(self, run_manager: Optional[AsyncCallbackManagerForToolRun] = None) -> str:
        """Generate a video segment asynchronously."""
        raise NotImplementedError("TextGenerate does not support async")
    
class VideoGeneratorAgent:
    tool_executor: ToolExecutor
    chat: AzureChatOpenAI
    folder: str = None

    def __init__(self):
        gpt_4_llm = AzureChatOpenAI(deployment_name="gpt-4-turbo", api_version="2023-07-01-preview", model_name="gpt-4-1106-preview", temperature=0, max_retries=10)

        blob_service_client = BlobServiceClient.from_connection_string(os.getenv('AzureWebJobsStorage'))
        container_client = blob_service_client.get_container_client("manim-memory")
        self.blob_client = container_client.get_blob_client("memory.txt")
        downloaded_blob = self.blob_client.download_blob()
        self.memory = downloaded_blob.readall().decode("utf-8")

        reflection_parser = PydanticOutputParser(pydantic_object=Reflection)
        reflection_fixing_parser = OutputFixingParser.from_llm(parser=reflection_parser, llm=gpt_4_llm)
        code_parser = PydanticOutputParser(pydantic_object=CodeCorrectnessReport)
        code_fixing_parser = OutputFixingParser.from_llm(parser=code_parser, llm=gpt_4_llm)

        self.rf_parser, self.cf_parser = reflection_fixing_parser, code_fixing_parser

        tools = [VideoGenerate()]
        tools_oai = [format_tool_to_openai_tool(tool) for tool in tools]
        self.tool_executor = ToolExecutor(tools)
        self.chat = gpt_4_llm.bind(tools=tools_oai)

        workflow = StateGraph(CodeCreateState)
        workflow.add_node("agent", self.call_model)
        workflow.add_node("action", self.call_tool)
        workflow.set_entry_point("agent")
        workflow.add_conditional_edges(
            "agent",
            self.should_continue,
            {
                "continue": "action",
                "end": END
            }
        )
        workflow.add_edge("action", "agent")
        self.app = workflow.compile()

    def __call__(self, prompt, folder, i):
        self.folder = folder
        resp = self.app.invoke({
            "messages": [
                ("system", f"You are a developer whose job it is to write a python file which can be run using manim -pql scene.py ClassName to generate the animation or visual that your client requests. Don't respond with anything except for the tool call and a 1 sentence explanation of what you did or are fixing. Don't keep trying something that isn't working; instead, switch to a different approach. Keep improving the video according to the customer's feedback until they are satisfied and say that there is no more work to be done. You remember this about similar jobs: {self.memory}"),
                ("user", f"Here's what I want you to do: {prompt}. Time is of the essence, so I'll pay you a large bonus if you get this done fast."),
            ],
            "memory": self.memory,
            "desired_visual": prompt,
            "gen_num": i
        })

        return folder

    def should_continue(self, state: CodeCreateState) -> str:
        gpt_4_llm = AzureChatOpenAI(deployment_name="gpt-4-turbo", api_version="2023-07-01-preview", model_name="gpt-4-1106-preview", temperature=0, max_retries=10)
        messages = state["messages"]
        last_message = messages[-1]

        if "tool_calls" not in last_message.additional_kwargs or len(messages) > 10: # this means 5 tool calls
            reflection_prompts = ChatPromptTemplate.from_messages(
                [
                    ("system", "You are an agent whose job it is to reflect on the steps taken by a user to create an animation of a desired visual and reflect on what they learned. The user has amnesia, so you need to do this so you can help them remember and not run into the same issues again in the future. Return your answer in the following format: {format_instructions}"),
                    ("user", "I just took these steps to make this animation: \"{desired_visual}\"\n\n{steps}"),
                ]
            )
            reflection_chain = (
                {
                    "format_instructions": itemgetter("format_instructions"),
                    "desired_visual": itemgetter("desired_visual"),
                    "steps": itemgetter("steps"),
                }
                | reflection_prompts
                | gpt_4_llm
                | self.rf_parser
            )
            reflection_result = reflection_chain.invoke({
                "format_instructions": self.rf_parser.get_format_instructions(),
                "desired_visual": state["desired_visual"],
                "steps": dumps(state["messages"])
            })

            try:
                existing_memory: Reflection = loads(state["memory"])
            except:
                existing_memory = Reflection(things_learned=[])
            existing_memory.things_learned.extend(reflection_result.things_learned)

            updated_memory_str = dumps(existing_memory)

            # write to blob storage
            # self.blob_client.upload_blob(updated_memory_str, overwrite=True)

            return "end"
        else:
            return "continue"
        
    def call_model(self, state: CodeCreateState) -> Dict[str, list[BaseMessage]]:
        messages = state['messages']
        response = self.chat.invoke(messages)
        return {"messages": [response]}

    def call_tool(self, state: CodeCreateState) -> Dict[str, list[BaseMessage]]:
        gpt_4_llm = AzureChatOpenAI(deployment_name="gpt-4-turbo", api_version="2023-07-01-preview", model_name="gpt-4-1106-preview", temperature=0, max_retries=10)

        messages = state['messages']
        last_message = messages[-1]

        calls = [ x for x in last_message.additional_kwargs["tool_calls"] ]
        resp_messages = []

        for call in calls:
            call_type = call["type"]
            call_id = call["id"]

            action = ToolInvocation(
                tool=call[call_type]["name"],
                tool_input=json.loads(call[call_type]["arguments"]),
            )

            #stdout, stderr, manim_code
            stdout, stderr, manim_code, desired_visual = self.tool_executor.invoke(action)

            # add tool message to output
            tool_message = ToolMessage(content=str(stderr), tool_call_id=call_id)
            resp_messages.append(tool_message)

            # # video rendered successfully; check for correctness
            # if "File</span> ready at" in stdout:
            #     code_checking_prompt = ChatPromptTemplate.from_messages(
            #         [
            #             ("system", "You are an educator who recently hired a software developer to make an educational video for you. You specifically told them that you wanted them to \"{desired_visual}\". They just finished a draft of the video and its your chance to review it. Format your review of this draft as follows: {format_instructions}"),
            #             ("user", 'Hi! Happy to report I finished a draft of your video. Here is the code:\n{manim_code}'),
            #         ]
            #     )
            #     code_checking_chain = (
            #         {
            #             "format_instructions": itemgetter("format_instructions"),
            #             "manim_code": itemgetter("manim_code"),
            #             "desired_visual": itemgetter("desired_visual"),
            #         }
            #         | code_checking_prompt
            #         | gpt_4_llm
            #         | self.cf_parser
            #     )

            #     code_correctness_output = code_checking_chain.invoke({
            #         "format_instructions": self.cf_parser.get_format_instructions(),
            #         "manim_code": manim_code,
            #         "desired_visual": desired_visual
            #     })

            #     if code_correctness_output.issues == []:
            #         resp_messages.append(HumanMessage(content="The code accurately generates the visual I want. No further action is needed"))
            #     else:
            #         resp_messages.append(HumanMessage(content=f"There are some things I need you to change. Here is my list: {code_correctness_output.issues}"))

            # copy file to saved spot
            try:
                html_obliterator = re.compile('<.*?>') 
                stdout_plain = re.sub(html_obliterator, '', stdout)
                stdout_plain = stdout_plain.replace("\n", "")
                stdout_plain = "".join(stdout_plain.split())
                url = re.compile(r"Filereadyat'([^']+)'").search(stdout_plain).group(1)
                logging.info(self.folder)
                logging.info(url)
                rdi = random.randint(0, 100000)
                shutil.copyfile(url, os.path.join(self.folder, f"animation_{state['gen_num']}.mp4"))
            except Exception as e:
                pass

        return {"messages": resp_messages}

    def combine_audio_video(self, audio, video, output):
        subprocess.call(["ffmpeg", "-i", audio, "-i", video, "-c:v", "copy", "-filter:a", "aresample=async=1", "-c:a", "flac", "-strict", "-2", output])

    def combine_videos(self, videos, final):
        c = "|".join(videos)
        subprocess.call([
            "ffmpeg",
            "-i", f"concat:{c}",  # Specify video file paths directly, separated by '|'
            "-c:a", "copy",
            "-c:v", "copy",
            final
        ])