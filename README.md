# kapsl

```
pip install kapsl
```

```python
from kapsl import Agent, tool, Client

@tool
def search(query: str) -> str:
    """Search the web."""
    return f"results for {query}"

Client().deploy(Agent(name="researcher", tools=[search]))
print(Client().run("researcher", "What is Kapsl?").wait())
```

Type hints become the schema. Docstrings become descriptions. `requirements=["requests"]` gets its own venv.

---

Python SDK for [Kapsl](https://kapsl.xyz) — the agent runtime.

Kapsl daemon required: `curl -fsSL https://kapsl.xyz/install.sh | sh && kapsl start`
