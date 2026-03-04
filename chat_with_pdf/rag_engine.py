"""
RAG Engine — LangChain 1.x Compatible
This is the AI BRAIN of the application.
RAG = Retrieval-Augmented Generation
It reads PDFs, stores them as vectors, and answers questions using only the PDF content.
"""

# 'os' — for file/folder path operations (checking if folder exists, joining paths)
import os

# 'shutil' — for high-level file operations (we use rmtree to delete entire folders)
import shutil

# 'PdfReader' from PyPDF2 — reads PDF files and extracts text from each page
from PyPDF2 import PdfReader

# 'RecursiveCharacterTextSplitter' — splits long text into smaller chunks
# It tries to split at natural boundaries (paragraphs, sentences, words) to keep chunks meaningful
from langchain_text_splitters import RecursiveCharacterTextSplitter

# 'HuggingFaceEmbeddings' — wrapper to use HuggingFace embedding models
# Embedding models convert text into numerical vectors (lists of numbers)
# Similar texts produce similar vectors — this enables "semantic search"
from langchain_community.embeddings import HuggingFaceEmbeddings

# 'Chroma' — LangChain wrapper for ChromaDB, a vector database
# It stores text chunks alongside their vector representations
# and lets you search for chunks that are semantically similar to a query
from langchain_community.vectorstores import Chroma

# 'ChatOllama' — LangChain wrapper for Ollama LLMs
# Ollama runs LLMs (like llama3.2) locally on your computer
# ChatOllama lets us use these local models through LangChain
from langchain_ollama import ChatOllama

# 'ChatPromptTemplate' — creates reusable prompt templates
# Templates have placeholders (like {context} and {question}) that get filled in at runtime
from langchain_core.prompts import ChatPromptTemplate

# 'RunnablePassthrough' — passes input through unchanged
# Used in the chain to forward the user's question directly to the prompt template
from langchain_core.runnables import RunnablePassthrough

# 'StrOutputParser' — extracts just the text string from the LLM's response object
# Without this, we'd get a complex object instead of a simple string
from langchain_core.output_parsers import StrOutputParser


# Define the path where ChromaDB will store its data files
# This creates a path like "D:\MLDL\DL\chat_with_pdf\chroma_db"
CHROMA_DIR = os.path.join(os.path.dirname(__file__), "chroma_db")


