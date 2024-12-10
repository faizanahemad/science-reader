import os
from copy import deepcopy

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
5. Output any relevant equations in latex format putting each equation in a new line in separate '$$' environment. For inline maths and notations use "\\\( ... \\\)" instead of '$$'.

Remember the '2) Proposed Solution' section must be detailed, comprehensive and in-depth covering all details. Section 2 must cover all about the methodology and the approach used in the paper, and why it is important and needed and how it improves over previous work.\n""".lstrip()

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
   - Output any relevant equations in latex format putting each equation in a new line in separate '$$' environment. For inline maths and notations use "\\\( ... \\\)" instead of '$$'.

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
   
Output any relevant equations in latex format putting each equation in a new line in separate '$$' environment. For inline maths and notations use "\\\( ... \\\)" instead of '$$'.

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
   
Output any relevant equations in latex format putting each equation in a new line in separate '$$' environment. For inline maths and notations use "\\\( ... \\\)" instead of '$$'.

Write your denser summary below:
""".lstrip()

class CustomPrompts:
    def __init__(self, llm, role):
        self.llm = llm
        self.role = role
        # TODO: decide on role prefixes needed or not.
        # 4. Provide code in python if asked for code or implementation.
        # Use markdown formatting to typeset and format your answer better.
        self.complex_output_instructions = """Use the below rules while providing response.
1. Use markdown lists and paragraphs for formatting.
2. Output any relevant equations in latex format putting each equation in a new line in separate '$$' environment. For inline maths and notations use "\\\( ... \\\)" instead of '$$'.
3. Provide references or links within the answer inline itself immediately closest to the point of mention or use. Provide references in a very compact format."""

        self.simple_output_instructions = """Use the below rules while providing response.
1. Use markdown lists and paragraphs for formatting.
2. Provide references within the answer inline itself immediately closest to the point of mention or use. Provide references in a very compact format."""
        self.gpt4_prompts = dict(
            short_streaming_answer_prompt=f"""Answer the question or query given below using the given context (text chunks of larger document) as a helpful reference. 
Question or Query is given below.
<|query|>
{{query}}
<|/query|>

<|document|>
Summary of the document is given below:

{{full_summary}}
Few text chunks from the document to answer the question below:
'''{{fragment}}'''
<|/document|>

Write informative, comprehensive and detailed answer below.
""",
            retrieve_prior_context_prompt="""You are given conversation details between a human and an AI. Based on the given conversation details and human's last response or query we want to search our database of responses.
You will generate a contextualised query based on the given conversation details and human's last response or query. The query should be a question or a statement that can be answered by the AI or by searching in our semantic database.
Ensure that the rephrased and contextualised version is different from the original query.
The summary of the conversation is as follows:
{requery_summary_text}

The last few messages of the conversation are as follows:
{previous_messages}

The last message of the conversation sent by the human is as follows:
{query}

Rephrase and contextualise the last message of the human as a question or a statement using the given previous conversation details so that we can search our database.
Rephrased and contextualised human's last message:
""",

            persist_current_turn_prompt="""You are given conversation details between a human and an AI. You are also given a summary of how the conversation has progressed till now. 
You will write a new summary for this conversation which takes the last 2 recent messages into account. 
You will also write a very short title for this conversation.

Capture the salient, important and noteworthy aspects and details from the user query and system response in your summary. 
Your summary should be detailed, comprehensive and in-depth.
Capture all important details in your conversation summary including factual details, names and other details mentioned by the human and the AI. 
Preserve important details that have been mentioned in the previous summary especially including factual details and references while adding more details from current user query and system response.
Write down any special rules or instructions that the AI assistant should follow in the conversation as well in the summary.

The previous summary and salient points of the conversation is as follows:
'''{previous_summary}'''

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
<summary> {{Detailed Conversation Summary with salient, important and noteworthy aspects and details.}} </summary>
<title> {{Very short title for the conversation}} </title>

We only write very short and relevant title inside <title> </title> tags.
Write the summary inside <summary> </summary> tags.

Write a title and summary of the conversation using the previous summary, previous messages and the last 2 recent messages. Please summarize the conversation very informatively, in detail and depth.

Conversation Summary and title in xml style format:
""",


            chat_slow_reply_prompt=f"""You are given conversation details between human and AI. We will be replying to the user's query or message given.
{self.complex_output_instructions}

Today's date is:
{self.date_string}

Answer the user's query or message using the following information:

{{conversation_docs_answer}}{{doc_answer}}{{web_text}}{{link_result_text}}
{{summary_text}}
{{permanent_instructions}}
<|previous_messages|>
{{previous_messages}}
<|/previous_messages|>


The most recent message of the conversation sent by the user now to which we will be replying is given below.
user's most recent message:
<|user_message|>
<most_recent_user_message>
{{query}}
</most_recent_user_message>
<|/user_message|>

Response to the user's query:
<|assistant_response|>
""",

            web_search_question_answering_prompt=f"""<task>Your role is to provide an answer to the user question incorporating the additional information you are provided within your response.</task>
Question is given below:
"{{query}}"
Relevant additional information with url links, titles and document context are mentioned below:
"{{additional_info}}"

Continue the answer ('Answer till now' if it is not empty) by incorporating additional information from other documents. 
Answer by thinking of Multiple different angles that 'the original question or request' can be answered with. Focus mainly on additional information from other documents. Provide the link and title before using their information in markdown format (like `[title](link) information from document`) for the documents you use in your answer.

{self.complex_output_instructions}
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
{self.complex_output_instructions}

Continue the answer using additional information from the documents.
""",
            paper_details_map = {
            "methodology": """
Read the document and provide information about "Motivation and Methodology" of the work.
Cover the below points while answering and also add other necessary points as needed.
    - What do the authors do in this overall work (i.e. their methodology) with details, include all aspects of their methodology, provide comprehensive details and go deep into their work.
    - Detailed methodology and approach described in this work.
    - what problem do they address ?
    - how do they solve the problem, provide details?
    - Why do they solve this particular problem?
    - what is their justification in using this method? Why do they use this method? 
    - What mathematical formulations or equations are used in the work, their meaning and justification?
    - Is the proposed methodology just a simple extension of existing methods?
    
Writing Instructions:
- Write fully formed sentences and paragraphs with complete thoughts for ease of reading.
- Write in a friendly and engaging tone in full sentences.
- Be detail oriented and provide all necessary information.
- Focus on readability, clarity and informativeness.
- Output any relevant equations in latex format putting each equation in a new line in separate '$$' environment. For inline maths and notations use "\\\( ... \\\)" instead of '$$'.
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
- Output any relevant equations in latex format putting each equation in a new line in separate '$$' environment. For inline maths and notations use "\\\( ... \\\)" instead of '$$'.
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
- Output any relevant equations in latex format putting each equation in a new line in separate '$$' environment. For inline maths and notations use "\\\( ... \\\)" instead of '$$'.
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
- Output any relevant equations in latex format putting each equation in a new line in separate '$$' environment. For inline maths and notations use "\\\( ... \\\)" instead of '$$'.
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
- Output any relevant equations in latex format putting each equation in a new line in separate '$$' environment. For inline maths and notations use "\\\( ... \\\)" instead of '$$'.
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
    def short_streaming_answer_prompt(self):
        prompts = self.prompts
        return prompts["short_streaming_answer_prompt"]


    @property
    def retrieve_prior_context_prompt(self):
        prompts = self.prompts
        return prompts["retrieve_prior_context_prompt"]

    @property
    def persist_current_turn_prompt(self):
        prompts = self.prompts
        return prompts["persist_current_turn_prompt"]


    @property
    def chat_fast_reply_prompt(self):
        prompts = self.prompts
        return prompts["chat_fast_reply_prompt"]

    @property
    def chat_slow_reply_prompt(self):
        prompts = self.prompts
        return prompts["chat_slow_reply_prompt"]

    @property
    def coding_prompt(self):
        other_unused_instructions = """
- When you are shown code snippets or functions and their usage example, write code that can be executed for real world use case, fetch real data and write code which can be used directly in production.
- When you write code that needs execution indicate that it needs to be executed by mentioning a comment within code which say "# execute_code".
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
- Certain diagrams can be made using mermaid js library as well. First write the mermaid diagram code inside <pre class="mermaid"> and </pre> tags.
- When you make plots and graphs, save them to the output directory with filename prefix as {plot_prefix} and extension as jpg.
- You can also make diagrams using mermaid js library. You can make Flowcharts, Sequence Diagrams, Gantt diagram, Class diagram, User Journey Diagram, Quadrant Chart, XY Chart. Write the diagram code inside <pre class="mermaid"> and </pre> tags so that our mermaid parser can pick it and draw it.
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
    def query_is_answered_by_search(self):
        """"""
        import datetime
        date = datetime.datetime.now().strftime("%d %B %Y")
        year = datetime.datetime.now().strftime("%Y")
        month = datetime.datetime.now().strftime("%B")
        day = datetime.datetime.now().strftime("%d")
        import re

        def parse_llm_output(llm_output):
            # Initialize a dictionary to hold the parsed data
            parsed_data = {
                "thoughts": None,
                "answered_already_by_previous_search": None,
                "web_search_needed": None,
                "web_search_queries": []
            }

            # Define regex patterns for extracting information
            thoughts_pattern = r"<thoughts>(.*?)</thoughts>"
            answered_already_pattern = r"<answered_already_by_previous_search>(.*?)</answered_already_by_previous_search>"
            web_search_needed_pattern = r"<web_search_needed>(.*?)</web_search_needed>"
            web_search_queries_pattern = r"<query>(.*?)</query>"

            # Extract information using regex
            thoughts_match = re.search(thoughts_pattern, llm_output, re.DOTALL)
            answered_already_match = re.search(answered_already_pattern, llm_output, re.DOTALL)
            web_search_needed_match = re.search(web_search_needed_pattern, llm_output, re.DOTALL)
            web_search_queries_matches = re.findall(web_search_queries_pattern, llm_output, re.DOTALL)

            # Update the dictionary with the extracted information
            if thoughts_match:
                parsed_data["thoughts"] = thoughts_match.group(1).strip()
            if answered_already_match:
                parsed_data["answered_already_by_previous_search"] = answered_already_match.group(
                    1).strip().lower() == "yes"
            if web_search_needed_match:
                parsed_data["web_search_needed"] = web_search_needed_match.group(1).strip().lower() == "yes"
            if web_search_queries_matches:
                parsed_data["web_search_queries"] = [query.strip() for query in web_search_queries_matches]

            return parsed_data

        prompt = f"""You are an expert AI system which determines whether our search results are useful and can answer a user query or not. If our search results can't answer the user query satisfactorily then you will decide if we need to do more web search and write two new web search queries for performing search again.
If our search results answer the query nicely and satisfactorily then <answered_already_by_previous_search> will be yes. If our search queries are sensible and work well to represent what should be searched then <answered_already_by_previous_search> will be yes. 
Usually our searches work well and we don't need to do more web search and <web_search_needed> will be no. Decide to do further web search only if absolutely needed and if our queries are not related or useful for user message. Mostly put <web_search_needed> as no.
{self.date_string} 

Previous web search queries are given below (empty if no web search done previously):
'''{{previous_web_search_queries}}'''

Previous web search results are given below (empty if no web search done previously):
'''{{previous_web_search_results}}'''

Previous web search results text is given below:
'''{{previous_web_search_results_text}}'''

Conversation context:
'''{{context}}'''

Current user message is given below: 
'''{{query}}'''

# Note: You can use the current date ({date}) and year ({year}) in the web search queries that you write. If our search queries are sensible and correct for user message and work well to represent what should be searched then <answered_already_by_previous_search> will be yes and <web_search_needed> will be no.

Output Template for our decision planner xml is given below.
<planner>
    <thoughts>Your thoughts in short on whether the previous web search queries and previous web search results are sufficient to answer the user message written shortly.</thoughts>
    <answered_already_by_previous_search>no</answered_already_by_previous_search>
    <web_search_needed>yes/no</web_search_needed>
    <web_search_queries>
        <query>web search query 1</query>
        <query>web search query 2 with year ({year}) or date ({date}) if needed</query>
    </web_search_queries>
</planner>

<web_search_queries> will be empty if no web search is needed, and not needed in the planner xml at all.

planner xml template if the user query is already answered by previous search:
<planner>
    <thoughts>Your thoughts on how the web search queries and previous web search results are sufficient to answer the user message.</thoughts>
    <answered_already_by_previous_search>yes</answered_already_by_previous_search>
    <web_search_needed>no</web_search_needed>
    <web_search_queries></web_search_queries>
</planner>

Write your output decision in the above planner xml format.
"""
        return prompt, parse_llm_output

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
    def planner_checker_prompt_explicit(self):
        # TODO: Fire web search and document search prior to planner for speed.
        import datetime
        year = datetime.datetime.now().strftime("%Y")
        web_search_prompt = f"""You are an expert AI assistant who decides what plan to follow to best answer to a user's message. You are able to determine which functions to call (function calling and tool usage) and what plan to use to best answer a query and help an user.
{self.date_string}
Now based on given user message and conversation context we need to decide a plan of execution to best answer the user's query in the planner xml format given below.

Planner rules:
- Inside need_finance_data tag, you will write yes if the user message needs finance data, stocks data or company data to answer the query. This will be needed for questions which need financial data or stock market or historical market data or company financial results or fund house data to answer them.
- Inside need_diagram tag, you will write yes if a diagram is asked explicitly in the user message. This will be needed if user has explicitly asked us to draw a diagram or plot or graph or show something that can be shown via drawing/charting/plotting/graphing/visualization.
- Inside code_execution tag, you will write yes if python code execution or data analysis or matplotlib/seaborn is asked explicitly in the user message. Code execution is needed when user asks data analysis results or plotting or diagraming of specific types with python. This will be needed if user has explicitly asked us to write python code.
- Inside code_execution tag, you will write no if user has asked for code but did not ask to execute the code or user did not ask for data analysis or python plotting.
- Inside web_search_needed tag, you will write yes if asked explicitly for web search or google search in the user message. This will be needed if user has explicitly asked us to do web search. If user has not asked for web search then put web search needed as no.
- Inside read_uploaded_document tag, you will write yes if we need to read any uploaded document given under 'Available Document Details' to answer the user query. This will be needed if user has uploaded a document relevant to this current user message and we need to read that particular document to answer the query.
- When user wants to refer to a particular document themselves they write as 'refer to document #doc_id' or 'refer to document titled "title of document"'. For example - "Summarise #doc_1" means we need to read the uploaded #doc_1 and summarise it. So read_uploaded_document will be yes, and within document_search_queries we will write <document_query><document_id>#doc_1</document_id><query>Summarise this document.</query></document_query>.
- User may also refer to uploaded docs by title or by their short names. Look at Previous User Messages as well to understand if current user message refers to any document in a hidden way.
- Sometimes the user may have referred to document title or document id as #doc_id in previous messages instead of the current user message. Infer the document id or title from the previous messages and write the document id or title in the document_query.
Your output should look be a valid xml tree with our plan of execution like below example format.
<planner>
    <domain>Science</domain>
    <need_finance_data>yes/no</need_finance_data>
    <need_diagram>yes/no</need_diagram>
    <code_execution>yes/no</code_execution>
    <web_search_needed>yes/no</web_search_needed>
    <web_search_type>general/academic</web_search_type>
    <web_search_queries>
        <query>diverse google search query based on given user message with year ({year}) if recent results are important.</query>
        <query>different_web_query based on the user message and conversation</query>
        <query>search engine optimised query based on the question and conversation</query>
        <query>search query based on the question and conversation</query>
    </web_search_queries>
    <read_uploaded_document>yes/no</read_uploaded_document>
    <document_search_queries>
        <document_query><document_id>#doc_2</document_id><query>What is the methodology</query></document_query>
        <document_query><document_id>#doc_3</document_id><query>What are the results</query></document_query>
        <document_query><document_id>#doc_3</document_id><query>What are the datasets used?</query></document_query>
    </document_search_queries>
</planner>

<document_search_queries> will be empty and not needed in the planner xml at all if no documents are uploaded or no documents need to be read.
<web_search_queries> will be empty if no web search is needed, and not needed in the planner xml at all.
<web_search_type> will not be needed in the planner xml if web search is not needed.
Example of how planner xml looks like if both web search is not needed and document search is not needed.
<planner>
    <domain>Identified Domain</domain>
    <need_finance_data>yes/no</need_finance_data>
    <need_diagram>yes/no</need_diagram>
    <code_execution>yes/no</code_execution>
    <web_search_needed>no</web_search_needed>
    <read_uploaded_document>no</read_uploaded_document>
</planner>

Web search type can be general or academic. If the question is looking for general information then choose general web search type. If the question is looking for academic or research papers then choose academic as web search type.
Generate 4 well specified and diverse web search queries if web search is needed. Include year and date in web search query if it needs recent, up to date or latest information.
<need_finance_data> will be yes if user message needs finance historical data, stocks historical data or stock market daily data like price and volume or company financial and quarterly/annual reports data to answer the query. This will be needed for questions which need financial data or stock market or historical market data or company financial results or fund house data to answer them.
<need_finance_data> will be no if it is a finance question but doesn't need any finance data or stock market data to answer the query, like asking for book recommendations or asking for finance concepts or definitions, doesn't need finance data so <need_finance_data> will be no.
<read_uploaded_document> could be yes if this current user message or any previous user message refers to an uploaded document and current message is asking indirectly about the uploaded document with phrases like "how does the work ... " or "what are their unqiue contributions?" etc. Here you need to infer document id or title from the previous messages and write the document id in the document_query.
List of possible domains:
- None
- Science
- Arts
- Health
- Psychology
- Finance
- Stock Market, Trading & Investing
- Mathematics
- QnA
- AI
- Software


Choose Domain as None if the user message query doesn't fit into any of the other domains.
{{permanent_instructions}}

If we have any documents uploaded then you will be given the document id, title and context so that you can decide if we need to read the document or not under read_uploaded_document.
Available Document Details (empty if no documents are uploaded, for read_uploaded_document is
'''{{doc_details}}'''

Conversation context and summary:
'''{{summary_text}}'''

Previous User Messages:
'''{{previous_messages}}'''


Current user message: 
'''{{context}}'''

Valid xml planner tree with our reasons and decisions:
"""
        return web_search_prompt

    @property
    def planner_checker_prompt_short(self):
        # TODO: Fire web search and document search prior to planner for speed.
        import datetime
        date = datetime.datetime.now().strftime("%d %B %Y")
        year = datetime.datetime.now().strftime("%Y")
        month = datetime.datetime.now().strftime("%B")
        day = datetime.datetime.now().strftime("%d")
        web_search_prompt = f"""You are an expert AI assistant who decides what plan to follow to best answer to a user's message and then answers the user's message if needed by themselves. You are able to determine which functions to call (function calling and tool usage) and what plan to use to best answer a query and help an user.
{self.date_string}

Now based on given user message and conversation context we need to decide a plan of execution to best answer the user's query in the planner xml format given below.

Planner rules:
- Inside need_finance_data tag, you will write yes if the user message needs finance data, stocks data or company data to answer the query. This will be needed for questions which need financial data or stock market or historical market data or company financial results or fund house data to answer them.
- Inside need_diagram tag, you will write yes if a diagram is needed for clear explanation or asked explicitly in the user message. This will be needed for questions which need a diagram for clear explanation or if user has explicitly asked us to draw a diagram or plot or graph.
- Inside code_execution tag, you will write yes if python code execution or data analysis or matplotlib/seaborn is really needed or asked explicitly in the user message. Data analysis and plotting may also be needed for finance data use cases or when user asks plotting or diagramming of specific types with python. This will be needed for questions which need python code execution or data analysis or matplotlib plot or if user has explicitly asked us to write python code.
- Inside code_execution tag, you will write no if user has asked for code or about python code but we don't need to execute code to answer the user query.
- Inside web_search_needed tag, you will write yes if web search is needed for clear explanation or asked explicitly in the user message. This will be needed for questions which need web search for clear explanation, or questions needs recent updated information or if user has explicitly asked us to do web search. Web search takes extra time and user has to wait for the answer so if an LLM or you can answer well without web search then put web search needed as no.

Your output should look be a valid xml tree with our plan of execution like below example format.
<planner>
    <domain>Science</domain>
    <need_finance_data>yes/no</need_finance_data>
    <need_diagram>yes/no</need_diagram>
    <code_execution>yes/no</code_execution>
    <web_search_needed>yes/no</web_search_needed>
    <web_search_type>general/academic</web_search_type>
    <web_search_queries>
        <query>diverse google search query based on given user message with year ({year}) if recent results are important.</query>
        <query>different_web_query based on the user message and conversation</query>
        <query>search engine optimised query based on the question and conversation</query>
        <query>search query based on the question and conversation</query>
    </web_search_queries>
    <read_uploaded_document>yes/no</read_uploaded_document>
    <document_search_queries>
        <document_query><document_id>#doc_2</document_id><query>What is the methodology</query></document_query>
        <document_query><document_id>#doc_3</document_id><query>What are the results</query></document_query>
        <document_query><document_id>#doc_3</document_id><query>What are the datasets used?</query></document_query>
    </document_search_queries>
</planner>

<document_search_queries> will be empty and not needed in the planner xml at all if no documents are uploaded or no documents need to be read.
<web_search_queries> will be empty if no web search is needed, and not needed in the planner xml at all.
<web_search_type> will not be needed in the planner xml if web search is not needed.
Example of how planner xml looks like if both web search is not needed and document search is not needed.
<planner>
    <domain>Identified Domain</domain>
    <need_finance_data>yes/no</need_finance_data>
    <need_diagram>yes/no</need_diagram>
    <code_execution>yes/no</code_execution>
    <web_search_needed>no</web_search_needed>
    <read_uploaded_document>no</read_uploaded_document>
</planner>

web_search will usually be yes if we have not done any web search previously or if the question is looking for latest information that an LLM can't answer. For programming framework help or general knowledge questions we may not need to do web search always but for frameworks or programming questions where we are not certain if you can answer by yourself then perform web search.
Web search type can be general or academic. If the question is looking for general information then choose general web search type. If the question is looking for academic or research papers then choose academic as web search type.
Generate 4 well specified and diverse web search queries if web search is needed. Include year and date in web search query if it needs recent, up to date or latest information.
We keep important factual information in short form in our memory pad. use_memory_pad will be yes if we need to use some information from the memory pad for better answering. This will generally be needed for questions which need facts to answer them and those facts are part of our conversation earlier.
<need_finance_data> will be yes if user message needs finance historical data, stocks historical data or stock market daily data like price and volume or company financial and quarterly/annual reports data to answer the query. This will be needed for questions which need financial data or stock market or historical market data or company financial results or fund house data to answer them.
<need_finance_data> will be no if it is a finance question but doesn't need any finance data or stock market data to answer the query, like asking for book recommendations or asking for finance concepts or definitions, doesn't need finance data so <need_finance_data> will be no.

List of possible domains:
- None
- Science
- Arts
- Health
- Psychology
- Finance
- Stock Market, Trading & Investing
- Mathematics
- QnA
- AI
- Software


Choose Domain as None if the user message query doesn't fit into any of the other domains.
{{permanent_instructions}}

If we have any documents uploaded then you will be given the document id, title and context so that you can decide if we need to read the document or not.
Available Document Details (empty if no documents are uploaded, for read_uploaded_document is
'''{{doc_details}}'''

Conversation context and summary:
'''{{summary_text}}'''

Previous User Messages:
'''{{previous_messages}}'''


Current user message: 
'''{{context}}'''

Valid xml planner tree with our reasons and decisions:
"""
        return web_search_prompt

    @property
    def planner_checker_prompt(self):
        # TODO: Fire web search and document search prior to planner for speed.
        import datetime
        date = datetime.datetime.now().strftime("%d %B %Y")
        year = datetime.datetime.now().strftime("%Y")
        month = datetime.datetime.now().strftime("%B")
        day = datetime.datetime.now().strftime("%d")
        web_search_prompt = f"""You are an expert AI assistant who decides what plan to follow to best answer to a user's message and then answers the user's message if needed by themselves. You are able to determine which functions to call (function calling and tool usage) and what plan to use to best answer a query and help an user.
{self.date_string}

Now based on given user message and conversation context we need to decide a plan of execution to best answer the user's query in the planner xml format given below.

Your output should look be a valid xml tree with our plan of execution like below example format.
<planner>
    <domain>Science</domain>
    <is_question_about_finance_stocks_mutual_fund_etf>yes/no<is_question_about_finance_stocks_mutual_fund_etf>
    <company_stock_fund_etf_name>company_ticker</company_stock_fund_etf_name>
    <is_diagram_needed_for_clear_explanation_or_asked_explicitly>yes/no</is_diagram_needed_for_clear_explanation_or_asked_explicitly>
    <suggested_diagram_type>
        <diagram_type>What type of diagram best explains what is asked or needed by user.</diagram_type>
        <drawing_library>Which Library from among mermaid js, draw.io (diagrams.net) xml, or python matplotlib/seaborn code is to be used</drawing_library>
    </suggested_diagram_type>
    <python_code_execution_or_data_analysis_or_matplotlib_needed_or_asked_explicitly>yes/no</python_code_execution_or_data_analysis_or_matplotlib_needed_or_asked_explicitly>
    <use_memory_pad>no</use_memory_pad>
    <web_search_needed_for_clear_explanation_or_asked_explicitly>yes/no</web_search_needed_for_clear_explanation_or_asked_explicitly>
    <web_search_type>general</web_search_type>
    <web_search_queries>
        <query>diverse google search query based on given document</query>
        <query>different_web_query based on the document and conversation</query>
        <query>search engine optimised query based on the question and conversation</query>
        <query>search query based on the question and conversation</query>
    </web_search_queries>
    <read_uploaded_document>yes/no</read_uploaded_document>
    <document_search_queries>
        <document_query><document_id>#doc_2</document_id><query>What is the methodology</query></document_query>
        <document_query><document_id>#doc_3</document_id><query>What are the results</query></document_query>
        <document_query><document_id>#doc_3</document_id><query>What are the datasets used?</query></document_query>
    </document_search_queries>
</planner>

<document_search_queries> will be empty if no documents are uploaded or no documents need to be read.
<web_search_queries> will be empty if no web search is needed.
web_search will usually be yes if we have not done any web search previously or if the question is looking for latest information that an LLM can't answer. For programming framework help or general knowledge questions we may not need to do web search always but for frameworks or programming questions where we are not certain if you can answer by yourself then perform web search.
Web search type can be general or academic. If the question is looking for general information then choose general web search type. If the question is looking for academic or research papers then choose academic as web search type.
Generate 4 well specified and diverse web search queries if web search is needed. 
We keep important factual information in short form in our memory pad. use_memory_pad will be yes if we need to use some information from the memory pad for better answering. This will generally be needed for questions which need facts to answer them and those facts are part of our conversation earlier.

Possible Domains:
- None
- Science
- Arts
- Health
- Psychology
- Finance
- Mathematics
- QnA
- AI
- Software

Choose Domain as None if the user message query doesn't fit into any of the other domains.
{{permanent_instructions}}

If we have any documents uploaded then you will be given the document id, title and context so that you can decide if we need to read the document or not.
Available Document Details (empty if no documents are uploaded, for read_uploaded_document is
'''{{doc_details}}'''

Conversation context and summary:
'''{{summary_text}}'''

Previous User Messages:
'''{{previous_messages}}'''


Current user message: 
'''{{context}}'''

Valid xml planner tree with our reasons and decisions:
"""
        return web_search_prompt

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
        if child.tag in ["web_search_queries", "document_search_queries"]:
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