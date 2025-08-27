import json
import random
import traceback
from typing import Union, List
import uuid


from common import LONG_CONTEXT_LLM, VERY_CHEAP_LLM, collapsible_wrapper
from prompts import tts_friendly_format_instructions, manager


import os
import tempfile
import shutil
import concurrent.futures
import logging
from openai import OpenAI
from pydub import AudioSegment  # For merging audio files
from code_runner import extract_code, run_code_with_constraints_v2, PersistentPythonEnvironment


# Local imports  
try:
    import sys
    from pathlib import Path
    sys.path.append(str(Path(__file__).parent.parent))
    from prompts import tts_friendly_format_instructions, diagram_instructions, ml_system_design_answer_short
    from base import CallLLm, CallMultipleLLM, simple_web_search_with_llm
    from common import (
        CHEAP_LLM, USE_OPENAI_API, convert_markdown_to_pdf, convert_to_pdf_link_if_needed, CHEAP_LONG_CONTEXT_LLM,
        get_async_future, sleep_and_get_future_result, convert_stream_to_iterable, EXPENSIVE_LLM, stream_multiple_models,
        collapsible_wrapper
    )
    from loggers import getLoggers
except ImportError as e:
    print(f"Import error: {e}")
    raise

import logging
import re
logger, time_logger, error_logger, success_logger, log_memory_usage = getLoggers(__name__, logging.WARNING, logging.INFO, logging.ERROR, logging.INFO)
import time
from .base_agent import Agent
from .search_and_information_agents import MultiSourceSearchAgent, PerplexitySearchAgent, JinaSearchAgent

mathematical_notation = """
- Formatting Mathematical Equations:
    - We are rendering in a markdown website, using mathjax for rendering maths. Write mathjax and website or markdown compatible maths.
    - Prefer using `$ ... $` for inline math and `\\\\[ ... \\\\]` for block math. For multiple lines of equations, use `$$ ... $$` mostly.
    - Output any relevant equations in latex format putting each equation in a new line in separate '$$' environment. If you use `\\[ ... \\]` then use `\\\\` instead of `\\` for making the double backslash. We need to use double backslash so it should be `\\\\[ ... \\\\]` instead of `\\[ ... \\]`.
    - We need to use double backslash so it should be `\\\\[ ... \\\\]` instead of `\\[ ... \\]` and and `\\\\( ... \\\\)` instead of `\\( ... \\)`.

- **Mathematical Notation**:
  - Present equations and formulas using LaTeX in separate `$$` environments or `\\\\( ... \\\\)` notation.
    $$
    \text{{Example Equation: }} E = mc^2
    $$

"""

