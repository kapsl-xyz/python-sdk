# kapsl

Python SDK for the [Kapsl](https://kapsl.xyz) agent runtime.

## Install

```bash
pip install kapsl
```

## Quick start

```python
from kapsl import Agent, tool, Client

@tool
def search(query: str) -> str:
    """Search the web."""
    return f"results for {query}"

agent = Agent(
    name="researcher",
    model="claude-sonnet-4-20250514",
    system="You are a research assistant.",
    tools=[search],
)

client = Client()
client.deploy(agent)

run = client.run("researcher", "What is Kapsl?")
print(run.wait())
```

## Requirements

- Python 3.10+
- A running Kapsl daemon (`kapsl start`)
