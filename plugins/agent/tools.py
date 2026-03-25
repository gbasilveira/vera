"""
Tool implementations for the template plugin.

MANDATORY RULES (enforced by vera lint):
  1. All tool functions MUST be async def
  2. First parameter MUST be deps (VeraDeps instance — not RunContext in direct calls)
  3. All inputs/outputs MUST be Pydantic BaseModel subclasses (no raw dict)
  4. External tools MUST set external=True in register_tool() call
  5. NEVER import openai/anthropic/ollama here — use deps.run_tool('llm.*')
  6. NEVER use os.environ — use deps.secrets.get('plugin.key')
"""
from plugins._template.schemas import DoThingInput, DoThingOutput


async def do_thing(deps, input: DoThingInput) -> DoThingOutput:
    """
    Example tool. Replace with real implementation.
    deps is a VeraDeps instance injected by the kernel.
    All middleware (auth, PII, audit) runs automatically.
    """
    # Example: call another tool
    # result = await deps.run_tool('llm.generate_structured', prompt=input.prompt, schema=MySchema)

    return DoThingOutput(result=f"processed: {input.value}")