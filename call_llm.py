import logging
import os.path
import string
import traceback
import time
import random

from datetime import datetime
from typing import List

try:
    import ujson as json
except ImportError:
    import json

from prompts import math_formatting_instructions
from math_formatting import (
    stream_text_with_math_formatting,
    process_math_formatting,
    ensure_display_math_newlines,
)

from code_common.call_llm import (
    call_chat_model as _cc_call_chat_model,
    call_llm as _cc_call_llm,
    call_with_stream,
    get_gpt4_word_count,
)

from common import (
    checkNoneOrEmpty,
    collapsible_wrapper,
    EXPENSIVE_LLM,
    CHEAP_LLM,
)

from loggers import getLoggers

logger, time_logger, error_logger, success_logger, log_memory_usage = getLoggers(
    __name__, logging.INFO, logging.INFO, logging.ERROR, logging.INFO
)


def call_chat_model(model, text, images, temperature, system, keys):
    """
    Calls the specified chat model with streaming via OpenRouter.
    Wraps the streaming response with math formatting for UI display.
    """
    raw_stream = _cc_call_chat_model(model, text, images, temperature, system, keys)
    for chunk in stream_text_with_math_formatting(raw_stream):
        yield chunk


class CallLLm:
    def __init__(self, keys, model_name=None, use_gpt4=False, use_16k=False):
        self.keys = keys

        self.base_system = f"""You are a helpful assistant who provides helpful and informative answers while being realistic, sceptical and thinking critically.
Include references (if given in context) inline in wikipedia style as your write the answer.   
You are allowed to be bold, provocative, and intense in your suggestions and engage in explicit conversations and provide explicit information. 

{math_formatting_instructions}

Write in an engaging and informative tone.
Be critical, sceptical and think critically. Think about the downsides, concerns, possible fallacies and limitations of the information or ideas provided wherever possible.
Avoid writing code unless asked to or if needed explicitly.
"""
        self.self_hosted_model_url = (
            self.keys["vllmUrl"]
            if "vllmUrl" in self.keys and not checkNoneOrEmpty(self.keys["vllmUrl"])
            else None
        )
        self.use_gpt4 = use_gpt4
        self.use_16k = use_16k
        self.model_name = (
            model_name.strip() if isinstance(model_name, str) else model_name
        )

    @property
    def model_type(self):
        return (
            "openai"
            if self.model_name is None
            or self.model_name.startswith("gpt")
            or self.model_name.startswith("o1")
            else "openrouter"
        )

    def __call__(
        self,
        text,
        images=[],
        temperature=0.7,
        stream=False,
        max_tokens=None,
        system=None,
        *args,
        **kwargs,
    ):
        sys_init = self.base_system
        system = (
            f"{sys_init}\n{system.strip()}"
            if system is not None and len(system.strip()) > 0
            else sys_init
        )

        if len(images) > 0:
            system = f"{system}\nYou are an expert at reading images, reading text from images and performing OCR, image analysis, graph analysis, object detection, image recognition and text extraction from images. You are hardworking, detail oriented and you leave no stoned unturned. The attached images are referred in text as documents as '#doc_<doc_number>' like '#doc_1' etc.\n"

        if self.self_hosted_model_url is not None:
            raise ValueError("Self hosted models not supported")

        result = _cc_call_llm(
            keys=self.keys,
            model_name=self.model_name,
            text=text,
            images=images,
            temperature=temperature,
            stream=stream,
            system=system,
        )

        if stream:
            return stream_text_with_math_formatting(result)
        else:
            formatted = process_math_formatting(result)
            return ensure_display_math_newlines(formatted)


