# Deployment & Installation Guide

## Prerequisites
- Node.js (v18+)
- Python (3.10+)
- Valid API keys: `GEMINI_API_KEY`, `GROQ_API_KEY`, `TAVILY_API_KEY`

## Local Development Setup

1. **Clone the Repository**
   ```bash
   git clone https://github.com/your-username/sagecommand-os.git
   cd sagecommand-os
   ```

2. **Backend Installation**
   ```bash
   cd backend
   python -m venv venv
   source venv/bin/activate  # On Windows: .\venv\Scripts\activate
   pip install -r requirements.txt
   ```
   Create a `.env` file in the `/backend` directory with your keys.
   Start the server:
   ```bash
   python server.py
   ```

3. **Frontend Installation**
   ```bash
   cd frontend
   npm install
   npm run dev
   ```

## Production Deployment (Cloud)

### Backend Deployment (Railway / Render / AWS)
1. Ensure the `requirements.txt` is updated.
2. In your cloud provider, set the start command to:
   ```bash
   uvicorn server:app --host 0.0.0.0 --port $PORT
   ```
3. Inject the `.env` variables into the cloud provider's secret manager.
4. **Important for WebSockets:** Ensure your hosting provider supports persistent HTTP/1.1 or HTTP/2 WebSocket connections without extremely short timeouts.

### Frontend Deployment (Vercel)
1. Push the repository to GitHub.
2. Import the project into Vercel.
3. Set the Root Directory to `frontend`.
4. Add the `NEXT_PUBLIC_WS_URL` environment variable pointing to your deployed backend URL (e.g., `wss://api.sagecommand.com/ws/sage`).
5. Click **Deploy**.

## Docker Containerization (Optional)
To containerize the application for Kubernetes or Docker Swarm, you should create a multi-stage `Dockerfile`. Ensure that the `sage_memory.sqlite` file is mounted to a persistent volume (e.g., AWS EBS or a Docker volume) to ensure Time Travel checkpoints survive container restarts.
