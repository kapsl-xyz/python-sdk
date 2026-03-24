"""Kapsl Python SDK — define tools, deploy agents, run them."""

from ._tool import tool
from ._client import Client, Run, KapslError

__all__ = ["tool", "Agent", "Client", "Run", "KapslError"]


class Agent:
    """An agent definition with tools, ready to deploy.

    Example::

        from kapsl import tool, Agent, Client

        @tool
        def search(query: str) -> str:
            \"\"\"Search the web.\"\"\"
            return f"results for {query}"

        agent = Agent(name="researcher", system="You are a researcher.", tools=[search])

        client = Client()
        client.deploy(agent)
        run = client.run("researcher", "Find info about Kapsl")
        print(run.wait())
    """

    def __init__(
        self,
        name: str,
        *,
        model: str = "claude-sonnet-4-20250514",
        system: str | None = None,
        tools: list | None = None,
        requirements: list[str] | None = None,
    ):
        self.name = name
        self.model = model
        self.system = system
        self.tools = tools or []
        self.requirements = requirements

        # Validate all tools have the @tool decorator
        for fn in self.tools:
            if not getattr(fn, "_kapsl_tool", False):
                raise ValueError(
                    f"Function '{fn.__name__}' is not decorated with @tool. "
                    f"Add @tool before the function definition."
                )
