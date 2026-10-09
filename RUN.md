# Run Instructions & Secrets Configuration

---

## 1. Setting Secrets (`.env`)

Create a `.env` file in the project root by copying the template:

```bash
cp .env.example .env
```

Open `.env` and fill in your API credentials. You only need **one** LLM provider (OpenAI, Gemini, or Azure) to run the application:

### Option A: OpenAI (or OpenAI-Compatible Custom Endpoint)
```dotenv
AI_PRIMARY_PROVIDER=openai
OPENAI_API_KEY=sk-proj-your-openai-api-key
OPENAI_MODEL=gpt-4o
# Optional custom endpoint (e.g. Ollama, Groq, vLLM, DeepSeek):
OPENAI_BASE_URL=https://api.openai.com/v1
```

### Option B: Google Gemini
```dotenv
AI_PRIMARY_PROVIDER=gemini
GEMINI_API_KEY=your-gemini-api-key
GEMINI_MODEL=gemini-2.5-flash
```

### Option C: Azure OpenAI / Azure AI Foundry
```dotenv
AI_PRIMARY_PROVIDER=azure
AZURE_OPENAI_AUTH_MODE=api-key
AZURE_OPENAI_API_KEY=your-azure-api-key
AZURE_OPENAI_BASE_URL=https://your-resource.openai.azure.com
AZURE_OPENAI_MODEL=gpt-4o
```

---

### Enterprise OCR Secrets (Optional for Document Intelligence)

If configured, the system uses Azure DI as primary OCR with automatic failover to Google Document AI:

```dotenv
# Primary OCR: Azure Document Intelligence
AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT=https://your-resource.cognitiveservices.azure.com/
AZURE_DOCUMENT_INTELLIGENCE_KEY=your-azure-key

# Secondary OCR Failover: Google Cloud Document AI
GCP_PROJECT_ID=your-gcp-project-id
GCP_LOCATION=us
DOCAI_PROCESSOR_ID=your-processor-id
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
```

*(If Cloud OCR credentials are not provided, the pipeline automatically falls back to Multimodal Vision LLM OCR).*

---

### Optional Web Search & Safety Thresholds
```dotenv
# Web search for Spreadsheet Data Agent
TAVILY_API_KEY=your-tavily-api-key

# Document Safety Thresholds
FIELD_CONFIDENCE_THRESHOLD=0.85
HANDWRITTEN_CONFIDENCE_PENALTY=0.20
```

---

## 2. Run Instructions

### Step 1: Create and Activate Virtual Environment
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### Step 2: Install Dependencies
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### Step 3: Run the Application
```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Access the application in your browser:
- **Web UI**: [http://localhost:8000](http://localhost:8000)
- **API Documentation (Swagger UI)**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **Health Check**: [http://localhost:8000/api/health](http://localhost:8000/api/health)

---

### Step 4: Run the Complete Test Suite
```bash
python -m unittest discover -s tests -t .
```

### Step 5: Run Multi-Module Evaluation Benchmarks
```bash
python evals/run_all_evaluations.py
```
