import json
import random
import traceback
from typing import Union, List
import uuid


from common import VERY_CHEAP_LLM, collapsible_wrapper, convert_iterable_to_stream, fix_broken_json
from prompts import tts_friendly_format_instructions


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
from .search_and_information_agents import MultiSourceSearchAgent, PerplexitySearchAgent, JinaSearchAgent

system_message = """You are an expert Technical Interview Coach and Evaluator with extensive experience conducting coding interviews at top-tier technology companies (FAANG+ level). Your role is to simulate a realistic, challenging coding interview environment that prepares candidates for the most demanding technical interviews.

**Your Core Mission:**
Transform candidates into interview-ready engineers through rigorous, uncompromising evaluation and feedback. You conduct a complete coding interview simulation that mirrors real-world interview processes at leading tech companies.

**Interview Process Overview:**
1. **Problem Presentation**: Present coding problems with optional strategic ambiguities
2. **Clarification Phase**: Evaluate quality of candidate's clarifying questions
3. **Verbal Solution Analysis**: Assess approach, algorithm choice, and communication
4. **Implementation Phase**: Guide code writing and execution
5. **Code Review**: Analyze correctness, efficiency, and code quality  
6. **Advanced Discussion**: Explore edge cases, scaling, and optimizations
7. **Variations & Challenges**: Present problem modifications and optimization requests

**Your Evaluation Philosophy - BE BRUTAL AND HONEST:**
- **No Sugar-Coating**: Provide harsh, unforgiving feedback that mirrors aggressive real-world interviewers
- **Zero Tolerance for Mediocrity**: Push candidates beyond their comfort zone
- **Expose Every Weakness**: Identify and ruthlessly highlight gaps in knowledge, approach, or communication
- **Prepare for Battle**: Create a stressful environment that prepares them for the most challenging interviews
- **Constructive Brutality**: Be harsh but educational - every criticism must help them improve

**Key Behavioral Guidelines:**
- Challenge every assumption and approach
- Demand clear, precise technical communication
- Evaluate both solution correctness AND interview performance
- Push for optimal solutions, not just working ones  
- Assess problem-solving methodology, not just final answers
- Provide detailed technical analysis with brutal honesty about shortcomings
- Simulate time pressure and stress that candidates will face
- Focus on interview skills as much as technical skills

**Feedback Standards:**
- Be direct and uncompromising in your assessments
- Highlight every missed optimization or poor choice
- Demand senior-level thinking and communication
- Point out when candidates would fail real interviews
- Provide specific, actionable improvements
- Don't accept "good enough" - push for excellence

**Your Personality:**
- Be direct and uncompromising in your assessments
- Highlight every missed optimization or poor choice
- Demand senior-level thinking and communication
- Point out when candidates would fail real interviews
- Provide specific, actionable improvements
- Don't accept "good enough" - push for excellence

Your goal is to create candidates who can handle the most challenging technical interviews with confidence, having been battle-tested through your rigorous evaluation process.
Write in simple markdown text, and do not use math or latex formatting. Write code in triple backticks. For single line code, use single backticks. And use code blocks for code and to explain complex mathematical concepts. 
"""

def run_user_code(code):
    """Execute user's code and return results"""
    try:
        from code_runner import extract_code, run_code_with_constraints_v2, PersistentPythonEnvironment
        
        extracted_code = extract_code(code, relax=True)
        if not extracted_code:
                return { "success": False, "failure_reason": "No Python code found to execute.", "stdout": "", "stderr": "", "extracted_code": "" }

        code_session = PersistentPythonEnvironment()
        
        success, failure_reason, stdout, stderr = run_code_with_constraints_v2(
            extracted_code, constraints={}, session=code_session
        )
        
        del code_session
        
        return {
            "success": success,
            "failure_reason": failure_reason,
            "stdout": stdout,
            "stderr": stderr,
            "extracted_code": extracted_code
        }
    except Exception as e:
        return {
            "success": False,
            "failure_reason": f"Execution error: {str(e)}",
            "stdout": "",
            "stderr": str(e),
            "extracted_code": code
        }
    
states = {
    "INIT": "Initial state - prepare problem with optional ambiguity",
    "CLARIFICATION_WAIT": "Waiting for user clarification questions, Back and forth clarification discussion", 
    "VERBAL_ANALYSIS": "Analyzing verbal solution and providing feedback",
    "IMPLEMENTATION_WAIT": "Waiting for user to implement code solution",
    "CODE_ANALYSIS": "Analyzing submitted code and running tests",
    "HINT_LOOP": "Helping user correct mistakes with hints",
    "SENIOR_DISCUSSION": "Edge cases, scaling, senior-level aspects",
    "VARIATIONS": "Asking for problem variations or alternative solutions",
    "OPTIMIZATION_REQUEST": "Requesting more optimal or constrained solution",
    "TERMINATED": "Interview session ended"
}


