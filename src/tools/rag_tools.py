"""
============================================================
RAG Tools (Retrieval-Augmented Generation)
============================================================
This module sets up the document intelligence pipeline:
  1. Loads maintenance manuals and compliance guides
  2. Splits them into chunks for embedding
  3. Stores embeddings in ChromaDB
  4. Provides a search function agents can call

The Knowledge Agent uses this to answer questions like:
  "What's the procedure for HVAC filter replacement?"
  "What safety requirements apply to boiler maintenance?"
  "What are the regulatory requirements for elevator inspection?"

Architecture:
  Documents -> LangChain TextSplitter -> OpenAI Embeddings -> ChromaDB
  
  Query -> Embedding -> ChromaDB Similarity Search -> Top-K Results

This is the same RAG pattern as FinanceRAG, applied to a
different domain. The architecture transfers directly.
============================================================
"""

import os
from pathlib import Path
from langchain_community.document_loaders import DirectoryLoader, TextLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from langchain_chroma import Chroma


# ============================================================
# CONFIGURATION
# ============================================================

# Where the maintenance documents live
DOCS_DIR = str(Path(__file__).parent.parent / "docs")

# Where ChromaDB stores the vector index
CHROMA_DIR = str(Path(__file__).parent.parent / "data" / "chroma_db")

# Embedding model (same as FinanceRAG for consistency)
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "text-embedding-ada-002")

# Chunking parameters
# - chunk_size: How many characters per chunk. 1000 is a good balance
#   between having enough context and keeping searches precise.
# - chunk_overlap: How many characters overlap between chunks.
#   200 ensures we don't lose context at chunk boundaries.
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200

# How many results to return from similarity search
TOP_K = 4


# ============================================================
# VECTOR STORE SETUP
# ============================================================

# Module-level variable to cache the vector store
# This avoids rebuilding the index on every query
_vector_store = None


def _get_or_create_vector_store() -> Chroma:
    """
    Load the vector store from disk, or create it from documents.
    
    This function:
      1. Checks if a ChromaDB index already exists on disk
      2. If yes, loads it (fast startup)
      3. If no, reads all maintenance documents, chunks them,
         embeds them, and creates a new index
    
    The index is cached in the module-level _vector_store variable
    so subsequent calls don't rebuild it.
    
    Returns:
        Chroma vector store ready for similarity search
    """
    global _vector_store

    if _vector_store is not None:
        return _vector_store

    embeddings = OpenAIEmbeddings(model=EMBEDDING_MODEL)

    # Check if index already exists on disk
    if os.path.exists(CHROMA_DIR) and os.listdir(CHROMA_DIR):
        print("Loading existing vector store from disk...")
        _vector_store = Chroma(
            persist_directory=CHROMA_DIR,
            embedding_function=embeddings,
            collection_name="maintenance_docs",
        )
        return _vector_store

    # ---- Build the index from scratch ----
    print(f"Building vector store from documents in {DOCS_DIR}...")

    # Step 1: Load all markdown documents from the docs directory
    # DirectoryLoader recursively finds all files matching the glob pattern
    loader = DirectoryLoader(
        DOCS_DIR,
        glob="**/*.md",
        loader_cls=TextLoader,
        loader_kwargs={"encoding": "utf-8"},
    )
    documents = loader.load()
    print(f"  Loaded {len(documents)} documents")

    # Step 2: Split documents into chunks
    # RecursiveCharacterTextSplitter tries to split at natural boundaries
    # (paragraphs, sentences, words) before falling back to character count.
    # This preserves readability of the chunks.
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        length_function=len,
        # Split hierarchy: try double newline first, then single, then space
        separators=["\n\n", "\n", " ", ""],
    )
    chunks = text_splitter.split_documents(documents)
    print(f"  Split into {len(chunks)} chunks")

    # Step 3: Create embeddings and store in ChromaDB
    # Each chunk gets converted to a vector (1536 dimensions for Ada-002)
    # ChromaDB stores these vectors and enables fast similarity search
    _vector_store = Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        persist_directory=CHROMA_DIR,
        collection_name="maintenance_docs",
    )
    print(f"  Vector store created and persisted to {CHROMA_DIR}")

    return _vector_store


def search_maintenance_docs(query: str) -> str:
    """
    Search maintenance documentation using semantic similarity.
    
    This is the main function the Knowledge Agent calls. It:
      1. Converts the query to an embedding vector
      2. Finds the most similar document chunks in ChromaDB
      3. Returns the relevant text with source information
    
    The beauty of semantic search: the query "what do I do when
    the boiler won't start" will match documents about "boiler
    emergency startup procedures" even though the words are different.
    
    Args:
        query: Natural language question about maintenance procedures
        
    Returns:
        Relevant document excerpts with source attribution
    """
    try:
        vector_store = _get_or_create_vector_store()

        # Perform similarity search
        # Returns the TOP_K most similar document chunks
        results = vector_store.similarity_search_with_score(query, k=TOP_K)

        if not results:
            return "No relevant maintenance documentation found for this query."

        # Format results for the agent
        # Include the source file and relevance score so the agent
        # can assess the quality of the information
        output = f"MAINTENANCE DOCUMENTATION SEARCH RESULTS (Query: '{query}'):\n\n"

        for i, (doc, score) in enumerate(results, 1):
            # Extract the filename from the full path
            source = Path(doc.metadata.get("source", "Unknown")).name
            # Score is distance (lower = more similar)
            relevance = f"{'High' if score < 0.5 else 'Medium' if score < 1.0 else 'Low'} relevance"

            output += f"--- Result {i} ({relevance}, source: {source}) ---\n"
            output += doc.page_content.strip()
            output += "\n\n"

        return output.strip()

    except Exception as e:
        return f"Error searching maintenance docs: {str(e)}. Ensure OPENAI_API_KEY is set."


def get_document_list() -> str:
    """
    List all available maintenance documents.
    Useful for the agent to know what documentation exists.
    """
    docs_path = Path(DOCS_DIR)
    if not docs_path.exists():
        return "No documentation directory found."

    files = list(docs_path.glob("**/*.md"))
    if not files:
        return "No maintenance documents found."

    result = "AVAILABLE MAINTENANCE DOCUMENTS:\n"
    for f in files:
        # Get file size for context
        size_kb = f.stat().st_size / 1024
        result += f"  - {f.name} ({size_kb:.1f} KB)\n"

    return result.strip()