class CodeSolveAgent(Agent):
    def __init__(self, keys, writer_model: Union[List[str], str], n_steps: int = 4):
        super().__init__(keys)
        self.writer_model = writer_model
        self.n_steps = n_steps
        # 1 step test cases and problem analysis and problem understanding.
        # 1 longer test cases which test corner cases or surprise cases.
        # 1 step solution - TDD
        # 1 step verification of solution
        # execution with asserts on test cases to know which failed and which passed.
        # re-iterate
        self.prompt_1 = f"""
You are an expert coding instructor and interview preparation mentor with extensive experience in software engineering, algorithms, data structures, system design, and technical interviews at top tech companies. You possess deep knowledge of platforms like LeetCode, HackerRank, CodeSignal, and others, along with proven expertise in teaching coding concepts effectively. You teach coding and interview preparation in python and pseudocode.
You are given a query about a coding problem, please help us learn and understand the problem.

{mathematical_notation}

Code is not required at this step. Avoid code.

### 1. Write down the problem statement in a clear way with examples, expected input, output, constraints and other relevant information.
- Use **clear examples**, **analogies** to illustrate concepts.
- What is the problem? What class of problem is it? Can you give a name to the problem?
- What needs to be returned? What is the expected output?
- What are the constraints?
- What are the problem specific things we need to consider and keep in mind?
- Provide **step-by-step explanations** of complex algorithms or logic mentioned in the problem statement.
- When explaining code or algorithms related to interview questions, use code notation to explain and avoid latex notation.
- Talk about other similar or related problems which I might confuse this problem with, and also talk or hint about the differences and their solutions.

### 2. Write down the test cases for the problem.
    - Simple Test cases
    - Corner Cases
    - Edge Cases
    - Surprise Cases
    - Longer test cases.
    - Longer test cases which test corner cases or surprise cases.
    - Think how a contrarian or surprising test case can be which might break the solution and make it fail. The test case should still be valid as per the problem statement.




Query:
<user_query>
{{query}}
</user_query>

The user query above contains the user's query and some context around it including the previous conversation history and retreived documents and web search results if applicable.

Code is not required at this step. Avoid code.
Write your problem understanding and test cases below which expands our understanding of the problem and enhances our learning and helps us prepare for the FAANG coding interviews at senior or staff level.
"""
        
        self.prompt_2 = f"""
You are an expert coding instructor and interview preparation mentor with extensive experience in software engineering, algorithms, data structures, system design, and technical interviews at top tech companies. You possess deep knowledge of platforms like LeetCode, HackerRank, CodeSignal, and others, along with proven expertise in teaching coding concepts effectively. You teach coding and interview preparation in python and pseudocode.
You are given a query about a coding problem, please help us learn and understand the problem.

{mathematical_notation}

Code is not required at this step. Avoid code.

### 1. More complex and harder test cases.
    - Simple Test cases
    - Corner Cases
    - Edge Cases
    - Surprise Cases
    - Longer test cases.
    - Longer test cases which test corner cases or surprise cases.
    - Think how a contrarian or surprising test case can be which might break the solution and make it fail. The test case should still be valid as per the problem statement.



Query:
<user_query>
{{query}}
</user_query>

<problem_understanding>
{{current_answer}}
</problem_understanding>

The user query above contains the user's query and some context around it including the previous conversation history and retreived documents and web search results if applicable.

Code is not required at this step. Avoid code.
Write your test cases below which expands our understanding of the problem and enhances our learning and helps us prepare for the FAANG coding interviews at senior or staff level.
"""
        
        self.prompt_3 = f"""
You are an expert coding instructor and interview preparation mentor with extensive experience in software engineering, algorithms, data structures, system design, and technical interviews at top tech companies. You possess deep knowledge of platforms like LeetCode, HackerRank, CodeSignal, and others, along with proven expertise in teaching coding concepts effectively. You teach coding and interview preparation in python and pseudocode.
You are given a query about a coding problem, please help us learn and understand the problem and then solve it step by step.

{mathematical_notation}

Code is required at this step.
### 1. Write down the solution in verbally, then in pseudocode and then write the code in python.
- Ask potential clarifying questions and then make standard assumptions and then write the solution.
- If no reference solutions are provided, develop the solution yourself and **guide us through it** and also mention that you are developing the solution yourself without any reference.
- Your thinking should be thorough and so it's fine if it's very long. You can think step by step before and after each action you decide to take.
- When no solution is provided, then write the solution yourself. Write a solution and run your solution on the sample data (generate sample data if needed) and check if your solution will work, if not then revise and correct your solution. 
- **Decompose** each solution into manageable and understandable parts.
- Use **clear examples**, **analogies** to illustrate concepts.
- Provide **step-by-step explanations** of complex algorithms or logic.
- Before writing code, write a verbal step by step description of the solution along with the time and space complexity of the solution and any pattern or concept used in the solution. Write in simple language with simple formatting with inline maths and notations (if needed).
- When explaining code or algorithms related to interview questions, use code notation to explain and avoid latex notation.
- Think carefully about the edge cases, corner cases etc.
- Use good coding practices and principles like DRY, KISS, YAGNI, SOLID, encapsulation, abstraction, modularity, etc.
- Use meaningful variable and function names.
- Write unit tests for the solution.
- Use assert statements to verify the correctness of the solution.
- Use comments to explain "why" behind the code in more complex algorithms.
- Use inline comments to explain "what" and "how" of the code.
- Your main python code should be structured in a way that the main solution is separated from the helper functions. 
- The test cases should each be in a separate code block calling the main solution function with the sample test data.
- Test cases should all be executed and their failures logged and finally the test results which failed should be printed. The failed test cases should be printed in a separate section than the successful test cases in code.
- Finally if any test cases failed, after all the test cases have been executed, and details printed, then raise an exception and print the exception message with the all the test results which failed. If all test cases pass, then do not raise an exception.
- The full executable and self-contained code should be written in a single code block in triple backticks in python.
- Write code that needs execution in a single code block.  
- When writing executable code, write full and complete executable code within a single code block even within same message since our code environment is stateless and does not store any variables or previous code/state. 
- When correction is to be made, first look at the current stdout and stderr and then analyse what test cases failed and then correct the pseudocode and logic first.
- For correcting the code if code is already given, analyse what test cases failed and what test cases passed, why and which part of algorithm or logic is wrong and correct the code.


Query:
<user_query>
{{query}}
</user_query>

<problem_understanding>
{{current_answer}}
</problem_understanding>

If code and current stdout and stderr are provided, then analyse them and correct the code if needed. Write the corrected code in a new python code block fully. Write full code in a single code block.

The user query above contains the user's query and some context around it including the previous conversation history and retreived documents and web search results if applicable.
Write your solution below which expands our understanding of the problem and enhances our learning and helps us prepare for the FAANG coding interviews at senior or staff level.
"""
        
    def __call__(self, text, images=[], temperature=0.7, stream=True, max_tokens=None, system=None, web_search=False):
        # Initialize empty current answer
        current_answer = ""
        
        # Execute prompt_1 first as it's the foundation
        llm = CallLLm(self.keys, self.writer_model if isinstance(self.writer_model, str) else self.writer_model[0])
        prompt = self.prompt_1.replace("{query}", text)
        response = llm(prompt, images, temperature, stream=stream, max_tokens=max_tokens, system=system)

        for chunk in collapsible_wrapper(response, header="Problem Understanding", show_initially=True):
            yield chunk
            current_answer += chunk
        
        yield "\n\n---\n\n"
        current_answer += "\n\n---\n\n"

        if self.n_steps >= 3:
            prompt = self.prompt_2.replace("{query}", text).replace("{current_answer}", current_answer)
            random_index = random.randint(0, min(1, len(self.writer_model) - 1))
            llm2 = CallLLm(self.keys, self.writer_model if isinstance(self.writer_model, str) else self.writer_model[random_index])
            response2 = llm2(prompt, images, temperature, stream=stream, max_tokens=max_tokens, system=system)

            for chunk in collapsible_wrapper(response2, header="More complex and harder test cases", show_initially=False):
                yield chunk
                current_answer += chunk
            yield "\n\n---\n\n"
            current_answer += "\n\n---\n\n"

        prompt = self.prompt_3.replace("{query}", text).replace("{current_answer}", current_answer)
        random_index = random.randint(0, min(2, len(self.writer_model) - 1))
        llm3 = CallLLm(self.keys, self.writer_model if isinstance(self.writer_model, str) else self.writer_model[random_index])
        response3 = llm3(prompt, images, temperature, stream=stream, max_tokens=max_tokens, system=system)

        code_written = ""
        for chunk in collapsible_wrapper(response3, header="Solution", show_initially=True):
            yield chunk
            current_answer += chunk
            code_written += chunk

        yield "\n\n---\n\n"
        current_answer += "\n\n---\n\n"
        
        extracted_code = extract_code(code_written, relax=True)
        code_session = PersistentPythonEnvironment()
        try:
            success, failure_reason, stdout, stderr = run_code_with_constraints_v2(extracted_code, constraints={}, session=code_session)
        except Exception as e:
            yield f"Code execution failed with the following error: \n```\n{str(e)}\n```\n\n"
            return
        
        def code_runner_result(failure_reason, stdout, stderr):
            if failure_reason is not None and failure_reason.strip() != "" and failure_reason.strip()!="None":
                # yield f"Code execution failed with the following error: \n```\n{failure_reason}\n```\n\n"
                yield f"STDOUT:\n\n```\n\n{stdout}\n\n```\n\n"
                yield f"STDERR:\n\n```\n\n{stderr}\n\n```\n\n"
                
            else:
                yield f"Code execution passed with the following output:\n"
                yield "\n\n```\n\n"
                yield f"{stdout}\n\n"
                yield "```\n\n"

        current_answer += "\n\n---\n\n"
        yield "\n\n---\n\n"
        for chunk in collapsible_wrapper(code_runner_result(failure_reason, stdout, stderr), header="Code Execution Results", show_initially=True):
            yield chunk
            current_answer += chunk
        current_answer += "\n\n---\n\n"

        del code_session


        n_steps = 1
        while failure_reason is not None and failure_reason.strip() != "" and failure_reason.strip()!="None" and n_steps < self.n_steps:
            # we need to re-iterate and correct the code
            prompt = self.prompt_3.replace("{query}", text).replace("{current_answer}", current_answer)
            random_index = random.randint(0, len(self.writer_model) - 1)
            llm3 = CallLLm(self.keys, self.writer_model if isinstance(self.writer_model, str) else self.writer_model[random_index])
            response3 = llm3(prompt, images, temperature, stream=stream, max_tokens=max_tokens, system=system)

            code_written = ""
            for chunk in collapsible_wrapper(response3, header="Solution", show_initially=True):
                yield chunk
                current_answer += chunk
                code_written += chunk
            yield "\n\n---\n\n"
            current_answer += "\n\n---\n\n"
            extracted_code = extract_code(code_written, relax=True)
            code_session = PersistentPythonEnvironment()
            success, failure_reason, stdout, stderr = run_code_with_constraints_v2(extracted_code, constraints={}, session=code_session)
            del code_session
            current_answer += "\n\n---\n\n"
            for chunk in collapsible_wrapper(code_runner_result(failure_reason, stdout, stderr), header="Code Execution Results", show_initially=True):
                yield chunk
                current_answer += chunk
            current_answer += "\n\n---\n\n"
            yield "\n\n---\n\n"
            n_steps += 1

