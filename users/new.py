from gremlin_python.driver import client, serializer
import os
import logging
from psycopg2 import pool
from pydantic import BaseModel, Field
from enum import Enum
import json
from stemtopics import Topics

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
    FRESHMAN = "F"
    SOPHOMORE = "S"
    JUNIOR = "J"
    SENIOR = "SR"

STARTING_KNOWLEDGE: dict[GradeLevel, Topics] = {
    GradeLevel.KINDERGARTEN: {
        Topics.COUNTING,
        Topics.BASIC_SHAPES,
        Topics.ADDITION,
        Topics.SUBTRACTION,
        Topics.COMPUTER_BASICS,
    },
    GradeLevel.FIRST_GRADE: {
        Topics.COUNTING,
        Topics.ADDITION,
        Topics.SUBTRACTION,
        Topics.BASIC_GEOMETRY,
        Topics.SIMPLE_MACHINES,
    },
    GradeLevel.SECOND_GRADE: {
        Topics.PLACE_VALUES,
        Topics.TIME_TELLING,
        Topics.MONEY_MATH,
        Topics.MULTIPLICATION,
        Topics.BASIC_PLANT_BIOLOGY,
    },
    GradeLevel.THIRD_GRADE: {
        Topics.MULTIPLICATION,
        Topics.DIVISION,
        Topics.SIMPLE_FRACTIONS,
        Topics.MEASUREMENTS,
        Topics.PHOTOSYNTHESIS,
    },
    GradeLevel.FOURTH_GRADE: {
        Topics.DECIMALS,
        Topics.FRACTIONS,
        Topics.AREA_AND_PERIMETER,
        Topics.ELECTRICITY_AND_MAGNETISM,
        Topics.ELEMENTS_AND_PERIODIC_TABLE,
    },
    GradeLevel.FIFTH_GRADE: {
        Topics.VOLUME,
        Topics.FRACTIONS,
        Topics.MIXTURES_AND_SOLUTIONS,
        Topics.LIGHT_AND_OPTICS,
        Topics.CELL_STRUCTURE_AND_FUNCTION,
    },
    GradeLevel.SIXTH_GRADE: {
        Topics.RATIOS,
        Topics.NEGATIVE_NUMBERS,
        Topics.ECOSYSTEMS_AND_BIOMES,
        Topics.ENERGY_TYPES_AND_CONVERSION,
        Topics.CHEMICAL_REACTIONS,
    },
    GradeLevel.SEVENTH_GRADE: {
        Topics.PROBABILITY,
        Topics.ALGEBRAIC_EXPRESSIONS,
        Topics.HUMAN_BODY_SYSTEMS,
        Topics.THERMODYNAMICS_IN_PHYSICS,
        Topics.SOLUTIONS_AND_MIXTURES,
    },
    GradeLevel.EIGHTH_GRADE: {
        Topics.LINEAR_EQUATIONS,
        Topics.FUNCTIONS,
        Topics.EVOLUTION_AND_NATURAL_SELECTION,
        Topics.WAVES_AND_SOUND,
        Topics.ATOMIC_AND_NUCLEAR_PHYSICS,
    },
    GradeLevel.NINTH_GRADE: {
        Topics.QUADRATIC_EQUATIONS,
        Topics.FUNCTIONS,
        Topics.GENETICS,
        Topics.CHEMICAL_BONDING,
        Topics.MOTION_AND_FORCES,
    },
    GradeLevel.TENTH_GRADE: {
        Topics.GEOMETRY_THEOREMS,
        Topics.ACID_BASE_REACTIONS,
        Topics.ELECTRICITY_AND_MAGNETISM,
        Topics.PLANT_AND_ANIMAL_CLASSIFICATION,
        Topics.CODING_SIMPLE_PROGRAMS,
    },
    GradeLevel.ELEVENTH_GRADE: {
        Topics.ALGEBRAIC_EXPRESSIONS,
        Topics.CHEMICAL_EQUILIBRIUM,
        Topics.FLUID_DYNAMICS,
        Topics.GENETICS_AND_MOLECULAR_BIOLOGY,
        Topics.DATABASES_ADVANCED,
    },
    GradeLevel.TWELFTH_GRADE: {
        Topics.CALCULUS_LIMITS,
        Topics.ECOLOGY_CONSERVATION,
        Topics.ELECTROCHEMISTRY,
        Topics.QUANTUM_THEORY_BASICS,
        Topics.NETWORKING_AND_SECURITY,
    },
    GradeLevel.FRESHMAN: {
        Topics.DERIVATIVES,
        Topics.CELL_BIOLOGY,
        Topics.ORGANIC_CHEMISTRY_BASICS,
        Topics.GENERAL_PHYSICS_I,
        Topics.INTRODUCTION_TO_PROGRAMMING,
    },
    GradeLevel.SOPHOMORE: {
        Topics.INTEGRALS,
        Topics.ECOLOGY,
        Topics.ORGANIC_CHEMISTRY,
        Topics.GENERAL_PHYSICS_II,
        Topics.DATA_STRUCTURES_COMPLEX,
    },
    GradeLevel.JUNIOR: {
        Topics.MULTIVARIABLE_CALCULUS,
        Topics.MICROORGANISMS,
        Topics.PHYSICAL_CHEMISTRY,
        Topics.MODERN_PHYSICS,
        Topics.SOFTWARE_ENGINEERING,
    },
    GradeLevel.SENIOR: {
        Topics.DIFFERENTIAL_EQUATIONS,
        Topics.GENETICS_AND_MOLECULAR_BIOLOGY,
        Topics.INORGANIC_CHEMISTRY,
        Topics.ADVANCED_PHYSICS_ELECTIVE,
        Topics.COMPUTER_NETWORKS_AND_SECURITY,
    },
}

