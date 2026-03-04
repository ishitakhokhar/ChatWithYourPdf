"""
Flask application — Chat with PDF.
This is the MAIN ENTRY POINT of the project.
It creates a web server that serves the chat UI and handles PDF uploads + questions.

WHAT CHANGED (Chat History Feature):
  - Imported chat_store module for database operations.
  - Added init_db() call at startup to create tables.
  - Added 5 new API routes for chat CRUD operations.
  - Modified /upload to accept chat_id and associate PDFs with chats.
  - Modified /ask to accept chat_id and save Q&A to the database.
"""

# 'os' module — used for file path operations (joining paths, creating folders)
import os

# 'Flask' — the web framework that creates our web server
# 'render_template' — loads and returns HTML files from the 'templates/' folder
# 'request' — gives access to incoming HTTP request data (uploaded files, JSON body)
# 'jsonify' — converts Python dicts into JSON responses to send back to the browser
from flask import Flask, render_template, request, jsonify

# Import our custom RAGEngine class from rag_engine.py
# This is the AI brain that processes PDFs and answers questions
from rag_engine import RAGEngine

# Import the chat_store module — handles all database operations
# WHY a separate module? Keeps database logic isolated from HTTP routing logic.
# This follows the Single Responsibility Principle — app.py handles HTTP, chat_store handles data.
import chat_store

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

# Create a Flask application instance
# __name__ tells Flask where to find templates and static files relative to this file
app = Flask(__name__)

# Define the folder path where uploaded PDFs will be saved
# os.path.dirname(__file__) = the folder where app.py is located
# os.path.join(..., "uploads") = creates the path like "D:\MLDL\DL\chat_with_pdf\uploads"
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")

# Create the uploads folder if it doesn't already exist
# exist_ok=True means don't throw an error if the folder already exists
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Create a single instance of the RAG engine using the llama3.2 model
# This object lives in memory for the entire lifetime of the server
# It holds the embedding model, the LLM, the vector store, and the chain
engine = RAGEngine(model_name="llama3.2")

# Initialize the chat database — creates tables if they don't exist yet
# WHY call this at startup?
#   - Ensures the database is ready before any request comes in.
#   - Uses "CREATE TABLE IF NOT EXISTS" — safe to call multiple times.
#   - The first run creates chat_history.db; subsequent runs do nothing.
chat_store.init_db()


# ---------------------------------------------------------------------------
# Routes — these define what happens when a user visits a URL
# ---------------------------------------------------------------------------

# ROUTE 1: GET / — When someone opens http://localhost:5000 in their browser
# This serves the main chat page
@app.route("/")
def index():
    """Serve the chat UI."""
    # Looks for 'index.html' inside the 'templates/' folder and returns it
    return render_template("index.html")


# ---------------------------------------------------------------------------
# Chat API Routes — NEW (for chat history feature)
# ---------------------------------------------------------------------------

# ROUTE: GET /chats — Return all chats for the sidebar
# WHY? The sidebar needs to display a list of all past conversations
# when the page loads. This endpoint provides that data.
@app.route("/chats", methods=["GET"])
def list_chats():
    """Return all chats, newest first."""
    chats = chat_store.get_all_chats()
    return jsonify(chats)


# ROUTE: POST /chats/new — Create a new empty chat
# WHY? When the user clicks "+ New Chat", we need to create a database
# record FIRST so we have a chat_id to associate messages with.
# The chat starts with title "New Chat" and gets renamed after the first question.
@app.route("/chats/new", methods=["POST"])
def new_chat():
    """Create a new chat and return its data."""
    chat = chat_store.create_chat()
    return jsonify(chat)


# ROUTE: GET /chats/<chat_id> — Return all messages for a specific chat
# WHY? When the user clicks on a chat in the sidebar, we need to load
# all its messages to display in the chat area.
# The <chat_id> part is a URL parameter — Flask extracts it automatically.
@app.route("/chats/<chat_id>", methods=["GET"])
def get_chat(chat_id):
    """Return all messages for a chat."""
    messages = chat_store.get_messages(chat_id)
    return jsonify(messages)


# ROUTE: DELETE /chats/<chat_id> — Delete a chat and all its messages
# WHY DELETE method? Following REST conventions:
#   GET = read, POST = create, DELETE = remove
# This makes the API predictable and standard.
@app.route("/chats/<chat_id>", methods=["DELETE"])
def delete_chat(chat_id):
    """Delete a chat and all its messages."""
    chat_store.delete_chat(chat_id)
    return jsonify({"message": "Chat deleted"})


# ---------------------------------------------------------------------------
# PDF Upload Route — MODIFIED to support chat_id
# ---------------------------------------------------------------------------

