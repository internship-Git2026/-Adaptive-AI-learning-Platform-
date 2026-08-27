from quiz_service import save_ai_quiz

sample_text = """

Python is a high level language.

Python supports object oriented programming.

Python is interpreted.

"""

status = save_ai_quiz(

    pdf_id=1,

    extracted_text=sample_text

)

print(status)