import random
import traceback
from typing import Union, List
import uuid


from common import collapsible_wrapper
from prompts import tts_friendly_format_instructions


import os
import tempfile
import shutil
import concurrent.futures
import logging
from openai import OpenAI
from pydub import AudioSegment  # For merging audio files


# Local imports  
try:
    import sys
    from pathlib import Path
    sys.path.append(str(Path(__file__).parent.parent))
    from prompts import tts_friendly_format_instructions, diagram_instructions
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
mathematical_notation = """
- Formatting Mathematical Equations:
  - Output any relevant equations in latex format putting each equation in a new line in separate '$$' environment. If you use `\\[ ... \\]` then use `\\\\` instead of `\\` for making the double backslash. We need to use double backslash so it should be `\\\\[ ... \\\\]` instead of `\\[ ... \\]`.
  - For inline maths and notations use "\\\\( ... \\\\)" instead of '$$'. That means for inline maths and notations use double backslash and a parenthesis opening and closing (so for opening you will use a double backslash and a opening parenthesis and for closing you will use a double backslash and a closing parenthesis) instead of dollar sign.
  - We need to use double backslash so it should be `\\\\[ ... \\\\]` instead of `\\[ ... \\]` and and `\\\\( ... \\\\)` instead of `\\( ... \\)` for inline maths.

- **Mathematical Notation**:
  - Present equations and formulas using LaTeX in separate `$$` environments or `\\\\( ... \\\\)` notation.
    $$
    \text{{Example Equation: }} E = mc^2
    $$
  - For inline math, use `\\\\( ... \\\\)` notation. That means for inline maths and notations use double backslash and a parenthesis opening and closing (so for opening you will use a double backslash and a opening parenthesis and for closing you will use a double backslash and a closing parenthesis) instead of dollar sign.

"""