class CodeEvaluationAgent(Agent):
    def __init__(self, keys, writer_model: Union[List[str], str]):
        super().__init__(keys)
        self.writer_model = writer_model
        
        # Prompt to generate code with test cases when only functions are present
        self.complete_code_prompt = f"""
You are an expert coding instructor and interview preparation mentor with extensive experience in software engineering, algorithms, data structures, and technical interviews at top tech companies.

I have code that contains a solution function or algorithm, but it lacks test cases and a main execution block. Please add the necessary code to make it fully executable with test cases.

{mathematical_notation}

Guidelines:
- Add test cases that cover normal cases, edge cases, and corner cases
- Include an if __name__ == "__main__" block
- Make sure all imports are included
- Keep all existing functions intact
- Use assert statements to verify correctness
- Print test results clearly showing which tests pass/fail
- Maintain the existing algorithm/solution logic

Here is the existing code:
```python
{{code}}
```

Please provide a complete, executable version of this code with appropriate test cases. The final code should be self-contained in a single file.
"""
        
        # Prompt to evaluate code and suggest improvements/corrections
        self.code_evaluation_prompt = f"""
You are an expert coding instructor and interview preparation mentor with extensive experience in software engineering, algorithms, data structures, and technical interviews at top tech companies.

I have executed some Python code and want your expert evaluation of it. Please analyze both the code and its execution results.

{mathematical_notation}

Original Code:
```python
{{code}}
```

Execution Results:
{{execution_results}}

Please provide an evaluation addressing the following:

1. **Correctness**: Does the code execute successfully? Do all tests pass? If not, identify the issues.

2. **Algorithm Analysis**: 
   - Time and space complexity analysis
   - Is the chosen algorithm optimal?
   - Are there edge cases not being handled?

3. **Code Quality**:
   - Style and readability
   - Variable naming and documentation
   - Potential refactoring opportunities
   - Adherence to Python best practices

4. **Improvements**:
   - If the code is correct but could be improved stylistically, suggest specific improvements
   - If the code fails or has bugs, provide a complete corrected version

If providing a corrected version, please ensure it's complete and executable.
"""

    def __call__(self, text, images=[], temperature=0.7, stream=True, max_tokens=None, system=None, web_search=False):
        # Extract code from text (taking the last code block if multiple exists)
        extracted_code = self._extract_last_code_block(text)
        
        if not extracted_code:
            yield "No code block found in the input text."
            return
        
        # Check if the code has a main execution block
        has_main_execution = 'if __name__ == "__main__"' in extracted_code
        has_main_function = re.search(r'def\s+(main|algorithm|solution)\s*\(', extracted_code) is not None
        
        # If code has a function but no main execution block, complete it
        if not has_main_execution and has_main_function:
            yield "Code has a solution function but no main execution block. Completing the code with test cases...\n\n"
            completed_code = yield from self._complete_code_with_tests(extracted_code)
            if completed_code:
                extracted_code = completed_code
                yield "\n\n---\n\n"
            else:
                yield "Failed to complete the code with test cases."
                return
        
        # Execute the code
        execution_results = yield from self._execute_code(extracted_code)
        
        # Evaluate the code
        yield from self._evaluate_code(extracted_code, execution_results)
    
    def _extract_last_code_block(self, text):
        """Extract the last code block from the text."""
        code_blocks = re.findall(r'```(?:python)?\s*(.*?)```', text, re.DOTALL)
        if not code_blocks:
            return None
        
        # Return the last code block
        return code_blocks[-1].strip()
    
    def _complete_code_with_tests(self, code):
        """Use LLM to complete code with test cases."""
        prompt = self.complete_code_prompt.replace("{code}", code)
        
        llm = CallLLm(self.keys, self.writer_model if isinstance(self.writer_model, str) else self.writer_model[0])
        response = llm(prompt, [], temperature=0.7, stream=True)
        
        completed_code = ""
        for chunk in collapsible_wrapper(response, header="Completed Code with Test Cases", show_initially=True):
            yield chunk
            completed_code += chunk
        
        # Extract the completed code from the response
        code_blocks = re.findall(r'```(?:python)?\s*(.*?)```', completed_code, re.DOTALL)
        if not code_blocks:
            return None
        
        return code_blocks[-1].strip()
    
    def _execute_code(self, code):
        """Execute the code and return the results."""
        yield "Executing code...\n\n"
        
        code_session = PersistentPythonEnvironment()
        try:
            success, failure_reason, stdout, stderr = run_code_with_constraints_v2(code, constraints={}, session=code_session)
            
            execution_results = ""
            
            if success:
                execution_output = f"Code execution passed with the following output:\n\n```\n{stdout}\n```\n\n"
                yield from collapsible_wrapper(execution_output, header="Code Execution Results", show_initially=True)
                execution_results = stdout
            else:
                execution_output = f"Code execution failed with the following error:\n\n```\nSTDOUT:\n{stdout}\n\nSTDERR:\n{stderr}\n\nERROR: {failure_reason}\n```\n\n"
                yield from collapsible_wrapper(execution_output, header="Code Execution Results", show_initially=True)
                execution_results = f"STDOUT:\n{stdout}\n\nSTDERR:\n{stderr}\n\nERROR: {failure_reason}"
            
            yield "\n\n---\n\n"
            del code_session
            return execution_results
            
        except Exception as e:
            error_output = f"Code execution failed with an unexpected error:\n\n```\n{str(e)}\n{traceback.format_exc()}\n```\n\n"
            yield from collapsible_wrapper(error_output, header="Execution Error", show_initially=True)
            yield "\n\n---\n\n"
            del code_session
            return f"Execution Error: {str(e)}\n{traceback.format_exc()}"
    
    def _evaluate_code(self, code, execution_results):
        """Use LLM to evaluate code quality and correctness."""
        prompt = self.code_evaluation_prompt.replace("{code}", code).replace("{execution_results}", execution_results)
        
        # Use a different model instance for evaluation
        random_index = random.randint(0, len(self.writer_model)-1 if isinstance(self.writer_model, list) else 0)
        llm = CallLLm(self.keys, self.writer_model if isinstance(self.writer_model, str) else self.writer_model[random_index])
        response = llm(prompt, [], temperature=0.7, stream=True)
        
        for chunk in collapsible_wrapper(response, header="Code Evaluation and Recommendations", show_initially=True):
            yield chunk

