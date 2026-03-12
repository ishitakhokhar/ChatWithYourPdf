"""
Flask app — main entry point for Chat with PDF.
Serves the chat UI, handles PDF uploads, and answers questions.

Chat history additions:
  - Hooked up chat_store for persistence (SQLite).
  - init_db() runs at startup so the tables are ready.
  - 5 new API routes for chat CRUD.
  - /upload and /ask now accept chat_id to tie things together.
"""

# we need os to work with file paths and create directories
import os

# Flask powers our web server; render_template serves HTML, request grabs incoming data, jsonify sends back JSON
from flask import Flask, render_template, request, jsonify

# our RAG pipeline — reads PDFs, builds vectors, answers questions
from rag_engine import RAGEngine

# chat persistence — keeps DB logic out of the routing layer
import chat_store

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

# create the Flask app instance — this is what Flask uses to register routes and serve requests
app = Flask(__name__)

# where uploaded PDFs get saved on disk — __file__ anchors it to wherever this script lives
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")

# create the uploads folder if it doesn't exist yet — exist_ok prevents crashing if it's already there
os.makedirs(UPLOAD_DIR, exist_ok=True)

# one RAG engine instance shared across all requests — avoids reloading the model on every call
engine = RAGEngine(model_name="llama3.2")

# make sure the DB tables exist before any requests come in — runs once at startup
chat_store.init_db()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

# root route — when someone visits "/", show them the chat page
@app.route("/")
def index():
    """Serve the chat UI."""
    # renders the Jinja2 template and sends back the full HTML page
    return render_template("index.html")


# ---------------------------------------------------------------------------
# Chat API (for the sidebar / history feature)
# ---------------------------------------------------------------------------

# list all chats — the sidebar calls this on page load
@app.route("/chats", methods=["GET"])
def list_chats():
    """Return all chats, newest first."""
    # pull every chat from the DB — they come back sorted by creation date
    chats = chat_store.get_all_chats()
    # convert the list to JSON so JavaScript can consume it
    return jsonify(chats)


# create a new empty chat — triggered by the "+" button
# we need the chat_id upfront so messages have somewhere to live
@app.route("/chats/new", methods=["POST"])
def new_chat():
    """Create a new chat and return its data."""
    # inserts a row in SQLite and gives us back the chat dict with id, title, etc.
    chat = chat_store.create_chat()
    # send the new chat data back so the frontend can add it to the sidebar
    return jsonify(chat)


# load all messages for one chat — used when clicking a sidebar item
@app.route("/chats/<chat_id>", methods=["GET"])
def get_chat(chat_id):
    """Return all messages for a chat."""
    # fetches messages in chronological order so they display correctly
    messages = chat_store.get_messages(chat_id)
    # send them back as a JSON array
    return jsonify(messages)


# delete a chat and its messages — follows REST conventions (DELETE = remove)
@app.route("/chats/<chat_id>", methods=["DELETE"])
def delete_chat(chat_id):
    """Delete a chat and all its messages."""
    # removes the chat row — cascade delete in the DB handles the messages automatically
    chat_store.delete_chat(chat_id)
    # confirm the deletion with a simple message
    return jsonify({"message": "Chat deleted"})


# ---------------------------------------------------------------------------
# PDF Upload
# ---------------------------------------------------------------------------

# handles PDF file uploads — POST because we're sending binary data
@app.route("/upload", methods=["POST"])
def upload_pdf():
    """Accept a PDF, build the vector store, and return status."""

    # basic validation — make sure we actually received a file in the request
    if "file" not in request.files:
        return jsonify({"error": "No file provided."}), 400

    # grab the uploaded file object from the request
    file = request.files["file"]

    # catch edge case where file input was submitted but no file was selected
    if file.filename == "":
        return jsonify({"error": "Empty filename."}), 400

    # only PDFs — we don't want users uploading Word docs or images by mistake
    if not file.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Only PDF files are supported."}), 400

    # build the full path where we'll save the file on disk
    save_path = os.path.join(UPLOAD_DIR, file.filename)

    # write the uploaded file to the uploads directory
    file.save(save_path)

    try:
        # extract text → chunk → embed → build RAG chain — the heavy lifting happens here
        num_chunks = engine.load_pdf(save_path)

        # link this PDF to the current chat so the sidebar can show which PDF each chat uses
        chat_id = request.form.get("chat_id")

        # only update if we actually have a chat_id — uploads without a chat are still valid
        if chat_id:
            chat_store.update_chat_pdf(chat_id, file.filename)

        # send back a success response with the filename and chunk count for the UI
        return jsonify({
            "message": f"✅ PDF uploaded and indexed successfully! ({num_chunks} chunks created)",
            "filename": file.filename,
            "chunks": num_chunks,
        })
    except Exception as e:
        # something went wrong during processing — return the error so the user knows what happened
        return jsonify({"error": f"Failed to process PDF: {str(e)}"}), 500


# ---------------------------------------------------------------------------
# Ask a question
# ---------------------------------------------------------------------------

# handles question submissions — POST because we're sending a JSON body
@app.route("/ask", methods=["POST"])
def ask_question():
    """Accept a question and return the RAG-generated answer."""

    # parse the incoming JSON body from the request
    data = request.get_json()

    # make sure the request included a question field
    if not data or "question" not in data:
        return jsonify({"error": "No question provided."}), 400

    # clean up whitespace — users sometimes accidentally add leading/trailing spaces
    question = data["question"].strip()

    # don't process empty strings — strip() might have removed everything
    if not question:
        return jsonify({"error": "Question cannot be empty."}), 400

    # grab the chat_id if provided — it's optional for standalone questions
    chat_id = data.get("chat_id")

    try:
        # retrieve relevant chunks → fill prompt → ask LLM → get answer
        answer = engine.ask(question)

        # persist both sides of the conversation so we can reload it later
        if chat_id:
            # save the user's question to the DB
            chat_store.add_message(chat_id, "user", question)
            # save the AI's response right after — keeps them paired together
            chat_store.add_message(chat_id, "assistant", answer)

            # auto-title: use the first question as the chat name (like ChatGPT does)
            messages = chat_store.get_messages(chat_id)

            # only set the title on the first exchange — 2 messages = 1 Q&A pair
            if len(messages) <= 2:
                # truncate long questions so the sidebar doesn't overflow
                title = question[:35] + ("..." if len(question) > 35 else "")
                chat_store.update_chat_title(chat_id, title)

        # send the answer back to the frontend
        return jsonify({"answer": answer})
    except Exception as e:
        # catch-all for any LLM or retrieval errors
        return jsonify({"error": f"Failed to generate answer: {str(e)}"}), 500


# ---------------------------------------------------------------------------
# Run the dev server
# ---------------------------------------------------------------------------

# this block only runs when you execute the file directly (not when imported)
if __name__ == "__main__":
    # debug=True gives auto-reload + detailed error pages during development
    app.run(debug=True, port=5000)
