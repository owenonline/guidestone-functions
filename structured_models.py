
from pydantic import BaseModel, Field, ValidationError, root_validator, validator
from enum import Enum
import re

## helper functions and classes for user creation ##

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

## helper class for token exchange ##
class TokenExchangeRequest(BaseModel):
    code: str
    redirect_uri: str

## helper functions and classes for graph expansion ##

# makes text safe for insertion into gremlin graph
def clean_text(text: str) -> str:
    if text is None:
        return None
    return re.sub(r'\\\n *\\', '', text).replace("'", "").replace('"', '').replace("/","").replace(" ","_").strip().lower()

class GraphExpandRequest(BaseModel):
    topic: str = Field(description="The topic to expand the graph on")

class LeafTopic(BaseModel):
    id: str = Field(description="the id of the node in the graph")
    topic: str = Field(description="the natural language and very brief description of what the topic is")

class TopicDependencies(BaseModel):
    dependencies: list[str] = Field(description="Topics that the user must already understand to understand the current topic. For example, to understand the topic 'fractions', the user must already understand the topic 'division'. Generate a full list of all of the topics IMMEDIATELY PRECEDING the current topic. For example, if the current topic is 'derivatives' you should include 'limits' in this list but NOT 'multiplication' since it is not a direct prerequisite for understanding derivatives.")

## helper functions and classes for creating lessons ##
class LessonCreateRequest(BaseModel):
    node_id: str = Field(description="The id of the node in the graph that needs a new lesson")