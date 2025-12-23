import os
from copy import deepcopy
from prompt_lib import WrappedManager, create_wrapped_manager

# Create the wrapped manager for managing prompts
manager = create_wrapped_manager("prompts.json")

# Create a cache dictionary to store prompts that might be created via the API
# This allows quick access to prompts without repeatedly accessing the manager
prompt_cache = {}

# Initialize the cache with existing prompts
try:
    for prompt_name in manager.keys():
        try:
            prompt_cache[prompt_name] = manager[prompt_name]
        except:
            pass  # Skip any prompts that can't be loaded
except:
    pass  # If manager is not ready, cache will be populated on first use

def refresh_cache():
    """
    Refresh the prompt cache from the manager.
    This function can be called to sync the cache with the manager.
    """
    global prompt_cache
    prompt_cache.clear()
    try:
        for prompt_name in manager.keys():
            try:
                prompt_cache[prompt_name] = manager[prompt_name]
            except:
                pass  # Skip any prompts that can't be loaded
    except:
        pass  # If manager is not ready, cache remains empty

def get_prompt(name, default=None):
    """
    Get a prompt from cache or manager.
    
    Args:
        name: The name of the prompt to retrieve
        default: Default value if prompt is not found
        
    Returns:
        The prompt content or default value
    """
    # First check cache
    if name in prompt_cache:
        return prompt_cache[name]
    
    # If not in cache, try to get from manager and cache it
    try:
        if name in manager:
            prompt = manager[name]
            prompt_cache[name] = prompt
            return prompt
    except:
        pass
    
    return default

# Extract all prompts from manager and assign them to variables for use in the codebase
math_formatting_instructions = manager["math_formatting_instructions"]
google_gl_prompt = manager["google_gl_prompt"]
google_behavioral_interview_prompt = manager["google_behavioral_interview_prompt"]
improve_code_prompt = manager["improve_code_prompt"]
improve_code_prompt_interviews = manager["improve_code_prompt_interviews"]
relationship_prompt = manager["relationship_prompt"]
dating_maverick_prompt = manager["dating_maverick_prompt"]
wife_prompt = manager["wife_prompt"]
diagram_instructions = manager["diagram_instructions"]
short_coding_interview_prompt = manager["short_coding_interview_prompt"]
more_related_questions_prompt = manager["more_related_questions_prompt"]
coding_interview_prompt = manager["coding_interview_prompt"]
ml_system_design_answer_short = manager["ml_system_design_answer_short"]
ml_system_design_answer = manager["ml_system_design_answer"]
ml_system_design_role = manager["ml_system_design_role"]
tts_friendly_format_instructions = manager["tts_friendly_format_instructions"]
engineering_excellence_prompt = manager["engineering_excellence_prompt"]
base_system = manager["base_system"]
chat_slow_reply_prompt = manager["chat_slow_reply_prompt"]
persist_current_turn_prompt = manager["persist_current_turn_prompt"]

# Extract preamble prompts from manager and assign them to variables
preamble_easy_copy = manager["preamble_easy_copy"]
preamble_short = manager["preamble_short"]
preamble_no_code_exec = manager["preamble_no_code_exec"]
preamble_no_code_prompt = manager["preamble_no_code_prompt"]
preamble_code_exec = manager["preamble_code_exec"]
preamble_cot = manager["preamble_cot"]

preamble_creative = manager["preamble_creative"]
preamble_argumentative = manager["preamble_argumentative"]
preamble_blackmail = manager["preamble_blackmail"]
preamble_web_search = manager["preamble_web_search"]
preamble_no_ai = manager["preamble_no_ai"]



PaperSummary=f"""\nYou will write a detailed, elaborate, comprehensive and in-depth research report on the provided link or paper in context. 
In the report first write a two paragraphs for extended summary of what the research does, their methodology and why it's important. 
Then proceed with the following 6 sections in your report - 
1) Original Problem and previous work in the area (What specific problems does this paper address? What has been done already and why that is not enough?) 
2) Proposed Solution (What methods/solutions/approaches they propose? Cover all significant aspects of their methodology, including what they do, their motivation, why and how they do?). Write in detail about the Proposed Solutions/methods/approaches. Explain any mathematical formulations or equations and how they are used in the work.
3) Datasets used, experiments performed and ablation studies performed. 
4) Key Insights gained and findings reported in detail. 
5) Results, Drawback of their methods and experiments and Future Work to be done. 
6) Glossary of uncommon terms used in the paper and their meanings comprehensively.

Other instructions:
1. All sections must be detailed, comprehensive and in-depth. All sections must be rigorous, informative, easy to understand and follow.
2. At the end write a summary of why the research/work was needed, what it does, and what it achieves.
3. Maintain academic rigor and academic tone throughout the report.
4. Be critical, skeptical and question the work done in the paper.
5. {math_formatting_instructions}
6. Explain the maths and mathematical concepts in detail with their mathematical formulation and their notation in detail. Why the equations in the given concepts or document look as they do and break the various parts of equation down with explanations for easier understanding.


Remember the '2) Proposed Solution' section must be detailed, comprehensive and in-depth covering all details. Section 2 must cover all about the methodology and the approach used in the paper, and why it is important and needed and how it improves over previous work.\n""".lstrip()

GeneralSummary=f"""\nYou will write a detailed, elaborate, comprehensive and in-depth research report on the provided link or document in context. 

In the report first write a two paragraphs for extended summary of what the document does, its purpose and why it's important. Then proceed with writing in detail and depth about the document.

Other instructions:
1. All sections must be detailed, comprehensive and in-depth. All sections must be rigorous, informative, easy to understand and follow.
2. Maintain rigor and professional tone throughout the report.
3. {math_formatting_instructions}


""".lstrip()

# TLDR prompt for generating short summaries of long answers
tldr_summary_prompt_system = """You are a skilled answer shortener. Your task is to create a TLDR (Too Long; Didn't Read) short version of a detailed answer.
You will be given a conversation summary so far, a user's original question and the full answer to shorten. You will be given instructions on how to shorten the answer. Then you will write the short version of the answer."""

tldr_summary_prompt = f"""{tldr_summary_prompt_system}

**Context:**
- Conversation summary so far: 
'''
{{summary}}
'''


- User's original question: 
'''
{{query}}
'''



---

**The full answer to shorten:**
'''
{{answer}}
'''

**Instructions:**
1. Create a concise TLDR short version of the above answer in few bullet points or 3-4 short paragraphs.
2. Focus on the key takeaways, main points, and actionable insights from the actual answer provided. Don't forget to also include any key information or insights from the answer as well.
3. Do NOT add any new information, opinions, or details that are not in the original answer.
4. This is strictly a summarization/paraphrasing task - only condense what is already written.
5. Keep the short version brief (under 400 words) but ensure it captures the essence of the full answer. Include few details where they are making most impact.
6. Use clear, simple language that is easy to scan quickly.
7. If the answer contains code, formulas, or technical details, summarize what they accomplish rather than including them verbatim.
8. Preserve any important steps, procedures, caveats, warnings, or limitations mentioned in the original answer.
9. Provide a one paragraph key takeaways and learnings or things to remember and do's/dont's to remember from the answer at the end.
10. Remove any historical context, background information, or repeatation of what is already mentioned in user query or conversation summary so far.

Write the short version of the answer below:
""".lstrip()

