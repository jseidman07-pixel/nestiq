# Nestiq

Nestiq is an AI-powered real estate investment agent built for the Google Cloud Rapid Agent Hackathon.

The agent helps users analyze potential real estate investment deals by storing property data, comparable sales, underwriting assumptions, and deal verdicts in MongoDB. It uses Google Cloud ADK / Gemini for reasoning and MongoDB for structured deal memory and future vector search.

## Core Concept

A user enters a property or deal scenario. Nestiq evaluates the investment using underwriting metrics such as:

- Net operating income
- Cap rate
- Cash-on-cash return
- Monthly cash flow
- Rent assumptions
- Comparable property context
- Buy / Negotiate / Walk Away verdict

## Tech Stack

- Python
- Google ADK
- Gemini / Google Cloud
- MongoDB Atlas
- PyMongo
- dotenv

## Status

Initial project setup complete.