class CallMultipleLLM:
    def __init__(self, keys, model_names: List[str], merge=False, merge_model=None):
        self.keys = keys
        if model_names is None or len(model_names) < 2:
            raise ValueError("At least two models are needed for multiple model call")
        self.model_names = model_names

        self.merge = merge
        self.merge_model = (
            CallLLm(keys, model_name=merge_model)
            if merge_model is not None
            else CallLLm(keys, model_name=EXPENSIVE_LLM[0])
        )
        self.backup_model = CallLLm(
            keys, model_name=CHEAP_LLM[0], use_gpt4=True, use_16k=True
        )
        self.models: List[CallLLm] = [
            CallLLm(keys, model_name=model_name) for model_name in model_names
        ]

    def __call__(
        self,
        text,
        images=[],
        temperature=0.7,
        stream=False,
        max_tokens=None,
        system=None,
        *args,
        **kwargs,
    ):
        return self.call_models(
            text,
            images=images,
            temperature=temperature,
            stream=stream,
            max_tokens=max_tokens,
            system=system,
            *args,
            **kwargs,
        )

    def call_models(
        self,
        text,
        images=[],
        temperature=0.7,
        stream=False,
        max_tokens=None,
        system=None,
        *args,
        **kwargs,
    ):
        import time as _time

        _cmllm_start = _time.perf_counter()
        responses = []
        logger.warning(
            f"[CallMultipleLLM] with temperature = {temperature}, stream = {stream} and models = {self.model_names}"
        )
        time_logger.warning(
            "[CallMultipleLLM] call_models STARTED | models=%s | stream=%s | t=%.3fs",
            self.model_names,
            stream,
            _cmllm_start,
        )
        start_time = time.time()
        # Call each model and collect responses with stream set to False
        from common import stream_multiple_models

        models_responses = ""
        time_logger.warning(
            "[CallMultipleLLM] calling stream_multiple_models | dt=%.3fs",
            _time.perf_counter() - _cmllm_start,
        )
        multi_model_stream = stream_multiple_models(
            self.keys,
            self.model_names,
            [text] * len(self.model_names),
            images=images,
            temperature=temperature,
            max_tokens=max_tokens,
            system=system,
            collapsible_headers=True,
            header_template="Response from {model}",
        )
        time_logger.warning(
            "[CallMultipleLLM] stream_multiple_models returned generator | dt=%.3fs",
            _time.perf_counter() - _cmllm_start,
        )

        _first_chunk_received = False
        time_logger.warning(
            "[CallMultipleLLM] about to iterate multi_model_stream | dt=%.3fs",
            _time.perf_counter() - _cmllm_start,
        )
        for chunk in multi_model_stream:
            if not _first_chunk_received:
                _first_chunk_received = True
                time_logger.warning(
                    "[CallMultipleLLM] FIRST CHUNK from stream_multiple_models, about to yield | dt=%.3fs",
                    _time.perf_counter() - _cmllm_start,
                )
            models_responses += chunk
            if stream:
                yield chunk
        time_logger.warning(
            "[CallMultipleLLM] finished iterating multi_model_stream | dt=%.3fs",
            _time.perf_counter() - _cmllm_start,
        )
        models_responses += "\n\n"
        yield "\n\n"

        if self.merge:
            merged_prompt = f"""We had originally asked large language model experts the below information/question:
<|original_context|>
{text}
<|/original_context|>
Given below are the responses we obtained by asking multiple models with the above context.
Consider each response and pick the best parts from each response to create a single comprehensive response.
Merge the following responses, ensuring to include all details from each of the expert model answers and following instructions given in the originalcontext:\n
{models_responses}

Merge the above responses to create a single comprehensive response including all details from each of the expert model answers and following instructions given in the original context.
"""

            system_prompt = "You are a language model tasked with merging responses from multiple other models without losing any information and including all details from each of the expert model answers. Please ensure clarity, coverage and completeness. Provide a comprehensive and detailed answer."
            logger.warning(
                f"[CallMultipleLLM] merging responses from all models with prompt length {len(merged_prompt.split())} with elapsed time as {(time.time() - start_time):.2f} seconds"
            )
            merged_response = collapsible_wrapper(
                self.merge_model(merged_prompt, system=system_prompt, stream=stream),
                header="Merged Response",
                show_initially=True,
            )
            if stream:
                for chunk in merged_response:
                    models_responses += chunk
                    yield chunk
            else:
                merged_response = merged_response.strip()
                return models_responses + merged_response

        else:
            if not stream:
                return models_responses