class NStepCodeAgent(Agent):
    def __init__(self, keys, writer_model: Union[List[str], str], n_steps: int = 4):
        super().__init__(keys)
        self.writer_model = writer_model
        self.n_steps = n_steps
        
        self.prompt_1 = f"""
You are an expert coding instructor and interview preparation mentor with extensive experience in software engineering, algorithms, data structures, system design, and technical interviews at top tech companies. You possess deep knowledge of platforms like LeetCode, HackerRank, CodeSignal, and others, along with proven expertise in teaching coding concepts effectively. You teach coding and interview preparation in python and pseudocode.

You are given a query about a coding problem, please help us learn and understand the problem and then solve it step by step.
If multiple solutions are provided, please help us understand the pros and cons of each solution and then solve the problem step by step.

### 1. Breaking Down Solutions by patterns and concepts
- If no reference solutions are provided, develop the solution yourself and **guide us through it** and also mention that you are developing the solution yourself without any reference.
- **Decompose** each solution into manageable and understandable parts.
- Use **clear examples**, **analogies** to illustrate concepts.
- Provide **step-by-step explanations** of complex algorithms or logic.
- Before writing code, write a verbal step by step description of the solution along with the time and space complexity of the solution and any pattern or concept used in the solution. Write in simple language with simple formatting with inline maths and notations (if needed).

### 2. Diagrams
    - Create diagrams to help us understand the solution and the problem.
    - Use ASCII art to help us understand each solution by running them step by step.
    - Use ASCII art diagrams mainly to help illustrate the solution (or multiple solutions) and the problem. 
    - Step by step running example of the solutions can be written in a plaintext code block.

- We program in python, so write the code in python only.
{mathematical_notation}
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
Write code only if it is not provided already and if you have any new insights or optimizations to share.

Only cover the below guidelines suggested items. Limit your response to the below guidelines and items.
## Guidelines:

### 1. Discuss about the "Before Writing Code part"
- What are the clarifying questions we should ask to the interviewer?
- What are some key assumptions we need to make to solve the problem?
- What are some problem specific things we need to consider and keep in mind?
- Anything else that might impress the interviewer and give us an edge over other candidates? Only concrete and specific things.

### 2. Data Access Patterns and Performance for each solution
- Discuss how **data access patterns** impact performance.
- Explain techniques to optimize **memory usage** and **data retrieval**.
- Address issues like **cache utilization** and **locality of reference**.
- Real world implications of the data access patterns and performance, Caching (CPU, RAM, Disk etc), and other optimizations.

### 3. Analyzing Provided Solutions (If Applicable)
- Only analyze the provided solutions, don't write code.
- Code is not needed, verbal explanation is enough.
- **Review** our solution thoroughly for correctness and efficiency.
- **Validate** the logic and identify any errors or edge cases missed.
- Discuss the **trade-offs** and decisions made in our approach.
- Suggest improvements in:
  - **Algorithmic Efficiency**: Optimizing runtime and memory/space usage.
  - **Code Style**: Enhancing readability and maintainability.
  - **Data Access Patterns**: Optimizing data access patterns and performance.
- Highlight **trade-offs** between different solutions:
  - **Time vs. Space Complexity**
  - **Preprocessing Time vs. Query Time**
  - **Simplicity vs. Efficiency**
  - **Memory Access Patterns**
  - Offer a detailed **complexity analysis** for each solution.
    - Use **Big O notation** and explain the reasoning behind it (how you arrived at the time and space complexity).
    - Compare complexities between different solutions and discuss implications.

- Compare the solutions (make a table) and discuss the pros and cons of each solution (if there are multiple solutions).
- Analyse and tell which solution (if multiple solutions are provided) is the best solution and why it would impress the interviewer.
{mathematical_notation}

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
Code is not needed. Do not write code. Focus only on the below guidelines.


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
- Encourage us to consider **real-world scenarios** where such trade-offs are critical.

### 3. System Design and Architecture Considerations:
  - Designing scalable systems which might tackle this problem at a much larger scale.
  - Designing systems which use this algorithm or concept but in a much larger scale or a constrained environment.
  - Understanding architectural patterns.
  - Balancing trade-offs in system components.

### 4. Related and Important Topics and Concepts
- Discuss common **algorithmic paradigms** (e.g., divide and conquer, dynamic programming) where this problem or solution fits in.
- Highlight similar **patterns** that frequently appear in coding interviews.
- **Discuss** related and important topics and concepts that are relevant to the problem and solution.
- **Provide** examples and analogies to help us understand the concepts.
- **Explain** the relationship between the concepts and the problem and solution.
- **Discuss** how the concepts can be applied to other problems and solutions.
- **Mention** any other related topics and concepts that are important to know.
- **Discuss** follow-up extensions and variations of the problem and solution.




Query:
<user_query>
{{query}}
</user_query>

The user query above contains the user's query and some context around it including the previous conversation history and retreived documents and web search results if applicable.


Current Answer:
<current_answer>
{{current_answer}}
</current_answer>

Extend the answer to provide more information and details ensuring we cover the above framework and guidelines. Stay true and relevant to the user query and context.
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

1. **Examples and Analogies**:
  - Incorporate practical examples to illustrate abstract concepts.
  - Use analogies to relate complex ideas to familiar scenarios.
  - Connect this to real world scenarios and problems where this concept or algorithm or solution can be used.
  - Suggesting more real world examples and scenarios where this solution can be used.

2. Diagrams
    - You can use diagrams (ASCII art diagram or text-based diagram) to compare multiple solutions and discuss the pros and cons of each solution.
    - You can use diagrams to help us understand various nuances and corner cases of the solution.
    


Query:
<user_query>
{{query}}
</user_query>

The user query above contains the user's query and some context around it including the previous conversation history and retreived documents and web search results if applicable.


Current Answer:
<current_answer>
{{current_answer}}
</current_answer>

Extend the answer to provide more information and details ensuring we cover the above framework and guidelines. Stay true and relevant to the user query and context.
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
- Ask and hint on how to solve the problem if some constraints, data, or other conditions  are changed as per the above what-if questions and scenarios.
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

Extend the answer to provide more information and details ensuring we cover the above framework and guidelines. Stay true and relevant to the user query and context.
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
                llm3 = CallLLm(self.keys, self.writer_model if isinstance(self.writer_model, str) else self.writer_model[min(2, len(self.writer_model) - 1)])
                prompt3 = self.prompt_3.replace("{query}", text).replace("{current_answer}", p3_answer)
                response3 = llm3(prompt3, images, temperature, stream=True, max_tokens=max_tokens, system=system)
                
                # Stream prompt_3 response through the queue
                for chunk in collapsible_wrapper(response3, header="Edge Cases and Corner Cases", show_initially=True):
                    response_queue.put(("prompt3", chunk))
                    p3_answer += chunk
                
                # Mark prompt3 as completed
                completed["prompt3"] = True
                response_queue.put(("prompt3", "\n\n---\n\n"))
                p3_answer += "\n\n---\n\n"
                response_queue.put(("prompt3_complete", ""))
                
                multiple_llm_models = ["openai/chatgpt-4o-latest", "anthropic/claude-3.7-sonnet:beta", "anthropic/claude-3.5-sonnet:beta", "cohere/command-a"]
                multiple_llm = CallMultipleLLM(self.keys, self.writer_model if isinstance(self.writer_model, list) else (multiple_llm_models + ([self.writer_model] if self.writer_model not in multiple_llm_models else [])), merge=True, merge_model=multiple_llm_models[0])
                what_if_response = multiple_llm(self.what_if_prompt.replace("{query}", text).replace("{current_answer}", p3_answer), images, temperature, stream=stream, max_tokens=max_tokens, system=system)
        
                
                # Execute prompt_4 with updated answer including prompt_3's output
                llm4 = CallLLm(self.keys, self.writer_model if isinstance(self.writer_model, str) else self.writer_model[min(3, len(self.writer_model) - 1)])
                prompt4 = self.prompt_4.replace("{query}", text).replace("{current_answer}", p3_answer)
                response4 = llm4(prompt4, images, temperature, stream=True, max_tokens=max_tokens, system=system)
                
                # Stream prompt_4 response through the queue
                for chunk in collapsible_wrapper(response4, header="Examples and Diagrams", show_initially=True):
                    response_queue.put(("prompt4", chunk))
                
                # Mark prompt4 as completed
                completed["prompt4"] = True
                response_queue.put(("prompt4", "\n\n---\n\n"))
                response_queue.put(("prompt4_complete", ""))

                for chunk in collapsible_wrapper(what_if_response, header="What-if questions and scenarios", show_initially=True):
                    response_queue.put(("what_if", chunk))
                
                completed["what_if"] = True
                response_queue.put(("what_if", "\n\n---\n\n"))
                response_queue.put(("what_if_complete", ""))
                
            except Exception as e:
                error_msg = f"Error in background task: {e}\n{traceback.format_exc()}"
                logger.error(error_msg)
                response_queue.put(("error", error_msg))
            
            # Signal completion
            response_queue.put(("done", None))
        
        # Start background task
        background_future = get_async_future(execute_prompts_3_and_4)
        
        # Execute prompt_2 while prompts 3 and 4 are running in background
        llm2 = CallLLm(self.keys, self.writer_model if isinstance(self.writer_model, str) else self.writer_model[min(1, len(self.writer_model) - 1)])
        prompt2 = self.prompt_2.replace("{query}", text).replace("{current_answer}", current_answer)
        response2 = llm2(prompt2, images, temperature, stream=stream, max_tokens=max_tokens, system=system)
        
        # Stream prompt_2 results while checking for any available results from prompts 3 and 4
        for chunk in collapsible_wrapper(response2, header="Analysis of the solution", show_initially=True):
            yield chunk
            current_answer += chunk
            
            
        
        yield "\n\n---\n\n"
        current_answer += "\n\n---\n\n"
        
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


class MLSystemDesignAgent(Agent):
    def __init__(self, keys, writer_model: Union[List[str], str], n_steps: int = 4):
        super().__init__(keys)
        self.writer_model = writer_model
        self.n_steps = n_steps
        
        # ML System Design prompt based on the prompt template
        self.ml_system_design_prompt = """