class InterviewSimulatorAgent(Agent):
    def __init__(self, keys, writer_model: Union[List[str], str], conversation_id: str = None, detail_level: int = 1, timeout: int = 90):
        super().__init__(keys)
        self.writer_model = writer_model
        self.conversation_id = conversation_id
        self.detail_level = detail_level
        self.timeout = timeout
        
        # Unified system message for all LLM calls
        self.system_message = system_message
        
        # State definitions
        self.STATES = states

        # Define possible intents
        self.POSSIBLE_INTENTS = [
            "ASK_CLARIFICATION",      # User wants to ask clarifying questions
            "PROVIDE_VERBAL_SOLUTION", # User wants to explain their approach
            "SUBMIT_CODE",            # User is submitting code implementation
            "REQUEST_HINT",           # User wants a hint
            "READY_TO_PROCEED",       # User is ready to move to next phase
            "DISCUSS_OPTIMIZATION",   # User wants to discuss optimization
            "DISCUSS_VARIATIONS",     # User wants to discuss problem variations
            "ASK_FOR_REVIEW",         # User wants code review
            "QUIT_SESSION",           # User wants to end the session
            "GENERAL_DISCUSSION",     # General discussion about the problem
            "CONFUSED_NEED_HELP",     # User is confused and needs guidance
            "CHALLENGE_ACCEPTED",     # User accepts a challenge/variation
            "PROVIDE_ALTERNATIVE"     # User provides alternative solution
        ]
        
        # Reward/penalty levels for gamification
        self.REWARD_LEVELS = {
            "EXCELLENT": {"audio": "reward_excellent", "animation": "celebration_5", "score": 10},
            "VERY_GOOD": {"audio": "reward_very_good", "animation": "celebration_4", "score": 7},
            "GOOD": {"audio": "reward_good", "animation": "celebration_3", "score": 5},
            "FAIR": {"audio": "reward_fair", "animation": "celebration_2", "score": 3},
            "BASIC": {"audio": "reward_basic", "animation": "celebration_1", "score": 1}
        }
        
        self.PENALTY_LEVELS = {
            "MINOR": {"audio": "penalty_minor", "animation": "disappointment_1", "score": -1},
            "SMALL_MISTAKE": {"audio": "penalty_minor", "animation": "disappointment_1", "score": -1},

            "MODERATE": {"audio": "penalty_moderate", "animation": "disappointment_2", "score": -3},
            "UNNECESSARY": {"audio": "penalty_moderate", "animation": "disappointment_2", "score": -3},

            "SIGNIFICANT": {"audio": "penalty_significant", "animation": "disappointment_3", "score": -5},
            "BIG_MISTAKE": {"audio": "penalty_significant", "animation": "disappointment_3", "score": -5},

            "MAJOR": {"audio": "penalty_major", "animation": "disappointment_4", "score": -7},
            "BLUNDER": {"audio": "penalty_major", "animation": "disappointment_4", "score": -7},

            "CRITICAL": {"audio": "penalty_critical", "animation": "disappointment_5", "score": -10},
            "DISASTER": {"audio": "penalty_critical", "animation": "disappointment_5", "score": -10}
        }

        self.quality_rewards = {
            "EXCELLENT": ("reward", "EXCELLENT", "Outstanding clarifying questions!"),
            "VERY_GOOD": ("reward", "VERY_GOOD", "Great questions!"),
            "GOOD": ("reward", "GOOD", "Good questions asked!"),
            "FAIR": ("reward", "FAIR", "Questions noted."),
            "BASIC": ("reward", "BASIC", "Questions noted."),

            "SMALL_MISTAKE": ("penalty", "SMALL_MISTAKE", "These questions weren't strictly necessary but it's good to be thorough."),
            "UNNECESSARY": ("penalty", "UNNECESSARY", "These questions weren't strictly necessary but it's good to be thorough."),
            "BIG_MISTAKE": ("penalty", "BIG_MISTAKE", "These questions weren't strictly necessary but it's good to be thorough."),
            "BLUNDER": ("penalty", "BLUNDER", "These questions weren't strictly necessary but it's good to be thorough."),
            "DISASTER": ("penalty", "DISASTER", "These questions weren't necessary.")
        }
        
        # Configuration
        self.ambiguity_probability = 0.3  # 30% chance to add ambiguity

    def _extract_conversation_id(self, text):
        """Extract conversation ID from text"""
        if self.conversation_id is not None:
            return self.conversation_id
        
        import re
        # First try to extract from text
        match = re.search(r'<conversation_id>([^<]+)</conversation_id>', text)
        if match:
            return match.group(1)
        
        # Final fallback to ensure we always have a valid ID
        return "default"

    def _create_storage_key(self, conversation_id, problem_name):
        """Create MD5 hash key for file storage"""
        import hashlib
        key = f"{conversation_id}_{problem_name}"
        return hashlib.md5(key.encode()).hexdigest()

    def _load_persistent_data(self, storage_key):
        """Load persistent data from file"""
        import json
        import os
        
        storage_dir = "temp/interview_sessions"
        os.makedirs(storage_dir, exist_ok=True)
        storage_path = os.path.join(storage_dir, f"{storage_key}.json")
        
        try:
            if os.path.exists(storage_path):
                with open(storage_path, 'r') as f:
                    return json.load(f)
        except Exception as e:
            print(f"Error loading persistent data: {e}")
        
        return {}

    def _save_persistent_data(self, storage_key, data):
        """Save persistent data to file"""
        import json
        import os
        
        storage_dir = "temp/interview_sessions"
        os.makedirs(storage_dir, exist_ok=True)
        storage_path = os.path.join(storage_dir, f"{storage_key}.json")
        
        try:
            with open(storage_path, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"Error saving persistent data: {e}")

    def _parse_previous_state(self, chat_history):
        """Parse the most recent state from chat history"""
        import re
        import json

        # Define the default state
        default_state = {
            "current_state": "INIT",
            "problem_statement": "",
            "original_problem": "",
            "problem_name": "",
            "user_score": 0,
            "clarification_count": 0,
            "hint_count": 0,
            "attempts": 0,
            "problem_solved": False,
            "session_problems_count": 0,
            "fast_solve_bonus": False,
            "good_questions_asked": 0,
            "session_start_time": None,
            "conversation_summary": ""
        }

        # Return default state if chat_history is empty
        if not chat_history:
            return default_state

        # Define multiple regex patterns to find state data with different possible formats
        state_patterns = [
            # Standard format with details tag
            r'<details[^>]*>\s*<summary><strong>🤖 Agent State</strong></summary>\s*<pre><code>(.*?)</code></pre>\s*</details>',
            # Alternative format that might appear in some messages
            r'<details[^>]*>\s*<summary><strong>🤖 Agent State</strong></summary>\s*<pre><code>(.*?)</code></pre>.*?</details>',
            # JSON within pre/code tags (NEW PATTERN)
            r'<pre><code>\s*(\{.*?\})\s*</code></pre>',
            # Direct JSON format that might be present in some messages
            r'"current_state":\s*"[^"]+",\s*"problem_statement":\s*"[^"]*".*?"conversation_summary":\s*"[^"]*"',
            # Direct JSON format that might be present in some messages
            r'\{.*\}',
        ]

        # Try each pattern until we find a match
        for pattern in state_patterns:
            matches = re.findall(pattern, chat_history, re.DOTALL)
            if matches:
                last_state_data = matches[-1].strip()
                try:
                    # Parse the JSON state data
                    state_data = json.loads(last_state_data)
                    
                    # If last state was TERMINATED, reset to INIT
                    if state_data.get("current_state") == "TERMINATED":
                        return default_state
                        
                    return {**default_state, **state_data}
                except json.JSONDecodeError:
                    print(f"Error: JSON decoding failed for the state data with pattern {pattern}.")
                    # Continue to try other patterns or matches
        
        # If we couldn't extract state from patterns, try to find it in the model's response
        model_response_pattern = r'<model>(.*?)</model>'
        model_matches = re.findall(model_response_pattern, chat_history, re.DOTALL)
        if model_matches:
            for model_content in model_matches:
                # Try the same patterns within the model content
                for pattern in state_patterns:
                    matches = re.findall(pattern, model_content, re.DOTALL)
                    if matches:
                        last_state_data = matches[-1].strip()
                        try:
                            state_data = json.loads(last_state_data)
                            if state_data.get("current_state") == "TERMINATED":
                                return default_state
                            return {**default_state, **state_data}
                        except json.JSONDecodeError:
                            print(f"Error: JSON decoding failed for state data in model content.")
        
        # Return default state if no valid state data is found
        return default_state

    def _create_state_info(self, state_data):
        """Create collapsible state information for persistence - excludes large text fields"""
        import json
        
        # Define large text fields that should be stored in files, not in chat
        large_text_fields = {
            'problem_statement', 
            'original_problem', 
            'detailed_problem_description', 
            'solution_details'
        }
        
        # Create a copy of state_data without large text fields
        compact_state_data = {k: v for k, v in state_data.items() if k not in large_text_fields}
        
        state_json = json.dumps(compact_state_data, indent=2)
        # Use a generator to yield the string
        yield convert_stream_to_iterable(collapsible_wrapper(
            f"<pre><code>{state_json}</code></pre>", 
            header="🤖 Agent State", 
            show_initially=False
        ))

    def _save_state(self, state_data, conversation_id):
        """Save state data by splitting into chat storage (short) and file storage (large), and yield state info"""
        if not state_data.get("problem_name") or not conversation_id:
            return
            
        self._save_complete_state(state_data, conversation_id)
        
        # Yield state info for display
        yield from self._create_state_info(state_data)
        

    def _get_full_state_data(self, text, conversation_id=None):
        """Get complete state data by combining chat state and persistent file data"""
        # Get basic state from chat history
        state_data = self._parse_previous_state(text)
        
        # If we have a problem name and conversation ID, load persistent data
        if state_data.get("problem_name") and conversation_id:
            storage_key = self._create_storage_key(conversation_id, state_data["problem_name"])
            persistent_data = self._load_persistent_data(storage_key)
            # Merge persistent data into state data
            state_data.update(persistent_data)
        
        return state_data

    def _save_complete_state(self, state_data, conversation_id):
        """Save state data by splitting into chat storage (short) and file storage (large)"""
        if not state_data.get("problem_name") or not conversation_id:
            return
            
        storage_key = self._create_storage_key(conversation_id, state_data["problem_name"])
        
        # Define large text fields that go to file storage
        large_text_fields = {
            'problem_statement', 
            'original_problem', 
            'detailed_problem_description', 
            'solution_details'
        }
        
        # Split data into persistent (large) and chat (compact) storage
        persistent_data = {k: v for k, v in state_data.items() if k in large_text_fields}
        
        # Save large text fields to file
        if persistent_data:
            self._save_persistent_data(storage_key, persistent_data)

    def _add_gamification(self, reward_type, level, message=""):
        """Add gamification elements to response with enhanced animation support"""
        if reward_type == "reward":
            reward_info = self.REWARD_LEVELS.get(level, self.REWARD_LEVELS["BASIC"])
            return f"""<audio style="display: none;">{reward_info['audio']}</audio>
<animation style="display: none;">{reward_info['animation']}</animation>
<message style="display: none;">{message}</message>
🎉 **{level.title()} Performance!** {message} (+{reward_info['score']} points)

"""
        elif reward_type == "penalty":
            penalty_info = self.PENALTY_LEVELS.get(level, self.PENALTY_LEVELS["MINOR"]) 
            return f"""<audio style="display: none;">{penalty_info['audio']}</audio>
<animation style="display: none;">{penalty_info['animation']}</animation>
<message style="display: none;">{message}</message>
😔 **{level.title()} Issue** {message} ({penalty_info['score']} points)

"""
        return ""
    
    def _calculate_fast_solve_bonus(self, start_time, problem_difficulty):
        """Calculate bonus for fast solving"""
        import time
        solve_time = time.time() - start_time
        # Award bonus for solving within time thresholds
        if solve_time < 300:  # 5 minutes
            return ("reward", "EXCELLENT", "Lightning fast solve!")
        elif solve_time < 600:  # 10 minutes
            return ("reward", "VERY_GOOD", "Quick solve!")
        return None

    def _check_session_achievements(self, state_data):
        """Check for session-level achievements"""
        if state_data["session_problems_count"] >= 3:
            return ("reward", "GOOD", "3 problems in one session!")
        return None

    def _intent_and_next_state_determination(self, text, state_data):
        """Determine intent and next state based on user input"""
        
        POSSIBLE_INTENTS = self.POSSIBLE_INTENTS
        
        current_state = state_data.get("current_state", "INIT")
        
        # Create context-aware prompt for intent detection
        intent_prompt = f"""
You are analyzing a candidate's response during a technical interview to determine their intent and what should happen next.

Current interview state: {current_state}
State description: {self.STATES.get(current_state, "Unknown state")}

Problem context: {state_data.get('problem_statement', 'No problem set yet')}

Expected solution: 
```
{state_data.get('solution_details', '')}
```

Candidate's message and context: "{text}"

Conversation summary so far: {state_data.get('conversation_summary', 'New session')}



Based on the candidate's message and current state, determine:
1. What the candidate intends to do
2. What the next state should be
3. Whether a response is needed and what type
4. `if intent in ["REQUEST_HINT", "GENERAL_DISCUSSION", "DISCUSS_OPTIMIZATION", "DISCUSS_VARIATIONS", "CONFUSED_NEED_HELP"]` then needs_response should be True. Also provide the full, immediately helpful, detailed and final response text in `suggested_response` field if needs_response is True.
5. Write in simple markdown text, and do not use math or latex formatting. Write code in triple backticks. For single line code, use single backticks. And use code blocks for code and to explain complex mathematical concepts. 

Possible intents: {', '.join(POSSIBLE_INTENTS)}
Possible next states: {', '.join([f"{key}: {value}" for key, value in self.STATES.items()])}

Respond with a JSON object:
{{
    "intent": "one of the possible intents",
    "next_state": "appropriate next state from the STATES list",
    "needs_response": true/false,
    "response_type": "HINT/DISCUSSION/FEEDBACK/ENCOURAGEMENT/CLARIFICATION/NONE",
    "suggested_response": "if needs_response is true, provide the response text here, Provide a detailed, helpful and encouraging response to the candidate's message. If needs_response is false, then provide an empty string."
}}

Consider the flow:
- INIT -> CLARIFICATION_WAIT (after problem presentation)
- CLARIFICATION_WAIT -> VERBAL_ANALYSIS (after approach given)
- VERBAL_ANALYSIS -> IMPLEMENTATION_WAIT (if approach good) or HINT_LOOP (if needs help)
- IMPLEMENTATION_WAIT -> CODE_ANALYSIS (after code submitted)
- CODE_ANALYSIS -> SENIOR_DISCUSSION (if correct) or HINT_LOOP (if incorrect)
- And so on...
"""
        
        current_system = f"You are currently analyzing the candidate's response to determine their intent and decide the next interview state. Current interview state: {current_state}. Your job is to parse their message and determine what they want to do next in the interview process, then decide the appropriate transition."
        
        llm = CallLLm(self.keys, self.writer_model if isinstance(self.writer_model, str) else self.writer_model[0])
        response = llm(intent_prompt, temperature=0.1, stream=False, system=self.system_message + "\n\n" + current_system)
        
        try:
            # Try to parse JSON response
            import json
            import re
            
            # Extract JSON from response if it's wrapped in other text
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                json_string = json_match.group()
                json_string = json_string.replace("```json", "").replace("```", "")
                analysis = json.loads(json_string)
                
                intent = analysis.get("intent", "GENERAL_DISCUSSION")
                next_state = analysis.get("next_state", current_state)
                needs_response = analysis.get("needs_response", True)
                response_text = analysis.get("suggested_response", "") if needs_response else ""
                
                # Validate next_state is in our STATES
                if next_state not in self.STATES:
                    next_state = current_state
                
                # Validate intent is in our possible intents
                if intent not in POSSIBLE_INTENTS:
                    intent = "GENERAL_DISCUSSION"
                
                return {
                    "intent": intent,
                    "next_state": next_state,
                    "response": response_text,
                    "needs_response": needs_response,
                    "response_type": analysis.get("response_type", "DISCUSSION")
                }
                
        except (json.JSONDecodeError, AttributeError, TypeError) as e:
            # Fallback logic if LLM doesn't return valid JSON
            logger.warning(f"Failed to parse intent analysis JSON: {e}")
        
        # Fallback: simple keyword-based intent detection
        text_lower = text.lower()
        
        if any(word in text_lower for word in ["hint", "help", "stuck", "confused"]):
            return {
                "intent": "REQUEST_HINT",
                "next_state": "HINT_LOOP",
                "response": "I can provide a hint to help you move forward.",
                "confidence": "HIGH",
                "reasoning": "Keyword-based fallback detection",
                "needs_response": True,
                "response_type": "HINT"
            }
        elif any(word in text_lower for word in ["quit", "exit", "done", "finish"]):
            return {
                "intent": "QUIT_SESSION",
                "next_state": "TERMINATED",
                "response": "",
                "confidence": "HIGH",
                "reasoning": "Keyword-based fallback detection",
                "needs_response": False,
                "response_type": "NONE"
            }
        elif "```" in text or "def " in text or "class " in text:
            return {
                "intent": "SUBMIT_CODE",
                "next_state": "CODE_ANALYSIS",
                "response": "",
                "confidence": "MEDIUM",
                "reasoning": "Code detected in message",
                "needs_response": False,
                "response_type": "NONE"
            }
        else:
            return {
                "intent": "GENERAL_DISCUSSION",
                "next_state": current_state,
                "response": "I understand. Let me help you with that.",
                "confidence": "LOW",
                "reasoning": "Fallback - no clear intent detected",
                "needs_response": True,
                "response_type": "DISCUSSION"
            }
    
    def _generate_detailed_problem_description(self, original_problem):
        """Generate detailed problem description via LLM"""
        prompt = f"""
Analyze this coding problem and provide a detailed, structured description:

Original Problem: {original_problem}

Please provide a comprehensive breakdown including:
1. Problem statement in clear terms
2. Input/output specifications
3. Constraints and edge cases
4. Examples with explanations
5. Key algorithmic concepts involved
6. Focus on the core coding problem and not the AI assistant's behavior or formatting guidelines.

Format this as a detailed problem description that would be used throughout an interview session.
"""
        
        current_system = "You are currently generating a detailed, comprehensive problem description for a coding interview. Your role is to transform the raw problem input into a well-structured, clear problem statement with proper constraints, examples, and specifications that an interviewer would present."
        
        llm = CallLLm(self.keys, self.writer_model if isinstance(self.writer_model, str) else self.writer_model[0])
        return llm(prompt, temperature=0.3, stream=False, system=self.system_message + "\n\n" + current_system)

    def _generate_solution_details(self, original_problem):
        """Generate detailed solution via LLM"""
        prompt = f"""
Provide a comprehensive solution analysis for this coding problem:

Problem: {original_problem}

Please include:
1. Multiple solution approaches (brute force, optimal, etc.)
2. Time and space complexity analysis
3. Code implementation in Python
4. Key insights and patterns
5. Common mistakes to avoid
6. Follow-up variations
7. Focus on the core coding problem and not the AI assistant's behavior or formatting guidelines.

This will be used by an interviewer to guide the candidate.
"""
        
        current_system = "You are currently generating comprehensive solution analysis and implementation details for the interviewer's reference. Your role is to create the 'answer key' that will help the interviewer evaluate the candidate's approach, identify optimal solutions, and provide hints when needed."
        
        llm = CallLLm(self.keys, self.writer_model if isinstance(self.writer_model, str) else self.writer_model[0])
        return llm(prompt, temperature=0.3, stream=False, system=self.system_message + "\n\n" + current_system)

    def _generate_problem_name(self, original_problem):
        """Generate a one-sentence problem name/description"""
        prompt = f"""
Given this coding problem, provide a concise one-sentence description that captures the essence:

Problem: {original_problem}

Give one sentence description of the coding problem. Ignore other details which talk about how the AI assistant must behave and formatting guidelines etc.

Return just the one-sentence description, nothing else.
"""
        
        current_system = "You are currently generating a concise, descriptive name for the coding problem that will be used for identification and storage purposes. Your role is to extract the core essence of the problem into a single, clear sentence."
        
        llm = CallLLm(self.keys, self.writer_model if isinstance(self.writer_model, str) else self.writer_model[0])
        return llm(prompt, temperature=0.3, stream=False, system=self.system_message + "\n\n" + current_system).strip()

    def _update_conversation_summary(self, state_data, original_problem=None, modified_problem=None, new_action=None):
        """Update the conversation summary with a structured LLM-based summary"""
        # Prepare the prompt for the LLM to generate a structured summary
        summary_prompt = f"""
Create a structured summary of the conversation so far. Include:
1. Original Problem: {original_problem or 'N/A'}
2. Modified Problem: {modified_problem or 'N/A'}
3. Recent Action: {new_action or 'N/A'}
4. Current State: {state_data.get('current_state', 'N/A')}
5. User Score: {state_data.get('user_score', 0)}
6. Clarification Count: {state_data.get('clarification_count', 0)}
7. Hint Count: {state_data.get('hint_count', 0)}
8. Attempts: {state_data.get('attempts', 0)}
9. Problem Solved: {state_data.get('problem_solved', False)}
10. Session Problems Count: {state_data.get('session_problems_count', 0)}
11. Fast Solve Bonus: {state_data.get('fast_solve_bonus', False)}
12. Good Questions Asked: {state_data.get('good_questions_asked', 0)}
13. Session Start Time: {state_data.get('session_start_time', 'N/A')}
14. Conversation Summary: Write your own summary of the conversation so far.

Provide a brief, concise and structured summary that captures the essence of the session till now with focus on recent actions and state.
"""
        
        # Call the LLM to generate the summary
        current_system = "You are currently updating the session summary to track the candidate's progress, actions, and performance throughout the interview. Your role is to maintain a concise but comprehensive record of what has happened so far."
        
        llm = CallLLm(self.keys, self.writer_model if isinstance(self.writer_model, str) else self.writer_model[0])
        structured_summary = llm(summary_prompt, temperature=0.3, stream=False, system=self.system_message + "\n\n" + current_system).strip()
        
        # Update the state data with the new structured summary
        state_data["conversation_summary"] = structured_summary

    def _evaluate_clarification_questions(self, user_input, problem_context):
        """Evaluate quality of user's clarification questions"""
        evaluation_prompt = f"""
Analyze the user's clarification questions for a coding interview problem. Also provide a response to the candidate's question if needed. And determine if the candidate is ready to proceed to the solution phase.

Problem context: 

```
{problem_context}
```

User questions: 

```
{user_input}
```

Rate the questions on:
1. Relevance (are they about important constraints/edge cases?)
2. Necessity (are they truly needed for solving the problem?)
3. Interview-appropriate (would these be good questions in a real interview?)
4. Write in short and concise manner. Be brutal and honest and unforgiving. We need to be harsh on the candidate so that they can improve and are prepared for the real interview.
5. Your output should be in JSON format as given below.
6. If user asks a clarification question then is_ready_to_proceed should be False. On the other hand, if user explicitly says that they are ready to proceed to the solution phase or coding phase, then is_ready_to_proceed should be True.

Return JSON: 
{{
    "quality": "EXCELLENT/VERY_GOOD/GOOD/FAIR/BASIC/UNNECESSARY/SMALL_MISTAKE/BIG_MISTAKE/BLUNDER/DISASTER", 
    "reasoning": "brief explanation of the quality of questions asked", 
    "clarification_response": "Helpful and encouraging response to the candidate's question which is not a solution to the problem but clears their doubt and guides them to the right path.",
    "is_ready_to_proceed": "True/False"
}}

"""
        
        current_system = "You are currently evaluating the quality of the candidate's clarifying questions. Your role is to assess whether their questions demonstrate good interview judgment, focus on important constraints, and show proper problem analysis skills. Be harsh in your evaluation."
        
        llm = CallLLm(self.keys, self.writer_model if isinstance(self.writer_model, str) else self.writer_model[0])
        response = llm(evaluation_prompt, temperature=0.3, stream=False, system=self.system_message + "\n\n" + current_system)
        
        try:
            import json
            import re
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
        except (json.JSONDecodeError, AttributeError):
            pass
        
        return {"quality": "FAIR", "reasoning": "Unable to evaluate", "clarification_response": "Unable to evaluate", "is_ready_to_proceed": False}

    def _generate_problem_with_ambiguity(self, original_problem, add_ambiguity):
        """Generate problem statement with optional ambiguity"""
        instruction = "Add subtle ambiguities that would require clarification in a real interview. Make 1-2 constraints unclear or missing." if add_ambiguity else "Present the problem clearly without ambiguities."
        ambiguity_prompt = f"""
You are conducting a coding interview. Transform this problem statement:

Original: {original_problem}
_
{instruction}

Focus on the core coding problem and not the AI assistant's behavior or formatting guidelines.

Return the problem statement that an interviewer would give.
Just the problem statement, nothing else.
"""
        
        current_system = f"You are currently transforming the problem statement for presentation to the candidate. Your role is to {'add strategic ambiguities that require clarification' if add_ambiguity else 'present the problem clearly without ambiguities'}. This tests the candidate's ability to ask good clarifying questions."
        
        llm = CallLLm(self.keys, self.writer_model if isinstance(self.writer_model, str) else self.writer_model[0])
        return llm(ambiguity_prompt, temperature=0.5, stream=False, system=self.system_message + "\n\n" + current_system)

    def _analyze_verbal_solution(self, problem_name, problem_statement, user_solution, correct_solution):
        """Analyze user's verbal solution approach"""
        analysis_prompt = f"""
**Role**: You are an expert coding interview evaluator and technical mentor with extensive experience conducting technical interviews at top-tier technology companies (FAANG+). 
You possess deep expertise in algorithms, data structures, system design, and candidate evaluation.
Your goal is to provide comprehensive, constructive feedback that optimizes for learning, understanding, and interview success at the senior/staff engineer level.

**Objective**: Analyze the candidate's verbal solution approach to a coding interview problem. Provide detailed, educational feedback that helps them understand what they did well, what needs improvement, and how to communicate more effectively in technical interviews. Focus on both technical correctness and interview communication skills.

**Problem Context**:

Problem name: 

```
{problem_name}
```

Problem statement:

```
{problem_statement}
```

---


**Candidate's Verbal Approach which we will evaluate**:

```
{user_solution}
```

Reference solution if we already have it (else this section just repeats the problem statement): 

```
{correct_solution}
```

---

## Evaluation Framework

Please conduct a comprehensive analysis across the following dimensions:

### 1. Technical Correctness Analysis
- **Algorithm Accuracy**: Does the proposed approach solve the problem correctly?
- **Logic Flow**: Is the step-by-step reasoning sound and logical?
- **Implementation Feasibility**: Can this verbal approach be translated into working code?
- **Mathematical Soundness**: Are any mathematical concepts or calculations correct?

### 2. Complexity Analysis & Optimization
- **Time Complexity**: Analyze the time complexity of the proposed approach
- **Space Complexity**: Evaluate space usage and memory efficiency
- **Optimization Opportunities**: Identify potential improvements or more efficient alternatives
- **Scalability**: How well would this approach handle large inputs or scale in production?

### 3. Edge Cases & Robustness
- **Boundary Conditions**: Does the candidate consider edge cases, empty inputs, single elements, etc.?
- **Error Handling**: Are potential failure scenarios addressed?
- **Input Validation**: Is there awareness of invalid or malformed inputs?
- **Corner Cases**: Are unusual but valid scenarios considered?

### 4. Interview Communication Excellence
- **Clarity of Explanation**: How clearly did the candidate communicate their thought process?
- **Structured Thinking**: Did they break down the problem systematically?
- **Technical Vocabulary**: Appropriate use of technical terms and concepts?
- **Engagement**: Did they ask good questions or seek clarification when needed?
- **Confidence**: How confidently did they present their solution?

### 5. Problem-Solving Approach
- **Problem Decomposition**: How well did they break down the complex problem into manageable parts?
- **Pattern Recognition**: Did they identify relevant algorithms, data structures, or patterns?
- **Alternative Approaches**: Did they consider multiple solutions or mention trade-offs?
- **Iterative Refinement**: Evidence of thinking through and improving their initial approach?

### 6. Senior-Level Considerations
- **System Design Awareness**: For applicable problems, consideration of real-world constraints
- **Code Organization**: Mentions of modularity, clean code principles, or architectural thinking
- **Testing Strategy**: Awareness of how they would test or validate their solution
- **Production Readiness**: Consideration of monitoring, error handling, or operational concerns

## Feedback Guidelines

Provide feedback that is:
- **Constructive and Actionable**: Specific suggestions for improvement
- **Balanced**: Highlight both strengths and areas for growth
- **Educational**: Explain concepts they may have missed or misunderstood
- **Interview-Focused**: Advice specifically relevant to technical interview success
- **Encouraging**: Maintain a supportive tone while being honest about gaps

## Output Format

Return your analysis as a JSON object with the following structure:

```json
{{
    "correctness": "CORRECT/PARTIALLY_CORRECT/INCORRECT",
    "optimality": "OPTIMAL/SUBOPTIMAL/INEFFICIENT", 
    "edge_case_handling": "EXCELLENT/GOOD/FAIR/POOR",
    "communication_quality": "EXCELLENT/VERY_GOOD/GOOD/FAIR/BASIC",
    "overall_interview_performance": "EXCELLENT/VERY_GOOD/GOOD/FAIR/NEEDS_IMPROVEMENT",
    "technical_depth": "SENIOR_LEVEL/MID_LEVEL/JUNIOR_LEVEL",
    "strengths": [
        "List of specific things the candidate did well",
        "Include both technical and communication strengths"
    ],
    "areas_for_improvement": [
        "Specific, actionable suggestions for improvement",
        "Focus on the most impactful changes they could make",
        "Important algorithmic concepts or patterns they didn't mention",
        "Key optimizations or approaches they overlooked"
    ],
    "complexity_analysis": "Your analysis of time/space complexity of their approach",
    "alternative_approaches": "Brief mention of other valid approaches they could have considered",
    "interview_tips": [
        "Specific advice for improving their interview communication",
        "Suggestions for better problem-solving presentation"
    ],
    "criticism": "Criticism of their approach in a brutal and unforgiving manner. Be harsh and honest and unforgiving. We need to be harsh on the candidate so that they can improve and are prepared for the real interview with a aggressive interviewer in a stressful environment.",
    "feedback": "Comprehensive, detailed feedback that synthesizes all the above analysis and adds your own insights and suggestions. This should read like feedback from an experienced interviewer - honest, constructive, and focused on helping them succeed. Include specific examples from their response and concrete suggestions for improvement. Structure this as if you're debriefing them after a real interview."
}}
```

## Analysis Instructions

1. **Be Brutal and Unforgiving**: Be harsh and honest and unforgiving. We need to be harsh on the candidate so that they can improve and are prepared for the real interview with a aggressive interviewer in a stressful environment.

2. Follow the "Output Format" strictly. Output only the JSON format analysis of "Candidate's Verbal Approach", nothing else.

3. Write in correct JSON format. We will load this JSON using python's json.loads() function.

4. Write in simple markdown text, and using code single backticks, not markdown. Don't use any math or latex notation.

Remember: Your goal is to help this candidate succeed in their next technical interview by providing world-class feedback that addresses both their technical solution and their communication approach.
"""
        
        current_system = "You are currently conducting a comprehensive analysis of the candidate's verbal solution approach. This is a critical evaluation phase where you must assess their technical understanding, communication skills, and interview performance. Be brutally honest in identifying gaps, weaknesses, and areas where they would fail in a real interview."
        
        llm = CallLLm(self.keys, self.writer_model if isinstance(self.writer_model, str) else self.writer_model[0])
        response = llm(analysis_prompt, temperature=0.3, stream=False, system=self.system_message + "\n\n" + current_system)
        
        try:
            import json
            import re
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                json_string = json_match.group().replace("```json", "").replace("```", "").replace("\n", "")
                # json_string = fix_broken_json(json_string)
                return json.loads(json_string)
        except (json.JSONDecodeError, AttributeError):
            pass
            
        return {"correctness": "PARTIALLY_CORRECT", "optimality": "SUBOPTIMAL", "quality": "FAIR", "feedback": "Unable to analyze properly"}

    

    def __call__(self, text, images=[], temperature=0.7, stream=True, max_tokens=None, system=None, web_search=False):
        import time
        
        # Extract conversation ID and parse state
        conversation_id = self._extract_conversation_id(text)
        state_data = self._get_full_state_data(text, conversation_id)

        # Handle special commands
        if "/hint" in text.lower():
            state_data["hint_count"] += 1
            self._update_conversation_summary(state_data, state_data.get("original_problem", ""), state_data.get("problem_statement", ""), f"User requested hint (total: {state_data['hint_count']})")
            yield self._add_gamification("penalty", "MINOR", "Hint used.")
            yield from self._handle_hint_request(text, state_data, conversation_id)
            yield from self._save_state(state_data, conversation_id)
            return
        
        intent_next_state = self._intent_and_next_state_determination(text, state_data)
        intent = intent_next_state["intent"]
        if intent in ["REQUEST_HINT", "GENERAL_DISCUSSION", "DISCUSS_OPTIMIZATION", "DISCUSS_VARIATIONS", "CONFUSED_NEED_HELP"] and state_data["current_state"] != "INIT": # "ASK_FOR_REVIEW"
            if intent == "REQUEST_HINT":
                state_data["hint_count"] += 1
            yield from intent_next_state["response"]
            yield from self._save_state(state_data, conversation_id)
            return
        
        if "/code" in text.lower() or "/implementation" in text.lower() or "/solution" in text.lower():
            pass

        if "/approach" in text.lower() or "/algorithm" in text.lower():
            pass
        
        if "/clarify" in text.lower():
            pass
        
        if "/debug" in text.lower():
            pass

        if "/help" in text.lower():
            pass

        if "/quit" in text.lower():
            self._update_conversation_summary(state_data, state_data.get("original_problem", ""), state_data.get("problem_statement", ""), "User quit the interview session")
            yield from self._handle_quit(state_data, conversation_id)
            return
        
        current_state = state_data.get("current_state", "INIT")
        
        
        
        handler_map = {
            "INIT": self._handle_init_state,
            "CLARIFICATION_WAIT": self._handle_clarification_wait,
            "VERBAL_ANALYSIS": self._handle_verbal_analysis,
            "IMPLEMENTATION_WAIT": self._handle_implementation_wait,
            "CODE_ANALYSIS": self._handle_code_analysis,
            "SENIOR_DISCUSSION": self._handle_senior_discussion,
            "VARIATIONS": self._handle_variations,
            "OPTIMIZATION_REQUEST": self._handle_optimization_request,
            "HINT_LOOP": self._handle_hint_loop,
        }
        
        handler = handler_map.get(current_state, self._handle_init_state)
        yield from handler(text, state_data, conversation_id)

    def _handle_init_state(self, text, state_data, conversation_id):
        """State 1: Prepare and present the problem."""
        import random
        import time
        
        # Generate problem name first
        problem_name = get_async_future(self._generate_problem_name, text)
        
        
        # Generate detailed problem description and solution
        yield "🔄 Preparing detailed problem analysis..."
        detailed_problem = get_async_future(self._generate_detailed_problem_description, text)
        solution_details = get_async_future(self._generate_solution_details, text)

        add_ambiguity = random.random() < self.ambiguity_probability
        
        problem_statement = get_async_future(self._generate_problem_with_ambiguity, text, add_ambiguity)

        problem_name = sleep_and_get_future_result(problem_name)
        state_data["problem_name"] = problem_name
        problem_statement = sleep_and_get_future_result(problem_statement)
        detailed_problem = sleep_and_get_future_result(detailed_problem)
        solution_details = sleep_and_get_future_result(solution_details)
        
        # Create storage key and load/save persistent data
        storage_key = self._create_storage_key(conversation_id, problem_name)
        
        # Save to persistent storage
        persistent_data = {
            "problem_statement": problem_statement,
            "detailed_problem_description": detailed_problem,
            "solution_details": solution_details,
            "original_problem": text
        }
        self._save_persistent_data(storage_key, persistent_data)
        
        state_data.update({
            "current_state": "CLARIFICATION_WAIT",
            "problem_statement": problem_statement,
            
            "original_problem": text,
            "session_start_time": time.time(),
            "session_problems_count": state_data.get("session_problems_count", 0) + 1,
            "user_score": state_data.get("user_score", 0) + 1
        })
        
        self._update_conversation_summary(state_data, text, problem_statement, f"Started interview session with problem: {problem_name}")
        
        yield f"🎯 **Interview Session Started!**\n\n---\n\n{problem_statement}\n\n---\n\nPlease take a moment to read through it. Do you have any clarifying questions about the requirements, constraints, or expected behavior?"
        yield self._add_gamification("reward", "BASIC", "Interview session started!")
        yield from self._save_state(state_data, conversation_id)

    def _handle_clarification_wait(self, text, state_data, conversation_id):
        """State 2: Handle user's first set of clarification questions."""
        evaluation = self._evaluate_clarification_questions(text, state_data["problem_statement"] + "\n\n" + state_data.get("detailed_problem_description", "") + "\n\n" + state_data.get("solution_details", ""))
        
        reward_type, level, msg = self.quality_rewards.get(evaluation["quality"], ("reward", "FAIR", "Questions noted."))

        is_ready_to_proceed = (evaluation["is_ready_to_proceed"] == "True")
        
        score_change = self.REWARD_LEVELS.get(level, {}).get("score", 1) if reward_type == "reward" else self.PENALTY_LEVELS.get(level, {}).get("score", -1)
        state_data["user_score"] += score_change
        state_data["clarification_count"] = 1
        state_data["good_questions_asked"] = 1 if evaluation["quality"] in ["EXCELLENT", "VERY_GOOD", "GOOD"] else 0

        summary_elements = [f"Asked clarification questions (quality: {evaluation['quality']})"]
        

        if not is_ready_to_proceed:
            yield self._add_gamification(reward_type, level, msg)

            if reward_type == "reward":
                
                yield from evaluation["clarification_response"]
            else:
                yield from evaluation["reasoning"]
                yield "\n\n"
                yield from evaluation["clarification_response"]

        if is_ready_to_proceed:
            state_data["current_state"] = "VERBAL_ANALYSIS"
            summary_elements.append("Ready to proceed with solution approach")
            yield self._add_gamification("reward", "GOOD", "Moving to the solution approach!")
            yield "**Great! Now let's hear your approach.**\n\nPlease explain your solution verbally. Walk me through:\n1. The algorithm or technique you plan to use\n2. The main steps of your solution\n3. The expected time and space complexity"
            yield "\n\n"
            
        else:
            
            state_data["clarification_count"] += 1
            summary_elements.append(f"Additional clarification question (total: {state_data['clarification_count']})")
            yield "\n\nAny more questions, or shall we proceed to the solution approach?"
            yield "\n\n"
            
        self._update_conversation_summary(state_data, state_data.get("original_problem", ""), state_data.get("problem_statement", ""), "\n".join(summary_elements))
        yield from self._save_state(state_data, conversation_id)


        

    def _handle_verbal_analysis(self, text, state_data, conversation_id):
        """State 6: Analyze verbal solution."""
        # Get solution details from already-loaded state data
        solution_context = state_data.get("solution_details", state_data.get("original_problem", ""))
        
        state_data["user_verbal_solution"] = text
        user_solution = state_data.get("user_verbal_solution", text)
        analysis = self._analyze_verbal_solution(state_data["problem_name"], state_data["problem_statement"], user_solution, solution_context)
        
        state_data["verbal_analysis"] = analysis
        
        yield f"**Analysis of your approach:**\n\n{analysis['feedback']}\n\n{analysis['criticism']}"

        verbal_str = "Candidate provided verbal solution approach."

        if analysis["correctness"] == "CORRECT":
            yield self._add_gamification("reward", "EXCELLENT", "Correct approach!")
            state_data["current_state"] = "IMPLEMENTATION_WAIT"
            state_data["user_score"] += 10
            self._update_conversation_summary(state_data, state_data.get("original_problem", ""), state_data.get("problem_statement", ""), verbal_str + " Verbal solution was correct")
            yield "\nExcellent! Your approach is sound. Please implement your solution in Python."
        elif analysis["correctness"] == "PARTIALLY_CORRECT":
            yield self._add_gamification("reward", "GOOD", "Good start, but needs refinement.")
            state_data["current_state"] = "HINT_LOOP"
            state_data["user_score"] += 3
            self._update_conversation_summary(state_data, state_data.get("original_problem", ""), state_data.get("problem_statement", ""), verbal_str + " Verbal solution was partially correct")
            yield "\nYou're on the right track! Think about the edge cases. Would you like a hint, or do you want to revise your approach?"
        else:
            yield self._add_gamification("penalty", "MODERATE", "Approach needs reconsideration.")
            state_data["current_state"] = "HINT_LOOP"
            state_data["user_score"] -= 3
            self._update_conversation_summary(state_data, state_data.get("original_problem", ""), state_data.get("problem_statement", ""), "Verbal solution was incorrect")
            yield "\nLet's rethink this. Would you like a hint to get on the right track?"
        
        yield convert_stream_to_iterable(collapsible_wrapper(
            f"<pre><code>{json.dumps(analysis, indent=2)}</code></pre>", 
            header="🤖 Feedback", 
            show_initially=False
        ))
        
        yield from self._save_state(state_data, conversation_id)

    def _handle_implementation_wait(self, text, state_data, conversation_id):
        """State 8: Handle code implementation."""
        if "```" not in text:
            yield "Please provide your implementation in a Python code block using ```python ... ```"
            return

        state_data["current_state"] = "CODE_ANALYSIS"
        yield from self._handle_code_analysis(text, state_data, conversation_id)

    def _analyze_code_quality(self, code, results, state_data):
        """Analyze the user's code and provide detailed feedback"""
        code_analysis_prompt = f"""
You are an expert coding interview evaluator and technical mentor with extensive experience conducting technical interviews at top-tier technology companies (FAANG+). You possess deep expertise in algorithms, data structures, system design, and candidate evaluation. Your goal is to provide comprehensive, constructive feedback that optimizes for learning, understanding, and interview success at the senior/staff engineer level.

**Objective**: Analyze the candidate's code implementation for correctness, efficiency, and style. Provide detailed, educational feedback that helps them understand what they did well, what needs improvement, and how to communicate more effectively in technical interviews. Focus on both technical correctness and interview communication skills.

**Problem Context**:
```
{state_data.get('problem_statement', '')}
```

**Expected Solution**:
```
{state_data.get('solution_details', '')}
```

---

**User's Code**:
```python
{code}
```

**Execution Results**:
```
{results}
```

Now analyze the user's code and provide detailed feedback. Compare the user's code with the expected solution and provide feedback on the code.
Focus on checking correctness and efficiency of the code. Also check if the code is optimized for the problem. Compare the user's code with the expected solution in granular details to see if the user's code is correct and efficient.

Finally, perform code review as below covering:
1. Code quality and style
2. Time/space complexity analysis
3. Potential optimizations
4. Alternative approaches briefly

Write a structured output in JSON format.

Output Format:
{{
    "feedback": "detailed feedback on the code along with detailed criticism of the code, approach and solution. Add suggestions to reach OPTIMAL and CORRECT solution if we are not there.",
    "correctness": "CORRECT/PARTIALLY_CORRECT/INCORRECT",
    "optimality": "OPTIMAL/PARTIALLY_OPTIMAL/INEFFICIENT",
    "style": "GOOD/AVERAGE/POOR",
    "code_review": "detailed code review of the code, time/space complexity analysis, potential optimizations, alternative approaches briefly"
}}

Now write your analysis in the above format. Write the feedback in simple markdown text, and using code single backticks. Don't use any math or latex notation.
"""

        current_system = "You are currently analyzing the candidate's code implementation for correctness and efficiency."

        llm = CallLLm(self.keys, self.writer_model if isinstance(self.writer_model, str) else self.writer_model[0])
        code_analysis_response = llm(code_analysis_prompt, temperature=0.5, stream=False, system=self.system_message + "\n\n" + current_system)
        import re
        import json
        # Default fallback response
        default_response = {
            "feedback": "Unable to analyze code properly due to parsing issues.",
            "correctness": "PARTIALLY_CORRECT", 
            "optimality": "PARTIALLY_OPTIMAL",
            "style": "AVERAGE"
        }
        # Strategy 1: Try ```json blocks
        json_match = re.search(r'```json\s*\n(.*?)\n\s*```', code_analysis_response, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1).strip())
            except json.JSONDecodeError:
                pass
        
        # Strategy 2: Try regular ``` blocks  
        code_match = re.search(r'```\s*\n(.*?)\n\s*```', code_analysis_response, re.DOTALL)
        if code_match:
            try:
                return json.loads(code_match.group(1).strip())
            except json.JSONDecodeError:
                pass
        
        # Strategy 3: Try to find JSON object directly (non-greedy)
        json_obj_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', code_analysis_response, re.DOTALL)
        if json_obj_match:
            try:
                return json.loads(json_obj_match.group(0))
            except json.JSONDecodeError:
                pass

        # Strategy 4: Try to find JSON object directly (non-greedy)
        json_obj_match = re.search(r'\{.*\}', code_analysis_response, re.DOTALL)
        if json_obj_match:
            try:
                return json.loads(json_obj_match.group(0))
            except json.JSONDecodeError:
                pass

        # Strategy 5: Extract JSON-like content manually
        try:
            # Look for feedback, correctness, optimality, style patterns
            feedback_match = re.search(r'"feedback":\s*"([^"]*)"', code_analysis_response)
            correctness_match = re.search(r'"correctness":\s*"(CORRECT|PARTIALLY_CORRECT|INCORRECT)"', code_analysis_response)
            optimality_match = re.search(r'"optimality":\s*"(OPTIMAL|PARTIALLY_OPTIMAL|INEFFICIENT)"', code_analysis_response)
            style_match = re.search(r'"style":\s*"(GOOD|AVERAGE|POOR)"', code_analysis_response)
            
            if feedback_match:
                return {
                    "feedback": feedback_match.group(1),
                    "correctness": correctness_match.group(1) if correctness_match else "PARTIALLY_CORRECT",
                    "optimality": optimality_match.group(1) if optimality_match else "PARTIALLY_OPTIMAL", 
                    "style": style_match.group(1) if style_match else "AVERAGE"
                }
        except Exception:
            pass
            
        # Final fallback - return default with raw response
        default_response["feedback"] = f"Raw LLM Response: {code_analysis_response[:500]}..."
        return default_response

    
    def _handle_code_analysis(self, text, state_data, conversation_id):
        """State: Analyze submitted code."""
        execution_result = run_user_code(text)
        state_data["attempts"] += 1
        state_data["user_code"] = execution_result['extracted_code']

        code_analysis = self._analyze_code_quality(execution_result['extracted_code'], execution_result['stdout'] + "\n\n" + execution_result['failure_reason'] or execution_result['stderr'], state_data)
        code_analysis["feedback"] = convert_iterable_to_stream(code_analysis["feedback"])
        if execution_result["success"] and code_analysis["correctness"] == "CORRECT" and code_analysis["optimality"] == "OPTIMAL":
            yield self._add_gamification("reward", "VERY_GOOD", "Code executed successfully!")
            state_data["current_state"] = "SENIOR_DISCUSSION"
            state_data["user_score"] += 7
            state_data["problem_solved"] = True
            self._update_conversation_summary(state_data, state_data.get("original_problem", ""), state_data.get("problem_statement", ""), f"Code executed successfully on attempt {state_data['attempts']}")
            yield f"**Execution Results:**\n```\n{execution_result['stdout']}\n```\n\nGreat! Your code runs. Let's review it for quality and optimality.\n\n"
            for chunk in code_analysis["feedback"]:
                yield chunk
            yield "\n\n"
            yield from code_analysis["code_review"]
            yield "\n\n"
            yield "Would you like to discuss the code further with me?"
            yield "\n\n"
            # Check for fast solve bonus
            if state_data.get("session_start_time"):
                bonus = self._calculate_fast_solve_bonus(state_data["session_start_time"], "medium")
                if bonus:
                    reward_type, level, msg = bonus
                    yield self._add_gamification(reward_type, level, msg)
                    state_data["user_score"] += self.REWARD_LEVELS[level]["score"]

        else:
            yield self._add_gamification("penalty", "MODERATE", "Code has execution issues.")
            state_data["current_state"] = "IMPLEMENTATION_WAIT"
            state_data["user_score"] -= 3
            state_data['last_attempt'] = text
            state_data['failure_reason'] = execution_result['failure_reason'] or execution_result['stderr']
            
            for chunk in code_analysis["feedback"]:
                yield chunk
            yield "\n\n"
            yield from code_analysis["code_review"]
            yield "\n\n"
            self._update_conversation_summary(state_data, state_data.get("original_problem", ""), state_data.get("problem_statement", ""), f"Code failed on attempt {state_data['attempts']}: {execution_result['failure_reason']}")
            yield f"**Execution Error:**\n```\n{execution_result['failure_reason'] or execution_result['stderr']}\n```\n\nLet's debug this. Would you like a hint, or do you want to try fixing it yourself?"

        yield from self._save_state(state_data, conversation_id)

    def _handle_hint_loop(self, text, state_data, conversation_id):
        """State 9: Provide hints when user is stuck."""
        if "/hint" not in text.lower() and not any(word in text.lower() for word in ["hint", "help", "stuck", "confused"]):
            # User is trying again, transition back to appropriate state
            if "```" in text:
                state_data["current_state"] = "CODE_ANALYSIS"
                yield from self._handle_code_analysis(text, state_data, conversation_id)
            else:
                state_data["current_state"] = "VERBAL_ANALYSIS"
                yield from self._handle_verbal_analysis(text, state_data, conversation_id)
            return

        state_data["hint_count"] += 1
        yield self._add_gamification("penalty", "MINOR", "Hint used.")
        
        # Get solution details from already-loaded state data
        solution_context = state_data.get("solution_details", "")
        
        hint_prompt = f"""
The user is stuck and needs a helpful hint. Provide a targeted hint based on their current situation.

Problem: {state_data.get('problem_statement', '')}
Solution context: {solution_context}
Last attempt: {state_data.get('last_attempt', text)}
Failure reason: {state_data.get('failure_reason', '')}
Current state: {state_data.get('current_state', '')}

Provide a helpful but not too revealing hint that guides them toward the solution.
"""

        current_system = "You are currently providing a hint to help the stuck candidate. Your role is to give targeted guidance that helps them progress without revealing the full solution. Be strategic - give just enough to get them unstuck while maintaining the challenge."
        
        llm = CallLLm(self.keys, self.writer_model if isinstance(self.writer_model, str) else self.writer_model[0])
        yield f"**💡 Hint:**\n\n"
        yield from llm(hint_prompt, stream=True, system=self.system_message + "\n\n" + current_system)
        
        # Decide where to go back to
        if "user_code" in state_data:
            state_data["current_state"] = "IMPLEMENTATION_WAIT"
            yield "\n\nPlease try implementing the fix."
        else:
            state_data["current_state"] = "VERBAL_ANALYSIS"
            yield "\n\nPlease try explaining your revised approach."

        self._update_conversation_summary(state_data, state_data.get("original_problem", ""), state_data.get("problem_statement", ""), f"Provided hint (total hints: {state_data['hint_count']})")
        yield from self._save_state(state_data, conversation_id)
        
    

    def _handle_senior_discussion(self, text, state_data, conversation_id):
        """State 11: Discuss scaling and edge cases."""
        discussion_prompt = f"""
The user has provided a good solution. Now ask insightful senior-level questions about:
- How would this scale with very large inputs?
- What are potential edge cases we haven't considered?
- How would you modify this for different constraints?
- System design considerations if this were part of a larger system

Problem: {state_data['problem_statement']}
User's solution:
```python
{state_data['user_code']}
```

Ask 1-2 thoughtful questions that would challenge a senior engineer.
"""

        state_data["current_state"] = "VARIATIONS"
        self._update_conversation_summary(state_data, state_data.get("original_problem", ""), state_data.get("problem_statement", ""), "Engaged in senior-level discussion")
        
        current_system = "You are currently engaging the candidate in senior-level technical discussions about scaling, edge cases, and system design considerations. Your role is to challenge them with questions that would be asked in staff/principal engineer interviews."
        
        llm = CallLLm(self.keys, self.writer_model if isinstance(self.writer_model, str) else self.writer_model[0])
        yield from llm(discussion_prompt, stream=True, system=self.system_message + "\n\n" + current_system)
        yield from self._save_state(state_data, conversation_id)

    def _handle_variations(self, text, state_data, conversation_id):
        """State 12: Propose a variation of the problem."""
        variation_prompt = f"""
Based on the original problem: {state_data['problem_statement']}

Propose an interesting variation such as:
- Changing a constraint (e.g., memory limitations)
- Asking for different output format
- Adding complexity (e.g., real-time updates)
- Modifying the problem domain slightly

Then ask the user how they would adapt their current solution to handle this variation.
Keep it challenging but reasonable.
"""

        state_data["current_state"] = "OPTIMIZATION_REQUEST"
        self._update_conversation_summary(state_data, state_data.get("original_problem", ""), state_data.get("problem_statement", ""), "Discussed problem variations")
        
        current_system = "You are currently proposing interesting variations of the original problem to test the candidate's ability to adapt their solution to changing requirements. Your role is to create challenging but reasonable modifications that test their flexibility and deeper understanding."
        
        llm = CallLLm(self.keys, self.writer_model if isinstance(self.writer_model, str) else self.writer_model[0])
        yield from llm(variation_prompt, stream=True, system=self.system_message + "\n\n" + current_system)
        yield from self._save_state(state_data, conversation_id)
        
    def _handle_optimization_request(self, text, state_data, conversation_id):
        """State 13: Ask for a more optimal solution."""
        optimization_prompt = f"""
The user's solution works correctly. Now challenge them for optimization:

Current solution:
```python
{state_data['user_code']}
```

Analyze the complexity and then ask them to optimize for:
- Better time complexity (if possible)
- Better space complexity (if possible)  
- More elegant/readable code
- Handling larger scale inputs

Be specific about what improvement you're asking for.
"""

        state_data["current_state"] = "VERBAL_ANALYSIS" # Loop back for new approach
        self._update_conversation_summary(state_data, state_data.get("original_problem", ""), state_data.get("problem_statement", ""), "Asked for optimization challenge")
        
        current_system = "You are currently challenging the candidate to optimize their working solution for better performance, elegance, or different constraints. Your role is to push them beyond their comfort zone and demand excellence in algorithmic thinking."
        
        llm = CallLLm(self.keys, self.writer_model if isinstance(self.writer_model, str) else self.writer_model[0])
        yield from llm(optimization_prompt, stream=True, system=self.system_message + "\n\n" + current_system)
        yield "\n\nWould you like to take on this optimization challenge, or shall we wrap up this problem and move to a new one?"
        yield from self._save_state(state_data, conversation_id)

    def _handle_hint_request(self, text, state_data, conversation_id):
        """Handle /hint command"""
        hint_prompt = f"""
The user is asking for a hint. Provide a helpful but not too revealing hint based on the current context.

Current State: {state_data.get('current_state', 'UNKNOWN')}


Problem: {state_data.get('problem_statement', '')}

Expected solution:
```
{state_data.get('solution_details', '')}
```

User's progress so far: {state_data.get('conversation_summary', '')}

Give a targeted hint that helps them progress without giving away the solution.
"""
        
        current_system = "You are currently providing a targeted hint in response to the candidate's explicit request for help. Your role is to give strategic guidance that helps them progress without revealing too much of the solution. Balance being helpful with maintaining the interview challenge."
        
        llm = CallLLm(self.keys, self.writer_model if isinstance(self.writer_model, str) else self.writer_model[0])
        yield f"**💡 Hint:**\n\n"
        yield from llm(hint_prompt, temperature=0.5, stream=True, system=self.system_message + "\n\n" + current_system)
        yield "\n\nTake your time to think about this hint and let me know how you'd like to proceed!\n\n"

    def _handle_quit(self, state_data, conversation_id):
        """State 14: Terminate the session."""
        state_data["current_state"] = "TERMINATED"
        
        # Check for final achievements
        achievements = []
        if state_data.get("problem_solved"):
            achievements.append("✅ Successfully solved the problem!")
        if state_data.get("good_questions_asked", 0) > 0:
            achievements.append(f"❓ Asked {state_data['good_questions_asked']} good clarifying questions")
        if state_data.get("hint_count", 0) == 0:
            achievements.append("🎯 Solved without using hints!")
        if state_data.get("attempts", 0) == 1:
            achievements.append("⚡ Got it right on the first try!")
            
        achievement_text = "\n".join(achievements) if achievements else "Keep practicing!"
        
        yield self._add_gamification("reward", "GOOD", "Thanks for the interview session!")
        yield f"""**🎯 Interview Session Complete!**

**Final Score:** {state_data['user_score']} points

**Session Summary:**
{state_data.get('conversation_summary', 'No summary available')}

**Achievements:**
{achievement_text}

Keep practicing and you'll do amazing in real interviews! 🚀"""
        
        yield from self._save_state(state_data, conversation_id)