chain_of_density_system_prompt = """You are an expert summarizer using the Chain of Density technique. Your goal is to create increasingly dense and informative summaries while maintaining clarity and readability. Follow these key principles:

1. Information Preservation:
   - Never remove information from previous summaries
   - Each iteration must contain ALL information from previous iterations
   - Only add new information, never subtract

2. Density Progression:
   - Each iteration should maintain similar length but pack in more information
   - Replace general statements with specific details
   - Combine related ideas efficiently without losing clarity

3. Detail Enhancement:
   - Add specific examples, data, and evidence
   - Include technical details appropriate to the document type
   - Highlight relationships between concepts
   - Clarify cause-and-effect connections

4. Writing Style:
   - Use clear, precise language
   - Maintain logical flow and coherence
   - Employ efficient sentence structure
   - Balance technical accuracy with readability

5. Quality Control:
   - Verify all information is accurate
   - Ensure no contradictions between iterations
   - Maintain consistent terminology
   - Preserve key context and nuance
   
6. Clarity and Readability:
   - Ensure the summary is easy to understand and follow
   - Use clear and concise language
   - Summary should be comprehensive and detailed
   - Fully formed sentences and paragraphs with complete thoughts for ease of reading.
   - Write in a friendly and engaging tone in full sentences.
   - Be detail oriented and provide all necessary information.
   - Focus on readability, clarity and informativeness.
   


Remember: Each new summary must be a more comprehensive and detailed version of the previous summary. New Summary must be more informative, readable, clearer, understandable and detailed than the previous summary.""".lstrip()

scientific_chain_of_density_prompt = """You are creating an increasingly detailed and dense summary of a scientific paper through multiple iterations. This is iteration {iteration}.

Document Type: {doc_type}
Key Elements to Focus On: {key_elements}
Technical Detail Level: {technical_level}
List of suggested improvements to be made to the summary: {improvements}
List of suggested missing elements from the summary which could be added if present in the document: {missing_elements}


Original text of the paper or research:
{text}

Previous summary iterations:
{previous_summaries}

Instructions for writing a good paper or research summary (follow these instructions carefully):
{PaperSummary}

Instructions for this iteration:
1. Preserve and enhance the previous summary. Follow the instructions for writing a good paper or research summary. Add more details and elaborate more on the previous summary in the same format.
2. Add new layers of information, details, examples, data, evidence, technical details, mathematical formulations, equations, relationships, cause-and-effect connections, technical dependencies, performance considerations, error handling and edge cases, integration points and interfaces, etc.
3. Make each section of the summary follow the instructions for writing a good paper or research summary and be more detailed, elaborate, longer, comprehensive and in-depth.
4. Write the full new summary at once. Do not break this into parts.

Write your denser scientific summary below:
""".lstrip()

business_chain_of_density_prompt = """You are creating an increasingly detailed and dense summary of a business document through multiple iterations. This is iteration {iteration}.

Document Type: {doc_type}
Key Elements to Focus On: {key_elements}
Technical Detail Level: {technical_level}
List of suggested improvements to be made to the summary: {improvements}
List of suggested missing elements from the summary which could be added if present in the document: {missing_elements}

Original text:
{text}

Previous summary iterations:
{previous_summaries}

Instructions for this iteration:
1. Preserve and enhance:
   - Key business metrics and KPIs
   - Market analysis and competitive insights
   - Strategic recommendations and action items
   - Financial projections and assumptions
2. Add new layers of:
   - Market-specific details and trends
   - Operational implications
   - Risk factors and mitigation strategies
   - Implementation timelines and resources

Write your denser business summary below:
""".lstrip()

technical_chain_of_density_prompt = """You are creating an increasingly detailed and dense summary of technical documentation through multiple iterations. This is iteration {iteration}.

Document Type: {doc_type}
Key Elements to Focus On: {key_elements}
Technical Detail Level: {technical_level}
List of suggested improvements to be made to the summary: {improvements}
List of suggested missing elements from the summary which could be added if present in the document: {missing_elements}

Original text:
{text}

Previous summary iterations:
{previous_summaries}

Instructions for this iteration:
1. Preserve and enhance:
   - Technical specifications and requirements
   - Implementation details and procedures
   - System architecture and components
   - Usage examples and best practices
2. Add new layers of:
   - Technical dependencies and prerequisites
   - Performance considerations
   - Error handling and edge cases
   - Integration points and interfaces
   


Write your denser technical summary below:
""".lstrip()

general_chain_of_density_prompt = """You are creating an increasingly detailed and dense summary through multiple iterations. This is iteration {iteration}.

Document Type: {doc_type}
Key Elements to Focus On: {key_elements}
Technical Detail Level: {technical_level}
List of suggested improvements to be made to the summary: {improvements}
List of suggested missing elements from the summary which could be added if present in the document: {missing_elements}

Original text:
{text}

Previous summary iterations:
{previous_summaries}

Instructions for this iteration:
1. Preserve and enhance:
   - Main ideas and key arguments
   - Supporting evidence and examples
   - Important relationships and connections
   - Context and implications
2. Add new layers of:
   - Specific details and examples
   - Cause-and-effect relationships
   - Comparative analysis
   - Practical applications
   

Write your denser summary below:
""".lstrip()