**Persona**: You are an expert in machine learning, system design, and problem-solving. Your goal is to provide comprehensive, detailed, and insightful answers to open-ended ML system design questions. When presented with a design problem that involves machine learning elements, you should:  
**Role**: You are an expert instructor and interview preparation mentor with extensive experience in software engineering, ML system design, ML problem solving, system design, and technical interviews at top tech companies. You possess deep knowledge of platforms like LeetCode, HackerRank, CodeSignal, and others, along with proven expertise in teaching system design concepts effectively.

**Objective**: We will provide you with a ML system design **question** to practice. You will provide comprehensive, detailed, and insightful solutions to the problem. Your task is to help us **learn and understand the solutions thoroughly** by guiding us through the problem-solving process step by step. 
Help prepare us for technical ML system design interviews at the senior or staff level for FAANG and other top ML and AI companies.

{more_instructions}

Query:
<user_query>
{query}
</user_query>

Provide a comprehensive solution to this ML system design problem, following the framework above. Include specific approaches, architectural diagrams, and tips that would impress an interviewer at top ML companies.
"""

        self.ml_system_design_prompt_2 = """
## Framework for ML System Design Solution:

### 1. Problem Understanding and Requirements
- Clearly define the problem and scope
- Identify functional and non-functional requirements
- Outline key constraints and metrics for success
- Ask clarifying questions to refine understanding

### 2. Data Engineering and Pipeline Design
- Discuss data collection, storage, and preprocessing approaches
- Design data pipelines for training and inference
- Address data quality, bias, and distribution shift issues
- Consider data storage solutions and schema design

### 3. Model Selection and Development
- Evaluate candidate ML algorithms and architectures
- Justify model choices based on requirements
- Discuss feature engineering approaches
- Address trade-offs between different modeling approaches

### 4. Training Infrastructure and Strategy
- Design for distributed training if needed
- Explain hyperparameter tuning strategy
- Discuss experiment tracking and model versioning
- Outline compute resources required

### 5. Evaluation and Testing
- Define appropriate evaluation metrics
- Design offline and online testing approaches
- Discuss A/B testing methodology
- Address model validation and quality assurance

### 6. Deployment and Serving
- Design scalable inference infrastructure
- Address latency and throughput requirements
- Discuss model serving options (batch vs. real-time)
- Plan for monitoring and observability

### 7. Monitoring and Maintenance
- Design for detecting model drift and performance degradation
- Create plans for model updates and retraining
- Implement feedback loops for continuous improvement
- Address interpretability and debugging needs

### 8. Scaling and Optimization
- Identify potential bottlenecks and solutions
- Discuss caching strategies and optimization techniques
- Address high availability and fault tolerance
- Plan for geographical distribution if needed
"""

        self.ml_system_design_prompt_3 = """

**Remember to:**  
- **Think Critically and Creatively:** Go beyond standard solutions and consider innovative ideas.  
- **Be Comprehensive:** Cover all aspects that are relevant to solving the problem effectively.  
- **Maintain Logical Flow:** Ensure that your answer progresses logically from one point to the next.  
- **Stay Focused:** Keep your response relevant to the question, avoiding unnecessary tangents.  
- **Provide detailed and in-depth answers:** Provide detailed and in-depth answers to the question.  
- **Discuss the overall ML system lifecycle:** Discuss the overall ML system lifecycle.
- Plan for scalability
- Design for maintainability
- Account for operational costs
- Plan for future growth
- Document design decisions
- Consider team structure
- Plan for knowledge sharing
- Make diagrams, system architecture, flow diagrams etc as needed.
- Prefer ASCII art diagrams and mermaid diagrams.



"""

        # Combiner prompt to synthesize outputs from different models
        self.combiner_prompt = """
You are an expert ML system design interview coach. You will be provided with multiple solutions to an ML system design problem from different AI models. Your task is to synthesize these solutions into a single, comprehensive response that:

1. Combines the best ideas and approaches from each solution
2. Eliminates redundancy while preserving unique insights
3. Ensures complete coverage of all important ML system design aspects
4. Organizes the information in a logical, interview-friendly structure
5. Highlights the most important points that would impress an interviewer.
6. While comparing the solutions to the ML system design problem, compare the solutions rather than the models from which they came.

The original query was:
<user_query>
{query}
</user_query>

Here are the solutions from different models:

{model_solutions}

Contrast and compare the solutions and provide an analysis of the differences, pros and cons of each solution.
Then, create a comprehensive final solution synthesis that combines the all elements from all solutions. Focus on providing a well-structured approach that would help someone ace an ML system design interview.
"""

        self.clarifications_assumptions_prompt = """
You are an expert ML system design interview coach. You will be provided with multiple solutions to an ML system design problem from different AI models. Your task is to suggest what questions to ask and what assumptions to clarify with the interviewer to refine the understanding of the problem and the solution.

The original query was:
<user_query>
{query}
</user_query>

Here are the solutions from different models:

{model_solutions}

Combined Solution:
<combined_solution>
{combined_solution}
</combined_solution>

Suggest what questions we should ask the interviewer in the beginning of the interview to refine the understanding of the problem before we start discussing the solution.
Also suggest what assumptions we should make to simplify the problem and the solution before we start discussing the solution.
"""

        self.other_areas_prompt_1 = """
You are an expert ML system design interview coach. You will be provided with multiple solutions to an ML system design problem from different AI models.
Now focus on the following areas and provide a more details and a continuation of the solution. Don't repeat the same things that are already covered in the solution. Only add new insights and details.

**1. Cover Breadth and Depth:**  
- **Breadth:** Provide a broad perspective by discussing all relevant aspects of the problem.  
- **Depth:** Dive deep into critical components, explaining them thoroughly.  
- Discuss the overall ML system lifecycle. Cover each aspect of the system lifecycle in detail.
- Model selection criteria
- Framework selection justification
- Infrastructure requirements
- Capacity planning
- Performance benchmarking
- Technical debt considerations
- Feature engineering strategies
- Model selection criteria
- Evaluation metrics selection
- Validation strategies
- Performance optimization
- Resource utilization
- System boundaries
- Integration points

  
**2. Explore Multiple Approaches and Trade-Offs:**  
- Discuss various possible solutions or methodologies.  
- For each approach, analyze the pros and cons.  
- Highlight trade-offs between different options.  
- Explore how to interface the solution with other systems and actual customers. How the trade-offs and constraints affect the solution.
  
