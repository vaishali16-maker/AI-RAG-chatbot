from pathlib import Path
import os
import logging
import re
import json
import fitz  # pymupdf
import cohere
from dotenv import load_dotenv
from supabase import create_client, Client
import ollama
import requests
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


# Setup
BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be set in your .env file")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
co = cohere.Client(os.environ.get("COHERE_API_KEY"))
EMBED_MODEL_NAME = "qwen3.5:4b"
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GROQ_MODEL = "openai/gpt-oss-20b"
GROQ_MODEL_SMALL = "llama-3.1-8b-instant"  # faster/cheaper than gpt-oss-20b
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


def _call_llm_with_model(messages: list[dict], model: str) -> str:
    if GROQ_API_KEY:
        try:
            resp = requests.post(
                GROQ_URL,
                headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                json={"model": model, "messages": messages, "reasoning_format": "hidden"},
                timeout=30,
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"].strip()
            return re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
        except Exception as e:
            raise RuntimeError(f"Groq generation failed: {e}") from e
    return _call_llm(messages)  # fallback to Ollama path if no Groq key


def _call_llm(messages: list[dict]) -> str:
    if GROQ_API_KEY:
        try:
            resp = requests.post(
                GROQ_URL,
                headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                json={
                    "model": GROQ_MODEL,
                    "messages": messages,
                    "reasoning_format": "hidden",
                },
                timeout=30,
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"].strip()
            content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
            return content
        except Exception as e:
            raise RuntimeError(f"Groq generation failed: {e}") from e
    else:
        try:
            response = ollama.chat(model=EMBED_MODEL_NAME, messages=messages, think=False)
            return response["message"]["content"].strip()
        except Exception as e:
            raise RuntimeError(
                f"Ollama generation failed — is 'ollama serve' running "
                f"and is '{EMBED_MODEL_NAME}' pulled? ({e})"
            ) from e


def _call_llm_stream(messages: list[dict]):
    if GROQ_API_KEY:
        try:
            with requests.post(
                GROQ_URL,
                headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                json={
                    "model": GROQ_MODEL,
                    "messages": messages,
                    "stream": True,
                    "reasoning_format": "hidden",
                },
                stream=True,
                timeout=60,
            ) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line:
                        continue
                    decoded = line.decode("utf-8")
                    if not decoded.startswith("data: "):
                        continue
                    payload = decoded[len("data: "):]
                    if payload.strip() == "[DONE]":
                        break
                    chunk = json.loads(payload)
                    delta = chunk["choices"][0]["delta"].get("content")
                    if delta:
                        yield delta
        except Exception as e:
            yield f"[error: Groq generation failed — {e}]"
    else:
        try:
            stream = ollama.chat(
                model=EMBED_MODEL_NAME, messages=messages, think=False, stream=True
            )
            for chunk in stream:
                token = chunk["message"]["content"]
                if token:
                    yield token
        except Exception as e:
            yield f"[error: Ollama generation failed — {e}]"


# 1. Extraction (layout-aware, with TOC-page filtering)
def _order_blocks_by_column(blocks: list, page_width: float) -> list:
    full_width_threshold = 0.6 * page_width
    full_width = []
    column_blocks = []
    for b in blocks:
        x0, y0, x1, y1 = b[0], b[1], b[2], b[3]
        if (x1 - x0) > full_width_threshold:
            full_width.append(b)
        else:
            column_blocks.append(b)

    full_width.sort(key=lambda b: b[1])
    mid_x = page_width / 2
    left = [b for b in column_blocks if (b[0] + b[2]) / 2 < mid_x]
    right = [b for b in column_blocks if (b[0] + b[2]) / 2 >= mid_x]
    left.sort(key=lambda b: b[1])
    right.sort(key=lambda b: b[1])
    if column_blocks:
        column_start_y = min(b[1] for b in column_blocks)
    else:
        column_start_y = float("inf")
    header_blocks = [b for b in full_width if b[1] < column_start_y]
    footer_blocks = [b for b in full_width if b[1] >= column_start_y]
    return header_blocks + left + right + footer_blocks


def _is_structural_page(block_texts: list[str]) -> bool:
    blocks = [b.strip() for b in block_texts if b.strip()]
    if len(blocks) < 3:
        return False
    long_blocks = sum(1 for b in blocks if len(b) > 200)
    short_blocks = sum(1 for b in blocks if len(b) < 80)
    return long_blocks == 0 and (short_blocks / len(blocks)) > 0.6


def extract_text_from_pdf(file_path: str, skip_structural_pages: bool = True) -> str:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"No file found at {file_path}")
    try:
        doc = fitz.open(str(path))
    except Exception as e:
        raise ValueError(f"Could not open '{path.name}' as a PDF: {e}") from e
    page_texts = []
    for page_num, page in enumerate(doc, start=1):
        try:
            blocks = page.get_text("blocks")
        except Exception as e:
            logger.warning("Skipping page %d of %s: %s", page_num, path.name, e)
            continue
        blocks = _order_blocks_by_column(blocks, page.rect.width)
        block_texts = [b[4] for b in blocks if b[4] and b[4].strip()]
        if not block_texts:
            continue
        if skip_structural_pages and _is_structural_page(block_texts):
            logger.info("Skipping page %d of %s (looks structural, not prose)", page_num, path.name)
            continue
        page_text = "\n".join(b.strip() for b in block_texts)
        page_texts.append(page_text)

    doc.close()
    full_text = "\n\n".join(page_texts)
    if not full_text.strip():
        raise ValueError(
            f"No extractable body text found in '{path.name}' "
            "(it may be a scanned/image-only PDF, or entirely front-matter)"
        )
    return full_text


# 2. Cleanup + Chunking (sentence-boundary, with overlap)
def clean_extracted_text(text: str) -> str:
    text = re.sub(r'[\U0001F300-\U0001FAFF\U00002600-\U000027BF]', '', text)  # emojis and symbols -> empty string
    text = re.sub(r'[•·.]{3,}', ' ', text)  # replace 3+ bullet points/dots with a single space
    text = re.sub(r'\s+', ' ', text)  # collapse whitespace
    return text.strip()


def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 150) -> list[str]:
    sentences = re.split(r'(?<=[.!?])\s+', text)
    chunks = []
    current = ""
    for sentence in sentences:
        if len(current) + len(sentence) <= chunk_size:
            current += (" " if current else "") + sentence
        else:
            if current:
                chunks.append(current.strip())
            overlap_text = current[-overlap:] if len(current) > overlap else current
            current = overlap_text + " " + sentence
    if current.strip():
        chunks.append(current.strip())
    return chunks


