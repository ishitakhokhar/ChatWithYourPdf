"""
RAG Engine — the AI brain of the app.
Reads PDFs, stores them as vectors, and answers questions using only the PDF content.
Built on LangChain 1.x.
"""

# os gives us file path utilities for locating the chroma_db folder
import os

# shutil provides high-level file operations — used for clearing directories if needed
import shutil

# PdfReader extracts raw text from PDF files page by page
from PyPDF2 import PdfReader

# RecursiveCharacterTextSplitter breaks long text into smaller overlapping chunks for embedding
from langchain_text_splitters import RecursiveCharacterTextSplitter

# HuggingFaceEmbeddings converts text chunks into numerical vectors for similarity search
from langchain_community.embeddings import HuggingFaceEmbeddings

# Chroma is our vector database — stores embeddings on disk and handles similarity queries
from langchain_community.vectorstores import Chroma

# ChatOllama connects to a locally-running Ollama LLM for generating answers
from langchain_ollama import ChatOllama

# ChatPromptTemplate lets us build a structured prompt with placeholders for context and question
from langchain_core.prompts import ChatPromptTemplate

# RunnablePassthrough passes the user's question straight through without transformation
from langchain_core.runnables import RunnablePassthrough

# StrOutputParser pulls the plain text string out of the LLM's response object
from langchain_core.output_parsers import StrOutputParser

# chroma's on-disk storage — sits alongside the source code so everything stays in one project folder
CHROMA_DIR = os.path.join(os.path.dirname(__file__), "chroma_db")


class RAGEngine:

    def __init__(self, model_name: str = "llama3.2"):

        # MiniLM is small and fast — good enough for semantic search in a local app
        self.embeddings = HuggingFaceEmbeddings(
            model_name="all-MiniLM-L6-v2"
        )

        # temperature=0 keeps answers consistent and deterministic — no creative hallucinations
        self.llm = ChatOllama(
            model=model_name,
            temperature=0
        )

        # will hold the Chroma vector store once a PDF is loaded
        self.vectorstore = None

        # will hold the full RAG chain (retriever → prompt → LLM → parser) once built
        self.chain = None

    # --- pull text out of a PDF ---

    @staticmethod
    def extract_text(pdf_path: str) -> str:
        # open the PDF file and create a reader to iterate over its pages
        reader = PdfReader(pdf_path)

        # we'll collect each page's text in this list
        pages = []

        # loop through every page in the PDF
        for page in reader.pages:
            # extract the text content from this page
            content = page.extract_text()

            # only keep pages that actually have text — some PDFs have blank or image-only pages
            if content:
                pages.append(content)

        # join all pages with newlines into one big string for chunking
        return "\n".join(pages)

    # --- split text into smaller pieces for embedding ---

    @staticmethod
    def chunk_text(text: str, chunk_size=500, chunk_overlap=50):
        # overlap prevents cutting a sentence right in the middle — nearby chunks share boundary text
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap
        )

        # turn the raw text into LangChain Document objects, each containing one chunk
        return splitter.create_documents([text])

    # --- embed chunks and store them in ChromaDB ---

    def build_vectorstore(self, documents):
        # on Windows the sqlite/hnsw files stay locked while the process runs,
        # so we can't just delete and recreate the folder — clear in-place instead

        # if we already have a vectorstore from a previous upload in this session
        if self.vectorstore is not None:
            # wipe old docs so each upload starts fresh — avoids mixing content from different PDFs
            try:
                # get the IDs of all existing documents in the store
                existing = self.vectorstore.get()

                # only delete if there are actually documents to remove
                if existing["ids"]:
                    self.vectorstore.delete(ids=existing["ids"])
            except Exception:
                # if deletion fails for any reason, just keep going — the new docs will still get added
                pass

            # add the new chunks to the now-empty vectorstore
            self.vectorstore.add_documents(documents)
        else:
            # no vectorstore in memory yet — check if there's one left over on disk from a previous run
            if os.path.exists(CHROMA_DIR):
                # folder from a previous run — reuse it instead of creating from scratch
                self.vectorstore = Chroma(
                    persist_directory=CHROMA_DIR,
                    embedding_function=self.embeddings,
                )

                # clean out the old data so we start fresh with the new PDF
                try:
                    # get all existing document IDs
                    existing = self.vectorstore.get()

                    # delete them if any exist
                    if existing["ids"]:
                        self.vectorstore.delete(ids=existing["ids"])
                except Exception:
                    # same as above — if cleanup fails, just continue
                    pass

                # now add the new chunks to the cleaned-up store
                self.vectorstore.add_documents(documents)
            else:
                # first time ever — create a brand new Chroma vectorstore from the documents
                self.vectorstore = Chroma.from_documents(
                    documents=documents,
                    embedding=self.embeddings,
                    persist_directory=CHROMA_DIR,
                )

    # --- wire up the full RAG chain ---

    def _build_chain(self):
        # top 8 chunks gives a good balance between context coverage and noise — too many dilutes relevance
        retriever = self.vectorstore.as_retriever(search_kwargs={"k": 8})

        # strict prompt — keeps the model from making stuff up or adding outside knowledge
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

        def format_docs(docs):
            # take the list of retrieved Document objects and join their text with double newlines
            return "\n\n".join(doc.page_content for doc in docs)

        # build the chain: question → find relevant chunks → fill prompt template → ask LLM → extract text
        self.chain = (
            {
                # retriever fetches similar chunks, then format_docs joins them into a single string
                "context": retriever | format_docs,
                # pass the original question straight through to fill the {question} placeholder
                "question": RunnablePassthrough(),
            }
            # pipe the filled-in dict into the prompt template
            | prompt
            # send the formatted prompt to the LLM for a response
            | self.llm
            # pull out just the text string from the LLM's response object
            | StrOutputParser()
        )

    # --- public API used by app.py ---

    def load_pdf(self, pdf_path: str):
        """Full pipeline: extract → chunk → embed → build chain."""
        # step 1: pull raw text from every page of the PDF
        text = self.extract_text(pdf_path)

        # if the PDF had no extractable text (scanned image, empty file, etc.), bail out
        if not text.strip():
            return 0

        # step 2: break the text into ~500-character overlapping chunks
        docs = self.chunk_text(text)

        # step 3: embed the chunks and store them in ChromaDB for similarity search
        self.build_vectorstore(docs)

        # step 4: wire up the retriever → prompt → LLM chain so we're ready to answer questions
        self._build_chain()

        # chunk count goes back to the UI so the user knows how much content was indexed
        return len(docs)

    def ask(self, question: str):
        # guard clause — can't answer questions if no PDF has been loaded yet
        if self.chain is None:
            return "Please upload a PDF first."

        # run the full RAG chain: retrieve chunks → fill prompt → LLM → return answer text
        return self.chain.invoke(question)