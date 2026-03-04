# Chat with PDF — Session, Memory, Multi-PDF & Interview Reference

## 1. Session & Memory Architecture

### Current Design: Stateless Single-PDF

The current implementation uses a **stateless, single-PDF** architecture:

```
Server Startup
    └── engine = RAGEngine()   ← singleton, shared across all requests
            ├── vectorstore = None
            └── chain = None

After upload:
    └── engine.vectorstore = Chroma(...)   ← replaced entirely each upload
    └── engine.chain = LCEL(...)           ← rebuilt each upload
```

**Key behaviors:**
- **No conversation memory**: Each `/ask` request is independent — the system has no concept of chat history. Every question is answered using only the retrieved context.
- **No session management**: There is no `session_id`, cookie, or token system. The single `engine` instance is shared.
- **Single-PDF active at a time**: `build_vectorstore()` calls `shutil.rmtree(CHROMA_DIR)` before creating a new store. This means uploading a new PDF **replaces** the previous one entirely.

### Where State Lives

| State | Location | Lifetime |
|-------|----------|----------|
| Uploaded PDF file | `uploads/` directory | Persists on disk until manually deleted |
| Vector embeddings | `chroma_db/` directory | Replaced on each new upload |
| RAG chain | `engine.chain` (Python memory) | Replaced on each new upload |
| UI chat messages | Browser DOM | Lost on page refresh |
| `pdfReady` flag | Browser JS variable | Lost on page refresh |

---

## 2. How Multi-PDF Support Could Be Added

The architecture would need these changes to support multiple PDFs:

```python
# Instead of shutil.rmtree:
def build_vectorstore(self, documents, pdf_id):
    if self.vectorstore is None:
        self.vectorstore = Chroma(
            persist_directory=CHROMA_DIR,
            embedding_function=self.embeddings
        )
    # Add documents with metadata tracking the source PDF
    self.vectorstore.add_documents(
        documents,
        metadatas=[{"source": pdf_id} for _ in documents]
    )
```

This would require:
1. Removing the `shutil.rmtree` call
2. Using `add_documents()` instead of `from_documents()`
3. Tagging chunks with source PDF metadata
4. Optionally, filtering retrieval by source PDF

---

## 3. How Conversation Memory Could Be Added

LangChain provides `ConversationBufferMemory` or `RunnableWithMessageHistory` for chat memory. Integration would look like:

```python
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_community.chat_message_histories import ChatMessageHistory

store = {}

def get_session_history(session_id: str):
    if session_id not in store:
        store[session_id] = ChatMessageHistory()
    return store[session_id]

chain_with_history = RunnableWithMessageHistory(
    self.chain,
    get_session_history,
    input_messages_key="question",
)
```

This would allow follow-up questions like "Tell me more about that" to work.

---

## 4. Dependencies Deep Dive (`requirements.txt`)

```
flask                    → Web framework (routes, templating, file handling)
PyPDF2                   → PDF text extraction (pure Python, no system deps)
langchain                → Core LangChain abstractions (base classes, schema)
langchain-community      → Community integrations (Chroma, HuggingFace)
langchain-ollama         → Ollama LLM integration (ChatOllama)
langchain-huggingface    → HuggingFace model loading utilities
chromadb                 → Vector database (SQLite + DuckDB backend)
sentence-transformers    → HuggingFace sentence embedding models
```

**Dependency graph:**
```
flask ─────────────────────────────────────── Web layer
PyPDF2 ────────────────────────────────────── PDF parsing
sentence-transformers ──┐
langchain-huggingface ──┼── Embedding layer
langchain-community ────┤
chromadb ───────────────┘── Vector storage
langchain ──────────────┐
langchain-ollama ───────┼── LLM + Chain layer
langchain-core ─────────┘
```

---

## 5. Interview Q&A Reference

### Q: What is RAG and why did you use it?
**A**: RAG (Retrieval-Augmented Generation) combines information retrieval with text generation. Instead of relying on the LLM's parametric knowledge (which may hallucinate), we retrieve relevant passages from the uploaded PDF and feed them as context. This grounds the LLM's response in actual document content.

### Q: Walk me through the data flow when a user asks a question.
**A**: The question is embedded into a 384-dim vector using `all-MiniLM-L6-v2`. ChromaDB performs cosine similarity search against all stored chunk vectors, returning the top-8 matches. These chunks are formatted into a prompt with strict instructions, sent to Ollama's `llama3.2` model, and the response is parsed and returned as JSON.

### Q: Why not use OpenAI's API?
**A**: Three reasons: (1) Privacy — user documents never leave the local machine. (2) Cost — Ollama is free. (3) No API key management — reduces deployment complexity for academic projects.

### Q: How do you prevent hallucinations?
**A**: Through the prompt design. The prompt includes strict rules: "Answer ONLY using the provided context", "Do NOT add outside knowledge", and provides a fallback response for questions not answerable from the document. Combined with `temperature=0`, this maximizes faithfulness.

### Q: What happens if the PDF is a scanned image?
**A**: PyPDF2 cannot extract text from scanned/image-based PDFs. `extract_text()` returns empty text, and `load_pdf()` returns 0 chunks. The system would need Tesseract OCR integration (via `pytesseract`) to handle scanned documents.

### Q: Why `RecursiveCharacterTextSplitter` over other splitters?
**A**: It preserves semantic boundaries by attempting splits at paragraph breaks first, then sentences, then words. This produces more meaningful chunks compared to fixed-size splitting, which might cut mid-sentence.

### Q: What is LCEL (LangChain Expression Language)?
**A**: LCEL is LangChain's declarative syntax for composing chains using the `|` pipe operator. It allows building data-flow pipelines where each step (retriever, prompt, LLM, parser) is connected as a Runnable. The `RunnablePassthrough` passes input through unchanged, enabling parallel branches in the chain.

### Q: How would you scale this for production?
**A**: Key changes needed: (1) Add session management with unique user IDs. (2) Use async endpoints (FastAPI). (3) Move ChromaDB to a client-server deployment. (4) Add authentication. (5) Queue long-running embedding tasks. (6) Support multi-PDF with metadata filtering. (7) Add conversation memory for follow-ups.

### Q: What are the limitations of this project?
**A**: (1) Single-user only. (2) No conversation memory — each question is independent. (3) New uploads replace previous PDFs. (4) No OCR for scanned PDFs. (5) Synchronous processing — the server blocks during LLM inference. (6) No streaming — user waits for complete response.