# 3. Ingestion (document record + linked chunks)
VALID_ROLES = ["employee", "manager", "hr", "admin"]


def find_documents_by_name(tenant_id: str, name: str) -> list[dict]:
    try:
        res = (
            supabase.table("documents")
            .select("id, name")
            .eq("tenant_id", tenant_id)
            .eq("name", name)
            .execute()
        )
    except Exception as e:
        raise RuntimeError(f"Failed to look up existing document '{name}': {e}") from e
    return res.data or []


def ingest_pdf(
    file_path: str,
    tenant_id: str,
    original_name: Optional[str] = None,
    allowed_roles: Optional[list] = None,
    uploaded_by: Optional[str] = None,
) -> dict:
    path = Path(file_path)
    name = original_name or path.name
    text = clean_extracted_text(extract_text_from_pdf(file_path))
    chunks = chunk_text(text)
    if not chunks:
        raise ValueError(f"'{name}' produced no chunks after splitting")
    try:
        from backend.ingestion.langchain_components import embeddings as lc_embeddings
        vectors = lc_embeddings.embed_documents(chunks)
    except Exception as e:
        raise RuntimeError(f"Embedding failed for '{name}': {e}") from e

    doc_row = {"tenant_id": tenant_id, "name": name}
    if allowed_roles:
        doc_row["allowed_roles"] = allowed_roles
    if uploaded_by:
        doc_row["uploaded_by"] = uploaded_by
    try:
        document_id = supabase.table("documents").insert(doc_row).execute().data[0]["id"]
    except Exception as e:
        raise RuntimeError(f"Failed to create document record for '{name}': {e}") from e

    rows = [
        {
            "document_id": document_id,
            "chunk_index": idx,
            "content": chunk,
            "embedding": vector,
        }
        for idx, (chunk, vector) in enumerate(zip(chunks, vectors))
    ]
    try:
        for start in range(0, len(rows), 100):
            supabase.table("chunks").insert(rows[start:start + 100]).execute()
    except Exception as e:
        supabase.table("documents").delete().eq("id", document_id).execute()
        raise RuntimeError(f"Failed to store chunks for '{name}': {e}") from e

    logger.info("Ingested '%s': %d chunks stored", name, len(chunks))
    extract_graph(document_id, text)
    upload_pdf_to_storage(document_id, file_path)
    return {"document_id": document_id, "name": name, "chunks": len(chunks)}

def upload_pdf_to_storage(document_id: str, file_path: str):
    try:
        with open(file_path, "rb") as f:
            supabase.storage.from_("documents").upload(
                f"{document_id}.pdf", f, {"content-type": "application/pdf"}
            )
    except Exception as e:
        logger.warning("Failed to store PDF for %s: %s", document_id, e)


def get_pdf_url(document_id: str) -> Optional[str]:
    try:
        res = supabase.storage.from_("documents").create_signed_url(f"{document_id}.pdf", 3600)
        return res.get("signedURL") or res.get("signed_url")
    except Exception:
        return None