**3. Include Technical Details and Mathematical Formulations:**  
- Incorporate relevant algorithms, models, and techniques.  
- Present important equations in LaTeX format for clarity.  
- Formatting Mathematical Equations:
  - Output any relevant equations in latex format putting each equation in a new line in separate '$$' environment. If you use `\\[ ... \\]` then use `\\\\` instead of `\\` for making the double backslash. We need to use double backslash so it should be `\\\\[ ... \\\\]` instead of `\\[ ... \\]`.
  - For inline maths and notations use "\\\\( ... \\\\)" instead of '$$'. That means for inline maths and notations use double backslash and a parenthesis opening and closing (so for opening you will use a double backslash and a opening parenthesis and for closing you will use a double backslash and a closing parenthesis) instead of dollar sign.
  - We need to use double backslash so it should be `\\\\[ ... \\\\]` instead of `\\[ ... \\]` and and `\\\\( ... \\\\)` instead of `\\( ... \\)` for inline maths.

  
**4. Discuss Design Choices at Various Points:**  
- At each stage of your proposed solution, explain the decisions you make.  
- Justify why you choose one approach over another based on the context.  
  
**5. Consider Practical Implementation Aspects:**  
- Talk about scalability, reliability, and performance.  
- Address data requirements, data processing, and model training considerations.  
- Mention tools, frameworks, or technologies that could be used.  
- DevOps integration points
- Monitoring setup
- Alerting thresholds
- Backup strategies
- Disaster recovery plans
- Documentation requirements
- Infrastructure requirements
- Deployment strategies
- Monitoring setup
- Alerting mechanisms
- Scaling policies
- Resource management
- Performance optimization
- Operational procedures


**6. Consider Other Software Engineering, Design and Architecture Aspects:**  
- Consider maintainability, long term impact, and scalability.  
- Consider how flexible the system is, how easy it is to modify, and how easy it is to understand.  
- Consider other leadership and management aspects.  

**7. ML Lifecycle:**
- Discuss the overall ML system lifecycle.
- Address scalability and performance.
- Address interfaces, APIs, trade-offs, constraints, scaling, cost reduction, maintainability, robustness, new feature addition, model retraining, new data gathering, reporting, business metrics and KPIs, lowering operational costs and other aspects.
- Data collection strategies
- Feature engineering pipeline
- Model evaluation metrics
- Deployment strategies
- Monitoring setup
- Feedback loops
- Data collection and validation
- Feature engineering pipeline
- Model development workflow
- Training infrastructure
- Evaluation framework
- Deployment strategy
- Monitoring system
- Feedback loops
- Retraining triggers
- Version control
- Documentation requirements
- Quality assurance

**8. Address Potential Challenges and Mitigation Strategies:**  
- Identify possible issues or obstacles that might arise.  
- Propose solutions or alternatives to overcome these challenges.  
- Improvement Plan and planned iterations. Discuss how to improve the system over time.
  
**9. Provide Examples and Analogies (if helpful):**  
- Use examples to illustrate complex concepts.  
- Draw parallels with similar well-known systems or problems.  
  

The original query was:
<user_query>
{query}
</user_query>

Here are the solutions from different models:

{model_solutions}

Combined Solution:
<combined_solution>
{combined_solution}
</combined_solution>


Now provide a continuation of the solution focusing on the above areas.
"""
        self.other_areas_prompt_2 = """
You are an expert ML system design interview coach. You will be provided with multiple solutions to an ML system design problem from different AI models.
Now focus on the following areas and provide a more details and a continuation of the solution. Don't repeat the same things that are already covered in the solution. Only add new insights and details.

**1. Model Development and Training Pipeline:**
- Discuss model versioning and experiment tracking
- Address data versioning and lineage
- Detail training infrastructure requirements
- Explain model validation and testing strategies
- Consider distributed training needs
- Address training/serving skew

**2. MLOps and Production Considerations:**
- Model deployment strategies (canary, blue-green, shadow)
- Monitoring and observability setup
- Feature store architecture and management
- Model registry and artifact management
- CI/CD pipeline for ML models
- A/B testing infrastructure

**3. Ethics and Responsible AI:**
- Discuss bias detection and mitigation
- Address fairness considerations
- Consider privacy implications
- Explain model interpretability approaches
- Detail security considerations
- Compliance requirements (GDPR, CCPA, etc.)

**4. Cost and Resource Optimization:**
- Training cost analysis
- Inference cost optimization
- Resource allocation strategies
- Hardware acceleration options
- Cost-performance tradeoffs
- Budget considerations

**5. Data Quality and Management:**
- Data validation pipelines
- Quality monitoring systems
- Data drift detection
- Schema evolution handling
- Data governance
- Data augmentation strategies

**6. Error Handling and Recovery:**
- Failure modes analysis
- Fallback strategies
- Recovery procedures
- Circuit breakers
- Graceful degradation approaches
- SLA considerations

**7. Performance Optimization:**
- Model optimization techniques
- Inference optimization
- Batch processing strategies
- Caching strategies
- Load balancing approaches
- Autoscaling policies


**8. Model Governance and Compliance:**
- Model documentation requirements
- Model cards implementation
- Regulatory compliance frameworks
- Audit trails and logging
- Version control for models and data
- Model lineage tracking
- Compliance testing procedures
- Documentation standards

**9. System Reliability Engineering:**
- Reliability metrics and SLOs
- Fault tolerance mechanisms
- Chaos engineering practices
- Disaster recovery procedures
- Backup and restore strategies
- High availability design
- Load balancing approaches
- Circuit breaker patterns

