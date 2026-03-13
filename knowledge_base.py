import os
import json
import markdown
from pathlib import Path
from typing import List, Dict, Any
import chromadb
from sentence_transformers import SentenceTransformer
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class PropertyKnowledgeBase:
    def __init__(self, knowledge_base_dir: str = "knowledge_base", db_path: str = "./chroma_db"):
        self.knowledge_base_dir = Path(knowledge_base_dir)
        self.db_path = db_path
        self.client = None
        self.collection = None
        self.embedder = None
        self._initialized = False
        
    def initialize(self):
        """Initialize ChromaDB and embedder - safe to call multiple times"""
        if self._initialized:
            return True
            
        try:
            # Initialize ChromaDB client
            self.client = chromadb.PersistentClient(path=self.db_path)
            
            # Get or create collection
            collection_name = "properties"
            try:
                self.collection = self.client.get_collection(name=collection_name)
                logger.info(f"Using existing collection: {collection_name}")
            except:
                self.collection = self.client.create_collection(name=collection_name)
                logger.info(f"Created new collection: {collection_name}")
            
            # Initialize sentence transformer embedder
            self.embedder = SentenceTransformer('all-MiniLM-L6-v2')
            
            # Load knowledge base if empty
            if self.collection.count() == 0:
                self._load_knowledge_base()
            
            self._initialized = True
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize knowledge base: {e}")
            return False
    
    def _load_knowledge_base(self):
        """Load and index all markdown files from knowledge base directory"""
        if not self.knowledge_base_dir.exists():
            logger.warning(f"Knowledge base directory not found: {self.knowledge_base_dir}")
            return
        
        documents = []
        metadatas = []
        ids = []
        
        # Process all markdown files
        for md_file in self.knowledge_base_dir.glob("*.md"):
            if md_file.name == "knowledge.md":  # Skip empty template
                continue
                
            try:
                with open(md_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Parse markdown
                html_content = markdown.markdown(content)
                
                # Split into sections by headers
                sections = self._split_into_sections(content, str(md_file))
                
                for i, section in enumerate(sections):
                    documents.append(section['text'])
                    metadatas.append({
                        'source_file': md_file.name,
                        'section_title': section['title'],
                        'file_path': str(md_file)
                    })
                    ids.append(f"{md_file.stem}_{i}")
                    
            except Exception as e:
                logger.error(f"Error processing {md_file}: {e}")
        
        if documents:
            # Generate embeddings
            embeddings = self.embedder.encode(documents).tolist()
            
            # Add to ChromaDB
            self.collection.add(
                documents=documents,
                metadatas=metadatas,
                ids=ids,
                embeddings=embeddings
            )
            
            logger.info(f"Loaded {len(documents)} sections from knowledge base")
    
    def _split_into_sections(self, content: str, file_path: str) -> List[Dict[str, str]]:
        """Split markdown content into sections by headers"""
        sections = []
        lines = content.split('\n')
        current_section = ""
        current_title = "Introduction"
        
        for line in lines:
            if line.startswith('#'):  # Header
                # Save previous section
                if current_section.strip():
                    sections.append({
                        'title': current_title,
                        'text': current_section.strip()
                    })
                
                # Start new section
                current_title = line.strip('# ').strip()
                current_section = ""
            else:
                current_section += line + "\n"
        
        # Add last section
        if current_section.strip():
            sections.append({
                'title': current_title,
                'text': current_section.strip()
            })
        
        return sections
    
    def search_properties(self, query: str, n_results: int = 5) -> Dict[str, Any]:
        """Search properties using semantic similarity"""
        if not self.initialize():
            return {"error": "Knowledge base not available"}
        
        try:
            # Generate query embedding
            query_embedding = self.embedder.encode([query]).tolist()
            
            # Search ChromaDB
            results = self.collection.query(
                query_embeddings=query_embedding,
                n_results=n_results,
                include=["documents", "metadatas", "distances"]
            )
            
            # Format results
            formatted_results = []
            for i in range(len(results['documents'][0])):
                formatted_results.append({
                    'text': results['documents'][0][i],
                    'metadata': results['metadatas'][0][i],
                    'score': 1 - results['distances'][0][i],  # Convert distance to similarity
                    'source': f"{results['metadatas'][0][i]['source_file']} - {results['metadatas'][0][i]['section_title']}"
                })
            
            return {
                'query': query,
                'results': formatted_results,
                'total_found': len(formatted_results)
            }
            
        except Exception as e:
            logger.error(f"Search error: {e}")
            return {"error": f"Search failed: {str(e)}"}
    
    def get_property_summary(self) -> str:
        """Get summary of all properties in knowledge base"""
        if not self.initialize():
            return "Knowledge base not available"
        
        try:
            # Get all unique source files
            all_metadata = self.collection.get(include=['metadatas'])
            source_files = set()
            
            for metadata in all_metadata['metadatas']:
                source_files.add(metadata['source_file'])
            
            return f"Knowledge base contains {len(source_files)} property files: {', '.join(sorted(source_files))}"
            
        except Exception as e:
            return f"Error getting summary: {str(e)}"

# Global instance
kb_instance = PropertyKnowledgeBase()

def search_properties(query: str, n_results: int = 5) -> Dict[str, Any]:
    """Global function for property search"""
    return kb_instance.search_properties(query, n_results)

def get_property_summary() -> str:
    """Global function for property summary"""
    return kb_instance.get_property_summary()

def initialize_knowledge_base() -> bool:
    """Initialize knowledge base - call this during app startup"""
    return kb_instance.initialize()

def get_all_knowledge() -> str:
    """Get all knowledge base content formatted for prompt injection"""
    if not kb_instance.initialize():
        return "Knowledge base not available"
    
    try:
        # Get all documents from collection
        all_data = kb_instance.collection.get(include=['documents', 'metadatas'])
        
        if not all_data['documents']:
            return "No knowledge base content available"
        
        # Group by source file for better organization
        content_by_file = {}
        for doc, metadata in zip(all_data['documents'], all_data['metadatas']):
            source_file = metadata['source_file']
            if source_file not in content_by_file:
                content_by_file[source_file] = []
            content_by_file[source_file].append({
                'section_title': metadata['section_title'],
                'text': doc
            })
        
        # Format as readable text
        formatted_content = "=== MONTREAL RENTAL PROPERTIES KNOWLEDGE BASE ===\n\n"
        
        for file_name in sorted(content_by_file.keys()):
            formatted_content += f"## {file_name.replace('.md', '').replace('_', ' ').title()}\n\n"
            
            for section in content_by_file[file_name]:
                formatted_content += f"### {section['section_title']}\n"
                formatted_content += section['text'] + "\n\n"
            
            formatted_content += "---\n\n"
        
        return formatted_content
        
    except Exception as e:
        logger.error(f"Error getting all knowledge: {e}")
        return f"Error retrieving knowledge base: {str(e)}"