class NStepCodeAgent_old(Agent):
    def __init__(self, keys, writer_model: Union[List[str], str], n_steps: int = 4):
        super().__init__(keys)
        self.writer_model = writer_model
        self.n_steps = n_steps
        
        self.prompt_1 = f"""
You are an expert coding instructor and interview preparation mentor with extensive experience in software engineering, algorithms, data structures, system design, and technical interviews at top tech companies. You possess deep knowledge of platforms like LeetCode, HackerRank, CodeSignal, and others, along with proven expertise in teaching coding concepts effectively. You teach coding and interview preparation in python and pseudocode.

You are given a query about a coding problem, please help us learn and understand the problem and then solve it step by step.
If multiple solutions are provided, please help us understand the pros and cons of each solution and then solve the problem step by step.
{mathematical_notation}

### 1. Breaking Down Solutions by patterns and concepts
- If no reference solutions are provided, develop the solution yourself and **guide us through it** and also mention that you are developing the solution yourself without any reference.
- When no solution is provided, then write the solution yourself. Write a solution and run your solution on the sample data (generate sample data if needed) and check if your solution will work, if not then revise and correct your solution. 
- **Decompose** each solution into manageable and understandable parts.
- Use **clear examples**, **analogies** to illustrate concepts.
- Provide **step-by-step explanations** of complex algorithms or logic.
- Before writing code, write a verbal step by step description of the solution along with the time and space complexity of the solution and any pattern or concept used in the solution. Write in simple language with simple formatting with inline maths and notations (if needed).
- When explaining code or algorithms related to interview questions, use code notation to explain and avoid latex notation.
- Talk about other similar or related problems which I might confuse this problem with, and also talk or hint about the differences and their solutions.

### 2. Diagrams (if needed and possible)
    - Create diagrams to help us understand the solution and the problem.
    - Use ASCII art to help us understand each solution by running them step by step.
    - Use ASCII art diagrams mainly to help illustrate the solution (or multiple solutions) and the problem. 
    - Step by step running example of the solutions can be written in a plaintext code block.

- We program in python, so write the code in python only.

- **When No Solution is Provided**:
  - Develop the solution yourself and **guide us through it**, following the steps above.


Query:
<user_query>
{{query}}
</user_query>

The user query above contains the user's query and some context around it including the previous conversation history and retreived documents and web search results if applicable.

Write your answer below which expands our understanding of the problem and enhances our learning and helps us prepare for the FAANG coding interviews at senior or staff level.
"""

        self.prompt_2 = f"""**Role**: You are an expert coding instructor and interview preparation mentor with extensive experience in software engineering, algorithms, data structures, system design, and technical interviews at top tech companies. You possess deep knowledge of platforms like LeetCode, HackerRank, CodeSignal, and others, along with proven expertise in teaching coding concepts effectively. You teach coding and interview preparation in python and pseudocode.

**Objective**: We will provide you with a coding **question** to practice, and potentially one or more **solutions** (which may include our own attempt). Your task is to help us **learn and understand the solution thoroughly** by guiding us through the problem-solving process step by step. 
Help prepare us for technical interviews at the senior or staff level.
You will expand upon the current answer and provide more information and details based on the below framework and guidelines and fill in any missing details.
Don't repeat the same information or details that are already provided in the current answer.
Code is not needed. Do not write code.

{mathematical_notation}

Code is not needed. Do not write code. Focus only on the below guidelines.

You will expand upon the current answer and provide more information and details based on the below framework and guidelines. 
Only cover the below guidelines suggested items. Limit your response to the below guidelines and items.
Don't repeat the same information or details that are already provided in the current answer.


## Guidelines:

1. **How real world questions can be asked that would need this solution**:
  - Suggesting more real world examples and scenarios where this solution can be used.
  - Ask questions that would need this solution.
  - Change the wording of the question to help our identification muscle work better. Like changing from "largest value in array" to "find the tallest student in the class when all heights are given". Transform the question to make it more real world and practical while keeping the core problem the same.

2. Other related questions or problems we have not discussed yet in our answer:
  - **Discuss** other related questions or problems that are similar or use similar concepts or algorithms or solutions.
  - Provide hints and clues to solve or approach the related questions or problems.
  - Give a verbal solution or pseudocode solution to the related questions or problems.
  - Relate it to the current problem and solution and to other problems and solutions we have discussed. 



Follow the above framework and guidelines to help us learn and understand the problem and then solve it in an interview setting.

You will expand upon the current answer and provide more information and details.


Query:
<user_query>
{{query}}
</user_query>

The user query above contains the user's query and some context around it including the previous conversation history and retreived documents and web search results if applicable.


Current Answer:
<current_answer>
{{current_answer}}
</current_answer>

Note that we already have current answer and we are looking to add more information and details to it. Follow from the current answer and add more information and details.
Code is not needed. Do not write code. Avoid code. Extend the answer to provide more information and details ensuring we cover the above framework and guidelines. Stay true and relevant to the user query and context.
Next Step or answer extension or continuation:
"""

        self.prompt_3 = f"""
**Role**: You are an expert coding instructor and interview preparation mentor with extensive experience in software engineering, algorithms, data structures, system design, and technical interviews at top tech companies. You possess deep knowledge of platforms like LeetCode, HackerRank, CodeSignal, and others, along with proven expertise in teaching coding concepts effectively. You teach coding and interview preparation in python and pseudocode.

**Objective**: We will provide you with a coding **question** to practice, and potentially one or more **solutions** (which may include our own attempt). Your task is to help us **learn and understand the solution thoroughly** by guiding us through the problem-solving process step by step. 
Help prepare us for technical interviews at the senior or staff level.

You will expand upon the current answer and provide more information and details based  on the below framework and guidelines.
Don't repeat the same information or details that are already provided in the current answer.
{mathematical_notation}
Code is not needed. Do not write code. 
Focus only on the below guidelines.

Guidelines:
### 1. Testing for Edge Cases
- Provide comprehensive **test cases** to verify correctness of edge cases, invalid or unexpected inputs and corner cases:
  - **Edge cases**
  - **Invalid or unexpected inputs**
  - **Corner cases** which might be tricky and requires careful handling.
- Explain how to handle exceptions and errors gracefully. What and how to check for input validation, output validation, edge cases handling, assertions or state check at each step of the solution.

### 2. Trade-Offs and Decision Making
- Discuss factors influencing the choice of solution:
  - **Input size and constraints**
  - **Execution environment limitations**
  - **Requirements for speed vs. memory usage**
  - What if we have more resources (CPU, RAM, Disk, Network, etc)? Can we design a simpler solution? Or can we trade speed for memory or vice versa?
  - Scaling to larger data size
  - Scaling to distributed systems (where consistency or partitioning is needed and we may have network latency and other constraints)
- Encourage us to consider **real-world scenarios** where such trade-offs are critical.




Query:
<user_query>
{{query}}
</user_query>

The user query above contains the user's query and some context around it including the previous conversation history and retreived documents and web search results if applicable.


Current Answer:
<current_answer>
{{current_answer}}
</current_answer>

Note that we already have current answer and we are looking to add more information and details to it. Follow from the current answer and add more information and details.
Extend the answer to provide more information and details ensuring we cover the above guidelines. Stay true and relevant to the user query and context.
Next Step or answer extension or continuation following the above guidelines:
"""
        """
- Discuss common **algorithmic paradigms** (e.g., divide and conquer, dynamic programming) where this problem or solution fits in.
- Highlight similar **patterns** that frequently appear in coding interviews.
- **Discuss** related and important topics and concepts that are relevant to the problem and solution.

- Incorporate practical examples to illustrate abstract concepts.
- Use analogies to relate complex ideas to familiar scenarios.

- Balancing trade-offs in system components.
- Understanding architectural patterns.
### 2. Related and Important Topics and Concepts
- Scaling to larger data size
- Scaling to distributed systems (where consistency or partitioning is needed and we may have network latency and other constraints)
- **Discuss** how the concepts can be applied to other problems and solutions.
- **Discuss** follow-up extensions and variations of the problem and solution.


        """

        self.prompt_3_v2 = f"""
**Role**: You are an expert coding instructor and interview preparation mentor with extensive experience in software engineering, algorithms, data structures, system design, and technical interviews at top tech companies. You possess deep knowledge of platforms like LeetCode, HackerRank, CodeSignal, and others, along with proven expertise in teaching coding concepts effectively. 
You teach coding and interview preparation in python and pseudocode. You are also an expert in system design, scaling, real-time systems, distributed systems, and architecture.

**Objective**: We will provide you with a coding **question** to practice, and potentially one or more **solutions** (which may include our own attempt). Your task is to help us **learn and understand the solution thoroughly** by guiding us through the problem-solving process step by step. 
Help prepare us for technical interviews at the senior or staff level. 

You will expand upon the current answer and provide more information and details based  on the below framework and guidelines.
Don't repeat the same information or details that are already provided in the current answer.
{mathematical_notation}
Code is not needed. Do not write code. Focus only on the below guidelines.

Guidelines:

### 1. Discuss about the "Before Writing Code part"
- What are the clarifying questions we should ask to the interviewer? What questions would you ask? Make an exhaustive list of questions in the order of priority.
- What answers would you assume to the above questions?

### 2. Analyzing Provided Solutions (If Applicable)
- Only analyze the provided solutions, don't write code.
- Discuss the **trade-offs** and decisions made in the different solutions or approaches possible.
  - **Time vs. Space Complexity**
  - **Simplicity vs. Efficiency**
  - Offer a detailed **complexity analysis** for each solution.
    - Use **Big O notation** and explain the reasoning behind it (how you arrived at the time and space complexity).
    - Compare complexities between different solutions and discuss implications.    
- Suggest improvements in:
  - **Algorithmic Efficiency**: Optimizing runtime and memory/space usage if possible.
  - **Storage or Memory**: What if we need to use less storage or memory? Can we use more memory to speed up the algorithm or solution?

### 3. System Design and Architecture Considerations:
  - Designing scalable systems which might tackle this problem at a much larger scale.
  - Designing systems which use this algorithm or concept but in a much larger scale or a constrained environment.
  - Distributed Systems, Real-time systems, systems with high availability, systems where data may get corrupted or lost, and other constraints. 
  - Focus on algorithms and solution paradigms rather than software or packages or libraries.
  - What changes might be needed to be made to the solution to make it scalable or realtime or distributed or high availability or fault tolerant or secure or in a constrained environment.


Query:
<user_query>
{{query}}
</user_query>

The user query above contains the user's query and some context around it including the previous conversation history and retreived documents and web search results if applicable.


Current Answer:
<current_answer>
{{current_answer}}
</current_answer>

Note that we already have current answer and we are looking to add more information and details to it. Follow from the current answer and add more information and details.
Extend the answer to provide more information and details ensuring we cover the above guidelines. Stay true and relevant to the user query and context.
Next Step or answer extension or continuation following the above guidelines:
"""

        
        self.prompt_4 = f"""
**Role**: You are an expert coding instructor and interview preparation mentor with extensive experience in software engineering, algorithms, data structures, system design, and technical interviews at top tech companies. You possess deep knowledge of platforms like LeetCode, HackerRank, CodeSignal, and others, along with proven expertise in teaching coding concepts effectively. You teach coding and interview preparation in python and pseudocode.

**Objective**: We will provide you with a coding **question** to practice, and potentially one or more **solutions** (which may include our own attempt). Your task is to help us **learn and understand the solution thoroughly** by guiding us through the problem-solving process step by step. 
Help prepare us for technical interviews at the senior or staff level.
{mathematical_notation}
Code is not needed. Do not write code. Focus only on the below guidelines.

You will expand upon the current answer and provide more information and details based on the below framework and guidelines. 
Only cover the below guidelines suggested items. Limit your response to the below guidelines and items.
Don't repeat the same information or details that are already provided in the current answer.


Guidelines:

1. **How real world questions can be asked that would need this solution**:
  - Suggesting more real world examples and scenarios where this solution can be used.
  - Ask questions that would need this solution.
  - Change the wording of the question to help our identification muscle work better. Like changing from "largest value in array" to "find the tallest student in the class when all heights are given". Transform the question to make it more real world and practical while keeping the core problem the same.

2. Other related questions or problems we have not discussed yet in our answer:
  - **Discuss** other related questions or problems that are similar or use similar concepts or algorithms or solutions.
  - Provide hints and clues to solve or approach the related questions or problems.
  - Give a verbal solution or pseudocode solution to the related questions or problems.
  - Relate it to the current problem and solution and to other problems and solutions we have discussed. 


Query:
<user_query>
{{query}}
</user_query>

The user query above contains the user's query and some context around it including the previous conversation history and retreived documents and web search results if applicable.


Current Answer:
<current_answer>
{{current_answer}}
</current_answer>

Note that we already have current answer and we are looking to add more information and details to it. Follow from the current answer and add more information and details.
Extend the current answer to provide more information and details to cover our above guidelines ensuring we cover the above framework and guidelines. Stay true and relevant to the user query and context.
Next Step or answer extension or continuation:
"""
        

        self.what_if_prompt = f"""
**Role**: You are an expert coding instructor and interview preparation mentor with extensive experience in software engineering, algorithms, data structures, system design, and technical interviews at top tech companies. You possess deep knowledge of platforms like LeetCode, HackerRank, CodeSignal, and others, along with proven expertise in teaching coding concepts effectively. You teach coding and interview preparation in python and pseudocode.

**Objective**: We will provide you with a coding **question** to practice, and potentially one or more **solutions** (which may include our own attempt). Your task is to help us **learn and understand the solution thoroughly** by guiding us through the problem-solving process step by step. 
Help prepare us for technical interviews at the senior or staff level.

{mathematical_notation}

Only cover the below guidelines suggested items. Limit your response to the below guidelines and items.

Guidelines:
### 1. What-if questions and scenarios
- **Discuss** what-if questions and scenarios that are relevant to the problem and solution.
- Ask and hint on how to solve the problem if some constraints, data, or other conditions are changed as per the above what-if questions and scenarios.
- Verbalize the solutions first and then also mention their time and space complexities. 

### 2. **More What-if questions and scenarios**:
  - **Discuss** what-if questions and scenarios that are relevant to the problem and solution.
  - Ask and hint on how to solve the problem if some constraints, data, or other conditions  are changed as per the above what-if questions and scenarios.
  - Verbalize the solutions first and then also mention their time and space complexities. 

### 3. **Mind Bending Questions**:
  - Tell us any new niche concepts or patterns that are used in the solution and any other niche concepts and topics that will be useful to learn.
  - Ask us some mind bending questions based on the solution and the problem to test our understanding and stimulate our thinking.
  - Provide verbal hints and clues to solve or approach the mind bending questions.


Query:
<user_query>
{{query}}
</user_query>

The user query above contains the user's query and some context around it including the previous conversation history and retreived documents and web search results if applicable.


Current Answer:
<current_answer>
{{current_answer}}
</current_answer>

Note that we already have current answer and we are looking to add more information and details to it. Follow from the current answer and add more information and details.
Extend the answer to provide more information and details ensuring we cover the above guidelines. Stay true and relevant to the user query and context.
Next Step or answer extension or continuation following the above guidelines:
"""
        
    
    
    def __call__(self, text, images=[], temperature=0.7, stream=True, max_tokens=None, system=None, web_search=False):
        # Initialize empty current answer
        current_answer = ""
        
        # Execute prompt_1 first as it's the foundation
        llm = CallLLm(self.keys, self.writer_model if isinstance(self.writer_model, str) else self.writer_model[0])
        prompt = self.prompt_1.replace("{query}", text)
        response = llm(prompt, images, temperature, stream=stream, max_tokens=max_tokens, system=system)

        for chunk in collapsible_wrapper(response, header="Solution", show_initially=True):
            yield chunk
            current_answer += chunk
        
        yield "\n\n---\n\n"
        current_answer += "\n\n---\n\n"

        if self.n_steps == 1:
            return
        
        # Create a queue for communication between threads
        from queue import Queue
        response_queue = Queue()
        
        # Flag to track completion status
        completed = {"prompt3": False, "prompt4": False, "what_if": False}
        
        # Background function to execute prompts 3 and 4 sequentially while streaming results
        def execute_prompts_3_and_4():
            try:
                p3_answer = current_answer
                # Execute prompt_3
                
                random_index = random.randint(0, min(2, len(self.writer_model) - 1))
                llm3 = CallLLm(self.keys, self.writer_model if isinstance(self.writer_model, str) else self.writer_model[random_index])
                # prompt3 = self.prompt_3.replace("{query}", text).replace("{current_answer}", p3_answer)
                # response3 = llm3(prompt3, images, temperature, stream=True, max_tokens=max_tokens, system=system)
                
                # # Stream prompt_3 response through the queue
                # for chunk in collapsible_wrapper(response3, header="Edge Cases and Corner Cases", show_initially=False):
                #     response_queue.put(("prompt3", chunk))
                #     p3_answer += chunk

                # response_queue.put(("prompt3", "\n\n---\n\n"))
                # p3_answer += "\n\n---\n\n"

                prompt3_v2 = self.prompt_3_v2.replace("{query}", text).replace("{current_answer}", p3_answer)
                response3_v2 = llm3(prompt3_v2, images, temperature, stream=True, max_tokens=max_tokens, system=system)
                for chunk in collapsible_wrapper(response3_v2, header="System Design and Architecture Considerations", show_initially=False):
                    response_queue.put(("prompt3", chunk))
                    p3_answer += chunk
                
                # Mark prompt3 as completed
                completed["prompt3"] = True
                response_queue.put(("prompt3", "\n\n---\n\n"))
                p3_answer += "\n\n---\n\n"
                response_queue.put(("prompt3_complete", ""))

                if self.n_steps == 3:
                    return
                
                multiple_llm_models = ["openai/chatgpt-4o-latest", "anthropic/claude-3.7-sonnet:beta", "x-ai/grok-3-beta"]
                if isinstance(self.writer_model, list):
                    multiple_llm_models += self.writer_model
                else:
                    multiple_llm_models += [self.writer_model]
                multiple_llm_models = list(set(multiple_llm_models))
                random.shuffle(multiple_llm_models)
                multiple_llm = [CallLLm(self.keys, model) for model in multiple_llm_models[:2]]
                what_if_response = multiple_llm[0](self.what_if_prompt.replace("{query}", text).replace("{current_answer}", p3_answer), images, temperature, stream=stream, max_tokens=max_tokens, system=system)
                
                # Execute prompt_4 with updated answer including prompt_3's output
                random_index = random.randint(0, min(3, len(self.writer_model) - 1))
                llm4 = CallLLm(self.keys, self.writer_model if isinstance(self.writer_model, str) else self.writer_model[random_index])
                prompt4 = self.prompt_4.replace("{query}", text).replace("{current_answer}", p3_answer)
                response4 = llm4(prompt4, images, temperature, stream=True, max_tokens=max_tokens, system=system)
                
                # Stream prompt_4 response through the queue
                for chunk in collapsible_wrapper(response4, header="Examples and Real World Questions", show_initially=False):
                    response_queue.put(("prompt4", chunk))
                
                # Mark prompt4 as completed
                completed["prompt4"] = True
                response_queue.put(("prompt4", "\n\n---\n\n"))
                response_queue.put(("prompt4_complete", ""))

                p3_answer += "\n\n---\n\n"
                for chunk in collapsible_wrapper(what_if_response, header="What-if questions and scenarios - 1", show_initially=False):
                    response_queue.put(("what_if", chunk))
                    p3_answer += chunk

                p3_answer += "\n\n---\n\n"
                for i, llm in enumerate(multiple_llm[1:], start=2):
                    what_if_response = llm(self.what_if_prompt.replace("{query}", text).replace("{current_answer}", p3_answer), images, temperature, stream=stream, max_tokens=max_tokens, system=system)
                    for chunk in collapsible_wrapper(what_if_response, header=f"What-if questions and scenarios - {i}", show_initially=False):
                        response_queue.put(("what_if", chunk))
                        p3_answer += chunk

                    p3_answer += "\n\n---\n\n"
                
                completed["what_if"] = True
                response_queue.put(("what_if", "\n\n---\n\n"))
                response_queue.put(("what_if_complete", ""))
                
            except Exception as e:
                error_msg = f"Error in background task: {e}\n{traceback.format_exc()}"
                logger.error(error_msg)
                response_queue.put(("error", error_msg))
            
            # Signal completion
            response_queue.put(("done", None))
        
        if self.n_steps > 2:
            # Start background task
            background_future = get_async_future(execute_prompts_3_and_4)
        
        # Execute prompt_2 while prompts 3 and 4 are running in background
        random_index = random.randint(0, min(1, len(self.writer_model) - 1))
        llm2 = CallLLm(self.keys, self.writer_model if isinstance(self.writer_model, str) else self.writer_model[random_index])
        prompt2 = self.prompt_2.replace("{query}", text).replace("{current_answer}", current_answer)
        response2 = llm2(prompt2, images, temperature, stream=stream, max_tokens=max_tokens, system=system)
        
        # Stream prompt_2 results while checking for any available results from prompts 3 and 4
        for chunk in collapsible_wrapper(response2, header="Analysis of the solution", show_initially=False):
            yield chunk
            current_answer += chunk
            
            
        
        yield "\n\n---\n\n"
        current_answer += "\n\n---\n\n"

        if self.n_steps == 2:
            return
        # After prompt_2 is done, process any remaining results from prompts 3 and 4
        # and continue streaming as they become available
        background_complete = False
        current_prompt = "prompt3"
        
        while not background_complete:
            try:
                # Get next item, waiting if necessary
                source, content = response_queue.get(timeout=0.1)
                
                if source == "done":
                    background_complete = True
                elif source == "error":
                    yield f"\n\nError in background processing: {content}\n\n"
                    background_complete = True
                elif source == "prompt3_complete":
                    # Just change phase without yielding the separator (it's already in the content)
                    current_prompt = "prompt4"
                elif source == "prompt4_complete":
                    current_prompt = "what_if"
                elif source == "what_if_complete":
                    current_prompt = None
                elif source == current_prompt:
                    yield content
                    current_answer += content
            except Exception as e:
                # Check if background task is done
                if background_future.done():
                    if background_future.exception():
                        yield f"\n\nError in background processing: {background_future.exception()}\n\n"
                    background_complete = True


