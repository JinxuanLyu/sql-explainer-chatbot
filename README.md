# SQL Query Explainer

## Topic
A narrow-domain chatbot that explains SQL query mechanics for:
- SELECT
- FROM
- WHERE
- JOIN (INNER / LEFT)
- GROUP BY
- COUNT, SUM, AVG, MIN, MAX
- Basic SQL concept questions (e.g., “What does SELECT do?”)

The assistant always:
- Uses structured bullet points
- Ends with: `Clause Summary: ...`
- Does not execute queries or assume schema

---

## Out-of-Scope Categories

The system defines 3 explicit out-of-scope types:

1) **OOS_NON_SQL** – Non-SQL questions  
2) **OOS_MISSING_QUERY** – Asked to explain but no query provided  
3) **OOS_ADVANCED_SQL** – CTEs, window functions, HAVING, UNION, FULL/RIGHT JOIN, DDL/DML  

Each returns a fixed structured refusal message.

---
## Project Structure

app/
-- main.py: FastAPI server
--guardrails.py: routing + OOS handling + deterministic checks
--llm.py: LLM call + post-generation backstop
--prompt.py: system prompt (persona + few-shot)
--index.html: frontend UI

eval/
--dataset.json: 20+ test cases
--run_eval.py: evaluation runner

Dockerfile
cloudbuild.yaml
pyproject.toml

---
## Run locally (uv)
(I gave permission to my project)

```bash
uv sync
gcloud auth application-default login
gcloud config set project ieor-4576-jinxuan
uv run uvicorn app.main:app --reload --port 8080
```

## Run on Google Shell:
```uv run uvicorn app.main:app --reload --port 8080
```


## Run Eval
```uv run python -m eval.run_eval
```

---
## Live URL
https://sql-explainer-chatbot-192593734991.us-central1.run.app/