**10. Infrastructure and Platform Design:**
- Container orchestration
- Service mesh architecture
- API gateway design
- Load balancing strategies
- Auto-scaling policies
- Resource allocation
- Infrastructure as Code (IaC)
- Platform security measures

**11. Data Engineering Pipeline:**
- Data ingestion patterns
- ETL/ELT workflows
- Stream processing
- Batch processing
- Data validation
- Data quality checks
- Schema evolution
- Data partitioning strategies

**12. Model Serving Architecture:**
- Serving infrastructure
- Model serving patterns
- Batch vs. Real-time inference
- Model compression techniques
- Hardware acceleration
- Inference optimization
- Serving scalability
- Load balancing strategies

**13. Monitoring and Observability:**
- Metrics collection
- Logging infrastructure
- Tracing systems
- Alerting mechanisms
- Dashboarding
- Performance monitoring
- Resource utilization
- System health checks

The original query was:
<user_query>
{query}
</user_query>

Here are the solutions from different models:

{model_solutions}

Combined Solution:
<combined_solution>
{combined_solution}
</combined_solution>


Now provide a continuation of the solution focusing on the above areas.
"""

        self.other_areas_prompt_3 = """
You are an expert ML system design interview coach. You will be provided with multiple solutions to an ML system design problem from different AI models.
Now focus on the following areas and provide a more details and a continuation of the solution. Don't repeat the same things that are already covered in the solution. Only add new insights and details.

**1. Security Considerations:**
- Data encryption
- Access control
- Authentication mechanisms
- Authorization policies
- Secure communication
- Vulnerability assessment
- Security testing
- Threat modeling

**2. Testing and Quality Assurance:**
- Unit testing strategies
- Integration testing
- System testing
- Performance testing
- Load testing
- Security testing
- Compliance testing
- Acceptance criteria
- ML metrics and KPIs

**3. Development and Deployment:**
- CI/CD pipelines
- Development workflows
- Code review processes
- Testing automation
- Deployment strategies
- Rollback procedures
- Feature flags
- Environment management

**4. Cost Optimization:**
- Resource optimization
- Cost monitoring
- Budget planning
- Resource allocation
- Capacity planning
- Performance tuning
- Infrastructure costs
- Operational costs

**5. Team and Process:**
- Team structure
- Roles and responsibilities
- Communication patterns
- Knowledge sharing
- Documentation practices
- Code review process
- Incident management
- Change management

**6. Future-Proofing:**
- Extensibility planning
- Technology evolution
- Scalability roadmap
- Migration strategies
- Technical debt management
- Innovation opportunities
- Platform evolution
- Architectural decisions

**7. Business Impact:**
- ROI analysis
- Business metrics
- Success criteria
- Performance indicators
- Business alignment
- Value proposition
- Risk assessment
- Impact measurement

**8. Experimentation and Research:**
- A/B testing framework
- Experiment tracking
- Research pipeline
- Innovation process
- Prototype development
- Validation methods
- Metrics definition
- Success criteria

**9. Edge Cases and Failure Modes:**
- Edge case handling
- Failure mode analysis
- Recovery procedures
- Graceful degradation
- Fallback strategies
- Error handling
- Exception management
- System boundaries


The original query was:
<user_query>
{query}
</user_query>

Here are the solutions from different models:

{model_solutions}

Combined Solution:
<combined_solution>
{combined_solution}
</combined_solution>


Now provide a continuation of the solution focusing on the above areas.
"""

        self.other_areas_phase_2_prompt_1 = """
You are an expert ML system design interview coach. You will be provided with multiple solutions to an ML system design problem from different AI models.
Now focus on the following areas and provide a more details and a continuation of the solution. Don't repeat the same things that are already covered in the solution. Only add new insights and details.

**1. Integration Patterns:**
- System interfaces
- API design
- Data contracts
- Integration patterns
- Communication protocols
- Service boundaries
- Interface evolution
- Version management

**2. Interdisciplinary Integration:**
- Domain expertise incorporation
- Subject matter expert collaboration
- Cross-functional team structures
- Knowledge elicitation techniques
- Translation of domain constraints to ML requirements
- Handling domain-specific uncertainty
- Integration with scientific workflows
- Validation through domain metrics

**3. User Experience and Human-Centered Design:**
- User interface considerations for ML systems
- Meaningful confidence indicators
- Error messaging strategies
- Design for appropriate trust
- Progressive disclosure of model details
- User control over model behavior
- User feedback collection mechanisms
- A/B testing for UX elements
- ML-specific UX patterns
- Explainability in user interfaces

**4. Multi-region and Edge Deployment:**
- Global distribution strategies
- Regional compliance variations
- Edge ML optimization techniques
- Model partitioning for edge-cloud collaboration
- Bandwidth optimization strategies
- Intermittent connectivity handling
- On-device training approaches
- Hardware acceleration for edge devices
- Versioning across distributed systems
- Region-specific model variations

**5. Privacy-Preserving ML Techniques:**
- Federated learning implementations
- Differential privacy approaches
- Homomorphic encryption options
- Secure multi-party computation
- Privacy-preserving data synthesis
- De-identification methodologies
- Anonymization techniques
- Privacy budget management
- Data minimization strategies
- Secure aggregation protocols

**6. Model Development Economics:**
- ROI calculation methodologies
- Cost attribution models
- Build vs. buy decision frameworks
- Commercial model API integration
- Open source model fine-tuning economics
- Training cost amortization
- Inference cost optimization
- Pricing models for ML capabilities
- Budget planning across ML lifecycle
- Economic impact of model performance

**7. Multimodal and Hybrid Systems:**
- Multimodal data integration architectures
- Cross-modal learning techniques
- Ensemble strategies for heterogeneous models
- Rule-based and ML hybrid approaches
- Symbolic and neural integration methods
- Knowledge graph augmentation
- Transfer learning across modalities
- Joint representation learning
- Attention mechanisms across modalities
- Multimodal evaluation frameworks