class CustomPrompts:
    def __init__(self, llm, role):
        self.llm = llm
        self.role = role
        # TODO: decide on role prefixes needed or not.
        # 4. Provide code in python if asked for code or implementation.
        # Use markdown formatting to typeset and format your answer better.
        
        self.gpt4_prompts = dict(       

            web_search_question_answering_prompt=f"""<task>Your role is to provide an answer to the user question incorporating the additional information you are provided within your response.</task>
Question is given below:
"{{query}}"
Relevant additional information with url links, titles and document context are mentioned below:
"{{additional_info}}"

Continue the answer ('Answer till now' if it is not empty) by incorporating additional information from other documents. 
Answer by thinking of Multiple different angles that 'the original question or request' can be answered with. Focus mainly on additional information from other documents. Provide the link and title before using their information in markdown format (like `[title](link) information from document`) for the documents you use in your answer.

Question: '''{{query}}'''
Answer till now (partial answer, can be empty): '''{{answer}}'''
Write answer using additional information below.
""",
            IdeaNovelty= f"""
I would like you to evaluate the following machine learning research idea:  

<idea>  
{{research_idea}}
</idea>  

Please provide a comprehensive evaluation based on the following criteria:  

1. Novelty:  
   - Originality: How novel and original is this research idea compared to existing literature?  
   - Prior work: Has similar work been done before? If so, how is this different and novel?  
   - Novel contributions: What are the key novel contributions of this work?  

2. Applicability and Impact:  
   - Real-world applications: What are the potential real-world applications of this work?  
   - Benefiting domains: Which domains and industries could benefit from this research?  
   - Problem significance: How important and impactful is the problem being addressed?  

3. Potential Weaknesses and Reasons for Rejection:  
   - Limitations: What are the main potential weaknesses and limitations of the proposed approach?  
   - Rejection reasons: What are some reasons reviewers might reject or criticize this work?  
   - Reviewer 2 critique: If you were a critical "Reviewer 2", what feedback would you give?  
   - Common pitfalls: What are some common causes of rejection for this type of research?  
   - Anticipate potential areas of misunderstanding that the reviewers might have.

4. Strengths:  
   - Key strengths: What are the main strengths and selling points of this research idea?  
   - Compelling aspects: What makes this a compelling and valuable piece of research?  

5. Datasets and Experiments:  
   - Required datasets: What kind of datasets would be needed to evaluate this idea?  
   - Dataset availability: Are appropriate datasets readily available or would new data need to be collected?  
   - Experimental validation: What experiments should be run to validate the idea and methodology?  
   - Ablation studies: What ablation studies would help show the importance of each component?  

6. Theoretical Contributions:  
   - Novel algorithms: Does the research introduce any novel algorithms or techniques?  
   - Mathematical formulations: Are there any new mathematical formulations or theoretical insights?  
   - Theoretical advances: How does the work advance the theoretical understanding of the problem?  

7. Empirical Results:  
   - Expected results: What are the expected empirical results and their significance?  
   - State-of-the-art comparison: How do the results compare to the current state-of-the-art?  
   - Robustness and generalization: Are the results robust and do they generalize well to different settings?  

8. Reproducibility:  
   - Code and data availability: Will the code and datasets be made publicly available to ensure reproducibility?  
   - Experimental setup: Are the experimental setup, hyperparameters, and implementation details clearly described?  
   - Evaluation metrics: Are the evaluation metrics and procedures well-defined and justified?  

9. Comparison with Existing Methods:  
   - Baseline methods: What are the relevant baseline methods for comparison?  
   - Advantages and improvements: How does the proposed approach improve upon existing methods?  
   - Comparative analysis: Provide a detailed comparative analysis with state-of-the-art techniques.  

10. Scalability and Efficiency:  
    - Computational complexity: Analyze the computational complexity of the proposed method.  
    - Scalability: How well does the approach scale to large datasets and complex problems?  
    - Efficiency: Discuss the efficiency of the method in terms of time and resource requirements.  

11. Clarity and Presentation:  
    - Writing quality: Is the research idea presented clearly, concisely, and coherently?  
    - Figures and tables: Are the figures and tables informative, well-designed, and properly labeled?  
    - Organization: Is the paper well-structured and easy to follow?  

12. Broader Impact and Limitations:  
    - Generalizability: How well does the proposed approach generalize to different datasets, tasks, or domains?  
    - Future directions: What are promising future research directions stemming from this work?  

13. Relevant Conferences and Journals:  
    - Target venues: Which top-tier conferences (e.g., NeurIPS, ICML, ICLR, AISTATS) or journals (e.g., Nature, Science) would be most suitable for this work?  
    - Fit with venue scope: How well does the research align with the scope and themes of the target venues?  

Please provide a detailed analysis addressing each of the points above. Be sceptical and critical of the idea. Format your response in a clear, structured way with the headings provided. Aim to provide a thorough, constructive, and rigorous evaluation similar to what reviewers at top-tier venues would expect. Include specific examples, suggestions for improvement, and insightful comments to help strengthen the research idea.  
""".lstrip(),
            IdeaComparison=f"""
I would like you to evaluate and compare two machine learning research ideas based on the following aspects. For each aspect, please assign a score out of 10 for both ideas and provide a brief justification for the score. After evaluating all aspects, calculate the average score for each idea and determine which idea is better, along with a detailed explanation of why it is preferred. Provide actionable insights on how to improve the chosen idea to increase its chances of acceptance and impact.

<ideas>  
{{research_idea}}
</ideas>  


First clearly write down the two ideas and your own understanding of them and their domain. 
Then evaluate them based on the following aspects.
While you do your evaluations on these aspects write your thoughts first about each idea under each aspect in details so we can justify the scores you give to each idea.
  
**Aspects for Comparison:**  
  
1. **Novelty and Originality:**  
   - Assess the uniqueness and innovativeness of each idea compared to existing literature. Are there unique contributions that set each idea apart?  
   - Consider whether the idea introduces new concepts, methods, or approaches that have not been explored before.
   - Would Reviewers find that the research does not offer new insights or advancements over existing literature.    
   - Evaluate the potential for the idea to open up new research directions or solve previously unsolved problems.
   - Consider the novelty of the proposed methodology and its potential to advance the state-of-the-art. Is the proposed methodology just a simple extension of existing methods?  
   - **Reviewer Influence:** Reviewers prioritize originality; lack of novelty can lead to rejection, especially from "Reviewer 2," who may be critical of incremental contributions.  
   - Idea 1 Comprehensive Analysis: [Insert analysis]
   - Idea 2 Comprehensive Analysis: [Insert analysis]
   - Idea 1 Score: [Insert score]    
   - Idea 2 Score: [Insert score]    
   - [Provide a detailed and exhaustive justification for the scores]  
  
2. **Potential Impact:**  
   - Evaluate the potential impact of each idea on the field of machine learning and its applications.  
   - Consider the significance of the problem being addressed and the potential for the idea to advance the state-of-the-art.  
   - Assess the potential for the idea to inspire future research and have a lasting impact on the field. Is this idea a moon-shot?
   - **Reviewer Influence:** High-impact ideas are often favored by reviewers, as they contribute significantly to the advancement of the field.  
   - Idea 1 Score: [Insert score]    
   - Idea 2 Score: [Insert score]    
   - [Provide a brief justification for the scores]  
  
3. **Technical Feasibility:**  
   - Analyze the technical feasibility of implementing each idea, considering the required resources, expertise, and current state of technology.  
   - Evaluate whether the proposed methods and algorithms are computationally tractable and can be implemented efficiently.  
   - Consider the availability of necessary datasets, tools, and infrastructure to support the implementation of the idea.
   - Are there open and easily accessible datasets to be used for this idea.
   - Are there any potential challenges in implementing the idea.
   - Are there easily available tools and libraries to implement the idea.  
   - Is this idea too grandiose and large and may not be feasible to implement. Would this idea benefit from being broken into smaller ideas or pieces? Is this idea a moon-shot and too risky?
   - What are the chances that this will work? Is this a small incremental improvement or large risky moon-shot idea. We want ideas which are not too risky and have a good chance of working but are also novel and new.
   - **Reviewer Influence:** Reviewers may express concerns about feasibility, especially if the proposal appears overly ambitious without a clear plan.  
   - Idea 1 Comprehensive Analysis: [Insert analysis]
   - Idea 2 Comprehensive Analysis: [Insert analysis]
   - Idea 1 Score: [Insert score]    
   - Idea 2 Score: [Insert score]    
   - [Provide a detailed and exhaustive justification for the scores]  
  
4. **Theoretical Contributions:**  
   - Compare the theoretical contributions of each idea, including novel algorithms, mathematical formulations, or theoretical insights.  
   - Assess the depth and rigor of the theoretical foundations underlying each idea.  
   - Evaluate the potential for the theoretical contributions to have broader implications beyond the specific problem being addressed.  
   - Idea 1 Score: [Insert score]    
   - Idea 2 Score: [Insert score]    
   - [Provide a detailed and exhaustive justification for the scores]  
  
5. **Empirical Results:**  
   - Assess the expected empirical results of each idea and their significance in advancing the state-of-the-art.  
   - Consider the quality and diversity of the datasets that would be used to evaluate the idea.  
   - Evaluate the proposed evaluation metrics and their appropriateness for measuring the performance of the idea.  
   - What kind of ablations can we run and will those ablations provide insights into the idea and impress the reviewers?
   - What kind of plots, visualizations and tables can we provide to show the results of the idea. Will these plots and tables be insightful and impress the reviewers.
   - **Reviewer Influence:** Reviewers often look for robust experimental validation. Weak or poorly defined experiments can lead to negative reviews.  
   - Idea 1 Score: [Insert score]    
   - Idea 2 Score: [Insert score]    
   - [Provide a detailed and exhaustive justification for the scores]  

6. **Scalability and Efficiency:**  
   - Compare the scalability and computational efficiency of each idea, especially for large-scale datasets and real-world scenarios.  
   - Evaluate the proposed algorithms and their ability to handle increasing data sizes and complexity.  
   - Consider the potential for the idea to be deployed in resource-constrained environments or real-time applications.  
   - **Reviewer Influence:** Reviewers may be concerned about scalability, especially if the method is intended for real-world applications.  
   - Idea 1 Score: [Insert score]    
   - Idea 2 Score: [Insert score]    
   - [Provide a brief justification for the scores]  
  
7. **Reproducibility and Code Availability:**  
   - Assess the ease of reproducibility and the availability of code for each idea, considering the potential for others to build upon the work.  
   - Evaluate the clarity and documentation of the proposed methods and algorithms.  
   - Consider the potential for the code and datasets to be shared and used by the research community.  
   - Would we need to do a code, dataset or other type of releases to promote reproducibility and or can people reproduce the idea by just the paper.
   - Idea 1 Score: [Insert score]    
   - Idea 2 Score: [Insert score]    
   - [Provide a brief justification for the scores]  
  
8. **Alignment with Current Research Trends:**  
   - Evaluate how well each idea aligns with current research trends and the interests of the machine learning community.  
   - Consider the relevance of the idea to ongoing research challenges and areas of active investigation.  
   - Assess the potential for the idea to contribute to the broader research agenda and inspire further work in the field.  
   - **Reviewer Influence:** Ideas that resonate with current trends are more likely to attract positive attention from reviewers.  
   - Idea 1 Score: [Insert score]    
   - Idea 2 Score: [Insert score]    
   - [Provide a detailed and exhaustive justification for the scores]  
  
9. **Time and Effort Required:**  
    - Estimate the time and effort required to develop and publish each idea, considering the complexity and scope of the work.  
    - Consider the availability of resources, expertise, and support needed to successfully execute the idea.  
    - Evaluate the potential challenges and risks associated with pursuing each idea and the likelihood of overcoming them within a reasonable timeframe.
    - Evaluate the potential for the idea to be effectively presented in research papers, conference presentations, and other dissemination channels.  
    - Write down your reasoning of what tasks will be needed for these ideas and what roadblocks can come in the way of implementing these ideas.
    - Write down a small step by step plan of how you will implement these ideas and how long each task for each idea may take.
    - Think of both ideas and evaluate which idea will require less effort and time to implement and publish. 
    - Idea 1 Exhaustive Analysis: [Analysis about idea 1]
    - Idea 2 Exhaustive Analysis: [Analysis about idea 2]
    - Idea 1 Score: [Insert score]    
    - Idea 2 Score: [Insert score]    
    - [Provide a detailed and exhaustive justification for the scores]  
  
10. **Reviewer 2's Perspective:**  
    - Consider potential criticisms or concerns that a critical reviewer (often referred to as "Reviewer 2") might raise about each idea.  
    - Anticipate potential weaknesses, limitations, or gaps in the proposed methods, experiments, or analysis that reviewers might point out.  
    - Evaluate the robustness and thoroughness of the idea in addressing potential counterarguments or alternative explanations.
    - Anticipate potential areas of misunderstanding that the reviewers might have.  
    - [Discuss potential criticisms or concerns that a critical reviewer might raise for each idea]  
    - Think of generic reviewer 2 comments and criticisms that can be raised for these ideas as seen in reddit and twitter.
    - Idea 1 Comprehensive thought process: [Insert analysis]
    - Idea 2 Comprehensive thought process: [Insert analysis]
    - Idea 1 Score: [Insert score]    
    - Idea 2 Score: [Insert score]    
    - [Provide a detailed and exhaustive justification for the scores]  
  
11. **Meta-Reviewer's Perspective:**  
    - Consider the perspective of a meta-reviewer, who oversees the review process and makes final decisions in borderline cases.  
    - Evaluate the overall strength and coherence of the idea, considering the balance of positive and negative reviews.  
    - Assess the potential for the idea to make a significant and impactful contribution to the field, even if some aspects require further refinement or clarification.  
    - [Evaluate the overall strength and coherence of each idea from a meta-reviewer's perspective]  
    - Think of generic meta-reviewer comments and criticisms that can be raised for these ideas as seen in reddit and twitter.
    - Idea 1 Score: [Insert score]    
    - Idea 2 Score: [Insert score]    
    - [Provide a detailed and exhaustive justification for the scores]  
  
12. **Common Weaknesses and Pitfalls:**  
    - Identify common weaknesses or pitfalls that reviewers often highlight in machine learning research papers.  
    - Consider issues such as lack of novelty, insufficient experimental evaluation, poor comparison with existing methods, or unclear contributions.  
    - Evaluate the idea's ability to address and mitigate these common weaknesses effectively.  
    - [Identify and assess common weaknesses or pitfalls that reviewers might highlight for each idea]  
    - Idea 1 Comprehensive Analysis: [Insert analysis]
    - Idea 2 Comprehensive Analysis: [Insert analysis]
    - Idea 1 Score: [Insert score]    
    - Idea 2 Score: [Insert score]    
    - [Provide a detailed and exhaustive justification for the scores]  

13. **Datasets and Resources:**  
    - Determine the availability of necessary datasets. Are they publicly accessible or will new data need to be collected?  
    - Evaluate the resources required for implementation, including computational power and human expertise.  
    - **Reviewer Influence:** Lack of access to datasets or inadequate resource planning can lead reviewers to question the viability of the research.  
    - Idea 1 Comprehensive Analysis: [Insert analysis]
    - Idea 2 Comprehensive Analysis: [Insert analysis]
    - Idea 1 Score: [Insert score]    
    - Idea 2 Score: [Insert score]    
    - [Provide a brief justification for the scores]  

14. **Conditions to Avoid easy Rejections**
    - Identify common pitfalls that lead to easy rejections of research papers in this field or idea domain.
    - Does this idea/abstract present a clear, side-by-side comparison of your approach versus existing methods, highlighting key differences in methodology and performance.
    - Does the idea abstract convey key contributions clearly, using concise language and illustrative examples.
    - Can the idea be easily reproduced. Are the datasets and code available for the idea.
    - Would a lazy reviewer misunderstand the idea or a research work written on this idea.   
    - Idea 1 Comprehensive Analysis: [Insert analysis]
    - Idea 2 Comprehensive Analysis: [Insert analysis]
    - Idea 1 Score: [Insert score]    
    - Idea 2 Score: [Insert score]    
    - [Provide a detailed and exhaustive justification for the scores]    
  
After assigning scores for each aspect and considering any important additional factors you can think of, make a table with both ideas and the criterias for scoring with the scores. 
Then please calculate the total score for each idea and provide a final ranking. 
Explain which idea is better overall and why, taking into account the scores, the importance of each aspect, and any additional considerations in the context of publishing a successful machine learning research paper with the least effort.  
  
Please ensure that your response is well-structured, detailed, and provides clear justification for the ranking and recommendation. 
Highlight the strengths and weaknesses of each idea and provide actionable insights on how to improve the chosen idea to increase its chances of acceptance and impact.  
""".lstrip(),
            IdeaFleshOut=f"""
I would like you to help me flesh out a machine learning research idea. Please guide me through the development of this idea by addressing the following aspects in detail. For each aspect, provide insightful suggestions, ask clarifying questions if needed, and help me expand on the points presented.  
  
**Research Idea:** 
<idea>
{{research_idea}}
</idea>
  
**Aspects to Address:**  
  
1. **Motivation and Background:**  
   - What is the motivation behind this research idea?  
   - What problem or challenge does this idea aim to address?  
   - Provide a brief background of the problem domain and its significance.  
   - What types of domains and papers should we search for in the literature review on this idea?  
   - Write four diverse search queries that we can use to search for literature related to this idea.  
  
2. **Methodology and Approach:**  
   - Describe the proposed methodology and approach in detail.  
   - What are the key components or steps involved in the methodology?  
   - How does this approach differ from existing methods or techniques?  
   - How does this idea advance the state-of-the-art in the field?   
   - What type of system diagram or flowchart can be used to illustrate the methodology?
  
3. **Dataset and Experiments:**  
   - What datasets are required to evaluate this idea?  
   - How do we benchmark this idea against existing methods? What existing methods to benchmark against?
   - What tasks can be performed on these datasets to validate the idea?  
   - What type of experiments can be performed to validate this idea?  
   - What metrics or evaluation criteria can be used to assess the performance of this idea?  
   - What are the expected results and outcomes of these experiments? Would we need human evaluation or can we use automatic evaluation?
   - Suggest specific experiments, analyses, or evaluations to strengthen the research proposal.  
  
4. **Ablations and Research Questions:**  
   - What ablation studies can be conducted to analyze the importance of different components?  
   - What research questions can be explored based on this idea?  
   - Are there any specific hypotheses that can be tested through experiments?  
   - What plots can be used to show the results of these ablation studies and research questions?  
  
5. **Novelty and Contributions (Reinforcement):**  
   - Highlight the unique aspects of the research that set it apart from existing work.  
   - Explain how the research will contribute to advancing the field of machine learning.  
   - Discuss the potential for the research to open new avenues or inspire further studies.  
   - What novel insights or techniques does this idea potentially introduce?   
  
6. **Challenges and Risks:**  
   - Identify potential obstacles or limitations that may affect the research.  
   - Discuss strategies for mitigating risks or overcoming challenges.  
   - Reflect on assumptions made and how they might impact the results.  
  
7. **Reviewer Perspectives and Feedback:**  
    - Anticipate potential questions or concerns that reviewers might have.  
    - Anticipate potential areas of misunderstanding that the reviewers might have.
    - Discuss how to address common criticisms and strengthen the research proposal.  
    - Reflect on ways to enhance the clarity, rigor, and appeal to the academic community.  

8. **Actionable Insights and Recommendations:**
    - Provide actionable insights on how to improve the research idea.
    - Suggest strategies for addressing potential challenges and enhancing the feasibility of the research.
    - Suggest strategies for making the research more palatable to reviewers and readers. Ensure that reviewers understand the idea, significance and impact of the research.
    - Recommend strategies for enhancing the impact and relevance of the research.
    
9. **Make an Action Plan and write an elaborate outline for the paper:**
    - Provide a step-by-step action plan for developing and writing the paper.
    - Suggest a structure that would make the paper compelling and easy to follow.
    - Suggest potential tables, figures, system diagrams, flowcharts and visualizations that could enhance the paper.
    - Suggest a timeline for completing the research, experiments, and paper writing process.
    - Write a detailed outline for the paper based on this idea. 
    - Include sections, subsections, and key points to be covered in each part.

10. **Sample Paper Components:**  
    - **Title:** Propose a compelling and descriptive title for a paper based on this idea.  
    - **Abstract:** Write a concise abstract summarizing the key aspects of the research.  
    - **Introduction:** Draft a brief introduction outlining the motivation, problem statement, and significance of the research.  
    - **Related Work:** Write briefly about the areas we need to cover in the related work section.
    
**Instructions:**  
  
- As you address each aspect and the sub-questions within those, provide detailed insights and suggestions to help me develop the research idea comprehensively.  
- Feel free to ask me questions to clarify uncertainties or to prompt deeper thinking about specific elements.  
- The goal is to collaboratively flesh out the research idea into a well-defined and robust proposal ready for development and publication.  

Please provide a comprehensive and detailed analysis of the research idea, covering each of the aspects and the sub-questions within the aspects, mentioned above. 
Finally write a sample title, abstract and a small introduction for a paper based on this idea.
""".lstrip(),
            IdeaDatasetsAndExperiments=f"""
Given the following high-level research idea:
<idea>
{{research_idea}}
</idea>

Please provide a detailed analysis of the datasets and experiments required to evaluate this idea.
some of the aspects to keep in mind when writing the answer are:
    - What datasets are required to evaluate this idea?
    - What tasks can be performed on these datasets to validate the idea?
    - How do we benchmark this idea against existing methods? What existing methods to benchmark against?
    - What type of experiments can be performed to validate this idea?
    - What metrics or evaluation criteria can be used to assess the performance of this idea?
    - What normalized metrics can be used to compare the results of this idea with existing methods?
    - What are the expected results and outcomes of these experiments? Would we need human evaluation or can we use automatic evaluation.
    - Suggest specific experiments, analyses, or evaluations to strengthen the research proposal.
    
Please provide a comprehensive and detailed analysis of the datasets and experiments required to evaluate this idea following the above pointers and going above and beyond to add your own criterion.

""".lstrip(),
            IdeaAblationsAndResearchQuestions=f"""
Given the following high-level research idea:
<idea>
{{research_idea}}
</idea>

Please provide a detailed analysis of the ablation studies and research questions that can be explored based on this idea.
some of the aspects to keep in mind when writing the answer are:
    - What ablation studies can be conducted to analyze the importance of different components?
    - What research questions can be explored based on this idea?
    - Are there any specific hypotheses that can be tested through experiments?
    - What interesting findings and conclusions might be drawn from these ablation studies and research questions?
    - What type of charts, plots or graphs can be used to show the results of these ablation studies and research questions.  
""".lstrip(),
            ResearchPreventRejections=f"""
Given the following high-level research idea:
<idea>
{{research_idea}}
</idea>

Please provide a detailed analysis of the potential pitfalls and conditions to avoid easy rejections for this research idea.
some of the aspects to keep in mind when writing the answer are:
    - Identify common pitfalls that lead to easy rejections of research papers in this field or idea domain.
    - Does this idea/abstract present a clear, side-by-side comparison of your approach versus existing methods, highlighting key differences in methodology and performance.
    - Does the idea abstract convey key contributions clearly, using concise language and illustrative examples.
    - Can the idea be easily reproduced. Are the datasets and code available for the idea.
    - Would a lazy reviewer misunderstand the idea or a research work written on this idea.
    - Write down the potential pitfalls and conditions to avoid easy rejections for this research idea.
    
Now lets go section by section and write down the potential pitfalls and reasons for rejections.
- Introduction
- Related Work
- Methodology
- Experiments
- Results
- Ablations
- Discussion
- Conclusion

Focus on each of the above sections and write down the potential pitfalls and conditions to avoid easy rejections for this research idea. Include all common and trivial rejection reasons as well.
Write down what easy and common excuses reviewers can use to reject for each of these sections.

Lets also think of the tables, figures and visualizations that can be used to avoid easy rejections. And what care we must take in our tables and figures to avoid easy rejections.
Aside from this lets also think of generic pitfalls and conditions to avoid easy rejections for this research idea.
""".lstrip(),
            ResearchReviewerFeedback=f"""
""".lstrip(),

            get_more_details_prompt=f"""Continue writing answer to a question or instruction which is partially answered. 
Provide new details from the additional information provided if it is not mentioned in the partial answer already given. 
Don't repeat information from the partial answer already given.
Question is given below:
"{{query}}"
Answer till now (partial answer already given): '''{{answer}}'''

Relevant additional information from the same document context are mentioned below:
'''{{additional_info}}'''

Continue the answer ('Answer till now') by incorporating additional information from this relevant additional context. 

Continue the answer using additional information from the documents.
""",
            paper_details_map = {
            "methodology": f"""
Read the document and provide information about "Motivation and Methodology" of the work.
Cover the below points while answering and also add other necessary points as needed.
    - What do the authors do in this overall work (i.e. their methodology) with details, include all aspects of their methodology, provide comprehensive details and go deep into their work.
    - Detailed methodology and approach described in this work.
    - Intuitive explanation of the methodology and approach.
    - Mathematics and mathematical formulations and equations used in the work, their meaning and justification.
    - how do they solve the problem, provide details?
    - what is their justification in using this method? Why do they use this method? 
    - What mathematical formulations or equations are used in the work, their meaning and justification?
    - Is the proposed methodology just a simple extension of existing methods?
    
{math_formatting_instructions}

Cover any other aspects of the methodology and approach that are not covered above but will aid in understanding the work and its implications and how we can replicate or extend the work.
""",
            "previous_literature_and_differentiation": """
Read the document and provide information about "Previous Literature and Background work" of the work.
Cover the below points while answering and also add other necessary points as needed.
    - Original Problem and previous work in the area (What specific problems does this paper address? What has been done already and why that is not enough?). Go into details about the previous methods and how they are not enough.
    - What is this work's unique contribution above and beyond previous works?
    - Give in-depth details about what previous literature or works are referred to and how are they relevant to the problem this method is solving?
    - Provide detailed comparison of their work with previous methods and how their work improves over previous methods.
    
Writing Instructions:
- Write fully formed sentences and paragraphs with complete thoughts for ease of reading.
- Write in a friendly and engaging tone in full sentences and paragraphs.
- Be detail oriented and provide all necessary information.
- Focus on readability, clarity and informativeness.


""",
            "experiments_and_evaluation":"""
Read the document and provide information about "Experiments and Evaluation" of the work.
Cover the below points while answering and also add other necessary points as needed.
    - How is the proposed method/idea evaluated?
    - What metrics are used to quantify their results?
    - what datasets do they evaluate on?
    - What experiments are performed?
    - Are there any experiments with surprising insights?
    - Any other surprising experiments or insights
    - Any drawbacks in their evaluation or experiments
    
Writing Instructions:
- Write fully formed sentences and paragraphs with complete thoughts for ease of reading.
- Write in a friendly and engaging tone in full sentences and paragraphs.
- Be detail oriented and provide all necessary information.
- Focus on readability, clarity and informativeness.


""",
            "results_and_comparison": """
Read the document and provide information about "Results" of the work.
Cover the below points while answering and also add other necessary points as needed.
    - What results do they get from their experiments 
    - how does this method perform compared to other methods?
    - Make markdown tables to highlight most important results.
    - Any Insights or surprising details from their results and their tables
    
Writing Instructions:
- Write fully formed sentences and paragraphs with complete thoughts for ease of reading.
- Write in a friendly and engaging tone in full sentences and paragraphs.
- Be detail oriented and provide all necessary information.
- Focus on readability, clarity and informativeness.


""",
            "limitations_and_future_work":"""
Read the document and provide information about "Limitations and Future Work" of the work. 
Cover the below points while answering and also add other necessary points as needed.
    - What are the limitations of this method, 
    - Where and when can this method or approach fail? 
    - What are some further future research opportunities for this domain as a follow up to this method?
    - What are some tangential interesting research questions or problems that a reader may want to follow upon?
    - What are some overlooked experiments which could have provided more insights into this approach or work.
    
Writing Instructions:
- Write fully formed sentences and paragraphs with complete thoughts for ease of reading.
- Write in a friendly and engaging tone in full sentences and paragraphs.
- Be detail oriented and provide all necessary information.
- Focus on readability, clarity and informativeness.


""",

            }
        )

    @property
    def chain_of_density_system_prompt(self):
        return chain_of_density_system_prompt
    
    @property
    def scientific_chain_of_density_prompt(self):
        return scientific_chain_of_density_prompt
    
    @property
    def business_chain_of_density_prompt(self):
        return business_chain_of_density_prompt
    
    @property
    def technical_chain_of_density_prompt(self):
        return technical_chain_of_density_prompt
    
    @property
    def general_chain_of_density_prompt(self):
        return general_chain_of_density_prompt
    
    @property
    def idea_novelty_prompt(self):
        return self.gpt4_prompts["IdeaNovelty"]

    @property
    def idea_comparison_prompt(self):
        return self.gpt4_prompts["IdeaComparison"]

    @property
    def idea_flesh_out_prompt(self):
        return self.gpt4_prompts["IdeaFleshOut"]

    @property
    def idea_datasets_and_experiments_prompt(self):
        return self.gpt4_prompts["IdeaDatasetsAndExperiments"]

    @property
    def idea_ablations_and_research_questions_prompt(self):
        return self.gpt4_prompts["IdeaAblationsAndResearchQuestions"]

    @property
    def research_prevent_rejections_prompt(self):
        return self.gpt4_prompts["ResearchPreventRejections"]
    
    @property
    def paper_summary_prompt(self):
        return PaperSummary
    
    @property
    def ml_system_design_role(self):
        return ml_system_design_role
    
    @property
    def ml_system_design_answer(self):
        return ml_system_design_answer
    
    @property
    def ml_system_design_answer_short(self):
        return ml_system_design_answer_short
    
    @property
    def engineering_excellence_prompt(self):
        return engineering_excellence_prompt
    
    @property
    def google_gl_prompt(self):
        return google_gl_prompt

    @property
    def google_behavioral_interview_prompt(self):
        return google_behavioral_interview_prompt
    
    @property
    def coding_interview_prompt(self):
        return coding_interview_prompt

    @property
    def prompts(self):
        if self.llm == "gpt4":
            prompts = self.gpt4_prompts
        elif self.llm == "gpt3":
            prompts = self.gpt4_prompts
        elif self.llm == "llama":
            raise ValueError(f"Invalid llm {self.llm}")
        elif self.llm == "claude":
            prompts = self.gpt4_prompts
        else:
            raise ValueError(f"Invalid llm {self.llm}")
        return prompts

    @property
    def paper_details_map(self):
        prompts = self.prompts
        return prompts["paper_details_map"]

    


    @property
    def persist_current_turn_prompt(self):
        return persist_current_turn_prompt
    
    @property
    def next_question_suggestions_prompt(self):
        nqs_prompt="""You are given conversation details between a human and an AI. You are also given a summary of how the conversation has progressed till now. 
You will write a list of next question/response suggestions that the human can ask to the AI after the current user query and system response to continue the conversation.
The next question/response suggestions should be in the form of a list of questions and the questions should be short and concise.

The next question/response suggestions can either be a question or a response that the user can tap on in the chat interface to continue the conversation.

Follow the below format for your response:

<next_question_suggestions>
    <suggestion>question/response suggestion 1</suggestion>
    <suggestion>question/response suggestion 2</suggestion>
    <suggestion>question/response suggestion 3</suggestion>
    ...
</next_question_suggestions>



The summary and salient points of the conversation is as follows:
'''{summary}'''

Previous messages of the conversation are as follows:
<|previous_messages|>
'''{previous_messages_text}'''
<|/previous_messages|>

The last 2 recent messages of the conversation from which we will derive the summary and salient points are as follows:


User query: 
<|user_message|>
'''{query}'''
<|/user_message|>

Assistant response: 
<|assistant_message|>
'''{response}'''
<|/assistant_message|>


Your response will be in below xml style format:
<next_question_suggestions>
    <suggestion>question/response suggestion 1</suggestion>
    <suggestion>question/response suggestion 2</suggestion>
    <suggestion>question/response suggestion 3</suggestion>
    ...
</next_question_suggestions>

Give 4 suggestions.
Now write your response in the above xml style format. Only output the xml tags and nothing else. Only write the <next_question_suggestions> tag and the <suggestion> tags inside it.

"""
        return nqs_prompt


    @property
    def chat_fast_reply_prompt(self):
        prompts = self.prompts
        return prompts["chat_fast_reply_prompt"]

    @property
    def chat_slow_reply_prompt(self):
        prompts = self.prompts
        return chat_slow_reply_prompt

    @property
    def coding_prompt(self):
        other_unused_instructions = """
- When you are shown code snippets or functions and their usage example, write code that can be executed for real world use case, fetch real data and write code which can be used directly in production.
- When you write code that needs execution indicate that it needs to be executed by mentioning a comment within code on the first line which say "# execute_code".
- Write actual runnable code when code needs to be executed and convert any pseudo-code or incomplete code (or placeholder) to actual complete executable code with proper and full implementation on each line with proper comments.
- Write code with indicative variable names and comments for better readability that demonstrate how the code is trying to solve our specific use case.
- Do not leak out any other information like OS or system info, file or directories not permitted etc. Do not run system commands or shell commands.
- Do not delete any files.
- Do not use any other libraries other than the ones mentioned above. 
- Code in python and write code in a single cell for code execution tasks.
- Code which doesn't need to be executed or can't be executed within our env should not have "# execute_code" in the first line.
- but ensure that it is safe code that does not delete files or have side effects.
- Write intermediate print statements for executable code to show the intermediate output of the code and help in debugging.
        """
        rules = """
## Rules for writing code (especially code that needs to be executed and run) and making diagrams, designs and plots are given below inside <executable_code_and_diagramming_rules> </executable_code_and_diagramming_rules> tags.
<executable_code_and_diagramming_rules>

**Coding Instructions**
- Only execute code when user explicitly asked to execute code.
- Indicate clearly what python code needs execution by writing the first line of code as '# execute_code'. Write code that needs execution in a single code block.  
- Write python code that needs to be executed only inside triple ticks (```)  write the first line of code that we can execute as '# execute_code'. We can only execute python code.
- Write executable code in case user asks to test already written code which was executable. 
- Write intermediate print statements for executable code to show the intermediate output of the code and help in debugging.
- When writing executable code, write full and complete executable code within each code block even within same message since our code environment is stateless and does not store any variables or previous code/state. 
- You are allowed to read files from the input directory {input_directory} and write files to the output directory {output_directory}. You can also read files from the output directory {output_directory}.
- If you need to download a file from the internet, you can download it to the output directory {output_directory} and then read it in your python code, make sure to mention the file name in comments before you download and store. 
- If asked to read files, only read these filenames from the input directory in our coding environment: {input_files}. This is the only list of files we have for code execution.
- You can use only the following libraries: pandas, numpy, scipy, matplotlib, seaborn, scikit-learn, networkx, pydot, requests, beautifulsoup etc.
- Files like csv, xlsx, xls, tsv, parquet, json, jsonl are data files and can be used in python for data analysis, xls and xlsx can be read with `openpyxl` and pandas and have multiple sheets so analysing xls, xlsx would require looking at all sheets.
- Some numeric columns may be strings in data files where numbers are separated by commas for readability, convert to string column using pandas `df[column_name].astype(str)` then remove commas, then convert them to numeric data before using them.
- Don't execute code unless we have all the files, folders and dependencies in our code environment. Just write the code simply and let user copy-paste and run it. 
- Only execute code when user told to execute code. 

**Diagramming and Plotting Instructions**
- Certain diagrams can be made using mermaid js library as well. First write the mermaid diagram code inside "```mermaid" and "```" triple ticks.
- When you make plots and graphs, save them to the output directory with filename prefix as {plot_prefix} and extension as jpg.
- You can also make diagrams using mermaid js library. You can make Flowcharts, Sequence Diagrams, Gantt diagram, Class diagram, User Journey Diagram, Quadrant Chart, XY Chart.
- You are allowed to make diagrams using draw.io or diagrams.net xml format. Always Write the draw.io xml code inside triple ticks like (```xml <Drawio xml code> ```).
- Use draw.io or diagrams.net to make diagrams like System design diagrams, complex scientific processes, flowcharts, network diagrams, architecture diagrams etc. Always Write the draw.io xml code inside triple ticks like (```xml <Drawio xml code> ```). so that our drawio parser can pick it and draw it.
- Make high quality plots with clear and extensive labels and explanations. Always save your plots to the directory {output_directory} with filename prefix as {plot_prefix}.

**More Coding Instructions**
- Write full and complete executable code since our code environment is stateless and does not store any variables or previous code/state.
- You are allowed to write output to stdout or to a file (in case of larger csv output) with filename prefix as {file_prefix}.
- Convert all pandas dataframe data to pure numpy explicitly before using libraries like scikit-learn, matplotlib and seaborn plotting. Remember to convert the data to numpy array explicitly before plotting.
- Remember to write python code that needs to be executed with first line comment as '# execute_code'. We can only execute python code.
- Ensure that all data is converted to numpy array explicitly before plotting in python. Convert DataFrame columns to numpy arrays for plotting.
- Allowed to read csv, excel, parquet, tsv only.
- Only execute code when asked to execute code. Code which doesn't need to be executed or can't be executed within our env should not have "# execute_code" in the first line.
</executable_code_and_diagramming_rules>

If any pandas data files are given in input folder (our coding environment) then their corresponding preview content is given below.
```plaintext
{input_files_preview}
```

""" + f"\n- {self.date_string}\n"
        return rules


    

    @property
    def date_string(self):
        import datetime
        import calendar
        date = datetime.datetime.now().strftime("%d %B %Y")
        year = datetime.datetime.now().strftime("%Y")
        month = datetime.datetime.now().strftime("%B")
        day = datetime.datetime.now().strftime("%d")
        weekday = datetime.datetime.now().weekday()
        weekday_name = calendar.day_name[weekday]
        time = datetime.datetime.now().strftime("%H:%M:%S")
        return f"The current date is '{date}', year is {year}, month is {month}, day is {day}. It is a {weekday_name}. The current time is {time}."

    

    
    @property
    def web_search_prompt(self):
        import datetime
        date = datetime.datetime.now().strftime("%d %B %Y")
        year = datetime.datetime.now().strftime("%Y")
        month = datetime.datetime.now().strftime("%B")
        day = datetime.datetime.now().strftime("%d")
        web_search_prompt = f"""Your task is to generate web search queries for given question and conversation context.
You are given a question and conversation context as below. {self.date_string} 
Current question: 
'''{{context}}'''

Conversation context:
'''{{doc_context}}'''

Generate web search queries to search the web for more information about the current question. 
If the current question or conversation context requires a date, use the current date provided above. If it is asking for latest information or information for certain years ago then use the current date or the year provided above. 
{{pqs}}
Generate {{n_query}} well specified and diverse web search queries as a valid python list. 

If the current question is a web search query with well defined search filters (like site or before/after or filetype etc) then formulate new queries while keeping the search filters in the new queries as well.

Your output should look like a python list of strings like below example.
Valid python list of web search query strings:
["diverse google search query based on given document", "different_web_query based on the document and conversation", "search engine optimised query based on the question and conversation"]

Few examples are given below.
<example 1>
question:
'''What are the best ways to improve my health?'''

conversation context:
'''I am having bad sleep and feel tired a lot. Doctor suggested to drink lots of water as well.'''

Valid python list of web search query strings:
["how to improve health", "how does drinking more water help improve my body?", "how to improve health and sleep by drinking water and exercising", "Ways to improve cardiovascular health in {year}"]
</example 1>

# Note: Each web search query is different and diverse and focuses on different aspects of the question and conversation context.

<example 2>
question:
'''What are the recent developments in medical research for cancer cure?'''

conversation context:
'''I am working on a new painkiller drug which may help cancer patients and want to know what are the latest trends in the field. I can also use ideas from broader developments in medicine.'''

Valid python list of web search query strings:
["latest discoveries and research in cancer cure in {year}", "latest research works in painkiller for cancer patients in {year}", "Pioneering painkiller research works in {month} {year}.", "Using cancer cure for medical research in {year}"]
</example 2>

# Note: You can use the current date ({date}) and year ({year}) provided in the web search query.

<example 3>
question:
'''What are the emerging trends in AI and large language models?'''

conversation context:
'''I am working on a new language model and want to know what are the latest trends in the field. I can also use ideas from broader developments in AI.'''

Valid python list of web search query strings:
["latest discoveries and research in AI in {year}", "research works in large language models {month} {year}", "Pioneering AI research works which can help improve large language models.", "Using large language models for AI research in {year}"]
</example 3>

# Note: You can use the current date ({date}) and year ({year}) provided in the web search query.

Current question: 
'''{{context}}'''
Output only a valid python list of web search query strings for the current question.
Valid python list of web search query strings:
"""
        return web_search_prompt

    @property
    def web_search_question_answering_prompt(self):
        prompts = self.prompts
        return prompts["web_search_question_answering_prompt"]

    @property
    def get_more_details_prompt(self):
        prompts = self.prompts
        return prompts["get_more_details_prompt"]

    @property
    def document_search_prompt(self):
        prompts = self.prompts
        return prompts["document_search_prompt"]

    @property
    def deep_caption_prompt(self):
        prompt = """
You are an expert at ocr, optical character recognition, text extraction, reading documents, tables, charts, graphs and data oriented images. 
You are able to understand the content of the document, table, chart, graph or image and provide a detailed caption or summary for it. 
You can also extract key information, trends, patterns, and insights from the document, table, chart, graph or image. 
You can also provide a detailed overview, explanation, analysis, description, interpretation, breakdown and summary of the data, trends, patterns, and insights present in the document, table, chart, graph or image. 
You write well and provide detailed, informative and insightful captions, summaries and explanations.

Given a general image, document, table, chart, graph or data oriented image, write a detailed caption or summary for it in the below format. Under possible_questions_users_may_ask_about_image_and_answer tag write questions and answers which are not covered under key insights, analysis, detailed_caption, structure_and_format, detailed_ocr_results, patterns_and_trends, summary, objects_in_image, insights, domain_of_image tags.
OCR the image, extract text, tables, data, charts or plot information or any other text.
Format to reply about the image is given below in xml format. Please use this format to reply about the image.
<image_details>
    <ocr>ocr results and extracted text from the image here if image has any text or numbers or symbols etc. Give structured output in markdown format.</ocr>
    <detailed_caption>caption for the image here</detailed_caption>
    <structure_and_format>geometric structure, patterns, shape details and format of the image here. If diagram then describe the various components of the diagram and how they are connected or interact.</structure_and_format>
    <key_insights>
        // Five key insights, trends, patterns, observations, and information extracted from the image here.
        <insight>key insight 1</insight>
        <insight>key insight 2</insight>
        <insight>key insight 3</insight>
        <insight>key observations 4</insight>
        <insight>relevant and important information extracted 5</insight>
    </key_insights>
    <patterns_and_trends>time series patterns, graph or chart patterns, trends, and information extracted from the image here</patterns_and_trends>
    <objects_in_image>objects, entities, and elements present in the image and their relative locations in the image.</objects_in_image>
    <detailed_insights>Insights, observations, and conclusions drawn from the image here. More depth and thoughts than key insights.</detailed_insights>
    <domain_of_image>domain or category of the image here like medical, general, science, table, pdf, scenic, data, charts, plots or graphs</domain_of_image>
    <possible_questions_users_may_ask_about_image_and_answer>
        <question>possible question 1</question>
        <answer>answer to possible question 1</answer>
        <question>possible question 2</question>
        <answer>answer to possible question 2</answer>
        <question>possible question 3</question>
        <answer>answer to possible question 3</answer>
        <question>possible question 4</question>
        <answer>answer to possible question 4</answer>
        <question>possible question 5</question>
        <answer>answer to possible question 5</answer>
    </possible_questions_users_may_ask_about_image_and_answer>
</image_details>

Reply with above format about the image given below.
Answer in xml format about the image:
"""
        return prompt

    def deep_caption_prompt_with_query(self, query):
        prompt = f"""{self.deep_caption_prompt}

Next answer the user's query given below about the image by looking at the image itself as well as the extracted details from xml.
Conversation Details and User's query:
'''{query}'''

First extract all details from the given image using xml format then answer the user's query inside <answer> </answer> tags.
Answer in xml format about the image followed by the answer to the user's query:
"""
        return prompt


