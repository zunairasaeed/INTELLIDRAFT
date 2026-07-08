INTELLIDRAFT
Agentic AI Research Assistant for Intelligent Academic Research, Journal Recommendation, LaTeX Alignment, and Citation Management
<p align="center">

An AI-powered research platform that assists researchers throughout the complete academic writing workflow—from literature discovery to journal recommendation, intelligent writing assistance, LaTeX template alignment, and citation management.

</p>
Overview

INTELLIDRAFT is a full-stack Agentic AI research platform developed as a Final Year Project. It combines Large Language Models (LLMs), Retrieval-Augmented Generation (RAG), semantic search, journal intelligence, and document editing into one unified research environment.

Unlike conventional academic tools that solve only isolated tasks, IntelliDraft provides an integrated research workflow where multiple AI agents collaborate to assist researchers from the initial literature search to the final publication-ready manuscript.

The system is built using React, FastAPI, Supabase, FAISS, Sentence Transformers, and LLM-based AI agents, offering a scalable and modular architecture.

Key Features
Semantic Literature Search
AI-powered research paper search
Query refinement using LLMs
Semantic Scholar integration
Intelligent keyword extraction
Paper ranking
Session history
Save papers for future use
Journal Recommendation
Research domain identification
Automatic keyword extraction
OpenAlex integration
Scimago Journal Ranking (SJR)
DOAJ support
Journal comparison
Open Access recommendations
Quartile-based recommendations
Research & Publishing Guide (RAG)
Retrieval-Augmented Generation
FAISS Vector Database
Sentence Transformers embeddings
Research methodology assistance
Publishing guidelines
Academic writing support
Source-aware responses
Intelligent LaTeX Alignment
Upload existing LaTeX documents
Automatic document parsing
Section detection
Template alignment
IEEE template support
ACM template support
Agentic document editing
Intelligent section rewriting
Export aligned LaTeX
Citation Management
Save citations
Generate citation keys
BibTeX export
IEEE export
APA export
LaTeX bibliography export
Bulk citation generation
Authentication & User Management
User Registration
Secure Login
Session Management
Saved Research History
Paper Inventory
User File Storage
AI Architecture

INTELLIDRAFT follows an Agentic AI Architecture where a central coordinator routes requests to specialized AI agents.

                    User
                      │
                      ▼
              React Frontend
                      │
                      ▼
            FastAPI Backend API
                      │
          Coordinator / Pipeline Router
                      │
     ┌──────────┬──────────┬──────────┬──────────┬──────────┐
     ▼          ▼          ▼          ▼          ▼
 Literature   Journal     RAG     LaTeX      Citation
   Agent       Agent      Agent    Agent       Agent

Each agent independently performs domain-specific reasoning while sharing common infrastructure such as authentication, storage, and LLM services.

System Architecture

The platform consists of five primary layers:

Presentation Layer – React.js frontend
API Layer – FastAPI backend
Agent Layer – Specialized AI pipelines
Knowledge Layer – FAISS, Semantic Scholar, OpenAlex, DOAJ, Scimago
Persistence Layer – Supabase PostgreSQL & Storage
Technology Stack
Frontend
React
React Router
JavaScript
HTML5
CSS3
Backend
FastAPI
Python
Pydantic
Uvicorn
AI & Machine Learning
Groq LLM
Llama 3.3
Sentence Transformers
FAISS
Retrieval-Augmented Generation (RAG)
Database
Supabase
PostgreSQL
Supabase Storage
External APIs
Semantic Scholar API
OpenAlex API
DOAJ API
Document Processing
LaTeX
BibTeX
AI Pipelines
1. Literature Search Pipeline
User Query
      │
      ▼
Input Validation
      │
Text Normalization
      │
Keyword Extraction
      │
Keyword Ranking
      │
Query Reconstruction
      │
Semantic Scholar Search
      │
Response Mapping
      │
LLM Research Summary
      │
Results
2. Journal Recommendation Pipeline
Research Topic
      │
Intent Classification
      │
Query Normalization
      │
OpenAlex Search
      │
Scimago Ranking
      │
DOAJ Enrichment
      │
LLM Recommendation
      │
Recommended Journals
3. Research Guide (RAG)
Question
      │
Query Refinement
      │
Embedding Generation
      │
FAISS Retrieval
      │
Relevant Context
      │
LLM Answer
      │
Response with Sources
4. LaTeX Alignment Pipeline
Upload .tex File
        │
Parser
        │
Section Detection
        │
Intent Router
        │
Agent Executor
        │
LLM Editing
        │
Surgical Writer
        │
Updated Document
        │
Export
5. Citation Pipeline
Paper
   │
Citation Extraction
   │
Citation Key
   │
Database
   │
Export
Project Structure
INTELLIDRAFT
│
├── frontend/                 # React Frontend
├── backend/                  # FastAPI Backend
├── src/
│   ├── semantic_literature_search/
│   ├── Journel_Research_Assistant/
│   ├── Research_and_publishing_guide_bot/
│   ├── Latex_Alignment/
│   └── Latex_editor/
│
├── database/
│
├── api/
│
├── requirements.txt
└── README.md
Installation

Clone the repository:

git clone https://github.com/yourusername/INTELLIDRAFT.git

Move into the project:

cd INTELLIDRAFT

Install Python dependencies:

pip install -r requirements.txt

Install frontend dependencies:

cd frontend/FYP\ Frontend/my-app
npm install

Run the backend:

uvicorn backend.main:app --reload --port 8001

Run the frontend:

npm start
Environment Variables

Create a .env file and configure the following:

SUPABASE_URL=
SUPABASE_SERVICE_ROLE_KEY=
SUPABASE_ANON_KEY=

GROQ_API_KEY=

SEMANTIC_SCHOLAR_API_KEY=

OPENALEX_BASE_URL=
DOAJ_BASE_URL=

PASSWORD_RESET_REDIRECT_URL=
API Modules
Module	Purpose
/auth	Authentication
/sessions	Chat Sessions
/chat	Conversation History
/pipelines/literature	Literature Search
/pipelines/journal-research	Journal Recommendation
/pipelines/research-guide	Writing Guide (RAG)
/pipelines/latex-alignment	Intelligent LaTeX Editing
/citations	Citation Management
/files	User File Storage
Project Workflow
User logs in.
Creates a research session.
Searches for literature.
Saves relevant papers.
Receives journal recommendations.
Uses the Research Guide for writing assistance.
Uploads a LaTeX document for template alignment.
Generates and manages citations.
Exports the final publication-ready assets.
Future Improvements
Multi-agent orchestration with autonomous planning
Multi-user collaborative workspaces
Additional journal template support
PDF semantic annotation
AI-powered plagiarism detection
Reviewer recommendation system
Research roadmap generation
Knowledge graph integration
Cloud-native deployment with Kubernetes
CI/CD automation
Contributors

Zunaira Saeed
Computer Engineering, UET Lahore

Final Year Project – INTELLIDRAFT

License

This project is developed for educational and research purposes as part of a Final Year Project at the University of Engineering and Technology (UET), Lahore.
