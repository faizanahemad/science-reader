"""
Notes search strategy for PKB v0.

NotesSearchStrategy provides search functionality for notes:
- FTS search on title and body
- Embedding-based semantic search
- Combined hybrid search
"""

import logging
from typing import List, Dict, Optional
from dataclasses import dataclass, field

import numpy as np

from ..database import PKBDatabase
from ..config import PKBConfig
from ..models import Note
from ..utils import now_iso, get_parallel_executor

logger = logging.getLogger(__name__)


@dataclass
class NoteSearchResult:
    """
    Search result for notes.
    
    Attributes:
        note: The matched Note object.
        score: Relevance score.
        source: Search strategy that found this result.
        metadata: Additional strategy-specific metadata.
    """
    note: Note
    score: float
    source: str
    metadata: Dict = field(default_factory=dict)


class NotesSearchStrategy:
    """
    Search functionality for notes.
    
    Provides both FTS and embedding-based search for notes,
    separate from claims search.
    
    Attributes:
        db: PKBDatabase instance.
        keys: API keys for embedding calls.
        config: PKBConfig with settings.
    """
    
    def __init__(
        self,
        db: PKBDatabase,
        keys: Dict[str, str] = None,
        config: PKBConfig = None
    ):
        """
        Initialize notes search.
        
        Args:
            db: PKBDatabase instance.
            keys: Optional API keys for embeddings.
            config: Optional PKBConfig.
        """
        self.db = db
        self.keys = keys or {}
        self.config = config or PKBConfig()
    
    def search_fts(
        self,
        query: str,
        k: int = 20,
        context_domain: Optional[str] = None
    ) -> List[NoteSearchResult]:
        """
        Search notes using FTS.
        
        Args:
            query: Search query.
            k: Number of results.
            context_domain: Optional domain filter.
            
        Returns:
            List of NoteSearchResult objects.
        """
        # Sanitize query
        import re
        sanitized = re.sub(r'[^\w\s\-]', ' ', query)
        words = sanitized.split()
        
        if not words:
            return []
        
        # Build FTS query
        fts_query = ' OR '.join([f"{w}*" for w in words])
        
        # Build SQL
        sql = """
            SELECT n.*, -bm25(notes_fts) as score
            FROM notes_fts
            JOIN notes n ON notes_fts.note_id = n.note_id
            WHERE notes_fts MATCH ?
        """
        params = [fts_query]
        
        if context_domain:
            sql += " AND n.context_domain = ?"
            params.append(context_domain)
        
        sql += " ORDER BY score DESC LIMIT ?"
        params.append(k)
        
        try:
            rows = self.db.fetchall(sql, tuple(params))
            
            results = []
            for row in rows:
                note = Note.from_row(row)
                result = NoteSearchResult(
                    note=note,
                    score=row['score'],
                    source='fts',
                    metadata={'fts_query': fts_query}
                )
                results.append(result)
            
            return results
            
        except Exception as e:
            logger.error(f"Notes FTS search failed: {e}")
            return []
    
    def search_embedding(
        self,
        query: str,
        k: int = 20,
        context_domain: Optional[str] = None
    ) -> List[NoteSearchResult]:
        """
        Search notes using embedding similarity.
        
        Args:
            query: Search query.
            k: Number of results.
            context_domain: Optional domain filter.
            
        Returns:
            List of NoteSearchResult objects.
        """
        if not self.config.embedding_enabled or not self.keys.get("OPENROUTER_API_KEY"):
            logger.warning("Embedding search not available")
            return []
        
        try:
            from code_common.call_llm import get_query_embedding
        except ImportError:
            logger.error("code_common.call_llm not available")
            return []
        
        # Get query embedding
        query_emb = get_query_embedding(query, self.keys)
        
        # Get all notes with embeddings
        sql = """
            SELECT n.*, ne.embedding
            FROM notes n
            JOIN note_embeddings ne ON n.note_id = ne.note_id
        """
        params = []
        
        if context_domain:
            sql += " WHERE n.context_domain = ?"
            params.append(context_domain)
        
        rows = self.db.fetchall(sql, tuple(params))
        
        # Compute similarities
        scores = []
        for row in rows:
            note = Note.from_row(row)
            note_emb = np.frombuffer(row['embedding'], dtype=np.float32)
            
            # Cosine similarity
            dot = np.dot(query_emb, note_emb)
            norm1 = np.linalg.norm(query_emb)
            norm2 = np.linalg.norm(note_emb)
            
            if norm1 > 0 and norm2 > 0:
                sim = dot / (norm1 * norm2)
                scores.append((note, float(sim)))
        
        # Sort and return top-k
        scores.sort(key=lambda x: x[1], reverse=True)
        
        return [
            NoteSearchResult(note=note, score=score, source='embedding')
            for note, score in scores[:k]
        ]
    
    def search(
        self,
        query: str,
        k: int = 20,
        context_domain: Optional[str] = None,
        use_embedding: bool = True
    ) -> List[NoteSearchResult]:
        """
        Search notes using both FTS and embedding (if available).
        
        Args:
            query: Search query.
            k: Number of results.
            context_domain: Optional domain filter.
            use_embedding: Whether to use embedding search.
            
        Returns:
            List of NoteSearchResult objects.
        """
        # Get FTS results
        fts_results = self.search_fts(query, k * 2, context_domain)
        
        if not use_embedding or not self.keys.get("OPENROUTER_API_KEY"):
            return fts_results[:k]
        
        # Get embedding results
        emb_results = self.search_embedding(query, k * 2, context_domain)
        
        if not emb_results:
            return fts_results[:k]
        
        # Merge with RRF
        return self._merge_results(fts_results, emb_results, k)
    
    def _merge_results(
        self,
        fts_results: List[NoteSearchResult],
        emb_results: List[NoteSearchResult],
        k: int
    ) -> List[NoteSearchResult]:
        """
        Merge FTS and embedding results using RRF.
        
        Args:
            fts_results: Results from FTS search.
            emb_results: Results from embedding search.
            k: Number of final results.
            
        Returns:
            Merged list of results.
        """
        rrf_k = 60  # RRF constant
        scores = {}  # note_id -> (result, total_score, sources)
        
        # Score FTS results
        for rank, result in enumerate(fts_results):
            nid = result.note.note_id
            rrf_score = 1.0 / (rank + rrf_k)
            scores[nid] = (result, rrf_score, ['fts'])
        
        # Score embedding results
        for rank, result in enumerate(emb_results):
            nid = result.note.note_id
            rrf_score = 1.0 / (rank + rrf_k)
            
            if nid in scores:
                _, total, sources = scores[nid]
                scores[nid] = (result, total + rrf_score, sources + ['embedding'])
            else:
                scores[nid] = (result, rrf_score, ['embedding'])
        
        # Sort by combined score
        sorted_items = sorted(scores.values(), key=lambda x: x[1], reverse=True)
        
        # Build final results
        final = []
        for result, score, sources in sorted_items[:k]:
            result.score = score
            result.source = 'hybrid' if len(sources) > 1 else sources[0]
            result.metadata['sources'] = sources
            final.append(result)
        
        return final
    
    def ensure_embedding(self, note: Note) -> Optional[np.ndarray]:
        """
        Ensure embedding exists for a note, computing if needed.
        
        Args:
            note: Note to embed.
            
        Returns:
            Embedding array or None if failed.
        """
        # Check if exists
        row = self.db.fetchone(
            "SELECT embedding FROM note_embeddings WHERE note_id = ?",
            (note.note_id,)
        )
        
        if row and row['embedding']:
            return np.frombuffer(row['embedding'], dtype=np.float32)
        
        # Compute embedding
        if not self.keys.get("OPENROUTER_API_KEY"):
            return None
        
        try:
            from code_common.call_llm import get_document_embedding
            
            # Combine title and body for embedding
            text = f"{note.title or ''}\n{note.body}".strip()
            embedding = get_document_embedding(text, self.keys)
            
            # Store
            embedding_blob = embedding.astype(np.float32).tobytes()
            with self.db.transaction() as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO note_embeddings (note_id, embedding, model_name, created_at)
                    VALUES (?, ?, ?, ?)
                """, (note.note_id, embedding_blob, self.config.embedding_model, now_iso()))
            
            return embedding
            
        except Exception as e:
            logger.error(f"Failed to compute note embedding: {e}")
            return None
