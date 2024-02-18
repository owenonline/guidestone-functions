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
    COLLEGE = "College"

STARTING_KNOWLEDGE = {
    GradeLevel.KINDERGARTEN: {
        "Math": "Basic counting, shapes, and simple addition and subtraction.",
        "Biology": "Basic body parts, plant and animal identification.",
        "Physics": "Understanding of everyday physical concepts like motion and gravity.",
        "Chemistry": "Familiarity with water, states of matter (solid, liquid, gas).",
        "Computer Science": "Basic computer and tablet usage."
    },
    GradeLevel.FIRST_GRADE: {
        "Math": "Numbers up to 100, more complex addition and subtraction.",
        "Biology": "Basic human needs, plant life cycles.",
        "Physics": "Simple machines, introduction to light and sound.",
        "Chemistry": "Mixtures vs. solutions, introduction to chemical reactions.",
        "Computer Science": "Typing skills, basic internet navigation."
    },
    GradeLevel.SECOND_GRADE: {
        "Math": "Place value, time, money, introduction to multiplication.",
        "Biology": "Animal habitats, human body systems.",
        "Physics": "Forces and motion, energy forms.",
        "Chemistry": "Properties of materials, changes in matter.",
        "Computer Science": "Creating and editing documents, basic coding concepts."
    },
    GradeLevel.THIRD_GRADE: {
        "Math": "Multiplication and division, fractions, measurement.",
        "Biology": "Plant and animal adaptations, ecosystems.",
        "Physics": "Heat and temperature, magnetism.",
        "Chemistry": "Acids and bases, conservation of mass.",
        "Computer Science": "More advanced coding (block-based), internet safety."
    },
    GradeLevel.FOURTH_GRADE: {
        "Math": "Multi-digit operations, expanded fractions, decimals.",
        "Biology": "Food chains, human organ systems.",
        "Physics": "Electricity and circuits, waves.",
        "Chemistry": "Elements and compounds, physical vs chemical changes.",
        "Computer Science": "Basic website navigation, introduction to digital projects."
    },
    GradeLevel.FIFTH_GRADE: {
        "Math": "Adding and subtracting fractions, volume, basic geometry.",
        "Biology": "Cells, the scientific method, human health.",
        "Physics": "Light and optics, force and motion in more depth.",
        "Chemistry": "Mixtures and solutions in depth, introduction to the periodic table.",
        "Computer Science": "Safe online communication, basic website creation."
    },
    GradeLevel.SIXTH_GRADE: {
        "Math": "Ratios, negative numbers, basic algebraic concepts.",
        "Biology": "Classification of living things, basic genetics.",
        "Physics": "Energy transfer, simple engineering principles.",
        "Chemistry": "Chemical reactions, introduction to atomic structure.",
        "Computer Science": "Intermediate coding, digital literacy and research skills."
    },
    GradeLevel.SEVENTH_GRADE: {
        "Math": "Proportional relationships, probability, more complex algebra.",
        "Biology": "Human body systems in detail, ecosystems.",
        "Physics": "Thermal energy, laws of motion.",
        "Chemistry": "Chemical equations, the mole concept.",
        "Computer Science": "Software use and installation, beginning of algorithm understanding."
    },
    GradeLevel.EIGHTH_GRADE: {
        "Math": "Linear equations, functions, introduction to geometry.",
        "Biology": "Evolution, cellular respiration and photosynthesis.",
        "Physics": "Waves and electromagnetic spectrum, Newton's laws.",
        "Chemistry": "Atomic theory, periodic trends.",
        "Computer Science": "Project-based coding, cybersecurity basics."
    },
    GradeLevel.NINTH_GRADE: {
        "Math": "Algebra I - Linear and quadratic equations, functions.",
        "Biology": "Genetics, biomes, structure and function of living organisms.",
        "Physics": "Motion and forces, energy forms and conversions.",
        "Chemistry": "Stoichiometry, chemical bonding, states of matter.",
        "Computer Science": "Introduction to high-level programming languages."
    },
    GradeLevel.TENTH_GRADE: {
        "Math": "Geometry - Theorems and proofs, circle geometry, transformations.",
        "Biology": "Cell biology, molecular genetics, ecology.",
        "Physics": "Electricity and magnetism, mechanical waves.",
        "Chemistry": "Acid-base chemistry, thermodynamics.",
        "Computer Science": "Object-oriented programming, data structures."
    },
    GradeLevel.ELEVENTH_GRADE: {
        "Math": "Algebra II - Polynomial functions, logarithms, sequences and series.",
        "Biology": "Anatomy and physiology, evolution, plant biology.",
        "Physics": "Fluid mechanics, thermal physics, nuclear physics.",
        "Chemistry": "Organic chemistry, kinetics, equilibrium.",
        "Computer Science": "Software development principles, databases."
    },
    GradeLevel.TWELFTH_GRADE: {
        "Math": "Pre-Calculus - Trigonometry, complex numbers, limits.",
        "Biology": "Advanced genetics, biotechnology, ecosystems.",
        "Physics": "physics 1 without calc, electromagnetism",
        "Chemistry": "Electrochemistry, photochemistry, materials science.",
        "Computer Science": "Advanced programming concepts, network security."
    },
    GradeLevel.COLLEGE: {
        "Math": "Calculus, linear algebra, differential equations.",
        "Biology": "Advanced cellular biology, systems biology, evolutionary biology.",
        "Physics": "Advanced topics in mechanics, electromagnetism, and thermodynamics.",
        "Chemistry": "Advanced organic and inorganic chemistry, analytical methods.",
        "Computer Science": "Complex algorithm design, machine learning, systems programming."
    }
}

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
        cursor.execute(insert_sql, (STARTING_KNOWLEDGE[create_user_body.grade_level][subject], [], json.dumps({}), "", subject))
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