class NStepCodeAgent(Agent):
    def __init__(self, keys, writer_model: Union[List[str], str], n_steps: int = 4):
        super().__init__(keys)
        self.writer_model = writer_model
        self.n_steps = n_steps
        
        self.prompt_1 = manager["code_agent_prompt1"]

        self.prompt_2 = manager["code_agent_prompt2"]

        self.prompt_2_v2 = manager["code_agent_prompt2_v2"]
        
        
        self.prompt_3 = manager["code_agent_prompt3"]

        

        self.what_if_prompt = manager["code_agent_what_if_prompt"]
        
    
    
    def __call__(self, text, images=[], temperature=0.7, stream=True, max_tokens=None, system=None, web_search=False):
        # Initialize empty current answer
        current_answer = ""
        
        # Execute prompt_1 first as it's the foundation

        if isinstance(self.writer_model, list):
            random.shuffle(self.writer_model)
        llm = CallLLm(self.keys, self.writer_model if isinstance(self.writer_model, str) else self.writer_model[0])
        prompt = self.prompt_1.replace("{query}", text)
        response = llm(prompt, images, temperature, stream=stream, max_tokens=max_tokens, system=system)

        for chunk in collapsible_wrapper(response, header=f"Solution using {llm.model_name}", show_initially=True):
            yield chunk
            current_answer += chunk
        
        yield "\n\n---\n\n"
        current_answer += "\n\n---\n\n"

        if self.n_steps == 1:
            return
        
        random_index = random.randint(0, min(1, len(self.writer_model) - 1))
        llm2 = CallLLm(self.keys, self.writer_model if isinstance(self.writer_model, str) else self.writer_model[random_index])
        prompt2 = self.prompt_2.replace("{query}", text).replace("{current_answer}", current_answer)
        response2 = llm2(prompt2, images, temperature, stream=stream, max_tokens=max_tokens, system=system)
        
        for chunk in collapsible_wrapper(response2, header=f"Similar problems and Real world examples from {llm2.model_name}", show_initially=True):
            yield chunk
            current_answer += chunk

        
        yield "\n\n---\n\n"
        current_answer += "\n\n---\n\n"

        random_index = random.randint(0, min(1, len(self.writer_model) - 1))
        llm2 = CallLLm(self.keys, self.writer_model if isinstance(self.writer_model, str) else self.writer_model[random_index])
        prompt2 = self.prompt_2_v2.replace("{query}", text).replace("{current_answer}", current_answer)
        response2 = llm2(prompt2, images, temperature, stream=stream, max_tokens=max_tokens, system=system)
        
        for chunk in collapsible_wrapper(response2, header=f"Similar problems and Real world examples from {llm2.model_name}", show_initially=False):
            yield chunk
            current_answer += chunk

        
        yield "\n\n---\n\n"
        current_answer += "\n\n---\n\n"

        
        
        multiple_llm_models = EXPENSIVE_LLM[:3] + LONG_CONTEXT_LLM[:1]
        if isinstance(self.writer_model, list):
            multiple_llm_models += self.writer_model
        else:
            multiple_llm_models = ([self.writer_model] + multiple_llm_models) if self.writer_model not in multiple_llm_models else multiple_llm_models
        multiple_llm_models = list(set(multiple_llm_models))
        random.shuffle(multiple_llm_models)
        multiple_llm = [CallLLm(self.keys, model) for model in multiple_llm_models[:2 if self.n_steps >= 3 else 1]]
        
        
        for i, llm in enumerate(multiple_llm, start=1):
            what_if_response = llm(self.what_if_prompt.replace("{query}", text).replace("{current_answer}", current_answer), images, temperature, stream=stream, max_tokens=max_tokens, system=system)
            for chunk in collapsible_wrapper(what_if_response, header=f"What-if questions and scenarios - {i} with {llm.model_name}", show_initially=False):
                yield chunk
                current_answer += chunk

            yield "\n\n---\n\n"
            current_answer += "\n\n---\n\n"

        
        if self.n_steps == 2:
            return
        
        if self.n_steps == 3:
            return
        
        
        random_index = random.randint(0, min(2, len(self.writer_model) - 1))
        llm3 = CallLLm(self.keys, self.writer_model if isinstance(self.writer_model, str) else self.writer_model[random_index])
        prompt3 = self.prompt_3.replace("{query}", text).replace("{current_answer}", current_answer)
        response3 = llm3(prompt3, images, temperature, stream=True, max_tokens=max_tokens, system=system)
        
        for chunk in collapsible_wrapper(response3, header=f"Analysis and System design from {llm3.model_name}", show_initially=False):
            yield chunk
            current_answer += chunk

        yield "\n\n---\n\n"
        current_answer += "\n\n---\n\n"

        if self.n_steps == 4:
            return
        return
        
        

