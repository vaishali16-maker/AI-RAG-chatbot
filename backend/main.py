import os
from fastapi import FastAPI, Request, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import json
from backend.ingestion.ingestion import (generate_answer_stream, search_documents,
 generate_answer, ingest_pdf, generate_faq, extract_text_from_pdf, clean_extracted_text)
from backend.ingestion.agent import ask_agent



app = FastAPI(title="AI Document Search API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
class Question(BaseModel):
    question: str

# API endpoint to ask a question to the agent
@app.post("/ask/agent")
def ask_agent_route(data: Question):
    return ask_agent(data.question)

# API endpoint to check if the API is running
@app.get("/")
def home():
    return {"message": "AI Document Search API is running"}

# API endpoint to upload a PDF and index it
@app.post("/upload")
async def upload_pdf(file: UploadFile = File(...)):
    upload_dir = "backend/ingestion/uploads"
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, file.filename)
    with open(file_path, "wb") as buffer:
        buffer.write(await file.read())
    chunk_count = ingest_pdf(file_path)
    try:
        full_text = clean_extracted_text(extract_text_from_pdf(file_path))
        suggested_questions = generate_faq(full_text)
    except Exception:
        suggested_questions = []
    return {
        "filename": file.filename,
        "chunks": chunk_count,
        "message": "PDF uploaded and indexed successfully",
        "suggested_questions": suggested_questions
    }

# API endpoint to ask a question and get an answer
@app.post("/ask")
def ask_question(data: Question):
    results = search_documents(data.question)
    context = "\n".join(item["content"] for item in results)
    answer = generate_answer(data.question, context)
    return {
        "question": data.question,
        "answer": answer,
        "sources": results
    }
# API endpoint to ask a question and stream the answer
@app.post("/ask/stream")
def ask_stream(data: Question):
    from backend.ingestion.ingestion import search_documents  # local import to avoid circulars
    results = search_documents(data.question)
    if not results:
        def empty_gen():
            yield "data: I could not find the answer in the document.\n\n"
        return StreamingResponse(empty_gen(), media_type="text/event-stream")
    context = "\n".join(item["content"] for item in results)
 
    def event_gen():
        sources_payload = json.dumps(
            [
                {
                    "source_file": r.get("source_file"),
                    "chunk_index": r.get("chunk_index"),
                    "similarity": r.get("similarity"),
                }
                for r in results
            ]
        )
        yield f"event: sources\ndata: {sources_payload}\n\n"
        for token in generate_answer_stream(data.question, context):
            safe_token = token.replace("\n", "\\n")
            yield f"data: {safe_token}\n\n"
        yield "event: done\ndata: {}\n\n"
    return StreamingResponse(event_gen(), media_type="text/event-stream")
 