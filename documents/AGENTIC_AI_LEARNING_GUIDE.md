# Agentic AI Learning Guide

## Project Objective

You're building an **AI Workflow & Agent Platform** — a system where:

1. **Users submit tasks** (e.g., "Research AI startups in healthcare and generate a report")
2. **The system breaks it into subtasks** (research, analyze, write, format)
3. **Agents execute those subtasks** (planner agent, executor agent, etc.)
4. **Tools get called** (search API, data processing, LLM)
5. **State is tracked & logged** (who did what, when, why, what failed)
6. **Work is retried** on failure
7. **Output is returned** to the user

---

## The Core Problem You're Solving

### Without this system:
```
User → Single LLM call → Hope it works → Done (or start over)
```

### With this system:
```
User → Workflow Engine → Breaks into tasks → Multiple agents work in parallel
       → Each agent uses specific tools → State tracked throughout
       → Failed tasks retry → Final output assembled → User sees everything
```

---

## What Is an Agent?

### Yes, an agent is a Python script

But it's structured differently than traditional code.

#### Traditional Code (Hardcoded Steps):
```python
def process_task(task):
    result1 = fetch_data(task.id)        # You decide this step
    result2 = analyze(result1)           # You decide this step
    result3 = format(result2)            # You decide this step
    return result3
```

**You decide the steps ahead of time.** The code just executes them in order.

#### Agent Code (Dynamic Decisions):
```python
def run_agent(task):
    context = task  # What we're trying to do
    tools = [search, analyze, format, email, etc]  # What we CAN do
    
    while not done:
        # Agent uses an LLM to decide the NEXT step
        decision = llm.ask("Given this context and these tools, what should I do next?")
        
        # Agent executes the decision
        result = execute_tool(decision.tool, decision.params)
        
        # Agent updates context
        context = context + result
        
        # Check if done
        done = llm.ask("Are we done with the goal?")
    
    return context
```

**The LLM decides the steps dynamically.** You just provide tools and a goal.

---

## How Agents Make Decisions

### Through an LLM (Large Language Model) like GPT-4o-mini

The agent doesn't "think" in the human sense—it uses an LLM to evaluate the current state and decide what to do next.

#### Example Walkthrough:
```
Agent context: "Research AI startups in healthcare and write a summary"
Available tools: [google_search, read_url, summarize_text, format_report]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

LLM Prompt:
"I need to research AI startups. What should I do first?"
↓
LLM Response: "Use google_search to find startups"

Action: google_search("AI startups healthcare 2026")
Result: [10 AI startups with names and URLs]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

LLM Prompt:
"I have a list of startups. What should I do next?"
↓
LLM Response: "Read the websites to get detailed info"

Action: read_url("startup1.com")
Result: [startup details: funding, team, tech]

Action: read_url("startup2.com")
Result: [startup details]

... (repeat for all startups)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

LLM Prompt:
"I have detailed data on all startups. What should I do next?"
↓
LLM Response: "Analyze the data to find patterns and trends"

Action: analyze(all_startup_data)
Result: [trends: funding focus, team backgrounds, etc]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

LLM Prompt:
"I have data, details, and trends. Write a summary now."
↓
LLM Response: "Write the final report"

Action: summarize_text(all_data)
Result: "Summary: These startups focus on..."

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

LLM Prompt:
"Are we done with the goal?"
↓
LLM Response: "Yes, the summary is complete"

Status: Done
Return: Final report to user
```

---

## How the System Breaks Tasks into 5 Tasks

The **Planner Agent** does this. It's another LLM call that reads the goal and decides what subtasks are needed.

### The Flow:

```python
# User submits
workflow_input = "Research AI startups and generate a market analysis"

# Planner Agent (an LLM call) breaks it down
planner_prompt = """
You are a workflow planner. 
Goal: Research AI startups and generate a market analysis
Break this into 3-5 concrete, executable tasks.
Each task should be simple (one executor agent can do it).

Return as JSON:
[
  {"task": "Search for AI startup databases", "tools": ["search", "browse"]},
  {"task": "Extract key startup info", "tools": ["parse", "extract"]},
  {"task": "Analyze market trends", "tools": ["analyze"]},
  {"task": "Write market analysis report", "tools": ["summarize", "format"]}
]
"""

tasks = llm.ask(planner_prompt)

# Output:
# Task 1: Search for AI startup databases
# Task 2: Extract key startup info (funding, team, tech)
# Task 3: Analyze market trends
# Task 4: Write market analysis report
# Task 5: Format and deliver final report
```

