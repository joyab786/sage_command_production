# SageCommand OS V2.0 - User Manual & Guide

## Overview
SageCommand OS acts as an autonomous AI Command Center. It connects to your industrial databases, identifies operational anomalies, and recommends (or executes) optimization strategies safely under Human-in-the-Loop constraints.

## Using the Dashboard

### 1. Connecting a Live Database (Tethering)
1. Click the **LIVE UPLINK** button in the top navigation bar.
2. A secure modal will appear. Paste your database connection string (e.g., `postgresql://user:pass@host/db` or `sqlite:///C:/path/to/db.sqlite`).
3. Click **Establish Tether**. The system will dynamically re-route the AI's internal tools to query this new database.

### 2. Uploading Flat Files
If you are working with offline data (e.g., `.csv` files from a legacy system):
1. Click **MOUNT FILE**.
2. Select your `.csv` file. 
3. SageCommand OS will automatically compile the CSV into a dynamic SQL database in the background and establish a tether to it.

### 3. Running a Core Scan
To prompt the AI to proactively search for anomalies across the connected infrastructure:
1. Click the **CORE SCAN** button in the top right.
2. The AI will spin up the `Discovery Agent`, `Strategy Worker`, and `Web Researcher`.
3. You can watch the active neural nodes pulse on the visualization graph as telemetry flows in real-time.

### 4. Human-in-the-Loop Execution
If the AI decides that it needs to perform a write operation (e.g., updating stock, creating a purchase order):
1. Execution is **Hard Halted**.
2. A Guardrail Intercept card will appear in the Execution Feed.
3. If you have the **Manager** role toggled, you can review the AI's logic and click **Authorize** to allow the SQL execution, or **Abort** to terminate the thread safely.

### 5. Multi-Modal Vision Diagnostics
If machinery on the factory floor is damaged:
1. Click **HARDWARE VISION**.
2. Upload a photo of the damaged machinery/component.
3. The Vision Diagnostics agent will assess the damage, identify the part, rate the severity, and output an incident report card into the execution feed.

### 6. Time Travel (State Reversion)
To audit previous AI decisions or rewind state:
1. Click **TIME TRAVEL**.
2. The modal will list every state snapshot from the LangGraph execution.
3. You can inspect previous checkpoints to understand the AI's logic pathway at any given moment.
