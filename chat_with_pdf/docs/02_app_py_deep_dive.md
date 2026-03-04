# Chat with PDF — `app.py` Deep Dive (Flask Backend)

## File Purpose

`app.py` is the **HTTP entry point** for the application. It initializes the Flask server, defines three routes (`/`, `/upload`, `/ask`), and delegates all AI/RAG logic to the `RAGEngine` class.

---

## Imports & Dependencies

```python
import os                                          # Line 5: File path operations
from flask import Flask, render_template, request, jsonify  # Line 6: Flask core
from rag_engine import RAGEngine                   # Line 7: Custom RAG engine
```

| Import | Role |
|--------|------|
| `os` | Build file paths, create directories |
| `Flask` | WSGI application factory |
| `render_template` | Serve Jinja2 HTML templates |
| `request` | Access incoming HTTP request data (files, JSON) |
| `jsonify` | Return JSON HTTP responses |
| `RAGEngine` | Custom class encapsulating the entire RAG pipeline |

---

## Line-by-Line Code Explanation

### Application Setup (Lines 9–18)

```python
app = Flask(__name__)                              # Line 12
```
Creates the Flask application instance. `__name__` tells Flask where to find templates and static files relative to this module.

```python
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")  # Line 14
os.makedirs(UPLOAD_DIR, exist_ok=True)                           # Line 15
```
- Constructs an absolute path to the `uploads/` directory next to `app.py`.
- `exist_ok=True` prevents errors if the directory already exists.

```python
engine = RAGEngine(model_name="llama3.2")          # Line 18
```
Creates a **singleton** `RAGEngine` instance at module level. This means:
- Embeddings model loads **once** at startup (saves ~2–3 seconds per request).
- The same vector store and chain are shared across all requests.
- This is a **single-user design** — appropriate for local/academic use.

---

### Route: `GET /` (Lines 24–27)

```python
@app.route("/")
def index():
    return render_template("index.html")
```
Serves the chat interface. Flask looks for `index.html` in the `templates/` directory.

---

### Route: `POST /upload` (Lines 30–54)

This route handles PDF file uploads with **three-layer validation**:

```python
if "file" not in request.files:                    # Line 33: No file field
    return jsonify({"error": "No file provided."}), 400

file = request.files["file"]
if file.filename == "":                            # Line 37: Empty filename
    return jsonify({"error": "Empty filename."}), 400

if not file.filename.lower().endswith(".pdf"):      # Line 40: Not a PDF
    return jsonify({"error": "Only PDF files are supported."}), 400
```

**Validation Chain:**
1. Check that the HTTP request contains a `file` field.
2. Check that the filename is not empty (browser quirk when no file is selected).
3. Check that the file extension is `.pdf`.

```python
save_path = os.path.join(UPLOAD_DIR, file.filename)  # Line 43
file.save(save_path)                                  # Line 44
```
Saves the uploaded file to disk. This is necessary because `PyPDF2.PdfReader` requires a file path.

```python
try:
    num_chunks = engine.load_pdf(save_path)           # Line 47
    return jsonify({
        "message": f"✅ PDF uploaded and indexed successfully! ({num_chunks} chunks created)",
        "filename": file.filename,
        "chunks": num_chunks,
    })
except Exception as e:
    return jsonify({"error": f"Failed to process PDF: {str(e)}"}), 500
```
- Delegates to `RAGEngine.load_pdf()` which extracts text, chunks it, embeds it, and builds the LCEL chain.
- Returns the chunk count to the frontend for display.
- Wraps in try/except to gracefully handle corrupt PDFs or Ollama connectivity failures.

---

### Route: `POST /ask` (Lines 57–72)

```python
data = request.get_json()                             # Line 60
if not data or "question" not in data:                # Line 61
    return jsonify({"error": "No question provided."}), 400

question = data["question"].strip()                   # Line 64
if not question:                                      # Line 65
    return jsonify({"error": "Question cannot be empty."}), 400
```
Parses JSON body and validates that a non-empty question is present.

```python
try:
    answer = engine.ask(question)                     # Line 69
    return jsonify({"answer": answer})                # Line 70
except Exception as e:
    return jsonify({"error": f"Failed to generate answer: {str(e)}"}), 500
```
- Invokes the LCEL chain (retrieval → prompt → LLM → parse).
- Returns the answer as JSON.

---

### Server Entry Point (Lines 78–79)

```python
if __name__ == "__main__":
    app.run(debug=True, port=5000)
```
- `debug=True` enables auto-reload on code changes and detailed error pages.
- Runs on `http://localhost:5000`.
- The `if __name__` guard ensures the server only starts when run directly, not when imported.

---

## Design Patterns Used

| Pattern | Where | Why |
|---------|-------|-----|
| **Singleton** | `engine = RAGEngine(...)` at module level | Avoid re-loading embedding model per request |
| **Separation of Concerns** | Routes in `app.py`, ML logic in `rag_engine.py` | Clean architecture, testability |
| **Fail-Fast Validation** | Multiple checks before processing | Return clear 400 errors early |
| **Error Boundary** | try/except around engine calls | Prevent 500 crashes from propagating raw tracebacks |
