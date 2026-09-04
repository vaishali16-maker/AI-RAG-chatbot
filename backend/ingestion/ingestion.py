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

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


# Setup
BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be set in your .env file" )
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
co = cohere.Client(os.environ.get("COHERE_API_KEY"))
EMBED_MODEL_NAME = "qwen3.5:4b"
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GROQ_MODEL = "openai/gpt-oss-20b"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


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


def extract_text_from_pdf(file_path: str,skip_structural_pages: bool = True,) -> str:
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
    text = re.sub(r'[\U0001F300-\U0001FAFF\U00002600-\U000027BF]', '', text)
    text = re.sub(r'[•·.]{3,}', ' ', text)
    text = re.sub(r'\s+', ' ', text)
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

# 3. Ingestion (metadata + batch insert)
def ingest_pdf(file_path: str) -> int:
    path = Path(file_path)
    text = extract_text_from_pdf(file_path)
    text = clean_extracted_text(text)
    chunks = chunk_text(text)
    if not chunks:
        raise ValueError(f"'{path.name}' produced no chunks after splitting")
    try:
        response = co.embed(
            texts=chunks,
            model="embed-english-light-v3.0",
            input_type="search_document",
        )
        vectors = response.embeddings
    except Exception as e:
        raise RuntimeError(f"Embedding failed for '{path.name}': {e}") from e
    rows = [
        {
            "content": chunk,
            "embedding": vector,
            "source_file": path.name,
            "chunk_index": idx,
        }
        for idx, (chunk, vector) in enumerate(zip(chunks, vectors))
    ]
    try:
        supabase.table("documents").insert(rows).execute()
    except Exception as e:
        raise RuntimeError(f"Failed to store chunks for '{path.name}': {e}") from e
    logger.info("Ingested '%s': %d chunks stored", path.name, len(chunks))
    return len(chunks)

# 4. Retrieval
def search_documents(query: str, match_count: int = 3, match_threshold: float = 0.15):
    try:
        response = co.embed(
            texts=[query],
            model="embed-english-light-v3.0",
            input_type="search_query",
        )
        query_vector = response.embeddings[0]
    except Exception as e:
        raise RuntimeError(f"Failed to embed query: {e}") from e
    try:
        result = supabase.rpc(
            "match_documents",
            {
                "query_embedding": query_vector,
                "match_threshold": match_threshold,
                "match_count": match_count,
            },
        ).execute()
    except Exception as e:
        raise RuntimeError(f"Vector search failed: {e}") from e
    return result.data or []


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
    prompt = f"""You are helping a salesperson quickly understand a product document.
Read the document excerpt below and write {num_questions} short, realistic questions
a salesperson or customer might ask about it (e.g. pricing, features, policies,
integrations, support), each with a concise, accurate answer based ONLY on the text.

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

# Main (CLI)
def ask(query: str) -> str:
    results = search_documents(query)
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