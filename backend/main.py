import os
import json
import uuid
from dataclasses import dataclass
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.ingestion.ingestion import (
    VALID_ROLES,
    search_documents,
    generate_answer,
    generate_answer_stream,
    generate_faq,
    ingest_pdf,
    extract_text_from_pdf,
    clean_extracted_text,
    find_documents_by_name,
    list_documents,
    delete_document,
)
from backend.ingestion.agent import ask_agent

app = FastAPI(title="Enterprise Knowledge Assistant API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://vaishali16-maker.github.io",
        "http://127.0.0.1:5500",
        "http://127.0.0.1:8000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class Question(BaseModel):
    question: str


@dataclass
class CurrentUser:
    tenant_id: str
    role: str
    user_id: Optional[str] = None


def get_current_user() -> CurrentUser:
    # PHASE 1: temporary fixed identity from .env.
    # PHASE 2 replaces the body of this function with Supabase token verification.
    tenant_id = os.environ.get("DEFAULT_TENANT_ID")
    if not tenant_id:
        raise HTTPException(status_code=500, detail="DEFAULT_TENANT_ID is not set in .env")
    return CurrentUser(tenant_id=tenant_id, role=os.environ.get("DEFAULT_ROLE", "admin"))


@app.get("/")
def home():
    return {"message": "Enterprise Knowledge Assistant API is running"}


@app.get("/documents")
def get_documents(user: CurrentUser = Depends(get_current_user)):
    return {"documents": list_documents(user.tenant_id, user.role)}


@app.delete("/documents/{document_id}")
def remove_document(document_id: str, user: CurrentUser = Depends(get_current_user)):
    if not delete_document(document_id, user.tenant_id):
        raise HTTPException(status_code=404, detail="Document not found")
    return {"message": "Document deleted"}


@app.post("/upload")
async def upload_pdf(
    file: UploadFile = File(...),
    allowed_roles: str = Form(""),
    user: CurrentUser = Depends(get_current_user),
):
    display_name = os.path.basename(file.filename or "")
    if not display_name.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    roles = [r.strip().lower() for r in allowed_roles.split(",") if r.strip()]
    bad_roles = [r for r in roles if r not in VALID_ROLES]
    if bad_roles:
        raise HTTPException(status_code=400, detail=f"Unknown role(s): {', '.join(bad_roles)}")

    upload_dir = "backend/ingestion/uploads"
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, f"{uuid.uuid4().hex}.pdf")  # never trust the user's filename on disk
    with open(file_path, "wb") as buffer:
        buffer.write(await file.read())

    try:
        old_ids = [d["id"] for d in find_documents_by_name(user.tenant_id, display_name)]
        result = ingest_pdf(
            file_path,
            tenant_id=user.tenant_id,
            original_name=display_name,
            allowed_roles=roles or None,
            uploaded_by=user.user_id,
        )
        for old_id in old_ids:  # replace older copies only after the new one succeeded
            delete_document(old_id, user.tenant_id)
        try:
            full_text = clean_extracted_text(extract_text_from_pdf(file_path))
            suggested_questions = generate_faq(full_text)
        except Exception:
            suggested_questions = []
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)

    return {
        "document_id": result["document_id"],
        "filename": result["name"],
        "chunks": result["chunks"],
        "message": "PDF uploaded and indexed successfully",
        "suggested_questions": suggested_questions,
    }


@app.post("/ask")
def ask_question(data: Question, user: CurrentUser = Depends(get_current_user)):
    results = search_documents(data.question, user.tenant_id, user.role)
    context = "\n".join(item["content"] for item in results)
    answer = generate_answer(data.question, context)
    return {"question": data.question, "answer": answer, "sources": results}


@app.post("/ask/agent")
def ask_agent_route(data: Question, user: CurrentUser = Depends(get_current_user)):
    return ask_agent(data.question, user.tenant_id, user.role)


@app.post("/ask/stream")
def ask_stream(data: Question, user: CurrentUser = Depends(get_current_user)):
    results = search_documents(data.question, user.tenant_id, user.role)
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