**8. Continuous Learning and Adaptation:**
- Online learning architectures
- Concept drift detection mechanisms
- Incremental learning approaches
- Catastrophic forgetting prevention
- Experience replay implementations
- Active learning workflows
- Curriculum learning strategies
- Self-supervised adaptation
- Reinforcement learning for adaptation
- Meta-learning applications

**9. Specialized Hardware Integration:**
- Custom accelerator selection criteria
- FPGA implementation strategies
- ASIC development considerations
- TPU/GPU optimization techniques
- Quantization for specialized hardware
- Model-hardware co-design principles
- Inference server optimization
- Hardware-aware training
- Multi-accelerator orchestration
- Energy efficiency optimization

**10. Technical Debt Management:**
- ML-specific code refactoring strategies
- Pipeline modernization approaches
- Legacy model migration techniques
- Feature maintenance lifecycles
- Deprecated data source handling
- Model cemetery management
- Documentation automation
- Technical knowledge transfer protocols
- Code quality metrics for ML
- Architecture modernization roadmaps

**11. Long-Term Support and Maintenance:**
- Model support planning
- End-of-life strategies for models
- Knowledge preservation mechanisms
- Long-term artifact storage
- Data evolution handling
- Code and environment preservation
- Dependency management strategies
- Documentation evolution
- Knowledge base maintenance
- Retraining decision frameworks


**12. Trade-off analysis:**
- Trade-off analysis
- Cost-benefit analysis
- Risk mitigation strategies
- Performance optimization
- Resource utilization
- System boundaries

**13. Foundation Models and Transfer Learning:**
- Pre-trained foundation model selection
- Fine-tuning strategies
- Prompt engineering architecture
- API integration vs. self-hosting tradeoffs
- Alignment techniques
- Domain adaptation approaches
- Parameter-efficient fine-tuning methods
- Quantization for deployment
- Inference optimization for large models
- Cost analysis for foundation model deployment

**14. Time Allocation Strategy:**
- Recommended time distribution for different design phases
- Critical path identification
- Prioritization framework for design components
- Time management during the interview
- Balancing breadth vs. depth in time-constrained settings
- Strategies for efficiently communicating complex designs
- Checkpoint approach for time management
- Decision framework for time allocation

**15. Industry-Specific ML System Patterns:**
- Healthcare ML design patterns (clinical validation, HIPAA compliance)
- Financial services ML architecture (fraud detection, regulatory requirements)
- Retail and e-commerce ML systems (recommendation systems, inventory forecasting)
- Manufacturing ML infrastructure (predictive maintenance, quality control)
- Content/media ML architectures (content moderation, recommendation)
- Transportation and logistics ML systems (route optimization, demand forecasting)
- Agriculture ML designs (yield prediction, resource optimization)
- Energy sector ML systems (consumption forecasting, grid optimization)

**16. Metric Selection and Design:**
- Business vs. technical metric alignment
- North star metric identification
- Proxy metrics design and validation
- Leading vs. lagging indicators
- Counter metrics to prevent optimization side effects
- Instrumentation strategies for metrics collection
- Metrics aggregation approaches
- Real-time vs. batch metric calculation
- Visualization and dashboarding considerations
- Statistical significance analysis

**17. Deployment Architecture Patterns:**
- Microservices vs. monolithic ML architectures
- Lambda architecture for ML systems
- Kappa architecture for streaming ML
- SAGA pattern for distributed ML transactions
- Circuit breaker pattern for ML services
- Bulkhead pattern for fault isolation
- Sidecar pattern for ML model deployment
- Ambassador pattern for ML API management
- Event sourcing for ML data pipelines
- CQRS for ML query optimization

The original query was:
<user_query>
{query}
</user_query>

Here are the solutions from different models:

{model_solutions}

Combined Solution:
<combined_solution>
{combined_solution}
</combined_solution>


More information about side areas:
<more_information>
{more_information}
</more_information>


Now provide a continuation of the solution focusing on the above areas.
"""

        self.other_areas_phase_2_prompt_2 = """
You are an expert ML system design interview coach. You will be provided with multiple solutions to an ML system design problem from different AI models.
Now focus on the following areas and provide a more details and a continuation of the solution. Don't repeat the same things that are already covered in the solution. Only add new insights and details.


**1. ML Interviewer Perspective:**
- Evaluation criteria used by interviewers
- Common red flags in ML system design interviews
- Indicators of senior/staff-level thinking
- Areas where candidates typically struggle
- Implicit expectations beyond stated requirements
- How to demonstrate technical leadership
- Balance between theoretical knowledge and practical implementation
- Signals of strong system design thinking

**2. Visualization and Communication:**
- System architecture diagram best practices
- Data flow visualization techniques
- Decision tree representation for model selection
- Pipeline visualization strategies
- Metrics dashboard design principles
- Sequence diagrams for temporal processes
- Component interaction visualization
- Error handling flow representation
- Deployment topology illustration
- Resource allocation visualization

**3. Interdisciplinary Integration:**
- Domain expertise incorporation
- Subject matter expert collaboration
- Cross-functional team structures
- Knowledge elicitation techniques
- Translation of domain constraints to ML requirements
- Handling domain-specific uncertainty
- Integration with scientific workflows
- Validation through domain metrics

**4. Advanced Responsible AI:**
- Model cards implementation and standardization
- Algorithmic impact assessments
- Disaggregated evaluation across demographic groups
- Fairness metrics selection framework
- Transparency report design
- Ethical review board integration
- Bias bounty programs
- Stakeholder inclusion in model governance
- Red teaming for adversarial testing
- Ethics-driven development lifecycle

**5. Machine Learning on Edge Devices:**
- On-device model optimization techniques
- Edge-cloud collaborative ML architectures
- Privacy-preserving edge inference
- Model compression for edge deployment
- Energy-efficient ML for battery-powered devices
- Federated learning at the edge
- Intermittent computation handling
- Sensor fusion strategies
- Update mechanism design
- Hardware acceleration selection

