from gremlin_python.driver import client, serializer
import os
import logging
from psycopg2 import pool
from pydantic import BaseModel, Field
from enum import Enum
import json

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

STARTING_KNOWLEDGE = {
    GradeLevel.KINDERGARTEN: {
        "Math": "Counting to 100, basic shapes, simple addition and subtraction.",
        "Biology": "Identifying basic body parts and familiar plants and animals.",
        "Physics": "Exploring motion, pushing and pulling.",
        "Chemistry": "Introduction to states of matter: solid, liquid, gas.",
        "Computer Science": "Understanding how to use a computer or tablet."
    },
    GradeLevel.FIRST_GRADE: {
        "Math": "Understanding numbers up to 120, exploring more complex addition and subtraction, basic geometry.",
        "Biology": "Learning about human needs, exploring plant parts and functions.",
        "Physics": "Discovering how light and sound work, exploring simple machines.",
        "Chemistry": "Differentiating between mixtures and solutions.",
        "Computer Science": "Practicing typing, beginning to navigate the internet."
    },
    GradeLevel.SECOND_GRADE: {
        "Math": "Introducing place value, time, and money, starting multiplication concepts.",
        "Biology": "Studying habitats and food chains, exploring human body basics.",
        "Physics": "Understanding forces and motion, exploring the concept of energy.",
        "Chemistry": "Exploring how materials can change state.",
        "Computer Science": "Using software to create documents, introducing simple coding."
    },
    GradeLevel.THIRD_GRADE: {
        "Math": "Mastering multiplication and division, understanding fractions, measuring objects.",
        "Biology": "Exploring how plants and animals adapt, learning about ecosystems.",
        "Physics": "Studying heat, light, and sound, exploring magnetism.",
        "Chemistry": "Introduction to chemical reactions and conservation of mass.",
        "Computer Science": "Developing coding skills with block-based programming, learning about internet safety."
    },
    GradeLevel.FOURTH_GRADE: {
        "Math": "Solving problems with multi-digit numbers, expanding knowledge of fractions and decimals.",
        "Biology": "Understanding food webs, studying human body systems.",
        "Physics": "Exploring electricity, circuits, and waves.",
        "Chemistry": "Learning about elements, compounds, and chemical changes.",
        "Computer Science": "Navigating websites, starting digital projects."
    },
    GradeLevel.FIFTH_GRADE: {
        "Math": "Adding and subtracting fractions, understanding volume and basic geometry.",
        "Biology": "Studying cells and human health, using the scientific method.",
        "Physics": "Deepening knowledge of forces and motion, exploring light and optics.",
        "Chemistry": "Exploring mixtures, solutions, and the periodic table.",
        "Computer Science": "Practicing safe online communication."
    },
    GradeLevel.SIXTH_GRADE: {
        "Math": "Exploring ratios and negative numbers, beginning algebra.",
        "Biology": "Classifying organisms, introducing genetics.",
        "Physics": "Studying energy transfer, simple engineering concepts.",
        "Chemistry": "Understanding chemical reactions and atomic structure.",
        "Computer Science": "Learning drag-and-drop coding, enhancing digital literacy."
    },
    GradeLevel.SEVENTH_GRADE: {
        "Math": "Studying proportional relationships, probability, and algebra.",
        "Biology": "Exploring human anatomy in detail, studying ecosystems.",
        "Physics": "Learning about thermal energy and motion.",
        "Chemistry": "Balancing chemical equations, introducing moles.",
        "Computer Science": "Understanding software use and installation."
    },
    GradeLevel.EIGHTH_GRADE: {
        "Math": "Studying linear equations, functions, and beginning geometry.",
        "Biology": "Exploring evolution, photosynthesis, and cellular respiration.",
        "Physics": "Learning about waves, electromagnetism, and Newton's laws.",
        "Chemistry": "Studying atomic theory and periodic trends.",
        "Computer Science": "Engaging in project-based coding, learning cybersecurity fundamentals."
    },
    GradeLevel.NINTH_GRADE: {
        "Math": "Diving into Algebra I, focusing on linear and quadratic equations.",
        "Biology": "Studying genetics, biomes, and organism structures.",
        "Physics": "Exploring motion, forces, and energy conversions.",
        "Chemistry": "Learning about stoichiometry, chemical bonds, and matter states.",
        "Computer Science": "Introduction to high-level programming languages."
    },
    GradeLevel.TENTH_GRADE: {
        "Math": "Engaging with Geometry, including theorems, circle geometry, and transformations.",
        "Biology": "Advancing in cell biology, genetics, and ecology.",
        "Physics": "Exploring electricity, magnetism, and mechanical waves.",
        "Chemistry": "Studying acid-base chemistry, thermodynamics.",
        "Computer Science": "Learning object-oriented programming and data structures."
    },
    GradeLevel.ELEVENTH_GRADE: {
        "Math": "Delving into Algebra II with polynomial functions, logarithms, and sequences.",
        "Biology": "Exploring evolution and plant biology in depth.",
        "Physics": "Studying fluid mechanics, thermal physics, and nuclear concepts.",
        "Chemistry": "Exploring kinetics and chemical equilibrium.",
        "Computer Science": "Studying software development and databases."
    },
    GradeLevel.TWELFTH_GRADE: {
        "Math": "Mastering Pre-Calculus, including trigonometry, complex numbers, and limits.",
        "Biology": "Focusing on advanced genetics and ecosystem studies.",
        "Physics": "Exploring advanced topics like electromagnetism without calculus.",
        "Chemistry": "Learning about electrochemistry, photochemistry, and materials science.",
        "Computer Science": "Advancing in programming, network security."
    },
    GradeLevel.FRESHMAN: {
        "Math": "Calculus I - Limits, derivatives, integrals, and their applications.",
        "Biology": "General Biology I - Cell structure, genetics, and basic metabolism.",
        "Physics": "General Physics I - Mechanics, including motion, forces, and energy.",
        "Chemistry": "General Chemistry I - Atomic structure, periodic table, stoichiometry, and chemical reactions.",
        "Computer Science": "Introduction to Programming - Basic syntax, control structures, data types, and simple data structures in a high-level programming language."
    },
    GradeLevel.SOPHOMORE: {
        "Math": "Calculus II - Sequences, series, polar coordinates, and parametric equations.",
        "Biology": "General Biology II - Evolution, ecology, plant and animal physiology.",
        "Physics": "General Physics II - Electricity, magnetism, and thermodynamics.",
        "Chemistry": "Organic Chemistry I - Structure, nomenclature, reactions, and mechanisms of organic molecules.",
        "Computer Science": "Data Structures and Algorithms - Introduction to complexity analysis, basic data structures (arrays, linked lists, stacks, queues, trees, graphs), and algorithmic strategies."
    },
    GradeLevel.JUNIOR:  {
        "Math": "Linear Algebra - Vector spaces, linear mappings, matrices, determinants, and eigenvalues and eigenvectors.",
        "Biology": "Cell Biology - In-depth study of cell structure and function, signaling pathways, and cell cycle.",
        "Physics": "Modern Physics - Introduction to quantum mechanics, atomic and nuclear physics, and special relativity.",
        "Chemistry": "Physical Chemistry - Thermodynamics, kinetics, quantum chemistry, and spectroscopy.",
        "Computer Science": "Software Engineering - Software development lifecycle, version control, testing, debugging, and basic software design patterns."
    },
    GradeLevel.SENIOR: {
        "Math": "Differential Equations - Ordinary differential equations, systems of ODEs, and an introduction to partial differential equations.",
        "Biology": "Genetics and Molecular Biology - Genetic information flow, gene expression, and genetic engineering techniques.",
        "Physics": "Advanced Physics Elective - Depending on the student's interest, a course in advanced mechanics, electromagnetism, computational physics, or another area of physics.",
        "Chemistry": "Inorganic Chemistry - Study of inorganic compounds, coordination chemistry, and organometallics.",
        "Computer Science": "Computer Networks and Security - Basics of network protocols, network architecture, data security, encryption, and cybersecurity fundamentals."
    }
}

