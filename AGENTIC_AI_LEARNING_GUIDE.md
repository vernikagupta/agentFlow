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
