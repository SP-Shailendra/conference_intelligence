from sentence_transformers import SentenceTransformer
import faiss
from data.knowledge import KNOWLEDGE_BASE

# Initialize models and FAISS index globally so they load once at startup
embedding_model = SentenceTransformer("all-MiniLM-L6-v2")

# Create FAISS Index
kb_embeddings = embedding_model.encode(KNOWLEDGE_BASE, convert_to_numpy=True)
dimension = kb_embeddings.shape[1]
index = faiss.IndexFlatL2(dimension)
index.add(kb_embeddings)

def retrieve_context(query: str, top_k: int = 3) -> list:
    query_embedding = embedding_model.encode([query], convert_to_numpy=True)
    distances, indices = index.search(query_embedding, top_k)
    
    return [KNOWLEDGE_BASE[i] for i in indices[0]]