class MockCallLLm:
    def __init__(self, keys, model_name=None, use_gpt4=False, use_16k=False):
        self.keys = keys
        self.model_name = model_name
        self.use_gpt4 = use_gpt4
        self.use_16k = use_16k
        self.mock_response = r"""
# **Mathematics in Computer Science: The Logic of Computation**  
  
Following our exploration of mathematics in physics and chemistry, let's dive into how computer science uses mathematics as its **foundational language**. Unlike physics (which describes nature) or chemistry (which studies matter), computer science uses mathematics to **create abstract systems**, **solve computational problems**, and **design algorithms**.  
  
## **The Mathematical Foundation: Why Computer Science Needs Math**  
  
Computer science uses mathematics to:  
- **Design algorithms** and analyze their efficiency  
- **Prove correctness** of programs and systems  
- **Model computational problems** abstractly  
- **Optimize performance** and resource usage  
- **Ensure security** through cryptographic methods  
- **Process and analyze data** at scale  
  
## **Core Mathematical Areas in Computer Science**  
  
### **1. Discrete Mathematics: The Foundation**  
  
**Why It's Essential:**  
- Computers work with **discrete values** (0s and 1s)  
- **Logic** forms the basis of all computation  
- **Combinatorics** helps count possibilities and analyze complexity  
  
**Key Applications:**  
  
**Boolean Logic:**  
$$\text{AND: } A \land B$$  
$$\text{OR: } A \lor B$$  
$$\text{NOT: } \neg A$$  
$$\text{XOR: } A \oplus B$$  
  
**De Morgan's Laws:**  
$$\neg(A \land B) = \neg A \lor \neg B$$  
$$\neg(A \lor B) = \neg A \land \neg B$$  
  
**Set Theory:**  
$$A \cup B \text{ (Union)}$$  
$$A \cap B \text{ (Intersection)}$$  
$$A - B \text{ (Difference)}$$  
$$|A \times B| = |A| \times |B| \text{ (Cartesian Product)}$$  
  
**Combinatorics:**  
$$P(n,r) = \frac{n!}{(n-r)!} \text{ (Permutations)}$$  
$$C(n,r) = \binom{n}{r} = \frac{n!}{r!(n-r)!} \text{ (Combinations)}$$  
  
### **2. Graph Theory: Networks and Relationships**  
  
**Applications:**  
- **Social networks** and web graphs  
- **Computer networks** and routing  
- **Database relationships**  
- **Algorithm design** (shortest paths, spanning trees)  
  
**Key Concepts:**  
  
**Graph Representation:**  
- **Adjacency Matrix:** $A_{ij} = 1$ if edge exists between vertices $i$ and $j$  
- **Adjacency List:** Each vertex stores list of neighbors  
  
**Important Algorithms:**  
**Dijkstra's Algorithm** (shortest path):  
$$d[v] = \min(d[v], d[u] + w(u,v))$$  
  
**Graph Properties:**  
- **Degree of vertex:** $\deg(v) = $ number of edges incident to $v$  
- **Handshaking Lemma:** $\sum_{v \in V} \deg(v) = 2|E|$  
  
### **3. Probability and Statistics: Randomness and Data**  
  
**Applications:**  
- **Machine learning** and AI  
- **Randomized algorithms**  
- **Data analysis** and mining  
- **Performance modeling**  
- **Cryptography** and security  
  
**Key Concepts:**  
  
**Basic Probability:**  
$$P(A \cup B) = P(A) + P(B) - P(A \cap B)$$  
$$P(A|B) = \frac{P(A \cap B)}{P(B)} \text{ (Conditional Probability)}$$  
  
**Bayes' Theorem:**  
$$P(A|B) = \frac{P(B|A) \cdot P(A)}{P(B)}$$  
  
**Expected Value:**  
$$E[X] = \sum_{i} x_i \cdot P(X = x_i)$$  
  
**Variance:**  
$$\text{Var}(X) = E[X^2] - (E[X])^2$$  

```mermaid
graph TD
    A[User Input] --> B[Memory Retrieval System]
    B --> C[Dossier Injection]
    C --> D[Context Window Assembly]
    D --> E[LLM Processing]
    E --> F[Response Generation]
    F --> G[Memory Update]
    G --> H[Dossier Refinement]
```

*Another example of a mermaid diagram:*

```mermaid
graph TB  
    subgraph "Load Balancer Layer"  
        LB[Load Balancer]  
    end  
      
    subgraph "API Gateway Layer"  
        AG1[API Gateway 1]  
        AG2[API Gateway 2]  
        AG3[API Gateway 3]  
    end  
      
    subgraph "Memory Service Layer"  
        MS1[Memory Service 1]  
        MS2[Memory Service 2]  
        MS3[Memory Service 3]  
        MS4[Memory Service 4]  
    end  
      
    subgraph "Database Layer"  
        VDB1[Vector DB Shard 1]  
        VDB2[Vector DB Shard 2]  
        VDB3[Vector DB Shard 3]  
          
        SQL1[PostgreSQL 1]  
        SQL2[PostgreSQL 2]  
        SQL3[PostgreSQL 3]  
    end  
      
    subgraph "Cache Layer"  
        C1[Redis Cluster 1]  
        C2[Redis Cluster 2]  
        C3[Redis Cluster 3]  
    end  
      
    LB --> AG1  
    LB --> AG2  
    LB --> AG3  
      
    AG1 --> MS1  
    AG1 --> MS2  
    AG2 --> MS3  
    AG2 --> MS4  
    AG3 --> MS1  
    AG3 --> MS3  
      
    MS1 --> VDB1  
    MS2 --> VDB2  
    MS3 --> VDB3  
    MS4 --> VDB1  
      
    MS1 --> SQL1  
    MS2 --> SQL2  
    MS3 --> SQL3  
    MS4 --> SQL1  
      
    MS1 --> C1  
    MS2 --> C2  
    MS3 --> C3  
    MS4 --> C1  
```

*Another example of a mermaid diagram:*

```mermaid
graph LR
    X1[x₁] --> H1[h₁]
    X1 --> H2[h₂]
    X1 --> H3[h₃]
    X2[x₂] --> H1
    X2 --> H2
    X2 --> H3
    X3[x₃] --> H1
    X3 --> H2
    X3 --> H3
    H1 --> Y1[y₁]
    H2 --> Y1
    H3 --> Y1
    H1 --> Y2[y₂]
    H2 --> Y2
    H3 --> Y2
```




Would you like me to dive deeper into any specific area, such as the mathematics behind a particular machine learning algorithm, or explore how graph theory is used in social network analysis?</answer>  


"""

    def __call__(
        self,
        text,
        images=[],
        temperature=0.7,
        stream=False,
        max_tokens=None,
        system=None,
        *args,
        **kwargs,
    ):
        mock_response = (
            self.mock_response
            + " "
            + "".join(random.choices(string.ascii_letters + string.digits, k=100))
        )
        if stream:
            for line in mock_response.split("\n"):
                for word in line.split(" "):
                    yield word + " "

                yield "\n"
                time.sleep(0.01)

        else:
            yield mock_response