prompts = CustomPrompts(os.environ.get("LLM_FAMILY", "gpt4"), os.environ.get("ROLE", "science"))

import xml.etree.ElementTree as ET


def xml_to_dict(xml_string):
    try:
        root = ET.fromstring(xml_string)
    except ET.ParseError:
        return "Invalid XML: Check if every opening tag has a corresponding closing tag."

    def parse_element(element):
        # Check if element has text content and is not None
        if element.text is not None:
            text = element.text.strip()
            # Convert yes/no to Boolean
            if text.lower() in ["yes", "no", "true", "false"]:
                return text.lower() == "yes" or text.lower() == "true"
                # Try converting text to float or int if possible
            try:
                return int(text)
            except ValueError:
                try:
                    return float(text)
                except ValueError:
                    return text
        else:
            # Return None if element has no text content
            return None

    def parse_list_elements(element):
        # Parse elements that should be lists
        result = []
        for subchild in element:
            if subchild.tag == "document_query":
                sub_result = {}
                for item in subchild:
                    sub_result[item.tag] = parse_element(item)
                result.append(sub_result)
            else:
                result.append(parse_element(subchild))
        return result

    def parse_nested_elements(element):
        # Parse nested elements and return a dictionary
        return {subchild.tag: parse_element(subchild) for subchild in element}

    result_dict = {}
    for child in root:
        if child.tag in ["web_search_queries", "document_search_queries", "documents_to_read"]:
            result_dict[child.tag] = parse_list_elements(child)
        elif child.tag == "suggested_diagram_type":
            result_dict[child.tag] = parse_nested_elements(child)
        else:
            result_dict[child.tag] = parse_element(child)

    return result_dict