# ROUTE: POST /upload — When the browser sends a PDF file
# WHAT CHANGED: Now accepts an optional 'chat_id' form field.
# If provided, the PDF filename is associated with that chat in the database.
@app.route("/upload", methods=["POST"])
def upload_pdf():
    """Accept a PDF, build the vector store, and return status."""

    # Check if the request contains a file with the key "file"
    # If not, the user didn't attach any file — return an error
    if "file" not in request.files:
        return jsonify({"error": "No file provided."}), 400

    # Get the actual file object from the request
    file = request.files["file"]

    # Check if the filename is empty (can happen with some browsers)
    if file.filename == "":
        return jsonify({"error": "Empty filename."}), 400

    # Only allow PDF files — reject anything else
    if not file.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Only PDF files are supported."}), 400

    # Build the full path where we'll save the file
    # Example: "D:\MLDL\DL\chat_with_pdf\uploads\myfile.pdf"
    save_path = os.path.join(UPLOAD_DIR, file.filename)

    # Save the uploaded file to disk
    file.save(save_path)

    try:
        # Call the RAG engine to:
        # 1. Extract text from the PDF
        # 2. Split it into chunks
        # 3. Create embeddings and store in ChromaDB
        # 4. Build the LangChain pipeline
        # Returns the number of chunks created
        num_chunks = engine.load_pdf(save_path)

        # NEW: Associate the PDF with the current chat (if chat_id was provided)
        # WHY? So the sidebar can show which PDF each chat is using.
        # The chat_id comes from a hidden form field sent by the frontend.
        chat_id = request.form.get("chat_id")
        if chat_id:
            chat_store.update_chat_pdf(chat_id, file.filename)

        # Return a success response with details about the processed PDF
        return jsonify({
            "message": f"✅ PDF uploaded and indexed successfully! ({num_chunks} chunks created)",
            "filename": file.filename,
            "chunks": num_chunks,
        })
    except Exception as e:
        # If anything goes wrong during processing, return the error message
        return jsonify({"error": f"Failed to process PDF: {str(e)}"}), 500


# ---------------------------------------------------------------------------
# Ask Route — MODIFIED to save messages to database
# ---------------------------------------------------------------------------

# ROUTE: POST /ask — When the browser sends a question
# WHAT CHANGED: Now accepts 'chat_id' in the JSON body.
# Both the question and answer are saved to the database.
@app.route("/ask", methods=["POST"])
def ask_question():
    """Accept a question and return the RAG-generated answer."""

    # Parse the JSON body from the request (e.g., {"question": "What is AI?", "chat_id": "abc123"})
    data = request.get_json()

    # Validate that the request contains a "question" field
    if not data or "question" not in data:
        return jsonify({"error": "No question provided."}), 400

    # Extract the question text and remove leading/trailing whitespace
    question = data["question"].strip()

    # Don't allow empty questions
    if not question:
        return jsonify({"error": "Question cannot be empty."}), 400

    # NEW: Get the chat_id from the request body
    # WHY? We need to know which chat this Q&A belongs to so we can save it.
    chat_id = data.get("chat_id")

    try:
        # Pass the question to the RAG engine
        # The engine will: retrieve relevant chunks → build prompt → call LLM → return answer
        answer = engine.ask(question)

        # NEW: Save both the question and answer to the database
        # WHY save both? When the user switches back to this chat later,
        # we need to reconstruct the full conversation (both sides).
        if chat_id:
            # Save the user's question
            chat_store.add_message(chat_id, "user", question)
            # Save the AI's answer
            chat_store.add_message(chat_id, "assistant", answer)

            # Auto-title: If this is the first message, update the chat title
            # WHY? "New Chat" is a meaningless default. Using the first question
            # as the title (truncated to 35 chars) gives users a preview of what
            # each conversation is about — just like ChatGPT does.
            messages = chat_store.get_messages(chat_id)
            if len(messages) <= 2:  # First Q&A pair (user + assistant = 2 messages)
                title = question[:35] + ("..." if len(question) > 35 else "")
                chat_store.update_chat_title(chat_id, title)

        # Return the answer as JSON
        return jsonify({"answer": answer})
    except Exception as e:
        # If the LLM or retrieval fails, return the error
        return jsonify({"error": f"Failed to generate answer: {str(e)}"}), 500


# ---------------------------------------------------------------------------
# Run — this block only executes when you run "python app.py" directly
# ---------------------------------------------------------------------------

# __name__ == "__main__" ensures this only runs when app.py is executed directly,
# not when it's imported as a module by another file
if __name__ == "__main__":
    # Start the Flask development server
    # debug=True — auto-reloads when you change code, shows detailed error pages
    # port=5000 — the server listens on http://localhost:5000
    app.run(debug=True, port=5000)