def get_starting_knowledge(grade_level: GradeLevel, topic) -> dict[str, str]:
    # for every grade level below or equal to current grade level
    # get the starting knowledge for the topic

    starting_knowledge = []
    for gl in GradeLevel:
        if gl.value <= grade_level.value:
            starting_knowledge.append(STARTING_KNOWLEDGE[gl][topic])

    return " and ".join(starting_knowledge)

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

        insert_sql = """
        INSERT INTO userData (name, email, profile_picture_url, grade_level, interests)
        VALUES (%s, %s, %s, %s, %s) RETURNING id;
        """
        cursor.execute(insert_sql, (name, email, profile_pic_url, grade_level, interests))
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
    cursor.execute(insert_sql, ("No topic; this is a root node", [], json.dumps({}), "", "You"))
    base_id = cursor.fetchone()[0]
    conn.commit()
    snc = graph_client.submit(f"g.addV('start_node').property('user_id','{user_id}').property('table_id','{base_id}').property('lesson_id','-1').property('status','complete').property('pk','pk')")
    snc.all().result()

    subjects = ["Math", "Physics", "Chemistry", "Biology", "Computer Science"]

    for subject in subjects:
        insert_sql = """
        INSERT INTO Nodes (topic, learning_status, masteries, blurb, public_name)
        VALUES (%s, %s, %s, %s, %s) RETURNING id;
        """
        cursor.execute(insert_sql, (get_starting_knowledge(create_user_body.grade_level, subject), [], json.dumps({}), "", subject))
        base_id = cursor.fetchone()[0]
        conn.commit()

        subject_l = subject.lower()
        sc = graph_client.submit(f"g.addV('{subject_l}_base_node').property('user_id','{user_id}').property('table_id','{base_id}').property('lesson_id','-1').property('status','complete').property('pk','pk')")
        sc.all().result()

        cc = graph_client.submit(f"g.V().hasLabel('start_node').has('user_id', '{user_id}').addE('base').to(g.V().hasLabel('{subject_l}_base_node').has('user_id', '{user_id}'))")
        cc.all().result()

    postgreSQL_pool.putconn(conn)
    postgreSQL_pool.closeall()

    return user_id