**6. Data-Centric ML Design:**
- Data quality assessment frameworks
- Data debugging strategies
- Active learning for efficient data collection
- Synthetic data generation architectures
- Data augmentation pipelines
- Weak supervision system design
- Data version control approaches
- Data documentation standards
- Data provenance tracking
- Dataset shifts handling mechanisms

**7. Evaluation Beyond Metrics:**
- A/B testing framework design
- Counterfactual evaluation approaches
- Human evaluation strategies
- Robustness assessment methods
- Stress testing methodologies
- Adversarial evaluation techniques
- Real-world pilot design
- Long-term impact assessment
- User acceptance testing approaches
- Comparative evaluation with existing systems

**8. MLOps Maturity Model:**
- Stages of MLOps maturity
- Manual to automated transition planning
- Continuous integration for ML models
- Continuous delivery for ML pipelines
- Continuous training architecture
- Feature store integration complexity
- Model governance progression
- Observability maturity path
- Compliance automation evolution
- Reproducibility guarantees by stage

**9. Generative AI System Design:**
- Prompt engineering infrastructure
- Chain-of-thought architecture
- Retrieval-augmented generation systems
- Safety mechanisms for generative models
- Hallucination mitigation strategies
- Content moderation pipelines
- User interaction designs
- Grounding mechanisms
- Context window optimization
- Output formatting and post-processing

**10. Cloud Provider ML Architecture:**
- AWS ML reference architectures
- GCP ML design patterns
- Azure ML infrastructure designs
- Hybrid cloud ML approaches
- Multi-cloud ML strategies
- Vendor lock-in mitigation
- Cloud cost optimization for ML
- Serverless ML architectures
- Cloud-native ML scaling patterns
- Managed services vs. custom infrastructure trade-offs

**11. Advanced Testing Strategies:**
- ML-specific unit testing frameworks
- Integration testing for ML pipelines
- Shadow deployment testing
- Canary testing for ML models
- Chaos engineering for ML systems
- Metamorphic testing for ML
- Golden dataset testing approach
- Model invariant testing
- Data contract testing
- Continuous model evaluation

**12. Knowledge Distillation and Model Compression:**
- Teacher-student architecture design
- Pruning strategies and infrastructure
- Quantization pipelines
- Low-rank factorization approaches
- Knowledge distillation at scale
- Sparse model training and serving
- Mixed precision training infrastructure
- Model compression automation
- Accuracy-latency trade-off framework
- Hardware-aware compression techniques

**13. ML System Failure Recovery:**
- Backup model deployment strategies
- Graceful degradation design
- Circuit breaker implementation for ML services
- Fallback heuristics design
- Automated recovery procedures
- Failure detection mechanisms
- State recovery approaches
- Service level objective maintenance during failures
- User communication during degraded performance
- Recovery testing methodologies

**14. Time Series and Sequential Data Systems:**
- Real-time forecasting architectures
- Streaming anomaly detection systems
- Sequential decision making frameworks
- Time-sensitive feature engineering pipelines
- Temporal data storage optimizations
- Seasonality handling mechanisms
- Concept drift detection for time series
- Multi-horizon prediction systems
- Event-driven forecasting architectures
- Temporal pattern mining infrastructure

The original query was:
<user_query>
{query}
</user_query>

Here are the solutions from different models:

{model_solutions}

Combined Solution:
<combined_solution>
{combined_solution}
</combined_solution>


More information about side areas:
<more_information>
{more_information}
</more_information>


Now provide a continuation of the solution focusing on the above areas.
"""


        self.other_areas_diagrams_prompt = f"""
You are an expert ML system design interview coach. You will be provided with multiple solutions to an ML system design problem from different AI models.
Now focus on the following areas and provide a more details and a continuation of the solution. Don't repeat the same things that are already covered in the solution. Only add new insights and details.

Focus only on making diagrams, system architecture, flow diagrams etc as needed in this prompt. Mostly ASCII art or mermaid diagrams. For complex diagrams, use mermaid diagrams.
{diagram_instructions}

The original query was:
<user_query>
{{query}}
</user_query>

Here are the solutions from different models:

{{model_solutions}}

Combined Solution:
<combined_solution>
{{combined_solution}}
</combined_solution>


More information about side areas:
<more_information>
{{more_information}}
</more_information>


Now provide a continuation of the solution focusing making diagrams, system architecture, flow diagrams etc only.
"""

        self.what_if_questions_prompt = """
You are an expert ML system design interview coach. You will be provided with multiple solutions to an ML system design problem from different AI models.
Now focus on the following areas and provide a more details and a continuation of the solution. Don't repeat the same things that are already covered in the solution. Only add new insights and details.

Only cover the below guidelines suggested items. Limit your response to the below guidelines and items.

Guidelines:
### 1. What-if questions and scenarios
- **Discuss** what-if questions and scenarios that are relevant to the problem and solution.
- Ask and hint on how to solve the problem if some constraints, data, or other conditions  are changed as per the above what-if questions and scenarios.
- Verbalize the solutions first and then also mention their time and space complexities. 


### 2. **More What-if questions and scenarios**:
  - **Discuss** what-if questions and scenarios that are relevant to the problem and solution.
  - Ask and hint on how to solve the problem if some constraints, data, or other conditions  are changed as per the above what-if questions and scenarios.
  - Verbalize the solutions first and then also mention their time and space complexities. 

### 3. **Mind Bending Questions**:
  - Tell us any new niche concepts or patterns that are used in the solution and any other niche concepts and topics that will be useful to learn.
  - Ask us some mind bending questions based on the solution and the problem to test our understanding and stimulate our thinking.
  - Provide verbal hints and clues to solve or approach the mind bending questions.


The original query was:
<user_query>
{query}
</user_query>

Here are the solutions from different models:

{model_solutions}

Combined Solution:
<combined_solution>
{combined_solution}
</combined_solution>


More information about side areas:
<more_information>
{more_information}
</more_information>

Now provide a continuation of the solution focusing on the above areas mentioned in the guidelines.
"""

        
        self.critic_prompt = """
You are an expert ML system design interview coach. You will be provided with multiple solutions to an ML system design problem from different AI models.
Now focus on the following areas and provide a more details and a continuation of the solution. Don't repeat the same things that are already covered in the solution. Only add new insights and details.



