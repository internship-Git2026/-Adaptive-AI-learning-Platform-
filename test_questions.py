from question_generator import generate_questions

text = """

Python is a high level programming language.

Python supports OOP.

Python is interpreted.

"""

questions = generate_questions(text)

print(questions)