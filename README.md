# AI RAG Chatbot

A Retrieval-Augmented Generation (RAG) chatbot that lets users upload a PDF and ask questions about it, with answers grounded in and cited from the actual document content.

**Live demo:** https://vaishali16-maker.github.io/AI-RAG-chatbot/

## How it works
1. Upload a PDF — text is extracted, cleaned, and split into overlapping chunks
2. Each chunk is embedded using Cohere's embeddings API and stored in Supabase (pgvector)
3. On a question, the query is embedded and matched against stored chunks via vector similarity search
4. Matched chunks are passed as context to an LLM (via Groq) to generate a grounded answer
5. Answers include the cited source chunk(s) and similarity score, so users can verify against the original text

## Stack
- **Backend:** FastAPI (Python)
- **Embeddings:** Cohere (`embed-english-light-v3.0`)
- **Vector store:** Supabase (pgvector)
- **LLM:** Groq (`openai/gpt-oss-20b`)
- **Frontend:** Static HTML/JS, hosted on GitHub Pages
- **Deployment:** Render (backend, free tier)

## Notes
- The backend runs on Render's free tier, which spins down after inactivity — the first request after idle time may take up to ~50 seconds to respond.
- Retrieval uses cosine similarity; the percentage shown next to each cited passage is the raw similarity score, not a fixed 0-100 confidence scale.

## Local setup

```bash
git clone https://github.com/vaishali16-maker/AI-RAG-chatbot.git
cd AI-RAG-chatbot
pip install -r backend/requirements.txt
```

Create a `.env` file in the project root with:

```
SUPABASE_URL=
SUPABASE_KEY=
COHERE_API_KEY=
GROQ_API_KEY=
```

Run the backend:

```bash
uvicorn backend.main:app --reload
```

Open `docs/index.html` in a browser (update `API_URL` in the script to `http://127.0.0.1:8000` for local testing).