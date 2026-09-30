import os
import json
import uuid
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from backend.auth import CurrentUser, get_current_user, require_roles
from datetime import datetime
from backend.ingestion.ingestion import supabase
import time
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
    check_cache, 
    store_cache, 
    log_request, 
    is_simple_question
)
from backend.ingestion.agent import ask_agent

app = FastAPI(title="Enterprise Knowledge Assistant API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://vaishali16-maker.github.io",
        "http://127.0.0.1:5500",
        "http://127.0.0.1:8000",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class Question(BaseModel):
    question: str



@app.get("/")
def home():
    return {"message": "Enterprise Knowledge Assistant API is running"}


@app.get("/documents")
def get_documents(user: CurrentUser = Depends(get_current_user)):
    return {"documents": list_documents(user.tenant_id, user.role)}


@app.delete("/documents/{document_id}")
def remove_document(document_id: str, user: CurrentUser = Depends(require_roles("admin", "hr"))):
    if not delete_document(document_id, user.tenant_id):
        raise HTTPException(status_code=404, detail="Document not found")
    return {"message": "Document deleted"}


@app.post("/upload")
async def upload_pdf(
    file: UploadFile = File(...),
    allowed_roles: str = Form(""),
    user: CurrentUser = Depends(require_roles("admin", "hr")),
):
    display_name = os.path.basename(file.filename or "")
    if not display_name.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    roles = [r.strip().lower() for r in allowed_roles.split(",") if r.strip()]
    bad_roles = [r for r in roles if r not in VALID_ROLES]
    if bad_roles:
        raise HTTPException(status_code=400, detail=f"Unknown role(s): {', '.join(bad_roles)}")
    if roles:
       roles = sorted(set(roles) | {"admin"})

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

@app.get("/me")
def me(user: CurrentUser = Depends(get_current_user)):
       return {"email": user.email, "role": user.role, "tenant_id": user.tenant_id}

@app.post("/ask")
def ask_question(data: Question, user: CurrentUser = Depends(get_current_user)):
    results = search_documents(data.question, user.tenant_id, user.role)
    context = "\n".join(item["content"] for item in results)
    answer = generate_answer(data.question, context)
    return {"question": data.question, "answer": answer, "sources": results}

@app.get("/conversations")
def list_conversations(user: CurrentUser = Depends(get_current_user)):
    res = (
        supabase.table("conversations")
        .select("id, title, created_at")
        .eq("user_id", user.user_id)
        .order("created_at", desc=True)
        .execute()
    )
    return {"conversations": res.data or []}


@app.get("/conversations/{conversation_id}/messages")
def get_messages(conversation_id: str, user: CurrentUser = Depends(get_current_user)):
    convo = (
        supabase.table("conversations")
        .select("id")
        .eq("id", conversation_id)
        .eq("user_id", user.user_id)
        .execute()
        .data
    )
    if not convo:
        raise HTTPException(status_code=404, detail="Conversation not found")
    res = (
        supabase.table("messages")
        .select("role, content, sources, created_at")
        .eq("conversation_id", conversation_id)
        .order("id")
        .execute()
    )
    return {"messages": res.data or []}


class AskWithHistory(Question):
    conversation_id: str | None = None


@app.post("/ask/chat")
@app.post("/ask/chat")
def ask_chat(data: AskWithHistory, user: CurrentUser = Depends(get_current_user)):
    start = time.time()
    conv_id = data.conversation_id
    if not conv_id:
        title = data.question[:60]
        conv_id = (
            supabase.table("conversations")
            .insert({"user_id": user.user_id, "title": title})
            .execute()
            .data[0]["id"]
        )

    supabase.table("messages").insert(
        {"conversation_id": conv_id, "role": "user", "content": data.question}
    ).execute()

    cached = check_cache(data.question, user.tenant_id)
    if cached:
        answer, sources = cached["answer"], cached.get("sources") or []
        model_used = "cache"
    else:
        model_used = "small" if is_simple_question(data.question) else "standard"
        result = ask_agent(data.question, user.tenant_id, user.role)
        answer, sources = result["answer"], result.get("sources", [])
        store_cache(data.question, user.tenant_id, answer, sources)

    latency_ms = int((time.time() - start) * 1000)
    log_request(user.tenant_id, user.user_id, data.question, bool(cached), model_used, latency_ms)

    supabase.table("messages").insert(
        {
            "conversation_id": conv_id,
            "role": "assistant",
            "content": answer,
            "sources": sources,
        }
    ).execute()

    return {
        "question": data.question,
        "answer": answer,
        "sources": sources,
        "conversation_id": conv_id,
        "cache_hit": bool(cached),
        "model": model_used,
    }


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