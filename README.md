\# ClaudeVision

&#x20;

Automated pipeline for extracting data from PDF technical drawings and generating structured outputs for estimating, pricing, and historical analysis.

&#x20;

\---

&#x20;

\## 🚀 What it does

&#x20;

\- Extracts text from engineering drawings (PDFs)

\- Identifies parts, materials, dimensions, and metadata

\- Produces structured JSON outputs

\- Prepares data for pricing and RAG (historical lookup)

&#x20;

\---

&#x20;

\## ▶️ Run

&#x20;

```bash

python src/main.py --search-root input/drawings --drawing-pattern "\*.pdf"