### Why 5 Tasks and Not 2?

The LLM (trained on lots of data) knows that breaking complex work into smaller steps is better because:
- **Simpler to execute** — each task has a clear goal
- **Easier to retry** — if Task 2 fails, only retry Task 2
- **Trackable** — you can see progress
- **Parallelizable** — tasks can run simultaneously

---

## Your Project Phase 1 Loop

This is how everything connects in your system:

```
User submits workflow
        ↓
API receives: "Research AI startups and write summary"
        ↓
Create Workflow record in database
        ↓
PlannerAgent.plan(workflow_input)
        ↓
LLM decides: "Need 4 tasks"
        ↓
Create 4 Task records in database
        ↓
Queue each task in Redis
        ↓
Worker picks Task 1 from queue
        ↓
ExecutorAgent for Task 1
        ↓
LLM decides: "Use search tool"
        ↓
Execute: search_tool(query)
        ↓
Get: [list of startups]
        ↓
LLM decides: "Use read_url tool"
        ↓
Execute: read_url(startup_url)
        ↓
Get: [startup details]
        ↓
LLM decides: "Task 1 complete"
        ↓
Mark Task 1 as done in database
        ↓
Worker picks Task 2 from queue
        ↓
... (ExecutorAgent for Task 2, 3, 4)
        ↓
All tasks done
        ↓
Planner assembles results
        ↓
Return final report to user
        ↓
User sees: Full execution log + final output
```

---

## Key Concepts

| Concept | What It Means | Your Project |
|---------|---------------|--------------|
| **Agent autonomy** | Agent decides what to do next, not a hardcoded script | Planner decides workflow steps; executor decides tool usage |
| **Tool use** | Agents call external functions/APIs, not just talk | Agents call search, databases, APIs via tools |
| **State management** | Track what happened, decisions made, errors | Workflows & tasks tables in PostgreSQL |
| **Planning** | Break complex goals into subtasks | PlannerAgent creates multiple tasks from one workflow |
| **Error recovery** | Retry failures, handle exceptions gracefully | Retry logic + execution logs |
| **Multi-step reasoning** | Don't solve everything in one call | Multiple agents over multiple tasks |
| **Observability** | See what the agent did and why | Execution logs show every decision and tool call |

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────┐
│                    Frontend (React)                  │
│              User submits workflow goal               │
└──────────────┬───────────────────────────────────────┘
               │
               ↓
┌──────────────────────────────────────────────────────┐
│                API Gateway (FastAPI)                 │
│          POST /workflows/   GET /workflows/{id}       │
└──────────────┬───────────────────────────────────────┘
               │
               ↓
┌──────────────────────────────────────────────────────┐
│          Workflow Engine (Python)                    │
│   - PlannerAgent (breaks into tasks)                 │
│   - Task creation and queuing                        │
└──────────────┬───────────────────────────────────────┘
               │
               ↓
┌──────────────────────────────────────────────────────┐
│         Task Queue (Redis)                           │
│   - Stores pending tasks                             │
│   - Distributes to workers                           │
└──────────────┬───────────────────────────────────────┘
               │
               ↓
┌──────────────────────────────────────────────────────┐
│      Worker Processes (Python)                       │
│   - ExecutorAgent (picks task, calls tools)          │
│   - Tool execution                                   │
│   - Logging and state updates                        │
└──────────────┬───────────────────────────────────────┘
               │
               ↓