class MLSystemDesignAgent(Agent):
    def __init__(self, keys, writer_model: Union[List[str], str], n_steps: int = 4):
        super().__init__(keys)
        self.writer_model = writer_model
        self.n_steps = n_steps

        self.system_prompt = manager["ml_system_design_system_prompt"]

        self.ml_system_design_prompt = manager["ml_system_design_answer"]

        self.ml_system_design_prompt_2 = manager["ml_system_design_answer_2"]

        self.ml_system_design_prompt_3 = manager["ml_system_design_answer_3"]


        
        self.clarifications_assumptions_prompt = manager["ml_system_design_clarifications_assumptions_prompt"]

        self.top_down_design_prompt = manager["ml_system_design_top_down_design_prompt"]

        self.other_areas_prompt_1 = manager["ml_system_design_other_areas_prompt_1"]

        self.other_areas_prompt_2 = manager["ml_system_design_other_areas_prompt_2"]

        
        
        self.what_if_questions_prompt = manager["ml_system_design_what_if_questions_prompt"]

        self.tips_prompt = manager["ml_system_design_tips_prompt"]

        
    def __call__(self, text, images=[], temperature=0.7, stream=True, max_tokens=None, system=None, web_search=True):
        # Define the models to use
        if system is None:
            system = self.system_prompt
        multiple_llm_models = EXPENSIVE_LLM[:3] + LONG_CONTEXT_LLM[:1]
        
        
        # Use provided models or fallback to default list
        if isinstance(self.writer_model, list):
            models_to_use = self.writer_model
        else: # if self.n_steps >= 4:
            # Add writer_model to the list if it's not already there
            models_to_use = multiple_llm_models
            if isinstance(self.writer_model, str) and self.writer_model not in models_to_use:
                models_to_use.append(self.writer_model)

        # else:
        #     models_to_use = [self.writer_model] * 3

        # random shuffle the models
        random.shuffle(models_to_use)
        
        # Format ML system design prompt with user query
        ml_design_prompts = [
            self.ml_system_design_prompt.replace("{query}", text) if i % 3 == 0 else 
            self.ml_system_design_prompt_2.replace("{query}", text) if i % 3 == 1 else 
            self.ml_system_design_prompt_3.replace("{query}", text) if i % 3 == 2 else ""
            for i in range(len(models_to_use))
        ]

        web_search_response_future = None
        if self.n_steps >= 4 and web_search:
            # we will perform web search as well.
            web_search_agent = MultiSourceSearchAgent(self.keys, model_name=CHEAP_LONG_CONTEXT_LLM[0], detail_level=2, timeout=120)
            web_search_response_future = get_async_future(web_search_agent.get_answer, text, images, temperature, stream, max_tokens, system, web_search)
            
        
        
        # Stream from multiple models
        model_responses = yield from stream_multiple_models(
            self.keys, 
            models_to_use, 
            ml_design_prompts, 
            images, 
            temperature, 
            max_tokens, 
            system,
            collapsible_headers=True,
            header_template="Response from {model}"
        )
        
        
        
        # Prepare the combiner prompt with all model responses
        model_solutions_text = ""
        for model_name, response in model_responses.items():
            model_solutions_text += f"### Solution from {model_name}\n{response}\n\n"
        combined_response = ""
        

        if self.n_steps <= 1:
            return
        other_prompts = [
            self.clarifications_assumptions_prompt.replace("{query}", text).replace("{model_solutions}", model_solutions_text).replace("{combined_solution}", combined_response),
            self.other_areas_prompt_1.replace("{query}", text).replace("{model_solutions}", model_solutions_text).replace("{combined_solution}", combined_response),
            self.other_areas_prompt_2.replace("{query}", text).replace("{model_solutions}", model_solutions_text).replace("{combined_solution}", combined_response),
            # self.other_areas_prompt_3.replace("{query}", text).replace("{model_solutions}", model_solutions_text).replace("{combined_solution}", combined_response),
            self.top_down_design_prompt.replace("{query}", text).replace("{model_solutions}", model_solutions_text).replace("{combined_solution}", combined_response),
        ]

        

        other_insights = ""
        for chunk in stream_multiple_models(
            self.keys, 
            models_to_use, 
            other_prompts, 
            images, 
            temperature, 
            max_tokens, 
            system,
            collapsible_headers=False,
            header_template=["Clarifications and Assumptions from {model}", 
                             "Other Areas from {model}", 
                             "Other Areas from {model}", 
                            #  "Other Areas from {model}", 
                             "Top-down Design from {model}"]
        ):
            yield chunk
            other_insights += chunk
        yield "\n\n"

        if self.n_steps <= 2:
            return

        phase_2_prompts = [
            # self.other_areas_diagrams_prompt.replace("{query}", text).replace("{model_solutions}", model_solutions_text).replace("{combined_solution}", combined_response).replace("{other_insights}", other_insights).replace("{more_information}", other_insights),
            self.what_if_questions_prompt.replace("{query}", text).replace("{model_solutions}", model_solutions_text).replace("{combined_solution}", combined_response).replace("{other_insights}", other_insights).replace("{more_information}", other_insights),
            # self.other_areas_phase_2_prompt_1.replace("{query}", text).replace("{model_solutions}", model_solutions_text).replace("{combined_solution}", combined_response).replace("{other_insights}", other_insights).replace("{more_information}", other_insights),
            # self.other_areas_phase_2_prompt_2.replace("{query}", text).replace("{model_solutions}", model_solutions_text).replace("{combined_solution}", combined_response).replace("{other_insights}", other_insights).replace("{more_information}", other_insights),
            self.tips_prompt.replace("{query}", text).replace("{model_solutions}", model_solutions_text).replace("{combined_solution}", combined_response).replace("{other_insights}", other_insights).replace("{more_information}", other_insights),
        ]

        

        phase_2_insights = ""
        for chunk in stream_multiple_models(
            self.keys, 
            models_to_use, 
            phase_2_prompts, 
            images, 
            temperature, 
            max_tokens, 
            system,
            collapsible_headers=False,
            header_template=[# "Diagrams from {model}", 
                             "What-if Questions from {model}", 
                            #  "Other Areas from {model}", 
                            #  "Other Areas from {model}", 
                             "Tips from {model}"]
        ):
            yield chunk
            phase_2_insights += chunk
        yield "\n\n"

        if self.n_steps <= 3:
            return

        web_search_response = web_search_response_future.result()
        yield from collapsible_wrapper(web_search_response, header="Web Search Results", show_initially=False, add_close_button=True)
        yield "\n\n"
        return


class MLSystemDesignInterviewerAgent(Agent):
    def __init__(self, keys, writer_model: Union[List[str], str], n_steps: int = 4):
        super().__init__(keys, writer_model, n_steps)

    def __call__(self, text, images=[], temperature=0.7, stream=True, max_tokens=None, system=None, web_search=False):
        return super().__call__(text, images, temperature, stream, max_tokens, system, web_search)
    

class MLSystemDesignCandidateAgent(Agent):
    def __init__(self, keys, writer_model: Union[List[str], str], n_steps: int = 4):
        super().__init__(keys, writer_model, n_steps)

    def __call__(self, text, images=[], temperature=0.7, stream=True, max_tokens=None, system=None, web_search=False):
        return super().__call__(text, images, temperature, stream, max_tokens, system, web_search)