"""

        self.combined_critic_prompt = """
You are an expert ML system design interview coach. You will be provided with multiple solutions to an ML system design problem from different AI models.
Now focus on the following areas and provide a more details and a continuation of the solution. Don't repeat the same things that are already covered in the solution. Only add new insights and details.



"""
       
        self.tips_prompt = """


1. **Structure is key** - Following a clear framework helps interviewers follow your thought process
2. **Clarify requirements early** - Don't rush into solutions before understanding what's needed
3. **Focus on trade-offs** - Highlight the pros and cons of different approaches
4. **Draw system diagrams** - Visual representations demonstrate your ability to communicate complex ideas
5. **Connect theory to practice** - Mention real-world examples from your experience when possible
6. **Be adaptable** - Show you can pivot as requirements change during the interview
7. **Know your metrics** - Demonstrate deep understanding of how to evaluate ML system performance
8. **End with monitoring** - Always include plans for maintaining system quality over time
"""

    def __call__(self, text, images=[], temperature=0.7, stream=True, max_tokens=None, system=None, web_search=False):
        # Define the models to use
        multiple_llm_models = ["openai/chatgpt-4o-latest", "anthropic/claude-3.7-sonnet:beta", 
                            "anthropic/claude-3.5-sonnet:beta", 
                            "cohere/command-a",
                            "o1", "anthropic/claude-3.7-sonnet:thinking"]
        
        
        # Use provided models or fallback to default list
        if isinstance(self.writer_model, list):
            models_to_use = self.writer_model
        else:
            # Add writer_model to the list if it's not already there
            models_to_use = multiple_llm_models
            if isinstance(self.writer_model, str) and self.writer_model not in models_to_use:
                models_to_use.append(self.writer_model)

        # random shuffle the models
        random.shuffle(models_to_use)
        
        # Format ML system design prompt with user query
        ml_design_prompts = [
            self.ml_system_design_prompt.replace("{query}", text).replace("{more_instructions}", 
            self.ml_system_design_prompt_2 if i % 3 == 0 else self.ml_system_design_prompt_3 if i % 3 == 1 else "") 
            for i in range(len(models_to_use))
        ]
        
        # Stream results as they come in
        yield "# ML System Design Interview Preparation\n\n"
        
        # Stream from multiple models
        model_responses = yield from stream_multiple_models(
            self.keys, 
            models_to_use, 
            ml_design_prompts, 
            images, 
            temperature, 
            max_tokens, 
            system,
            collapsible_headers=False,
            header_template="Response from {model}"
        )
        
        # Combine all model responses
        yield "## Combined Analysis\n\n"
        
        # Prepare the combiner prompt with all model responses
        model_solutions_text = ""
        for model_name, response in model_responses.items():
            model_solutions_text += f"### Solution from {model_name}\n{response}\n\n"
        
        combiner_prompt = self.combiner_prompt.replace("{query}", text).replace("{model_solutions}", model_solutions_text)
        
        
        
        
        # Call the combiner model
        combiner_model = "openai/chatgpt-4o-latest"
        combined_response = ""
        try:
            combiner_llm = CallLLm(self.keys, combiner_model)
            combiner_response = combiner_llm(combiner_prompt, images, temperature, stream=True, max_tokens=max_tokens, system=system)
            
            # Stream the combined response inside a collapsible wrapper
            for chunk in collapsible_wrapper(combiner_response, header="Comprehensive ML System Design Solution", show_initially=True):
                yield chunk
                combined_response += chunk
                
        except Exception as e:
            error_msg = f"Error combining responses: {str(e)}\n{traceback.format_exc()}"
            logger.error(error_msg)
            yield f"\nError in combining responses: {error_msg}\n"

        if self.n_steps <= 1:
            return
        other_prompts = [
            self.other_areas_prompt_1.replace("{query}", text).replace("{model_solutions}", model_solutions_text).replace("{combined_solution}", combined_response) ,
            self.other_areas_prompt_2.replace("{query}", text).replace("{model_solutions}", model_solutions_text).replace("{combined_solution}", combined_response),
            self.other_areas_prompt_3.replace("{query}", text).replace("{model_solutions}", model_solutions_text).replace("{combined_solution}", combined_response),
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
            collapsible_headers=True,
            header_template="More Insights from {model}"
        ):
            yield chunk
            other_insights += chunk

        if self.n_steps <= 2:
            return

        phase_2_prompts = [
            self.other_areas_diagrams_prompt.replace("{query}", text).replace("{model_solutions}", model_solutions_text).replace("{combined_solution}", combined_response).replace("{other_insights}", other_insights).replace("{more_information}", other_insights),
            self.what_if_questions_prompt.replace("{query}", text).replace("{model_solutions}", model_solutions_text).replace("{combined_solution}", combined_response).replace("{other_insights}", other_insights).replace("{more_information}", other_insights),
            self.other_areas_phase_2_prompt_1.replace("{query}", text).replace("{model_solutions}", model_solutions_text).replace("{combined_solution}", combined_response).replace("{other_insights}", other_insights).replace("{more_information}", other_insights),
            self.other_areas_phase_2_prompt_2.replace("{query}", text).replace("{model_solutions}", model_solutions_text).replace("{combined_solution}", combined_response).replace("{other_insights}", other_insights).replace("{more_information}", other_insights),
            
        ]

        if self.n_steps <= 3:
            phase_2_prompts = phase_2_prompts[:2]

        phase_2_insights = ""
        for chunk in stream_multiple_models(
            self.keys, 
            models_to_use, 
            phase_2_prompts, 
            images, 
            temperature, 
            max_tokens, 
            system,
            collapsible_headers=True,
            header_template="More Insights from {model}"
        ):
            yield chunk
            phase_2_insights += chunk
            
            
            
        
        # Final insights and recommendations
        yield "\n\n## Final Tips for Interview Success\n\n"
        final_tips = self.tips_prompt
        yield final_tips


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

