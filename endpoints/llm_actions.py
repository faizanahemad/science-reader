"""
Ephemeral LLM actions (non-persistent utilities).

This module hosts helper functions used by endpoints for one-off / temporary
LLM operations that should not live in `server.py`.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Optional


def direct_temporary_llm_action(
    *,
    keys: Any,
    action_type: str,
    selected_text: str,
    user_message: str = "",
    history: Optional[list[dict]] = None,
) -> Iterable[str]:
    """
    Direct LLM call for temporary actions when no conversation context is available.

    Parameters
    ----------
    keys:
        Auth/API key bundle (as produced by `endpoints.utils.keyParser(session)`).
    action_type:
        One of: explain, critique, expand, eli5, ask_temp.
    selected_text:
        The selected text that the action should operate on.
    user_message:
        Optional user prompt (used for ask_temp).
    history:
        Optional list of previous messages (used for ask_temp). Each item is
        expected to look like: {"role": "user"|"assistant", "content": "..."}.

    Yields
    ------
    str
        Streaming text chunks from the model.
    """

    from call_llm import CallLLm
    from common import EXPENSIVE_LLM

    prompts: dict[str, str] = {
        "explain": f"""You are an expert educator. Please explain the following text clearly and thoroughly.

**Text to explain:**
```
{selected_text}
```

Provide a clear, comprehensive explanation that:
1. Breaks down complex concepts
2. Uses simple language where possible
3. Provides examples or analogies when helpful
4. Highlights key points and their significance

Your explanation:""",
        "critique": f"""You are a critical analyst. Please provide a thoughtful critique of the following text.

**Text to critique:**
```
{selected_text}
```

Analyze this text by considering:
1. Strengths and weaknesses
2. Logical consistency
3. Missing information or gaps
4. Potential biases or assumptions
5. Areas for improvement

Your critique:""",
        "expand": f"""You are a knowledgeable expert. Please expand on the following text with more details and depth.

**Text to expand:**
```
{selected_text}
```

Provide an expanded version that:
1. Adds more context and background
2. Explores related concepts
3. Provides additional examples
4. Discusses implications and applications
5. Connects to broader topics

Your expanded explanation:""",
        "eli5": f"""You are explaining to a curious 5-year-old. Please explain the following text using simple words, fun analogies, and clear examples.

**Text to explain simply:**
```
{selected_text}
```

Rules for your explanation:
1. Use very simple words a child would understand
2. Use fun analogies (like toys, animals, or everyday things)
3. Be engaging and friendly
4. Break things into tiny, easy steps
5. Include a simple "the big idea is..." summary at the end

Your simple explanation:""",
        "ask_temp": f"""You are a helpful assistant having a conversation. The user has selected some text and wants to discuss it.

**Selected text for context:**
```
{selected_text}
```

**User's question/message:**
{user_message}

Please respond helpfully and conversationally:""",
    }

    if action_type == "ask_temp" and history:
        history_text = "\n\n**Previous conversation:**\n"
        for msg in history:
            role = "User" if msg.get("role") == "user" else "Assistant"
            history_text += f"{role}: {msg.get('content', '')}\n"
        prompts["ask_temp"] = prompts["ask_temp"].replace(
            "**User's question/message:**",
            history_text + "\n**User's latest question/message:**",
        )

    prompt = prompts.get(action_type, prompts["explain"])

    llm = CallLLm(keys, model_name=EXPENSIVE_LLM[2], use_gpt4=False, use_16k=False)
    response_stream = llm(
        prompt,
        images=[],
        temperature=0.4,
        stream=True,
        max_tokens=2000,
        system="You are a helpful, clear, and engaging assistant. Respond concisely but thoroughly.",
    )

    for chunk in response_stream:
        if chunk:
            yield chunk


