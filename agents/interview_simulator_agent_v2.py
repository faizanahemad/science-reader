import json
import random
import traceback
from typing import Union, List
import uuid
import time
import re
import logging

from common import VERY_CHEAP_LLM, collapsible_wrapper, convert_iterable_to_stream, fix_broken_json
from prompts import tts_friendly_format_instructions

import os
import tempfile
import shutil
import concurrent.futures
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

from .base_agent import Agent
from .search_and_information_agents import MultiSourceSearchAgent, PerplexitySearchAgent, JinaSearchAgent

logger, time_logger, error_logger, success_logger, log_memory_usage = getLoggers(__name__, logging.WARNING, logging.INFO, logging.ERROR, logging.INFO)

# Reused from v1
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


class InterviewSimulatorAgentV2(Agent):
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

    # Reused utility functions from v1
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
        # Default state
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
            "conversation_summary": "",
            "senior_discussion_done": False,
            "optimization_request_done": False
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
        # Define large text fields that should be stored in files, not in chat
        large_text_fields = {
            'problem_statement', 
            'original_problem', 
            'detailed_problem_description', 
            'solution_details',
            'conversation_summary'
        }
        
        # Create a copy of state_data without large text fields
        compact_state_data = {k: v for k, v in state_data.items() if k not in large_text_fields}
        
        state_json = json.dumps(compact_state_data, indent=2)
        # Use a generator to yield the string
        yield from convert_stream_to_iterable(collapsible_wrapper(
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
            'solution_details',
            'conversation_summary',
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
        solve_time = time.time() - start_time
        # Award bonus for solving within time thresholds
        if solve_time < 300:  # 5 minutes
            return ("reward", "EXCELLENT", "Lightning fast solve!")
        elif solve_time < 600:  # 10 minutes
            return ("reward", "VERY_GOOD", "Quick solve!")
        return None

    def _check_code_correctness(self, text, execution_result, problem_statement, solution_details, state_data):
        """Check if the submitted code is correct for the given problem using LLM analysis"""
        
        # Extract code from user's text
        user_code = execution_result.get('extracted_code', '')
        execution_success = execution_result.get('success', False)
        stdout = execution_result.get('stdout', '')
        stderr = execution_result.get('stderr', '')
        failure_reason = execution_result.get('failure_reason', '')
        
        # Create comprehensive prompt for correctness evaluation
        correctness_prompt = f"""
You are evaluating a candidate's code submission during a technical interview to determine if it correctly solves the given problem.

**Problem Statement:**
```
{problem_statement}
```

**Expected Solution Details:**
```
{solution_details}
```

**Candidate's Submitted Code:**
```python
{user_code}
```

**Execution Results:**
- Execution Success: {execution_success}
- Standard Output: {stdout}
- Standard Error: {stderr}
- Failure Reason: {failure_reason}

**Current Interview Context:**
- Current State: {state_data.get('current_state', 'Unknown')}
- Attempts So Far: {state_data.get('attempts', 0)}
- Problem Solved: {state_data.get('problem_solved', False)}

**Your Evaluation Task:**
Analyze the code submission across multiple dimensions:

1. **Logical Correctness**: Does the code solve the problem as specified?
2. **Algorithm Correctness**: Is the approach/algorithm appropriate and correct?
3. **Implementation Quality**: Are there bugs, edge cases missed, or implementation issues?
4. **Execution Success**: Did the code run without errors?
5. **Output Correctness**: If there's output, does it match expected results?
6. **Efficiency**: Is the solution reasonably efficient for the problem?
7. **Code Quality**: Is the code readable and well-structured?

**Correctness Levels:**
- **PERFECT**: Code is completely correct, handles edge cases, efficient, clean
- **MOSTLY_CORRECT**: Code works for main cases but may miss some edge cases or have minor issues
- **PARTIALLY_CORRECT**: Code has the right idea but has significant bugs or issues
- **INCORRECT**: Code doesn't solve the problem or has major logical errors
- **EXECUTION_FAILED**: Code has syntax errors or runtime issues preventing execution

**Reward Guidelines:**
- PERFECT → ("reward", "EXCELLENT", "Perfect solution!")
- MOSTLY_CORRECT → ("reward", "VERY_GOOD", "Great solution with minor improvements possible!")
- PARTIALLY_CORRECT → ("reward", "FAIR", "Good approach but needs fixes!")
- INCORRECT → ("penalty", "MODERATE", "Solution doesn't solve the problem correctly!")
- EXECUTION_FAILED → ("penalty", "SIGNIFICANT", "Code has execution issues!")

Provide your analysis in JSON format:
{{
    "is_correct": true/false,
    "correctness_level": "PERFECT/MOSTLY_CORRECT/PARTIALLY_CORRECT/INCORRECT/EXECUTION_FAILED",
    "feedback": "detailed feedback explaining the correctness assessment",
    "strengths": ["list of code strengths"],
    "weaknesses": ["list of issues or improvements needed"],
    "correctness_reward": ["reward/penalty", "LEVEL", "message"] or null,
    "algorithm_assessment": "assessment of the algorithmic approach",
    "edge_cases_handled": true/false,
    "efficiency_rating": "excellent/good/fair/poor",
    "overall_score": 0-100,
    "reasoning": "brief explanation of the overall assessment"
}}

Focus on being thorough and fair in your evaluation while maintaining interview standards.
"""
        
        current_system = "You are evaluating code correctness during a technical interview. Provide comprehensive analysis of the candidate's solution, considering both correctness and quality aspects."
        
        try:
            llm = CallLLm(self.keys, self.writer_model if isinstance(self.writer_model, str) else self.writer_model[0])
            response = llm(correctness_prompt, temperature=0.2, stream=False, system=self.system_message + "\n\n" + current_system)
            
            # Parse JSON response
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                json_string = json_match.group()
                json_string = json_string.replace("```json", "").replace("```", "")
                analysis = json.loads(json_string)
                
                # Validate and structure the response
                is_correct = analysis.get("is_correct", False)
                correctness_level = analysis.get("correctness_level", "INCORRECT")
                feedback = analysis.get("feedback", "Code analysis completed.")
                correctness_reward = analysis.get("correctness_reward")
                
                # Ensure correctness_reward is properly formatted
                if correctness_reward and len(correctness_reward) == 3:
                    reward_type, reward_level, reward_message = correctness_reward
                    # Validate reward components
                    if reward_type not in ["reward", "penalty"]:
                        correctness_reward = None
                    elif reward_type == "reward" and reward_level not in self.REWARD_LEVELS:
                        correctness_reward = None
                    elif reward_type == "penalty" and reward_level not in self.PENALTY_LEVELS:
                        correctness_reward = None
                else:
                    correctness_reward = None

                # Format comprehensive feedback as markdown
                strengths = analysis.get("strengths", [])
                weaknesses = analysis.get("weaknesses", [])
                algorithm_assessment = analysis.get("algorithm_assessment", "")
                edge_cases_handled = analysis.get("edge_cases_handled", False)
                
                overall_feedback = feedback
                
                if strengths:
                    overall_feedback += "\n\n**Strengths:**\n" + "\n".join([f"- {strength}" for strength in strengths])
                
                if weaknesses:
                    overall_feedback += "\n\n**Areas for Improvement:**\n" + "\n".join([f"- {weakness}" for weakness in weaknesses])
                
                if algorithm_assessment:
                    overall_feedback += f"\n\n**Algorithm Assessment:**\n{algorithm_assessment}"
                
                overall_feedback += f"\n\n**Edge Cases Handled:** {'Yes' if edge_cases_handled else 'No'}"
                
                return {
                    "is_correct": is_correct,
                    "correctness_level": correctness_level,
                    "feedback": overall_feedback,
                    "strengths": analysis.get("strengths", []),
                    "weaknesses": analysis.get("weaknesses", []),
                    "correctness_reward": correctness_reward,
                    "algorithm_assessment": analysis.get("algorithm_assessment", ""),
                    "edge_cases_handled": analysis.get("edge_cases_handled", False),
                    "efficiency_rating": analysis.get("efficiency_rating", "fair"),
                    "overall_score": analysis.get("overall_score", 50),
                    "reasoning": analysis.get("reasoning", "LLM analysis completed")
                }
                
        except (json.JSONDecodeError, AttributeError, TypeError, Exception) as e:
            logger.warning(f"Failed to parse code correctness analysis: {e}")
        
        # Fallback analysis based on execution results
        if execution_success:
            # Code executed successfully - likely at least partially correct
            return {
                "is_correct": True,
                "correctness_level": "MOSTLY_CORRECT",
                "feedback": "Code executed successfully. Manual review recommended for full correctness assessment. LLM review failed.",
                "strengths": ["Code runs without errors"],
                "weaknesses": ["Detailed analysis unavailable"],
                "correctness_reward": ("reward", "GOOD", "Code executes successfully!"),
                "algorithm_assessment": "Unable to assess - fallback mode",
                "edge_cases_handled": False,
                "efficiency_rating": "unknown",
                "overall_score": 70,
                "reasoning": "Fallback assessment based on execution success"
            }
        else:
            # Code failed to execute
            return {
                "is_correct": False,
                "correctness_level": "EXECUTION_FAILED",
                "feedback": f"Code failed to execute: {failure_reason or stderr}",
                "strengths": [],
                "weaknesses": ["Code has execution errors"],
                "correctness_reward": ("penalty", "MODERATE", "Code has execution issues!"),
                "algorithm_assessment": "Cannot assess due to execution failure",
                "edge_cases_handled": False,
                "efficiency_rating": "unknown",
                "overall_score": 20,
                "reasoning": "Fallback assessment - execution failed"
            }
    
    def _check_session_achievements(self, state_data):
        """Check for various session achievements and return appropriate rewards/penalties"""
        achievements = []
        
        # Perfect score achievements
        if state_data.get("user_score", 0) >= 50:
            achievements.append(("reward", "EXCELLENT", "🏆 Score Master! Outstanding performance!"))
        elif state_data.get("user_score", 0) >= 30:
            achievements.append(("reward", "VERY_GOOD", "🌟 High Achiever! Great performance!"))
        
        # No hints achievement
        if state_data.get("hint_count", 0) == 0 and state_data.get("problem_solved", False):
            achievements.append(("reward", "EXCELLENT", "💪 Independent Solver! No hints needed!"))
        
        # Multiple attempts penalty
        if state_data.get("attempts", 0) > 5:
            achievements.append(("penalty", "MODERATE", "⚠️ Too many code attempts - work on accuracy!"))
        
        # Excellent clarification questions
        if state_data.get("good_questions_asked", 0) >= 3:
            achievements.append(("reward", "VERY_GOOD", "🤔 Great Questions! Excellent clarification skills!"))
        
        # Senior discussion completion
        if state_data.get("senior_discussion_done", False):
            achievements.append(("reward", "GOOD", "🎯 Senior Level! Advanced discussion completed!"))
        
        # Optimization completion
        if state_data.get("optimization_request_done", False):
            achievements.append(("reward", "GOOD", "⚡ Optimizer! Code improvement completed!"))
        
        # Low score penalty
        if state_data.get("user_score", 0) < -10:
            achievements.append(("penalty", "SIGNIFICANT", "📉 Struggling - focus on fundamentals!"))
        
        # Hint abuse penalty
        if state_data.get("hint_count", 0) > 5:
            achievements.append(("penalty", "MAJOR", "🚨 Hint Overuse! Develop independent problem-solving!"))
        
        return achievements

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
14. Senior Discussion Done: {state_data.get('senior_discussion_done', False)}
15. Optimization Request Done: {state_data.get('optimization_request_done', False)}
16. Conversation Summary: Write your own summary of the conversation so far.

Write all the information in markdown format in a structured way and write an elaborate summary of the conversation so far.

Provide a brief, concise and structured summary that captures the essence of the session till now with focus on recent actions and state.
"""
        
        # Call the LLM to generate the summary
        current_system = "You are currently updating the session summary to track the candidate's progress, actions, and performance throughout the interview. Your role is to maintain a concise but comprehensive record of what has happened so far."
        
        llm = CallLLm(self.keys, self.writer_model if isinstance(self.writer_model, str) else self.writer_model[0])
        structured_summary = llm(summary_prompt, temperature=0.3, stream=False, system=self.system_message + "\n\n" + current_system).strip()
        
        # Update the state data with the new structured summary
        state_data["conversation_summary"] = structured_summary

        return structured_summary

    # NEW SIMPLIFIED ARCHITECTURE - Two main LLM calls

    def _set_problem_details(self, text, intent_data):
        """Parse original problem and solution details from user text using LLM"""
        
        # Create prompt for LLM to extract problem details
        problem_parsing_prompt = f"""
You are analyzing a user's input to extract technical interview problem details. The user may have provided:
1. A problem statement (with or without ambiguity)
2. Solution details or hints about the solution
3. Just a problem name or topic

**User Input:** 
```
{text}
```

**Current Intent Data:** 
```json
{intent_data}
```

Ambiguous problem statement:
```
{intent_data.get("problem_statement", "")}
```

Your task is to:
1. Extract the original problem statement (without any added ambiguity)
2. Identify the problem name/title
3. Extract or generate solution details if available
4. Determine if this is a well-known problem or a custom one

Provide your analysis in JSON format:
{{
    "problem_name": "clear, concise problem title",
    "original_problem": "clean problem statement without ambiguity",
    "solution_details": "detailed solution approach, algorithm, time/space complexity",
    "is_well_known_problem": true/false,
    "problem_category": "category like arrays, strings, dynamic programming, etc.",
    "difficulty_level": "easy/medium/hard",
}}

If the user input doesn't contain a clear problem, generate a reasonable default based on the context.
"""
        
        # Call LLM to parse problem details
        current_system = "You are a technical interview problem parser. Extract and structure problem information from user input, ensuring clarity and completeness."
        
        llm = CallLLm(self.keys, self.writer_model if isinstance(self.writer_model, str) else self.writer_model[0])
        response = llm(problem_parsing_prompt, temperature=0.3, stream=False, system=self.system_message + "\n\n" + current_system)
        
        try:
            # Try to parse JSON response
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                json_string = json_match.group()
                json_string = json_string.replace("```json", "").replace("```", "")
                parsed_details = json.loads(json_string)
                return parsed_details
        except (json.JSONDecodeError, AttributeError, TypeError) as e:
            logger.warning(f"Failed to parse problem details JSON: {e}")
        
        # Fallback response
        return {
            "problem_name": intent_data.get("problem_name", "Technical Interview Problem"),
            "original_problem": "Problem details to be determined",
            "problem_statement": intent_data.get("direct_response", "Problem statement to be generated"),
            "solution_details": "Solution approach to be discussed",
            "is_well_known_problem": False,
            "problem_category": "general",
            "difficulty_level": "medium",
            "reasoning": "Fallback response due to parsing error"
        }
        
    
    def _determine_intent_and_transition(self, text, state_data):
        """LLM Call 1: Determine intent, state transition, rewards/penalties, and optional direct response"""
        
        current_state = state_data.get("current_state", "INIT")
        
        # Create context-aware prompt for intent detection, transition logic, AND gamification
        ambiguity_probability = random.random() < 0.5
        add_ambiguity = "- Add some ambiguity to the problem statement to make it more challenging and force the candidate to ask clarification questions." if ambiguity_probability and state_data.get("current_state", "INIT") == "INIT" else ""
        intent_prompt = f"""
You are analyzing a candidate's response during a technical interview to determine their intent, state transition, appropriate rewards/penalties, and provide direct responses when appropriate.

**Current Context:**
- Problem name: {state_data.get('problem_name', 'No problem name set yet')}
- Current interview state: {current_state}
- State description: {self.STATES.get(current_state, "Unknown state")}
- Problem context: {state_data.get('problem_statement', 'No problem set yet')}
- Expected solution: {state_data.get('solution_details', '')}
- Conversation summary: {state_data.get('conversation_summary', 'New session')}
- Senior discussion done: {state_data.get('senior_discussion_done', False)}
- Optimization request done: {state_data.get('optimization_request_done', False)}
- Current score: {state_data.get('user_score', 0)}
- Hints used: {state_data.get('hint_count', 0)}
- Attempts so far: {state_data.get('attempts', 0)}
- Clarifications asked: {state_data.get('clarification_count', 0)}

**Candidate's message:** "{text}"

**State Transition Logic to Follow:**
- INIT → CLARIFICATION_WAIT (after problem presentation)
- CLARIFICATION_WAIT → CLARIFICATION_WAIT (if more questions) OR VERBAL_ANALYSIS (if ready to proceed)
- VERBAL_ANALYSIS → IMPLEMENTATION_WAIT (if approach good) OR HINT_LOOP (if needs help)
- IMPLEMENTATION_WAIT → CODE_ANALYSIS (after code submitted)
- CODE_ANALYSIS → IMPLEMENTATION_WAIT (if incorrect) OR next phase (if correct)
- Next phase logic:
  - SENIOR_DISCUSSION: if solution is optimal OR close to optimal with trade-offs
  - OPTIMIZATION_REQUEST: if solution is not optimal but can be improved
- After both senior_discussion_done=True AND optimization_request_done=True → VARIATIONS
- VARIATIONS can loop back to VERBAL_ANALYSIS for new challenges
- Any state → TERMINATED (if user quits)

**GAMIFICATION - Reward/Penalty Evaluation:**
Evaluate the candidate's performance and determine appropriate rewards/penalties:

**REWARD LEVELS:** EXCELLENT (+10), VERY_GOOD (+7), GOOD (+5), FAIR (+3), BASIC (+1)
**PENALTY LEVELS:** MINOR (-1), MODERATE (-3), SIGNIFICANT (-5), MAJOR (-7), CRITICAL (-10)

**Reward Scenarios:**
- Outstanding clarification questions (relevant, insightful): EXCELLENT/VERY_GOOD
- Good clarification questions (helpful but basic): GOOD/FAIR
- Correct verbal solution approach: EXCELLENT/VERY_GOOD
- Partially correct verbal approach: GOOD/FAIR
- Working code on first try: EXCELLENT
- Working code after few attempts: VERY_GOOD/GOOD
- Good senior-level discussion: VERY_GOOD/GOOD
- Successfully handling variations: EXCELLENT/VERY_GOOD
- Quick problem solving: EXCELLENT (speed bonus)
- Clean, optimized code: VERY_GOOD/EXCELLENT

**Penalty Scenarios:**
- Irrelevant/unnecessary clarification questions: MINOR/MODERATE
- Poor clarification questions (missing obvious points): MODERATE/SIGNIFICANT
- Incorrect verbal approach: MODERATE/SIGNIFICANT
- Non-working code: MODERATE
- Multiple failed attempts: SIGNIFICANT
- Poor senior discussion answers: MODERATE/SIGNIFICANT
- Unable to handle variations: SIGNIFICANT/MAJOR
- Asking for too many hints: MINOR/MODERATE (progressive)
- Poor coding practices: MINOR/MODERATE

**Direct Response Intents** (provide immediate response):
For these intents, provide a helpful, detailed response directly:
- REQUEST_HINT
- GENERAL_DISCUSSION 
- DISCUSS_OPTIMIZATION
- DISCUSS_VARIATIONS
- CONFUSED_NEED_HELP
- INIT (In this state, assume you are the interviewer and present the problem statement to the candidate)
{add_ambiguity}

**Available Intents:** {', '.join(self.POSSIBLE_INTENTS)}

**Available States:** {', '.join([f"{key}: {value}" for key, value in self.STATES.items()])}

Respond with a JSON object:
{{
    "intent": "one of the possible intents",
    "current_state": "current state from the STATES list",
    "problem_name": "exact problem name copied from the problem_name field or name given by you if not set yet",
    "next_state": "appropriate next state from the STATES list", 
    "should_transition": true/false,
    "provides_direct_response": true/false,
    "direct_response": "if provides_direct_response is true, provide detailed helpful response here, otherwise empty string",
    "reward_type": "reward/penalty/none",
    "reward_level": "EXCELLENT/VERY_GOOD/GOOD/FAIR/BASIC/MINOR/MODERATE/SIGNIFICANT/MAJOR/CRITICAL",
    "reward_message": "brief/concise specific message explaining why this reward/penalty was given",
    "reasoning": "brief/concise explanation of the decision including reward rationale"
}}

Focus on comprehensive evaluation - determine intent, state transitions, appropriate gamification, and direct responses.
"""
        
        current_system = f"You are currently analyzing the candidate's response to determine their intent and decide the next interview state transition. Current state: {current_state}. Provide direct responses for hint/discussion intents, otherwise determine appropriate state transitions."
        
        llm = CallLLm(self.keys, self.writer_model if isinstance(self.writer_model, str) else self.writer_model[0])
        response = llm(intent_prompt, temperature=0.1, stream=False, system=self.system_message + "\n\n" + current_system)
        
        try:
            # Try to parse JSON response
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                json_string = json_match.group()
                json_string = json_string.replace("```json", "").replace("```", "")
                analysis = json.loads(json_string)
                
                intent = analysis.get("intent", "GENERAL_DISCUSSION")
                current_state = analysis.get("current_state", current_state)
                next_state = analysis.get("next_state", current_state)
                should_transition = analysis.get("should_transition", False)
                provides_direct_response = analysis.get("provides_direct_response", False)
                direct_response = analysis.get("direct_response", "") if provides_direct_response else ""
                reward_type = analysis.get("reward_type", "none")
                reward_level = analysis.get("reward_level", "BASIC")
                reward_message = analysis.get("reward_message", "")
                
                # Validate next_state is in our STATES
                if next_state not in self.STATES:
                    next_state = current_state
                    should_transition = False
                
                # Validate intent is in our possible intents
                if intent not in self.POSSIBLE_INTENTS:
                    intent = "GENERAL_DISCUSSION"
                
                # Validate reward_type
                if reward_type not in ["reward", "penalty", "none"]:
                    reward_type = "none"
                
                # Validate reward_level
                valid_levels = list(self.REWARD_LEVELS.keys()) + list(self.PENALTY_LEVELS.keys())
                if reward_level not in valid_levels:
                    reward_level = "BASIC" if reward_type == "reward" else "MINOR"
                
                return {
                    "intent": intent,
                    "current_state": current_state,
                    "next_state": next_state,
                    "should_transition": should_transition,
                    "provides_direct_response": provides_direct_response,
                    "direct_response": direct_response,
                    "reward_type": reward_type,
                    "reward_level": reward_level,
                    "reward_message": reward_message,
                    "reasoning": analysis.get("reasoning", "")
                }
                
        except (json.JSONDecodeError, AttributeError, TypeError) as e:
            # Fallback logic if LLM doesn't return valid JSON
            logger.warning(f"Failed to parse intent analysis JSON: {e}")
        
        # Fallback: simple keyword-based intent detection
        text_lower = text.lower()
        
        if any(word in text_lower for word in ["hint", "help", "stuck", "confused"]):
            # Determine penalty based on hint count
            hint_count = state_data.get("hint_count", 0)
            if hint_count >= 3:
                penalty_level = "MODERATE"
                penalty_msg = "Multiple hints used - try to solve independently!"
            elif hint_count >= 1:
                penalty_level = "MINOR"
                penalty_msg = "Hint requested - work towards independence!"
            else:
                penalty_level = "MINOR"
                penalty_msg = "First hint used."
                
            return {
                "intent": "REQUEST_HINT",
                "next_state": "HINT_LOOP",
                "should_transition": True,
                "provides_direct_response": True,
                "direct_response": "I can provide a hint to help you move forward.",
                "reward_type": "penalty",
                "reward_level": penalty_level,
                "reward_message": penalty_msg,
                "reasoning": "Keyword-based fallback detection - hint request"
            }
        elif any(word in text_lower for word in ["quit", "exit", "done", "finish"]):
            return {
                "intent": "QUIT_SESSION",
                "next_state": "TERMINATED",
                "should_transition": True,
                "provides_direct_response": False,
                "direct_response": "",
                "reward_type": "reward",
                "reward_level": "FAIR",
                "reward_message": "Thanks for participating in the interview session!",
                "reasoning": "Keyword-based fallback detection - session end"
            }
        elif "```" in text or "def " in text or "class " in text:
            return {
                "intent": "SUBMIT_CODE",
                "next_state": "CODE_ANALYSIS",
                "should_transition": True,
                "provides_direct_response": False,
                "direct_response": "",
                "reward_type": "reward",
                "reward_level": "FAIR",
                "reward_message": "Code submission attempt!",
                "reasoning": "Code detected in message"
            }
        else:
            return {
                "intent": "GENERAL_DISCUSSION",
                "next_state": current_state,
                "should_transition": False,
                "provides_direct_response": True,
                "direct_response": "I understand. Let me help you with that.",
                "reward_type": "none",
                "reward_level": "BASIC",
                "reward_message": "",
                "reasoning": "Fallback - no clear intent detected"
            }

    def _generate_state_response(self, text, state_data, intent_data):
        """LLM Call 2: Generate appropriate response based on current state and context"""
        
        current_state = state_data.get("current_state", "INIT")
        next_state = intent_data.get("next_state", current_state)
        intent = intent_data.get("intent", "GENERAL_DISCUSSION")
        
        # Build context for response generation
        context = {
            "current_state": current_state,
            "next_state": next_state,
            "intent": intent,
            "user_input": text,
            "problem_statement": state_data.get("problem_statement", ""),
            "solution_details": state_data.get("solution_details", ""),
            "conversation_summary": state_data.get("conversation_summary", ""),
            "user_score": state_data.get("user_score", 0),
            "attempts": state_data.get("attempts", 0),
            "hint_count": state_data.get("hint_count", 0),
            "problem_name": state_data.get("problem_name", ""),
            "senior_discussion_done": state_data.get("senior_discussion_done", False),
            "optimization_request_done": state_data.get("optimization_request_done", False)
        }
        
        # State-specific response generation prompt
        response_prompt = f"""
You are generating the appropriate response for a technical interview based on the current state and user intent.

**Context:**
- Current State: {current_state}
- Next State: {next_state}
- User Intent: {intent}
- User Input: "{text}"
- Problem: {context['problem_statement']}
- Expected Solution: {context['solution_details']}
- Conversation Summary: {context['conversation_summary']}
- Senior Discussion Done: {context['senior_discussion_done']}
- Optimization Request Done: {context['optimization_request_done']}

**Instructions based on state:**

**INIT State:** Generate problem statement with optional ambiguity, present it clearly, ask for clarifications.

**CLARIFICATION_WAIT State:** Evaluate clarification questions, provide answers, determine if ready to proceed to verbal solution.

**VERBAL_ANALYSIS State:** Analyze the user's verbal approach, provide detailed feedback on correctness, optimality, and communication.

**IMPLEMENTATION_WAIT State:** Wait for code implementation, guide if needed.

**CODE_ANALYSIS State:** Analyze submitted code, run it conceptually, provide feedback on correctness, efficiency, style. If we are in this state, then we need to execute the user given code. Also we can only be in this state if the user has submitted code.

**SENIOR_DISCUSSION State:** Discuss scaling, edge cases, system design considerations. Mark senior_discussion_done=True when complete.

**OPTIMIZATION_REQUEST State:** Request more optimal solution, discuss trade-offs. Mark optimization_request_done=True when complete.

**VARIATIONS State:** Propose problem variations, alternative constraints.

**HINT_LOOP State:** Provide targeted hints without giving away the solution.

**TERMINATED State:** Wrap up session with summary and achievements.

**requires_code_execution** is true if the user has submitted runnable code and we are in the CODE_ANALYSIS state.

Provide your response in JSON format:
{{
    "response_text": "the main response to the user",
    "reward_type": "reward/penalty/none",
    "reward_level": "EXCELLENT/VERY_GOOD/GOOD/FAIR/BASIC/MINOR/MODERATE/SIGNIFICANT/MAJOR/CRITICAL",
    "reward_message": "message for the reward/penalty",
    "state_updates": {{
        "key": "value pairs for any state data that needs to be updated"
    }},
    "requires_code_execution": true/false,
    "reasoning": "brief explanation of the response strategy"
}}

Focus on being helpful, challenging, and maintaining the interview flow while providing constructive feedback.
"""
        
        current_system = f"You are currently generating an appropriate response for the {current_state} state transitioning to {next_state}. Your role is to provide helpful, challenging feedback that maintains the interview flow and helps the candidate improve."
        
        llm = CallLLm(self.keys, self.writer_model if isinstance(self.writer_model, str) else self.writer_model[0])
        response = llm(response_prompt, temperature=0.3, stream=False, system=self.system_message + "\n\n" + current_system)
        
        try:
            # Try to parse JSON response
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                json_string = json_match.group()
                json_string = json_string.replace("```json", "").replace("```", "")
                return json.loads(json_string)
        except (json.JSONDecodeError, AttributeError, TypeError) as e:
            logger.warning(f"Failed to parse response generation JSON: {e}")
        
        # Fallback response
        return {
            "response_text": f"I understand your input in the {current_state} state. Let me help you proceed.",
            "reward_type": "none",
            "reward_level": "BASIC",
            "reward_message": "",
            "state_updates": {},
            "requires_code_execution": False,
            "reasoning": "Fallback response due to parsing error"
        }

    def _unified_handler(self, text, state_data, conversation_id, intent_data, response_data):
        """Unified handler that processes the response and manages state transitions"""
        
        additional_rewards = []  # Track additional rewards from execution and other factors
        
        # Handle code execution if needed
        if response_data.get("requires_code_execution", False) and "```" in text:
            execution_result = run_user_code(text)
            # Check if the code execution result is correct using LLM
            correctness_result = self._check_code_correctness(
                text, 
                execution_result, 
                state_data.get("problem_name", "") + "\n\n" + state_data.get("problem_statement", "") + "\n\n" + state_data.get("original_problem", ""),
                state_data.get("solution_details", ""),
                state_data
            )
            
            # Update state with correctness assessment
            state_data["code_correctness"] = correctness_result.get("is_correct", False)
            state_data["correctness_feedback"] = correctness_result.get("feedback", "")
            code_correctness = correctness_result.get("is_correct", False)
            
            # Apply correctness-based rewards/penalties
            if correctness_result.get("correctness_reward"):
                additional_rewards.append(correctness_result["correctness_reward"])
            state_data["attempts"] = state_data.get("attempts", 0) + 1
            state_data["user_code"] = execution_result.get('extracted_code', '')
            
            # Determine execution-based rewards/penalties
            if code_correctness and execution_result["success"]:
                # Determine reward level based on attempt number
                attempts = state_data.get("attempts", 1)
                if attempts == 1:
                    exec_reward = ("reward", "EXCELLENT", "Perfect! Working code on first try!")
                elif attempts <= 2:
                    exec_reward = ("reward", "VERY_GOOD", "Great! Working code with minimal attempts!")
                elif attempts <= 3:
                    exec_reward = ("reward", "GOOD", "Good! Code works after a few tries!")
                else:
                    exec_reward = ("reward", "FAIR", "Code finally works after multiple attempts.")
                
                additional_rewards.append(exec_reward)
                response_data["response_text"] += f"\n\n**Feedback:**\n{correctness_result.get('feedback', '')}\n\n**Execution Results:**\n```\n{execution_result['stdout']}\n```\n\n"
                
                # Check for fast solve bonus
                if state_data.get("session_start_time"):
                    bonus = self._calculate_fast_solve_bonus(state_data["session_start_time"], "medium")
                    if bonus:
                        additional_rewards.append(bonus)
                
                # Mark problem as solved
                state_data["problem_solved"] = True
                
            else:
                # Code failed - penalty based on attempt number
                attempts = state_data.get("attempts", 1)
                if attempts <= 2:
                    exec_penalty = ("penalty", "MODERATE", "Code has execution issues - debug and try again!")
                elif attempts <= 4:
                    exec_penalty = ("penalty", "SIGNIFICANT", "Multiple failed attempts - review your approach!")
                else:
                    exec_penalty = ("penalty", "MAJOR", "Too many failed attempts - time to rethink!")
                    
                additional_rewards.append(exec_penalty)
                response_data["response_text"] += f"\n\n**Feedback:**\n{correctness_result.get('feedback', '')}\n\n**Execution Error:**\n```\n{execution_result['failure_reason'] or execution_result['stderr']}\n```\n\n"
        
        # Apply state updates
        state_updates = response_data.get("state_updates", {})
        for key, value in state_updates.items():
            state_data[key] = value
        
        # Handle state transition
        if intent_data.get("should_transition", False):
            state_data["current_state"] = intent_data["next_state"]
        
        # Apply additional rewards from execution and other factors
        for reward_type, reward_level, reward_message in additional_rewards:
            # Update score
            if reward_type == "reward":
                score_change = self.REWARD_LEVELS.get(reward_level, {}).get("score", 1)
                state_data["user_score"] = state_data.get("user_score", 0) + score_change
            else:
                score_change = self.PENALTY_LEVELS.get(reward_level, {}).get("score", -1)
                state_data["user_score"] = state_data.get("user_score", 0) + score_change
            
            # Yield gamification
            yield self._add_gamification(reward_type, reward_level, reward_message)
        
        # Check for session achievements (especially after major state changes)
        current_state = state_data.get("current_state", "")
        if current_state in ["SENIOR_DISCUSSION", "VARIATIONS", "TERMINATED"] or state_data.get("problem_solved", False):
            achievements = self._check_session_achievements(state_data)
            for achievement_type, achievement_level, achievement_message in achievements:
                # Update score
                if achievement_type == "reward":
                    score_change = self.REWARD_LEVELS.get(achievement_level, {}).get("score", 1)
                    state_data["user_score"] = state_data.get("user_score", 0) + score_change
                else:
                    score_change = self.PENALTY_LEVELS.get(achievement_level, {}).get("score", -1)
                    state_data["user_score"] = state_data.get("user_score", 0) + score_change
                
                # Yield gamification
                yield self._add_gamification(achievement_type, achievement_level, achievement_message)
        
        # Apply additional rewards/penalties from second LLM call (if different from intent detection)
        response_reward_type = response_data.get("reward_type", "none")
        if response_reward_type != "none":
            reward_level = response_data.get("reward_level", "BASIC")
            reward_message = response_data.get("reward_message", "")
            
            # Update score
            if response_reward_type == "reward":
                score_change = self.REWARD_LEVELS.get(reward_level, {}).get("score", 1)
                state_data["user_score"] = state_data.get("user_score", 0) + score_change
            else:
                score_change = self.PENALTY_LEVELS.get(reward_level, {}).get("score", -1)
                state_data["user_score"] = state_data.get("user_score", 0) + score_change
            
            # Yield gamification
            yield self._add_gamification(response_reward_type, reward_level, reward_message)
        
        # Yield main response
        response_text = response_data.get("response_text", "")
        if response_text:
            yield from response_text
        
        # Update conversation summary with comprehensive reward tracking
        reward_summary = f"Intent: {intent_data.get('intent')} | State: {state_data.get('current_state')} | Score: {state_data.get('user_score', 0)}"
        if additional_rewards:
            reward_summary += f" | Additional rewards: {len(additional_rewards)}"
        
        self._update_conversation_summary(
            state_data, 
            state_data.get("original_problem", ""), 
            state_data.get("problem_statement", ""), 
            reward_summary
        )
        
        # Save state
        yield from self._save_state(state_data, conversation_id)
        yield "\n\n"
        return

    # Main call method - simplified with two LLM calls
    def __call__(self, text, images=[], temperature=0.7, stream=True, max_tokens=None, system=None, web_search=False):
        
        # Extract conversation ID and parse state
        conversation_id = self._extract_conversation_id(text)
        state_data = self._get_full_state_data(text, conversation_id)

        # Handle special commands first
        if "/hint" in text.lower():
            state_data["hint_count"] = state_data.get("hint_count", 0) + 1
            self._update_conversation_summary(state_data, state_data.get("original_problem", ""), state_data.get("problem_statement", ""), f"User requested hint (total: {state_data['hint_count']})")
            yield self._add_gamification("penalty", "MINOR", "Hint used.")
            
            # Provide hint directly
            hint_response = f"**💡 Hint:**\n\nBased on your current progress, consider looking at the problem from a different angle. Think about the key constraints and what data structures might be most efficient here."
            yield hint_response + "\n\nTake your time to think about this hint and let me know how you'd like to proceed!\n\n"
            yield from self._save_state(state_data, conversation_id)
            yield "\n\n"
            return

        if "/quit" in text.lower():
            state_data["current_state"] = "TERMINATED"
            self._update_conversation_summary(state_data, state_data.get("original_problem", ""), state_data.get("problem_statement", ""), "User quit the interview session")
            
            # Check for final achievements and apply them
            final_achievements = self._check_session_achievements(state_data)
            for achievement_type, achievement_level, achievement_message in final_achievements:
                # Update score
                if achievement_type == "reward":
                    score_change = self.REWARD_LEVELS.get(achievement_level, {}).get("score", 1)
                    state_data["user_score"] = state_data.get("user_score", 0) + score_change
                else:
                    score_change = self.PENALTY_LEVELS.get(achievement_level, {}).get("score", -1)
                    state_data["user_score"] = state_data.get("user_score", 0) + score_change
                
                # Yield gamification
                yield self._add_gamification(achievement_type, achievement_level, achievement_message)
            
            yield self._add_gamification("reward", "GOOD", "Thanks for the interview session!")
            
            # Generate comprehensive session statistics
            stats_text = f"""**🎯 Interview Session Complete!**

**📊 Performance Dashboard:**
- **Final Score:** {state_data.get('user_score', 0)} points
- **Problem Solved:** {'✅ Yes' if state_data.get('problem_solved', False) else '❌ No'}
- **Code Attempts:** {state_data.get('attempts', 0)}
- **Hints Used:** {state_data.get('hint_count', 0)}
- **Clarifications Asked:** {state_data.get('clarification_count', 0)}
- **Good Questions:** {state_data.get('good_questions_asked', 0)}

**🏆 Achievements Unlocked:**"""
            
            if final_achievements:
                for _, _, achievement_msg in final_achievements:
                    stats_text += f"\n- {achievement_msg}"
            else:
                stats_text += "\n- 🎯 Session Participant - Every attempt counts!"
            
            stats_text += f"""

**📝 Session Summary:**
{state_data.get('conversation_summary', 'No summary available')}

**💡 Keep practicing and you'll do amazing in real interviews!** 🚀

*Score Ranges: 🏆 50+ = Excellent | 🌟 30+ = Very Good | ⭐ 10+ = Good | 📈 0+ = Fair*"""
            
            yield stats_text
            yield from self._save_state(state_data, conversation_id)
            yield "\n\n"
            return

        # LLM Call 1: Intent Detection + State Transition + Gamification
        intent_data = self._determine_intent_and_transition(text, state_data)

        if intent_data.get("current_state") == "INIT":
            problem_details = self._set_problem_details(text, intent_data)
            state_data["problem_name"] = problem_details.get("problem_name", "")
            state_data["problem_statement"] = intent_data.get("direct_response", "")
            state_data["solution_details"] = problem_details.get("solution_details", "")
            state_data["original_problem"] = problem_details.get("original_problem", "")
        state_data["current_state"] = intent_data.get("next_state", "INIT")
            
        
        # Apply rewards/penalties from intent detection
        reward_type = intent_data.get("reward_type", "none")
        if reward_type != "none":
            reward_level = intent_data.get("reward_level", "BASIC")
            reward_message = intent_data.get("reward_message", "")
            
            # Update score
            if reward_type == "reward":
                score_change = self.REWARD_LEVELS.get(reward_level, {}).get("score", 1)
                state_data["user_score"] = state_data.get("user_score", 0) + score_change
            else:
                score_change = self.PENALTY_LEVELS.get(reward_level, {}).get("score", -1)
                state_data["user_score"] = state_data.get("user_score", 0) + score_change
            
            # Yield gamification
            yield self._add_gamification(reward_type, reward_level, reward_message)
        
        # If intent provides direct response, use it
        if intent_data.get("provides_direct_response", False) and intent_data.get("direct_response"):
            if intent_data.get("intent") == "REQUEST_HINT":
                state_data["hint_count"] = state_data.get("hint_count", 0) + 1
            
            yield from intent_data["direct_response"]
            yield "\n\n"
            
            # Update conversation summary for direct responses
            original_problem = state_data.get("original_problem", "")
            problem_statement = state_data.get("problem_statement", "")
            reward_level = intent_data.get("reward_level", "BASIC")
            structured_summary = self._update_conversation_summary(
                state_data, 
                original_problem, 
                problem_statement, 
                f"Intent: {intent_data.get('intent')} | Direct response provided | Reward: {reward_type} {reward_level}"
            )
            
            yield from self._save_state(state_data, conversation_id)
            yield "\n\n"
            return
        
        # LLM Call 2: Generate Response based on state
        response_data = self._generate_state_response(text, state_data, intent_data)
        
        # Unified Handler: Process response and manage state
        yield from self._unified_handler(text, state_data, conversation_id, intent_data, response_data) 
        return