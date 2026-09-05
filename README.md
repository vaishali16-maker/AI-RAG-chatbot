# AI RAG Chatbot

A Retrieval-Augmented Generation (RAG) chatbot built for sales teams — upload 
product spec sheets, pricing docs, or policy PDFs and get grounded, cited answers 
to pricing, feature, and policy questions instead of digging through documents manually.

**Live demo:** https://vaishali16-maker.github.io/AI-RAG-chatbot/ 
                

## How it works
1. Upload a PDF — text is extracted, cleaned, and split into overlapping chunks
2. Each chunk is embedded using Cohere's embeddings API and stored in Supabase (pgvector)
3. On a question, the query is embedded and matched against stored chunks via vector similarity search
4. Matched chunks are passed as context to an LLM (via Groq) to generate a grounded answer
5. Answers include the cited source chunk(s) and similarity score, so users can verify against the original text

### Tested Capabilities
Beyond basic Q&A, this system has been validated against harder query types:
- **Multi-fact reasoning**: correctly computes derived values (e.g. discounted 
  per-seat pricing) by combining multiple facts from the document
- **Cross-section synthesis**: connects related information from different 
  parts of a document (e.g. security certification + deployment options)
- **Hallucination resistance**: correctly declines to answer when information 
  isn't present in the document, rather than guessing
- **Policy edge-case reasoning**: compares dates/numbers against stated rules 
  (e.g. refund eligibility based on cancellation timing)

  ### Limitations & Next Steps
- Currently single-PDF per session — multi-document support planned
- No conversation memory yet — each question is independent
- Cold start (~50s) on Render free tier for the first request after inactivity
- Re-uploading the same file now correctly replaces old chunks instead of 
  duplicating them (fixed after discovering duplicate chunks were degrading 
  retrieval quality during testing)

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