┌──────────────────────────────────────────────────────┐
│   Database (PostgreSQL)                              │
│   - workflows table                                  │
│   - tasks table                                      │
│   - execution_logs table                             │
└──────────────────────────────────────────────────────┘
```

---

## Why This Teaches Real Agentic AI

This project forces you to learn:

| Skill | Why It Matters |
|-------|----------------|
| **APIs & HTTP** | How systems communicate; your frontend will talk to your backend |
| **Async systems** | Tasks run in the background; users don't wait |
| **Queues** | Distribute work; handle spikes; retry failures |
| **Orchestration** | Coordinate multiple agents and tasks |
| **Agent reasoning** | How LLMs decide the next action |
| **Databases** | Persist workflow state across restarts |
| **Scaling** | From single worker to many workers |
| **Deployment** | Docker, Docker Compose, cloud platforms |
| **Observability** | Logs, traces, monitoring |
| **Error handling** | Retries, fallbacks, graceful degradation |

---

## What's Next?

Once you've internalized this:

1. **Phase 1 Build**: FastAPI API + PlannerAgent + ExecutorAgent + Queue + Worker
2. **Phase 1 Test**: Submit a workflow, see it break into tasks, see agents execute them
3. **Phase 2**: Add memory, vector search, more sophisticated planning
4. **Phase 3**: Distributed workers, real tool registry, observability
5. **Phase 4+**: RBAC, multi-user, UI, evaluation, model routing

Start small. Build iteratively. Let each phase teach you the next.

---

## Quick Reference: Agents in Your Code

### PlannerAgent
- **Purpose**: Break a complex goal into subtasks
- **Input**: User workflow goal
- **Output**: List of tasks with names, descriptions, required tools
- **Decision process**: LLM reads goal → suggests task breakdown

### ExecutorAgent
- **Purpose**: Execute one task by calling tools
- **Input**: Task description, available tools
- **Output**: Task result
- **Decision process**: LLM reads task + tools → chooses which tool → executes → checks if done

### The Loop
```python
while workflow_not_done:
    task = get_next_task()
    executor = ExecutorAgent(task)
    result = executor.execute()  # LLM makes decisions here
    save_result(result)
    mark_task_done()