# The main RAGEngine class — this is the core of the entire application
class RAGEngine:

    # Constructor — called when we create a new RAGEngine instance
    # model_name parameter lets us choose which Ollama model to use (default: llama3.2)
    def __init__(self, model_name: str = "llama3.2"):

        # Initialize the EMBEDDING MODEL
        # "all-MiniLM-L6-v2" is a fast, lightweight model that converts text → 384-dimensional vectors
        # This model runs locally using sentence-transformers library
        # It is used TWICE: once to embed PDF chunks (during upload), once to embed questions (during ask)
        self.embeddings = HuggingFaceEmbeddings(
            model_name="all-MiniLM-L6-v2"
        )

        # Initialize the LLM (Large Language Model)
        # ChatOllama connects to the Ollama server running on your machine
        # model="llama3.2" — the specific model to use (must be downloaded via 'ollama pull llama3.2')
        # temperature=0 — makes output deterministic (no randomness)
        #   temperature=0 means the model always picks the most likely next word
        #   temperature=1 would mean more creative/random responses
        self.llm = ChatOllama(
            model=model_name,
            temperature=0
        )

        # These will be set later when a PDF is uploaded
        # vectorstore — the ChromaDB instance holding all the indexed chunks
        self.vectorstore = None
        # chain — the LangChain pipeline (retriever → prompt → LLM → parser)
        self.chain = None

    # --------------------------------------------------
    # STEP 1: Extract text from a PDF file
    # --------------------------------------------------

    # @staticmethod means this method doesn't need access to 'self' (the instance)
    # It's a utility function that just takes a file path and returns text
    @staticmethod
    def extract_text(pdf_path: str) -> str:
        # Create a PdfReader object that opens and reads the PDF file
        reader = PdfReader(pdf_path)

        # List to collect text from each page
        pages = []

        # Loop through every page in the PDF
        for page in reader.pages:
            # Extract the text content from this page
            # Returns None if the page has no extractable text (e.g., scanned images)
            content = page.extract_text()

            # Only add non-empty pages
            if content:
                pages.append(content)

        # Join all pages' text with newline separator and return as one big string
        return "\n".join(pages)

    # --------------------------------------------------
    # STEP 2: Split the full text into smaller chunks
    # --------------------------------------------------

    # Another static utility method — doesn't need 'self'
    @staticmethod
    def chunk_text(text: str, chunk_size=500, chunk_overlap=50):
        # Create a text splitter that breaks text into chunks
        # chunk_size=500 — each chunk will be approximately 500 characters long
        # chunk_overlap=50 — consecutive chunks share 50 characters of overlap
        #   WHY OVERLAP? If a sentence falls on a chunk boundary, both chunks will
        #   contain the full sentence, so we don't lose context
        # RecursiveCharacterTextSplitter tries to split at:
        #   1. Paragraph breaks (\n\n)  2. Line breaks (\n)  3. Spaces  4. Characters
        #   It picks the largest natural boundary that keeps chunks under the size limit
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap
        )

        # create_documents() takes a list of texts and returns a list of LangChain Document objects
        # Each Document has .page_content (the text) and .metadata (empty here)
        return splitter.create_documents([text])

    # --------------------------------------------------
    # STEP 3: Convert chunks to vectors and store in ChromaDB
    # --------------------------------------------------
    def build_vectorstore(self, documents):

        # WINDOWS FIX: Instead of deleting the chroma_db folder and recreating it,
        # we REUSE the existing ChromaDB and just clear + re-add documents.
        #
        # WHY? On Windows, ChromaDB (which uses SQLite + HNSW files internally)
        # keeps file handles open. If we try to delete the folder with shutil.rmtree(),
        # Windows throws: [WinError 32] The process cannot access the file because
        # it is being used by another process.
        #
        # SOLUTION: Never delete the folder. Instead:
        #   1. If a vectorstore already exists → clear all its documents
        #   2. If no vectorstore exists → create a new one
        # This way the ChromaDB files stay in place and no file locks are violated.

        if self.vectorstore is not None:
            # CLEAR the existing collection — remove all old documents
            # WHY? We want each PDF upload to start fresh, not mix old + new chunks.
            # .get() returns all document IDs, then .delete() removes them.
            try:
                existing = self.vectorstore.get()
                if existing["ids"]:
                    self.vectorstore.delete(ids=existing["ids"])
            except Exception:
                pass

            # ADD the new documents to the now-empty collection
            self.vectorstore.add_documents(documents)
        else:
            # First time — no vectorstore exists yet
            # Check if a chroma_db folder exists from a previous server run
            if os.path.exists(CHROMA_DIR):
                # Connect to the existing ChromaDB on disk, clear it, and add new docs
                self.vectorstore = Chroma(
                    persist_directory=CHROMA_DIR,
                    embedding_function=self.embeddings,
                )
                try:
                    existing = self.vectorstore.get()
                    if existing["ids"]:
                        self.vectorstore.delete(ids=existing["ids"])
                except Exception:
                    pass
                self.vectorstore.add_documents(documents)
            else:
                # Create a brand new ChromaDB vector store from scratch
                # What happens internally:
                #   1. Each document's text is passed through self.embeddings (all-MiniLM-L6-v2)
                #   2. Each text chunk is converted to a 384-dimensional vector
                #   3. Both the original text AND its vector are stored in ChromaDB
                #   4. The data is saved to disk at CHROMA_DIR so it persists between restarts
                self.vectorstore = Chroma.from_documents(
                    documents=documents,        # The list of text chunks to index
                    embedding=self.embeddings,   # The embedding model to convert text → vectors
                    persist_directory=CHROMA_DIR, # Where to save the database files on disk
                )

    # --------------------------------------------------
    # STEP 4: Build the RAG chain (the full question-answering pipeline)
    # --------------------------------------------------
    def _build_chain(self):

        # Create a RETRIEVER from the vector store
        # A retriever takes a query, converts it to a vector, and finds similar chunks
        # search_kwargs={"k": 8} means "return the top 8 most similar chunks"
        # More chunks = more context for the LLM, but also more noise
        retriever = self.vectorstore.as_retriever(search_kwargs={"k": 8})

        # Create the PROMPT TEMPLATE
        # This is the instruction we send to the LLM along with the context and question
        # {context} will be replaced with the retrieved chunks
        # {question} will be replaced with the user's question
        # The strict rules prevent the LLM from making up answers (hallucinating)
        prompt = ChatPromptTemplate.from_template(
    """You must answer ONLY using the provided context.

STRICT RULES:
1. Do NOT add any outside knowledge.
2. Do NOT explain beyond what is written.
3. If information is not explicitly written, respond:
   "The answer is not available in the uploaded document."
4. Answer using only sentences found in the context.

Context:
{context}

Question:
{question}

Answer:""")

        # Helper function to format retrieved documents into a single string
        # Takes a list of Document objects and joins their text with double newlines
        def format_docs(docs):
            return "\n\n".join(doc.page_content for doc in docs)

        # BUILD THE CHAIN — this is the core LangChain pipeline
        # The chain works like a data processing pipeline:
        #
        # Input: a question string (e.g., "What is machine learning?")
        #
        # Step 1: Create a dict with two keys:
        #   "context": retriever | format_docs
        #     → The question goes into the retriever
        #     → Retriever finds top 8 similar chunks from ChromaDB
        #     → format_docs joins them into one string
        #   "question": RunnablePassthrough()
        #     → The question passes through unchanged
        #
        # Step 2: | prompt
        #   → The dict fills the template: {context} gets the chunks, {question} gets the question
        #   → Result: a complete prompt string ready for the LLM
        #
        # Step 3: | self.llm
        #   → The prompt is sent to Ollama's llama3.2 model
        #   → The LLM generates a response
        #
        # Step 4: | StrOutputParser()
        #   → Extracts the plain text string from the LLM's response object
        #
        # Final output: a string answer like "Machine learning is a subset of AI that..."
        self.chain = (
            {
                "context": retriever | format_docs,
                "question": RunnablePassthrough(),
            }
            | prompt
            | self.llm
            | StrOutputParser()
        )

    # --------------------------------------------------
    # PUBLIC API — these methods are called by app.py
    # --------------------------------------------------

    # Called when a user uploads a PDF
    # Orchestrates the entire indexing pipeline: extract → chunk → store → build chain
    def load_pdf(self, pdf_path: str):

        # Step 1: Extract all text from the PDF
        text = self.extract_text(pdf_path)

        # If the PDF has no extractable text (e.g., scanned images only), return 0
        if not text.strip():
            return 0

        # Step 2: Split the text into chunks
        docs = self.chunk_text(text)

        # Step 3: Create embeddings and store in ChromaDB
        self.build_vectorstore(docs)

        # Step 4: Build the LangChain question-answering chain
        self._build_chain()

        # Return the number of chunks created (shown to the user in the UI)
        return len(docs)

    # Called when a user asks a question
    def ask(self, question: str):

        # If no PDF has been uploaded yet, the chain is None
        # Return a helpful message instead of crashing
        if self.chain is None:
            return "Please upload a PDF first."

        # Run the entire chain:
        # question → retriever finds chunks → prompt template → LLM generates → parser extracts text
        # Returns the final answer string
        return self.chain.invoke(question)