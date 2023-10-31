import os
from copy import deepcopy

from langchain.prompts import PromptTemplate

class CustomPrompts:
    def __init__(self, llm, role):
        self.llm = llm
        self.role = role
        # TODO: decide on role prefixes needed or not.
        # 4. Provide code in python if asked for code or implementation.
        # Use markdown formatting to typeset and format your answer better.
        self.complex_output_instructions = """Use the below rules while providing response.
1. Use markdown for formatting. Use lists and paragraphs. Take a deep breath, then brainstorm and muse around creatively before writing your answer.
2. Output any relevant equations in latex format putting each equation in a new line in separate '$$' environment.
3. Provide references or links within the answer inline itself immediately closest to the point of mention or use. Provide references in a very compact format.
4. Answer the question with creativity and deep insight as well as you can with your own knowledge. You are a insightful, thoughtful and creative expert in the domain of the user query."""

        self.simple_output_instructions = """Use the below rules while providing response.
1. Use markdown for formatting. Use lists and paragraphs.
2. Provide references within the answer inline itself immediately closest to the point of mention or use. Provide references in a very compact format."""
        self.gpt4_prompts = dict(
            streaming_followup=PromptTemplate(
                input_variables=["followup", "query", "answer", "fragment", "summary", "full_summary",
                                 "questions_answers"],
                template=f"""Provide answer to a follow up question which is based on an earlier question. Answer the followup question or information request from context (text chunks of larger document) you are provided. 
Followup question or information request is given below.
"{{followup}}"

Summary of the document is given below.
"{{full_summary}}"

Few text chunks from within the document to answer this follow up question as below.
"{{fragment}}"

Few question and answer pairs from the document are given below.
"{{questions_answers}}"

Summaries of certain parts of document below:
"{{summary}}"

Previous question or earlier question and its answer is provided below:

Earlier Question: "{{query}}"

Earlier Answer:
"{{answer}}"

Keep the earlier question in consideration while answering.
{self.complex_output_instructions}

Current Question: {{followup}}
Answer: 
""",
            ),
            short_streaming_answer_prompt=PromptTemplate(
                input_variables=["query", "fragment", "summary", "questions_answers", "full_summary"],
                template=f"""Answer the question or information request given below using the given context (text chunks of larger document) as a helpful reference. 
Question or Query is given below.
{{query}}
{{full_summary}}
Few text chunks from the document to answer the question below:
'''{{fragment}}'''
{{questions_answers}}
{{summary}}

{self.complex_output_instructions}

Question or Query is given below.
{{query}}

Write informative answer below.
""",
            ),
            running_summary_prompt=PromptTemplate(
                input_variables=["summary", "document", "previous_chunk_summary"],
                template=f"""We are reading a large document in fragments sequentially to write a continuous summary.
'''{{document}}'''
{{previous_chunk_summary}}
{{summary}}
Instructions for this summarization task as below:
- Ignore references.
- Provide detailed, comprehensive, informative and in-depth response.
- Include key experiments, experimental observations, results and insights.
- Use markdown for formatting. Use lists and paragraphs.

Summary:
""",
            ),
            retrieve_prior_context_prompt=PromptTemplate(
                input_variables=["requery_summary_text", "previous_messages", "query"],
                template="""You are given conversation details between a human and an AI. Based on the given conversation details and human's last response or query we want to search our database of responses.
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
"""
            ),
            long_persist_current_turn_prompt=PromptTemplate(
                input_variables=["previous_messages", "previous_summary", "older_summary"],
                template="""You are given conversation details between a human and an AI. You will summarise the conversation provided below.
The older summary of the conversation is as follows:
'''{older_summary}'''

The recent summary of the conversation is as follows:
'''{previous_summary}'''

The last few messages of the conversation from which we will derive the summary are as follows:
'''
{previous_messages}
'''
             
Please summarize the conversation very informatively, in great detail and depth. Your summary should be detailed, comprehensive, thoughtful, insightful, informative, and in-depth. Ensure you capture all nuances and key points from the dialogue. Capture all essential details mentioned by both user and assistant.

Format your summary using markdown, starting with a long comprehensive overview paragraph. Follow this with in depth bullet points with good detailing highlighting about all the details of the conversation. Finally, conclude with an extensive final remark about the overall conversation including any plans or action items. Mention all solutions, suggestions, references, methods and techniques we discussed in depth and proper detail. Capture any solutions, ideas, thoughts, suggestions, action items we had discussed in depth and comprehensively.

Prioritise clarity, informativeness, wide coverage, density and depth in your summary to fully represent the conversation and all its smaller details. Keep your response dense in information and details.

Conversation Summary:
""",
            ),
            persist_current_turn_prompt=PromptTemplate(
                input_variables=["query", "response", "previous_summary",],
                template="""You are given conversation details between a human and an AI. You are also given a summary of how the conversation has progressed till now. 
Write a new summary of the conversation. Capture the salient, important and noteworthy aspects and details from the user query and system response. Your summary should be detailed, comprehensive and in-depth.
Capture all important details in your conversation summary including code, factual details, names and other details mentioned by the human and the AI. 
Preserve important details that have been mentioned in the previous summary especially including factual details and references.

The previous summary and salient points of the conversation is as follows:
'''{previous_summary}'''

Previous messages of the conversation are as follows:
'''{previous_messages_text}'''

The last 2 messages of the conversation from which we will derive the summary and salient points are as follows:
User query: '''{query}'''
System response: '''{response}'''

Write a summary of the conversation using the previous summary and the last 2 messages. Please summarize the conversation very informatively, in great detail and depth.
Conversation Summary:
""",
            ),

            # Translate the above prompt string to PromptTemplate object
            chat_fast_reply_prompt=PromptTemplate(
                input_variables=["query", "summary_text", "previous_messages", "document_nodes", "permanent_instructions", "doc_answer", "web_text", "link_result_text", "conversation_docs_answer"],
                template=f"""You are given conversation details between human and AI. Remember that as an AI expert assistant, you must fulfill the user's request and provide informative answers to the human's query. 
Provide a short and concise reply now, we will expand and enhance your answer later.
Use all the documents provided here in your answer to the user's query. Don't write code unless specifically asked to do so.
{self.complex_output_instructions}
{{summary_text}}
{{previous_messages}}
{{document_nodes}}
{{conversation_docs_answer}}
{{permanent_instructions}}
{{doc_answer}}
{{web_text}}
{{link_result_text}}
The most recent message of the conversation sent by the user now to which we will be replying is given below.
user's query: "{{query}}"
Write a clear, helpful and informative response to the user's query.
Response to the user's query:
""",
            ),
            chat_slow_reply_prompt=PromptTemplate(
                input_variables=["query", "summary_text", "previous_messages", "other_relevant_messages", "document_nodes", "permanent_instructions", "doc_answer", "web_text", "link_result_text", "partial_answer_text", "provide_detailed_answers_text", "conversation_docs_answer"],
                template=f"""You are given conversation details between human and AI. You are also given a summary of how the conversation has progressed till now.
Remember that as an AI expert assistant, you must fulfill the user's request and provide informative answers to the human's query.
{self.complex_output_instructions} 
Use all the documents provided here in your answer to the user's query. Don't write code unless specifically asked to do so.
{{provide_detailed_answers_text}}
The most recent message of the conversation sent by the user now to which we will be replying is given below.
user's query:\n'''{{query}}'''
{{summary_text}}
{{previous_messages}}
{{other_relevant_messages}}
{{document_nodes}}
{{conversation_docs_answer}}
{{permanent_instructions}}
{{doc_answer}}
{{web_text}}
{{link_result_text}}
{{partial_answer_text}}
Write a clear, detailed, comprehensive, thoughtful and informative response to the user's query.
user's query:\n'''{{query}}'''
Response to the user's query:
""",
            ),
            web_search_prompt=PromptTemplate(
                input_variables=["context", "doc_context", "previous_answer", "pqs", "n_query"],
                template="""<task>Your task is to generate web search queries for a given document and conversation context.</task>
You are given a question and conversation context as below.
Current question: 
'''{context}'''

Earlier conversation context:
'''{doc_context}'''

Generate web search queries to search the web for more information about the current user query. {previous_answer}
{pqs}
Generate {n_query} well specified and diverse web search queries as a valid python list. 
Instructions for how to generate the queries are given below.
1. Generate diverse web search queries for the current question using the current question and conversation context. 
2. Determine the subject domain of the current question from the context and the current question and mention the domain in your web search queries. 
3. Your output will look like a python list of strings like below.
["diverse google search query based on given document", "different_web_query based on the document and conversation"]

Current question: 
'''{context}'''
Output only a valid python list of web search query strings for the current question.
""",
            ),
            document_search_prompt=PromptTemplate(
                input_variables=["context", "doc_context"],
                template="""You are given a question and conversation summary of previous messages between an AI assistant and human as below. 
The question which is given below needs to be answered by using a document context that will be provided later. 
For now we need to rephrase this question better using the given conversation summary.

Current Question: '''{context}'''

Previous conversation summary: '''{doc_context}'''

We want to rephrase the question to help us search our document store for more information about the query.

Generate one well specified search query as a valid python list. 
Instructions for how to generate the queries are given below.
1. Output should be only a python list of strings (a valid python syntax code which is a list of strings). 
2. Convert abbreviations to full forms and correct typos in the query using the given context.
3. Your output will look like a python list of strings like below.
["query_1"]

Output only a valid python list of web search query strings.
""",
            ),
            web_search_question_answering_prompt=PromptTemplate(
                input_variables=["query", "answer", "additional_info"],
                template=f"""<task>Your role is to provide an answer to the user question incorporating the additional information you are provided within your response.</task>
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
            ),

            get_more_details_prompt=PromptTemplate(
                input_variables=["query", "answer", "additional_info"],
                template=f"""Continue writing answer to a question or instruction which is partially answered. 
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
"""
            ),
            paper_details_map = {
            "methodology": """
Read the document and provide information about "Motivation and Methodology" of the work.
Cover the below points while answering and also add other necessary points as needed.
    - What do the authors do in this overall work (i.e. their methodology) with details.
    - Detailed methodology and approach described in this work.
    - what problem do they address ?
    - how do they solve the problem, provide details?
    - Why do they solve this particular problem?
    - what is their justification in using this method? Why do they use this method? 
    - Any insights from their methods
    - Any drawbacks in their method or process
""",
            "previous_literature_and_differentiation": """
Read the document and provide information about "Previous Literature and Background work" of the work.
Cover the below points while answering and also add other necessary points as needed.
    - What is this work's unique contribution over previous works?
    - what previous literature or works are referred to?
    - How are the previous works relevant to the problem this method is solving?
    - how their work is different from previous literature?
    - What improvements does their work bring over previous methods.
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
""",
            "results_and_comparison": """
Read the document and provide information about "Results" of the work.
Cover the below points while answering and also add other necessary points as needed.
    - What results do they get from their experiments 
    - how does this method perform compared to other methods?
    - Make markdown tables to highlight most important results.
    - Any Insights or surprising details from their results and their tables
""",
            "limitations_and_future_work":"""
Read the document and provide information about "Limitations and Future Work" of the work. 
Cover the below points while answering and also add other necessary points as needed.
    - What are the limitations of this method, 
    - Where and when can this method or approach fail? 
    - What are some further future research opportunities for this domain as a follow up to this method?
    - What are some tangential interesting research questions or problems that a reader may want to follow upon?
    - What are some overlooked experiments which could have provided more insights into this approach or work.
""",
            }
        )
        self.llama_prompts  = dict(
            streaming_followup=PromptTemplate(
                input_variables=["followup", "query", "answer", "fragment", "summary", "full_summary",
                                 "questions_answers"],
                template=f"""Provide answer to a follow up question which is based on an earlier question. Answer the followup question or information request from context (text chunks of larger document) you are provided. 
Followup question or information request is given below.
"{{followup}}"

Summary of the document is given below.
"{{full_summary}}"

Few text chunks from within the document to answer this follow up question as below.
"{{fragment}}"

Few question and answer pairs from the document are given below.
"{{questions_answers}}"

Summaries of certain parts of document below:
"{{summary}}"

Previous question or earlier question and its answer is provided below:

Earlier Question: "{{query}}"

Earlier Answer:
"{{answer}}"

Keep the earlier question in consideration while answering.
{self.simple_output_instructions}

Current Question: {{followup}}
Answer: 
""",
            ),
            short_streaming_answer_prompt=PromptTemplate(
                input_variables=["query", "fragment", "summary", "questions_answers", "full_summary"],
                template=f"""Answer the question or information request given below using the given context (text chunks of larger document) as a helpful reference. 
Question or Query is given below.
{{query}}
{{full_summary}}
Few text chunks from the document to answer the question below:
'''{{fragment}}'''
{{questions_answers}}
{{summary}}
{self.simple_output_instructions}

Question or Query is given below.
{{query}}

Write informative answer below.
""",
            ),
            running_summary_prompt=PromptTemplate(
                input_variables=["summary", "document", "previous_chunk_summary"],
                template=f"""We are reading a large document in fragments sequentially to write a continuous summary. 
'''{{document}}'''
{{previous_chunk_summary}}
{{summary}}
Ignore references. Always provide detailed, comprehensive, informative and in-depth response. Include key experiments, experimental observations, results and conclusions.
Summary:
""",
            ),
            retrieve_prior_context_prompt=PromptTemplate(
                input_variables=["requery_summary_text", "previous_messages", "query"],
                template="""You are given conversation details between a human and an AI. 
Based on the given conversation details and human's last response or query we want to search our database of responses.
You will generate a contextualised query based on the given conversation details and human's last response or query.
The summary of the conversation is as follows:
{requery_summary_text}

The last few messages of the conversation are as follows:
{previous_messages}

The last message of the conversation sent by the human is as follows:
{query}

Rephrase and contextualise the last message of the human as a question or a statement using the given previous conversation details so that we can search our database.
Rephrased and contextualised human's last message:
"""
            ),
            long_persist_current_turn_prompt=PromptTemplate(
                input_variables=["previous_messages", "previous_summary", "older_summary"],
                template="""You are given conversation details between a human and an AI. You will summarise the conversation provided below.
The older summary of the conversation is as follows:
'''{older_summary}'''

The recent summary of the conversation is as follows:
'''{previous_summary}'''

The last few messages of the conversation from which we will derive the summary are as follows:
'''
{previous_messages}
'''

Please summarize the conversation very informatively, in great detail and depth. Your summary should be detailed, comprehensive, thoughtful, insightful, informative, and in-depth. Ensure you capture all nuances and key points from the dialogue. Capture all essential details mentioned by both user and assistant.

Format your summary using markdown, starting with a long comprehensive overview paragraph. Follow this with in depth bullet points with good detailing highlighting about all the details of the conversation. Finally, conclude with an extensive final remark about the overall conversation including any plans or action items. Mention all solutions, suggestions, references, methods and techniques we discussed in depth and proper detail. Capture any solutions, ideas, thoughts, suggestions, action items we had discussed in depth and comprehensively.

Prioritise clarity, informativeness, wide coverage, density and depth in your summary to fully represent the conversation and all its smaller details. Keep your response dense in information and details.

Conversation Summary:
""",
            ),
            persist_current_turn_prompt=PromptTemplate(
                input_variables=["query", "response", "previous_summary", "previous_messages_text"],
                template="""You are given conversation details between a human and an AI. You are also given a summary of how the conversation has progressed till now. 
Write a new summary of the conversation. Capture all important details in your summary including code, factual details, links and references, named entities and other details mentioned by the human and the AI. Your summary should be detailed, comprehensive and in-depth.

The previous summary and salient points of the conversation is as follows:
'''{previous_summary}'''

Previous messages of the conversation are as follows:
'''{previous_messages_text}'''

The last 2 messages of the conversation from which we will derive the summary and salient points are as follows:
User query: '''{query}'''
System response: '''{response}'''

Please summarize the conversation very informatively, in great detail and depth. Lets write a new summary of the conversation. 
Conversation Summary:
""",
            ),
            chat_fast_reply_prompt=PromptTemplate(
                input_variables=["query", "summary_text", "previous_messages", "document_nodes",
                                 "permanent_instructions", "doc_answer", "web_text", "link_result_text", "conversation_docs_answer"],
                template=f"""You are given conversation details between human and AI. Provide informative answer to the human's query. 
Use all the documents provided here in your answer to the user's query. Don't write code unless specifically asked to do so.
{self.simple_output_instructions}

{{summary_text}}
{{previous_messages}}
{{document_nodes}}
{{conversation_docs_answer}}
{{permanent_instructions}}
{{doc_answer}}
{{web_text}}
{{link_result_text}}

Write a clear, helpful and informative response to the most recent user's query.
user's query:\n'''{{query}}'''
Response to the user's query:
""",
            ),
            chat_slow_reply_prompt=PromptTemplate(
                input_variables=["query", "summary_text", "previous_messages", "other_relevant_messages",
                                 "document_nodes", "permanent_instructions", "doc_answer", "web_text",
                                 "link_result_text", "partial_answer_text", "provide_detailed_answers_text", "conversation_docs_answer"],
                template=f"""You are given conversation details between human and AI.
As an AI expert assistant, you must fulfill the user's request and provide informative answers to the human's query.
{self.simple_output_instructions}
Use all the documents provided here in your answer to the user's query. Don't write code unless specifically asked to do so.
{{provide_detailed_answers_text}}

The most recent message of the conversation sent by the user now to which we will be replying is given below.
user's query:\n'''{{query}}'''

{{summary_text}}
{{previous_messages}}
{{other_relevant_messages}}
{{document_nodes}}
{{conversation_docs_answer}}
{{permanent_instructions}}
{{doc_answer}}
{{web_text}}
{{link_result_text}}
{{partial_answer_text}}
Write a clear, detailed, comprehensive, thoughtful and informative response to the user's query.
user's query:\n'''{{query}}'''
Response to the user's query:
""",
            ),
            web_search_prompt=PromptTemplate(
                input_variables=["context", "doc_context", "previous_answer", "pqs", "n_query"],
                template="""You are given a query or question or conversation context as below.
Current question: 
'''{context}'''

Earlier conversation context:
'''{doc_context}'''

We want to generate {n_query} web search queries to search the web for more information about the current query.
{previous_answer}
{pqs}
Instructions for how to generate the web search queries are given below.
1. Generate {n_query} well specified and diverse web search queries using the current question and conversation context.
2. Write one search query per line for a total of {n_query} queries.
3. Only write the search queries. Don't write anything else.
4. After writing the google web search queries write ###END### on a new line.
5. End your response for queries with ###END###.

Current question: 
'''{context}'''
Google Search Queries are written below.
""",
            ),
            document_search_prompt=PromptTemplate(
                input_variables=["context", "doc_context"],
                template="""You are given a question and conversation summary of previous messages between an AI assistant and human as below. 
The question which is given below needs to be answered by using a document context that will be provided later. 
For now we need to rephrase this question better using the given conversation summary.

Current Question: '''{context}'''

Previous conversation summary: '''{doc_context}'''

We want to rephrase the question to help us search our document store for more information about the query.

Generate one well specified search query as a valid python list. 
Instructions for how to generate the queries are given below.
1. Output should be only a python list of strings (a valid python syntax code which is a list of strings). 
2. Convert abbreviations to full forms and correct typos in the query using the given context.
3. Your output will look like a python list of strings like below.
["query_1"]

Output only a valid python list of web search query strings.
""",
            ),
            web_search_question_answering_prompt=PromptTemplate(
                input_variables=["query", "answer", "additional_info"],
                template=f"""Continue writing answer to a question which is partially answered. Provide new details from the additional information provided.
Question is given below:
"{{query}}"

Relevant additional information from other documents with url links, titles and document context are mentioned below:
"{{additional_info}}"

Continue the answer ('Answer till now') by incorporating additional information from other documents. 

{self.simple_output_instructions}
Question: '''{{query}}'''
Answer till now (partial answer): '''{{answer}}'''
Write continued answer using additional information below.
""",
            ),
            get_more_details_prompt=PromptTemplate(
                input_variables=["query", "answer", "additional_info"],
                template=f"""Continue writing answer to a question which is partially answered. 
Provide new details from the additional information provided. Don't repeat information from the partial answer already given.
Question is given below:
"{{query}}"
Answer till now (partial answer already given): '''{{answer}}'''

Relevant additional information from the same document context are mentioned below:
'''{{additional_info}}'''

Continue the answer ('Answer till now') by incorporating additional information from this relevant additional context. 
{self.simple_output_instructions}


Continue answer using additional information from the documents.
"""
            ),
            paper_details_map = {
            "methodology": """
Read the document and provide information about "Motivation and Methodology" of the work. Answer the following:
    - What do the authors do in this overall work (i.e. their methodology) with details.
    - what problem do they address ?
    - how do they solve the problem, provide details?
    - what is their justification in using this method? Why do they use this method? 
    - Any insights from their methods
""",
            "previous_literature_and_differentiation": """
Read the document and provide information about "Previous Literature and Background work" of the work. Answer the following:
    - What is this work's unique contribution over previous works?
    - what previous literature or works are referred to?
    - How are the previous works relevant to the problem this method is solving?
""",
            "experiments_and_evaluation":"""
Read the document and provide information about "Experiments and Evaluation" of the work. Answer the following:
    - How is the proposed method/idea evaluated?
    - What metrics are used to quantify their results?
    - what datasets do they evaluate on?
    - What experiments are performed?
    - Any surprising experiments or insights
""",
            "results_and_comparison": """
Read the document and provide information about "Results" of the work. Answer the following:
    - What results do they get from their experiments 
    - how does this method perform compared to other methods?
""",
            "limitations_and_future_work":"""
Read the document and provide information about "Limitations and Future Work" of the work. Answer the following:
    - What are the limitations of this method, 
    - What are some further future research opportunities for this domain as a follow up to this method?
    - What are some overlooked experiments which could have provided more insights into this approach or work.
""",
            }
        )


    @property
    def prompts(self):
        if self.llm == "gpt4":
            prompts = self.gpt4_prompts
        elif self.llm == "gpt3":
            prompts = self.gpt4_prompts
        elif self.llm == "llama":
            prompts = self.llama_prompts
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
    def streaming_followup(self):
        prompts = self.prompts
        return prompts["streaming_followup"]

    @property
    def short_streaming_answer_prompt(self):
        prompts = self.prompts
        return prompts["short_streaming_answer_prompt"]

    @property
    def running_summary_prompt(self):
        prompts = self.prompts
        return prompts["running_summary_prompt"]

    @property
    def retrieve_prior_context_prompt(self):
        prompts = self.prompts
        return prompts["retrieve_prior_context_prompt"]

    @property
    def persist_current_turn_prompt(self):
        prompts = self.prompts
        return prompts["persist_current_turn_prompt"]

    @property
    def long_persist_current_turn_prompt(self):
        prompts = self.prompts
        return prompts["long_persist_current_turn_prompt"]

    @property
    def chat_fast_reply_prompt(self):
        prompts = self.prompts
        return prompts["chat_fast_reply_prompt"]

    @property
    def chat_slow_reply_prompt(self):
        prompts = self.prompts
        return prompts["chat_slow_reply_prompt"]

    @property
    def web_search_prompt(self):
        prompts = self.prompts
        return prompts["web_search_prompt"]

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


prompts = CustomPrompts(os.environ.get("LLM_FAMILY", "gpt4"), os.environ.get("ROLE", "science"))