def list_documents(tenant_id: str, role: str) -> list[dict]:
    try:
        res = (
            supabase.table("documents")
            .select("id, name, allowed_roles, created_at")
            .eq("tenant_id", tenant_id)
            .contains("allowed_roles", [role])
            .order("created_at", desc=True)
            .execute()
        )
    except Exception as e:
        raise RuntimeError(f"Failed to list documents: {e}") from e
    return res.data or []


def delete_document(document_id: str, tenant_id: str) -> bool:
    try:
        res = (
            supabase.table("documents")
            .delete()
            .eq("id", document_id)
            .eq("tenant_id", tenant_id)
            .execute()
        )
    except Exception as e:
        raise RuntimeError(f"Failed to delete document {document_id}: {e}") from e
    return bool(res.data)


# 4. Retrieval (always scoped to a tenant and role)
def search_documents(
    query: str,
    tenant_id: str,
    role: str,
    match_count: int = 3,
    match_threshold: float = 0.15,
):
    try:
        from backend.ingestion.langchain_components import embeddings as lc_embeddings
        query_vector = lc_embeddings.embed_query(query)
    except Exception as e:
        raise RuntimeError(f"Failed to embed query: {e}") from e
    try:
        result = supabase.rpc(
            "match_chunks",
            {
                "query_embedding": query_vector,
                "match_threshold": match_threshold,
                "match_count": match_count,
                "p_tenant_id": tenant_id,
                "p_role": role,
            },
        ).execute()
    except Exception as e:
        raise RuntimeError(f"Vector search failed: {e}") from e
    rows = result.data or []
    for r in rows:
        r["source_file"] = r.get("document_name")  # keeps the existing frontend working
    return rows


# 4b. Semantic cache
def check_cache(question: str, tenant_id: str, threshold: float = 0.95):
    try:
        from backend.ingestion.langchain_components import embeddings as lc_embeddings
        query_vector = lc_embeddings.embed_query(question)
    except Exception:
        return None
    try:
        result = supabase.rpc(
            "match_cached_query",
            {
                "query_embedding": query_vector,
                "p_tenant_id": tenant_id,
                "match_threshold": threshold,
            },
        ).execute()
    except Exception:
        return None
    rows = result.data or []
    return rows[0] if rows else None


def store_cache(question: str, tenant_id: str, answer: str, sources: list):
    try:
        from backend.ingestion.langchain_components import embeddings as lc_embeddings
        query_vector = lc_embeddings.embed_query(question)
        supabase.table("query_cache").insert(
            {
                "tenant_id": tenant_id,
                "question": question,
                "embedding": query_vector,
                "answer": answer,
                "sources": sources,
            }
        ).execute()
    except Exception as e:
        logger.warning("Failed to store cache entry: %s", e)


def log_request(tenant_id, user_id, question, cache_hit, model, latency_ms):
    try:
        supabase.table("request_log").insert(
            {
                "tenant_id": tenant_id,
                "user_id": user_id,
                "question": question,
                "cache_hit": cache_hit,
                "model": model,
                "latency_ms": latency_ms,
            }
        ).execute()
    except Exception as e:
        logger.warning("Failed to log request: %s", e)


def is_simple_question(question: str) -> bool:
    """Cheap heuristic router: short, single-fact-looking questions -> small model."""
    q = question.strip().lower()
    word_count = len(q.split())
    complex_signals = ["compare", "difference", "why", "explain", "summarize", "and", "vs"]
    if word_count > 15:
        return False
    if any(sig in q for sig in complex_signals):
        return False
    return True


# 5. Generation
def generate_answer(query: str, context: str) -> str:
    system_prompt = f"""You are an AI document assistant.
Answer the user's question using ONLY the information provided in the context.
Rules:
- Give a clear, complete answer in a natural sentence.
- Do not answer with only a few words when a complete sentence is possible.
- Directly answer what the user asked.
- Do not add information that is not present in the context.
- If the answer is not present in the context, say:
"I could not find the answer in the document."
- Keep the answer concise and easy to understand.
Context:{context}
Question:{query}
Answer:"""
    return _call_llm([{"role": "user", "content": system_prompt}])


def generate_answer_routed(query: str, context: str, use_small_model: bool) -> str:
    system_prompt = f"""You are an AI document assistant.
Answer the user's question using ONLY the information provided in the context.
Rules:
- Give a clear, complete answer in a natural sentence.
- Do not add information that is not present in the context.
- If the answer is not present in the context, say:
"I could not find the answer in the document."
Context:{context}
Question:{query}
Answer:"""
    model = GROQ_MODEL_SMALL if use_small_model else GROQ_MODEL
    return _call_llm_with_model([{"role": "user", "content": system_prompt}], model)


