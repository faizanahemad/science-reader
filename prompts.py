from langchain.prompts import PromptTemplate
prompts = {

    "DocIndex": dict(
        streaming_followup = PromptTemplate(
            input_variables=["followup", "query", "answer", "fragment", "summary", "full_summary", "questions_answers"],
            template="""Provide answer to a follow up question which is based on an earlier question. Answer the followup question or information request from context (text chunks of larger document) you are provided. 

Followup question or information request is given below:

"{followup}"

Summary of the document:

"{full_summary}"

Few text chunks from within the document to answer this follow up question as below:

"{fragment}"

Few question and answer pairs from the document are given below:

"{questions_answers}"

Summaries of certain parts of document below:

"{summary}"

Previous question or earlier question and its answer is provided below:

Earlier Question:
"{query}"

Earlier Answer:
"{answer}"

Answer elaborately providing as much detail as possible. Keep the earlier question in consideration while answering.
Use markdown formatting to typeset/format your answer better.
Output any relevant equations in latex/markdown format. Remember to put each equation or math in their own environment of '$$', our screen is not wide hence we need to show math equations in less width.

Question: {followup}
Answer: 

""",
        ),
        short_streaming_answer_prompt = PromptTemplate(
            input_variables=["query", "fragment", "summary", "questions_answers", "full_summary"],
            template="""Answer the question or information request given below using the given context (text chunks of larger document) as a helpful reference. 
Question or Query is given below:
{query}

Short summary of the document is given below:
'''{full_summary}'''

Few text chunks from the document to answer the question below:
'''{fragment}'''

Next, You are given few question and answer pairs from the document below:
'''{questions_answers}'''

You are also given summaries of certain parts of document below:
'''{summary}'''

If the given context can't be used to provide a good and complete answer then provide detailed information which can help in answering the question partly.
Use markdown syntax and markdown formatting to typeset and format your answer better.
Output any relevant equations in latex/markdown format. Remember to put each equation or math in their own environment of '$$', our screen is not wide hence we need to show math equations in less width.
Helpful, detailed and informative answer:
""",
        ),
        
        running_summary_prompt = PromptTemplate(
                input_variables=["summary", "document", "previous_chunk_summary"],
                template="""We are reading a large document in fragments sequentially to write a continous summary.

Current chunk/fragment we are looking at:

"{document}"

Summary of previous chunk/fragment:

"{previous_chunk_summary}"

The summary written till now will be empty if this is the first chunk/fragment of the larger document. The summary we have written till now:

"{summary}"

Instructions for this task as below:
- No use of quotes.
- Use markdown formatting to typeset/format your answer better.
- Output any relevant equations in latex/markdown format. Remember to put each equation or math in their own environment of '$$', our screen is not wide hence we need to show math equations in less width.
- Ignore irrelevant details not relevant to the overall document.
- Continue and extend the above summary written till now by adding details from the current chunk/fragment. Continue writing from the "summary we have written till now", don't repeat information we already have. 
- Add html header '<h4>topic/header text of current chunk</h4>' and header text (inside <h4> tags) at appropriate places when the current chunk/fragment moves to a new topic. In case the topic discussed is still the same as last topic of 'summary written till now' then don't add header <h4> tags and header text.
- One chunk/fragment can have multiple html header '<h4>topic/header text of current chunk</h4>' and one html header can span over to multiple chunks/fragments as well. A topic or html header may start in one chunk/fragment and it's content can go over into the next chunk/fragment as well.
- Your output will look as below in structure:
"
<h4>Title or Topic of this Part</h4>
details of this part
</br>

<h4>Title or Topic of next part</h4>
Details of next part
</br>

"

Very Short Summary:

    """,
            ),
        
        running_methodology_prompt = PromptTemplate(
                input_variables=["summary", "document"],
                template="""We are reading a large document in small chunks/fragments sequentially and creating an extended and detailed summary. This large document is a scientific document and hence it is important to preserve all details and nuances in our summary along with scientific content.

Given below is the current chunk/fragment we are looking at:

"{document}"

The extended and detailed summary generated till now will be empty if this is the first chunk/fragment of the larger document. The extended and detailed summary we have generated till now looks as below:

"{summary}"

Now continue and extend the above summary (this is a continuation of writing task) by using the current chunk/fragment and adding details from the current chunk/fragment. Remember that you are to continue writing from the "extended and detailed summary we have generated till now" and keep writing further, don't repeat the summary we have till now. Just output the continuation.

    """,
            ),
        
        
    )
}