```

---

## How Frontend, Backend, and Workers Work Together

### Frontend (React/Next.js)
- Presents the UI to the user.
- Lets the user submit workflow goals.
- Calls backend REST endpoints like `POST /workflows/` and `GET /workflows/{id}`.
- Displays workflow status, task progress, logs, and final output.

### Backend (FastAPI)
- Receives requests from the frontend.
- Validates input and stores workflow/task records in the database.
- Creates tasks and enqueues them for execution.
- Exposes endpoints for status checks and results retrieval.

### Worker / Queue / Database
- The worker reads tasks from the queue (Redis or a simple in-memory queue).
- It executes the task logic, which may use agent reasoning and tools.
- It updates task status and writes results back to the database.
- The backend reads from the database when the frontend asks for status.

### Simple flow example
1. User submits workflow through React.
2. React sends `POST /workflows/` with the goal.
3. FastAPI creates the workflow and tasks in PostgreSQL.
4. FastAPI adds tasks to Redis.
5. Worker picks up a task and executes it.
6. Worker updates task status in PostgreSQL.
7. Frontend polls or refreshes `GET /workflows/{id}`.
8. User sees progress and output.

---

## What a Team Lead Decides First

As a project lead, after defining the objective, the next decisions are:

1. **Who is the user?**
   - Internal engineer? Product manager? External customer?
   - That determines the UI and feature expectations.

2. **What is the MVP?**
   - The smallest useful product that delivers real value.
   - For this project, the MVP is: submit a workflow, create tasks, execute them asynchronously, store results, and show status.

3. **What are the success criteria?**
   - Example: API accepts workflow requests, tasks run, failures retry, and status is visible.
   - This prevents scope creep and keeps the team focused.

4. **What is the architecture boundary?**
   - Frontend for UI
   - Backend for API and orchestration
   - Worker for execution
   - Queue for task distribution
   - Database for persistence

5. **What should we build first?**
   - Build the backend API and data model first.
   - Then add the worker and queue.
   - Then build the frontend to use the API.

---

## First Practical Build Steps

These are the exact first components to create:

1. **Database model**
   - `workflows` table
   - `tasks` table
   - `execution_logs` table

2. **Backend API**
   - `POST /workflows/` to start a workflow
   - `GET /workflows/{workflow_id}` to read workflow state
   - `GET /tasks/{task_id}` to read task state

3. **Worker**
   - A simple process that reads queued tasks and executes them
   - Update task status to `running`, `failed`, or `done`

4. **Frontend UI**
   - A form to submit workflow goals
   - A page to show workflow and task progress
   - A page to show final output and logs

---

## Why this order matters

- **Backend first** gives you a working API that can be tested independently.
- **Worker next** makes the system execute tasks, which is the core behavior.
- **Frontend last** lets you build a usable interface on a stable backend.

This approach makes the project manageable and helps you learn each layer step by step.

---

## Phase 1 Task List and Reasoning

### Phase 1 objective
Build a minimum viable workflow platform where:
- the user can submit a workflow request via a simple UI,
- FastAPI receives the request and records it,
- one worker picks up the task and executes it,
- the system stores status and result,
- the UI can show progress and output.

### Task 1: Define the data model and API contract
- Create the database schema for `workflows`, `tasks`, and `execution_logs`.
- Decide what data each record stores.
- Define the first REST endpoints:
  - `POST /workflows/`
  - `GET /workflows/{workflow_id}`
  - `GET /tasks/{task_id}`

**Reasoning:** This is the foundation. If the data model and API contract are clear, the rest of the system can be built in layers.

### Task 2: Implement the backend workflow creation
- Build the FastAPI endpoint for `POST /workflows/`.
- Validate the incoming request and create a workflow record.
- Create one or more task records for the workflow.
- Return the workflow ID and initial status.

**Reasoning:** The first vertical slice should handle input from the user and persist the workflow. This proves the API and database flow end to end.

### Task 3: Add a simple task queue and worker loop
- Start with a simple in-memory queue or a single Redis list.
- Build one worker that reads tasks and executes them.
- Update task status to `running`, `completed`, or `failed`.
- Write a placeholder task executor that can run a simple action.

**Reasoning:** The worker is the core engine. A single worker proves the async execution model before adding complexity.

### Task 4: Store execution results and logs
- Save the task output and execution logs to the database.
- Link logs to the workflow and task records.
- Make sure failures are recorded with an error message.

**Reasoning:** The platform is only useful if you can inspect what happened. Logs and results are critical for debugging and verification.

### Task 5: Implement status query endpoints
- Build `GET /workflows/{workflow_id}` to return workflow and task progress.
- Build `GET /tasks/{task_id}` for task-level details.
- Return clear status fields: `pending`, `running`, `completed`, `failed`.

**Reasoning:** Users need feedback. Status endpoints make the system observable and support the UI.

### Task 6: Build a minimal frontend UI
- Create a very simple UI with one form to submit workflow requests.
- Add a results page or panel to show workflow status and final output.
- Use the backend REST API to submit the request and fetch status.

**Reasoning:** The UI ties the system together and gives you a real product feel, even if it is simple.

### Task 7: Validate the end-to-end flow
- Submit a workflow through the UI.
- Confirm the backend creates the workflow and tasks.
- Confirm the worker executes the task.
- Confirm the UI shows status and final output.

**Reasoning:** A working end-to-end flow is the true MVP. It proves that the pieces can talk to each other.

---

## Beginner concepts: endpoints, databases, and architecture

### What is an endpoint?
An endpoint is a URL that the frontend uses to talk to the backend.
- The backend exposes endpoints like `POST /workflows/` and `GET /workflows/{id}`.
- The frontend sends data to these URLs and receives JSON back.
- Think of an endpoint as a door in your backend that accepts requests and returns responses.

### What is a database?
A database is where your app stores information so it can remember it later.
- For this project, you store workflows, tasks, and logs in the database.
- The backend writes data when something happens, and reads data when someone asks for it.
- The database is not the code itself; it is the storage behind your system.

### What is architecture?
Architecture is the plan for how all the pieces fit together.
- It is not code, it is the structure of the system.
- For your project, the architecture defines:
  - the frontend UI,
  - the backend API,
  - the worker that executes tasks,
  - the queue that passes work, and
  - the database that stores state.
- Good architecture means each part has a clear job and the system is easy to understand.

### How to think about it as a beginner
- The frontend is what the user sees.
- The backend is the server that handles requests.
- The endpoint is the specific function on the backend the frontend calls.
- The database is where the backend saves and reads the data.
- The worker is the background engine that does the actual task work.

### Simple analogy
- User = customer
- Frontend = waiter taking the order
- Endpoint = the menu item the waiter chooses
- Backend = kitchen manager receiving the order
- Database = order ticket and order history
- Worker = cook preparing the dish
- Result = the finished meal returned to the customer

---

## Why start here?

- **Smallest useful slice:** You get a working product with minimal features.
- **Fast feedback:** You can test the full path early.
- **Low risk:** You avoid adding agents, memory, or distributed systems too soon.
- **Build confidence:** Once Phase 1 works, you can extend with real planning and task breakdown.

This is the right start for a Phase 1 MVP, because it delivers a functioning workflow platform without over-engineering.

```

---

## Recommended Reading

After you build Phase 1, look into:
- **LangChain**: Tool calling and agent frameworks
- **LangGraph**: State machine for agent workflows
- **OpenAI Assistants API**: Multi-turn agent conversations
- **ReAct pattern**: Reasoning + Acting (what your agents do)

---

**Created on**: May 17, 2026  
**Purpose**: Reference guide for agentic AI learning project  
**Next Step**: Build Phase 1 with the manager agent's guidance