def generate_answer_stream(query: str, context: str):
    system_prompt = f"""You are an AI document assistant.
Answer the user's question using ONLY the information provided in the context.
Rules:
- Give a clear, complete answer in a natural sentence.
- Do not answer with only a few words when a complete sentence is possible.
- Directly answer what the user asked.
- Do not add information that is not present in the context.
- If the answer is not present in the context, say:
"I could not find the answer in the document."
- Keep the answer concise and easy to understand.
Context:{context}
Question:{query}
Answer:"""
    for token in _call_llm_stream([{"role": "user", "content": system_prompt}]):
        yield token


def _sample_text(text: str, max_chars: int = 4000) -> str:
    if len(text) <= max_chars:
        return text
    slice_size = max_chars // 3
    start = text[:slice_size]
    mid_point = len(text) // 2
    middle = text[mid_point - slice_size // 2: mid_point + slice_size // 2]
    end = text[-slice_size:]
    return f"{start}\n...\n{middle}\n...\n{end}"


def generate_faq(text: str, num_questions: int = 4) -> list[dict]:
    excerpt = _sample_text(text, max_chars=4000)
    prompt = f"""You are helping someone quickly understand a company document.
Read the document excerpt below and write {num_questions} short, realistic questions
an employee might ask about it (e.g. policies, procedures, benefits, deadlines),
each with a concise, accurate answer based ONLY on the text.

Respond with ONLY a JSON array, no other text, no markdown code fences, in this exact shape:
[{{"question": "...", "answer": "..."}}, ...]

Document excerpt:{excerpt}
JSON array:"""
    try:
        raw = _call_llm([{"role": "user", "content": prompt}])
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if match:
            raw = match.group(0)
        pairs = json.loads(raw)
        cleaned = [
            {"question": p["question"].strip(), "answer": p["answer"].strip()}
            for p in pairs
            if isinstance(p, dict) and p.get("question") and p.get("answer")
        ]
        return cleaned[:num_questions]
    except Exception as e:
        logger.warning(
            "FAQ generation failed, skipping suggestions: %s | raw response: %r",
            e, locals().get("raw")
        )
        return []

def extract_graph(document_id: str, text: str):
    excerpt = _sample_text(text, max_chars=6000)
    prompt = f"""Extract key entities and relationships from this document excerpt.
Respond with ONLY a JSON object, no other text:
{{"entities": [{{"name": "...", "type": "..."}}],
  "relations": [{{"source": "...", "relation": "...", "target": "..."}}]}}
Keep it to the 10-15 most important entities/relations.
Document excerpt:{excerpt}
JSON:"""
    try:
        raw = _call_llm([{"role": "user", "content": prompt}])
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
        data = json.loads(raw)
        name_to_id = {}
        for e in data.get("entities", []):
            row = supabase.table("entities").insert(
                {"document_id": document_id, "name": e["name"], "type": e.get("type")}
            ).execute().data[0]
            name_to_id[e["name"]] = row["id"]
        for r in data.get("relations", []):
            src, tgt = name_to_id.get(r["source"]), name_to_id.get(r["target"])
            if src and tgt:
                supabase.table("relations").insert(
                    {"document_id": document_id, "source_entity_id": src,
                     "target_entity_id": tgt, "relation": r["relation"]}
                ).execute()
    except Exception as e:
        logger.warning("Graph extraction failed: %s", e)


def expand_graph_context(document_ids: list[str], question: str) -> str:
    if not document_ids:
        return ""
    try:
        rels = (
            supabase.table("relations")
            .select("relation, source_entity_id, target_entity_id")
            .in_("document_id", document_ids)
            .execute().data or []
        )
        ent_ids = {r["source_entity_id"] for r in rels} | {r["target_entity_id"] for r in rels}
        if not ent_ids:
            return ""
        ents = {e["id"]: e["name"] for e in supabase.table("entities").select("id, name").in_("id", list(ent_ids)).execute().data or []}
        facts = [f"{ents.get(r['source_entity_id'],'?')} {r['relation']} {ents.get(r['target_entity_id'],'?')}" for r in rels]
        return "\nRelated facts:\n" + "\n".join(facts[:15])
    except Exception:
        return ""


# Main (CLI) — uses env defaults, matching the /docs testing setup
def ask(query: str) -> str:
    tenant_id = os.environ.get("DEFAULT_TENANT_ID")
    role = os.environ.get("DEFAULT_ROLE", "admin")
    if not tenant_id:
        return "DEFAULT_TENANT_ID is not set in .env — cannot run CLI query."
    results = search_documents(query, tenant_id=tenant_id, role=role)
    if not results:
        return "I could not find the answer in the document."
    context = "\n".join(item["content"] for item in results)
    return generate_answer(query, context)



if __name__ == "__main__":
    try:
        user_query = input("Ask a question about the PDF: ")
        print(ask(user_query))
    except Exception as e:
        logger.error("Something went wrong: %s", e)