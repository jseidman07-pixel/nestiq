# Nestiq — Auburn Housing Intelligence

AI-powered housing advisor for Auburn University students. Built for the Google Cloud Rapid Agent Hackathon (MongoDB track).

## What It Does
- Searches 35+ Auburn off-campus properties using MongoDB Atlas Vector Search
- Gives every property a Sign / Negotiate / Pass verdict
- Shows true cost including utilities and move-in fees
- Models roommate scenarios and fragility risk
- Surfaces real student reviews from Google, Reddit, and Yelp (2024+ only)
- Scans lease PDFs with Gemini 2.5 for red flags and negotiation leverage
- Autonomously scrapes apartment websites with Playwright + Gemini
- Autonomously collects and analyzes new reviews nightly

## Live Demo
https://nestiq-1035779764999.us-central1.run.app

## Tech Stack
- Google ADK + Gemini 2.5 Flash
- MongoDB Atlas + Vector Search
- Vertex AI text-embedding-004
- FastAPI + Cloud Run
- Playwright (autonomous web scraping)
- Google Places API

## Run Locally
```bash
git clone https://github.com/jseidman07-pixel/nestiq
cd nestiq
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # add your keys
uvicorn app.main:app --reload
```

## Hackathon
Google Cloud Rapid Agent Hackathon · MongoDB Track · June 2026