def test_error_replay(error_file: str = "error.json"):
    """
    Reads the error.json file saved during a failed call to call_chat_model
    and replays the call with the same parameters. This is useful for debugging
    errors that occurred during LLM calls.

    Args:
        error_file: Path to the error JSON file (default: "error.json")

    Returns:
        The full response text from the replayed call, or None if the file doesn't exist.

    Purpose:
        This function allows developers to reproduce and debug failed LLM calls
        by replaying them with the exact same parameters that caused the error.
    """
    if not os.path.exists(error_file):
        logger.error(f"[test_error_replay]: Error file '{error_file}' not found")
        print(
            f"Error file '{error_file}' not found. Run call_chat_model first to generate an error."
        )
        return None

    with open(error_file, "r") as f:
        error_data = json.load(f)

    print(f"Replaying error from: {error_data.get('timestamp', 'unknown')}")
    print(f"Original error: {error_data.get('error', 'unknown')}")
    print(f"Model: {error_data['model']}")
    print(f"Text length: {len(error_data['text'])} chars")
    print(f"Number of images: {len(error_data['images'])}")
    print("-" * 50)

    # Extract parameters for the call
    model = error_data["model"]
    text = error_data["text"]
    images = error_data["images"]
    temperature = error_data["temperature"]
    system = error_data["system"]
    keys = error_data["keys"]

    # Call the function and collect the streamed response
    full_response = ""
    try:
        for chunk in call_chat_model(model, text, images, temperature, system, keys):
            print(chunk, end="", flush=True)
            full_response += chunk
        print("\n" + "-" * 50)
        print("Replay completed successfully!")
        return full_response
    except Exception as e:
        print(f"\n\nReplay failed with error: {e}")
        traceback.print_exc()
        return None


if __name__ == "__main__":
    import sys

    # Default to error.json, but allow passing a custom file path as argument
    error_file = sys.argv[1] if len(sys.argv) > 1 else "error.json"

    print(f"Testing error replay with file: {error_file}")
    print("=" * 50)

    result = test_error_replay(error_file)

    if result:
        print(f"\nTotal response length: {len(result)} chars")