def get_starting_knowledge(grade_level: GradeLevel) -> list[str]:
    # for every grade level below or equal to current grade level
    # get the starting knowledge for the topic

    starting_knowledge = []
    for gl in GradeLevel:
        if gl.value <= grade_level.value:
            try:
                vals = [x.value for x in STARTING_KNOWLEDGE[gl]]
                starting_knowledge.extend(vals)
            except Exception:
                logging.info(STARTING_KNOWLEDGE[gl])
                pass

    return starting_knowledge

class UserCreateRequest(BaseModel):
    name: str = Field(description="The name of the user")
    email: str = Field(description="The email of the user")
    profile_pic_url: str = Field(description="The profile picture of the user")
    grade_level: GradeLevel = Field(description="The grade level of the user")
    interests: list[str] = Field(description="The interests of the user")

def create_new_user(req_json: dict) -> int:
    graph_client = client.Client('wss://guidestone-gremlin.gremlin.cosmos.azure.com:443/','g', 
                    username=f"/dbs/guidestone/colls/knowledge-graph", 
                    password=os.getenv("KNOWLEDGE_GRAPH_KEY"),
                    message_serializer=serializer.GraphSONSerializersV2d0())
    
    postgreSQL_pool = pool.SimpleConnectionPool(1, int(os.getenv("PYTHON_THREADPOOL_THREAD_COUNT")), os.getenv("POSTGRES_CONN_STRING"))  
    conn = postgreSQL_pool.getconn()
    cursor = conn.cursor()

    try:
        create_user_body = UserCreateRequest(**req_json)
    except Exception as e:
        logging.error("Could not parse user creation request: " + str(e))

    # add user to postgres
    try:
        name = create_user_body.name
        email = create_user_body.email
        profile_pic_url = create_user_body.profile_pic_url
        grade_level = create_user_body.grade_level.value
        interests = create_user_body.interests
        base_knowledge = get_starting_knowledge(create_user_body.grade_level)

        insert_sql = """
        INSERT INTO userData (name, email, profile_picture_url, grade_level, interests, base_knowledge)
        VALUES (%s, %s, %s, %s, %s, %s) RETURNING id;
        """
        cursor.execute(insert_sql, (name, email, profile_pic_url, grade_level, interests, base_knowledge))
        user_id = cursor.fetchone()[0]
        conn.commit()

    except Exception as e:
        conn.rollback()
        postgreSQL_pool.putconn(conn)
        postgreSQL_pool.closeall()
        raise e
    
    # create starting graph for user in gremlin
    insert_sql = """
    INSERT INTO Nodes (topic, learning_status, masteries, blurb, public_name)
    VALUES (%s, %s, %s, %s, %s) RETURNING id;
    """
    cursor.execute(insert_sql, (Topics.HUMAN_INTUITION, [], json.dumps({}), "", "You"))
    base_id = cursor.fetchone()[0]
    conn.commit()
    snc = graph_client.submit(f"g.addV('start_node').property('user_id','{user_id}').property('table_id','{base_id}').property('lesson_id','-1').property('status','complete').property('pk','pk')")
    snc.all().result()

    # subjects = ["Math", "Physics", "Chemistry", "Biology", "Computer Science"]

    # for subject in subjects:
    #     insert_sql = """
    #     INSERT INTO Nodes (topic, learning_status, masteries, blurb, public_name)
    #     VALUES (%s, %s, %s, %s, %s) RETURNING id;
    #     """
    #     cursor.execute(insert_sql, (get_starting_knowledge(create_user_body.grade_level, subject), [], json.dumps({}), "", subject))
    #     base_id = cursor.fetchone()[0]
    #     conn.commit()

    #     subject_l = subject.lower()
    #     sc = graph_client.submit(f"g.addV('{subject_l}_base_node').property('user_id','{user_id}').property('table_id','{base_id}').property('lesson_id','-1').property('status','complete').property('pk','pk')")
    #     sc.all().result()

    #     cc = graph_client.submit(f"g.V().hasLabel('start_node').has('user_id', '{user_id}').addE('base').to(g.V().hasLabel('{subject_l}_base_node').has('user_id', '{user_id}'))")
    #     cc.all().result()

    postgreSQL_pool.putconn(conn)
    postgreSQL_pool.closeall()

    return user_id