"""
6. **Applicability and Real-World Impact:**  
   - Evaluate the potential real-world applications and impact of each idea in solving practical problems.  
   - Consider the scalability and generalizability of the proposed methods to real-world scenarios.  
   - Assess the potential for the idea to be adopted and used by practitioners and industry professionals.  
   - Idea 1 Score: [Insert score]    
   - Idea 2 Score: [Insert score]    
   - [Provide a brief justification for the scores]  
   
11. **Potential for Follow-up Work:**  
    - Evaluate the potential for follow-up work and future research directions based on each idea.  
    - Consider the depth and breadth of the research questions that can be explored as a result of pursuing each idea.  
    - Assess the potential for the idea to inspire new research avenues and attract the interest of other researchers in the field.  
    - Assess the potential for future research stemming from each idea. What new questions or avenues does it open?  
    - Evaluate how the idea contributes to the advancement of the field.  
    - Idea 1 Score: [Insert score]    
    - Idea 2 Score: [Insert score]    
    - [Provide a brief justification for the scores]  
    
16. **Clarity of Problem Statement:**  
    - Assess how clearly the problem is articulated. Is the motivation behind the research easy to understand?  
    - Evaluate the significance of the problem. Does the proposal convincingly argue why this problem is important?  
    - **Reviewer Influence:** A poorly defined problem statement can lead to confusion and skepticism among reviewers.  
    - Idea 1 Score: [Insert score]    
    - Idea 2 Score: [Insert score]    
    - [Provide a brief justification for the scores]  
  
17. **Proposed Methodology:**  
    - Evaluate the soundness and innovation of the proposed methodology. Are the techniques well-justified?  
    - Consider the novelty of the proposed methodology and its potential to advance the state-of-the-art. Is the proposed methodology just a simple extension of existing methods?
    - Consider whether the methodology is appropriate for the problem being addressed.  
    - **Reviewer Influence:** Reviewers may question the validity of the methodology if it lacks rigor or if alternative approaches are not adequately considered.  
    - Idea 1 Score: [Insert score]    
    - Idea 2 Score: [Insert score]    
    - [Provide a detailed and exhaustive justification for the scores]  
"""