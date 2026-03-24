# kapsl

Python SDK for [Kapsl](https://kapsl.xyz) — the agent runtime.

Define agents with `@tool` functions. Deploy them. Run them. The runtime handles execution, persistence, retries, and crash recovery.

## Install

```bash
pip install kapsl
```

You also need the Kapsl daemon running:

```bash
curl -fsSL https://kapsl.xyz/install.sh | sh
kapsl start
```

## Quick start

```python
from kapsl import Agent, tool, Client

@tool
def search(query: str) -> str:
    """Search the web for information."""
    return f"results for {query}"

agent = Agent(
    name="researcher",
    system="You are a research assistant.",
    tools=[search],
)

client = Client()
client.deploy(agent)

run = client.run("researcher", "What is Kapsl?")
print(run.wait())
```

`run.wait()` streams step-by-step progress to stderr and returns the final output.

## Tools

Decorate any function with `@tool`. Type hints and docstrings become the schema — no manual JSON Schema needed.

```python
@tool
def get_weather(city: str, units: str = "celsius") -> str:
    """Get current weather for a city.

    Args:
        city: City name.
        units: Temperature units (celsius or fahrenheit).
    """
    return requests.get(f"https://weather.api/v1/{city}?units={units}").text
```

Supports: `str`, `int`, `float`, `bool`, `list[T]`, `dict[str, T]`, `Optional[T]`, and nested combinations.

## Dependencies

Agents that need third-party packages:

```python
agent = Agent(
    name="scraper",
    system="You scrape websites.",
    tools=[scrape],
    requirements=["beautifulsoup4", "requests"],
)
```

The runtime creates an isolated venv per agent at deploy time.

## Client API

```python
client = Client(base_url="http://127.0.0.1:50051")  # default

# Deploy
client.deploy(agent)

# Run
run = client.run("researcher", "query")
result = run.wait()              # blocks, streams progress to stderr
result = run.wait(on_event=None) # blocks, no progress output

# Inspect
run.status   # "completed", "failed", etc.
run.output   # final output value
```

## Requirements

- Python 3.10+
- A running Kapsl daemon (`kapsl start`)
- `ANTHROPIC_API_KEY` set in the daemon's environment

## Links

- [Kapsl](https://kapsl.xyz) — the agent runtime
- [PyPI](https://pypi.org/project/kapsl/)
