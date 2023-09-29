review_params = {
"review_simple" : "As a reviewer, your primary role is to provide a thoughtful and fair evaluation of the paper or research submitted. Start by understanding the research's objectives, methodology, results, and implications. Ensure that it offers clarity, originality, and contributes significantly to the field. Evaluate the validity of the experimental design, the robustness of the data analysis, and the transparency of the methods used. Look for potential impacts of the research on the field and society at large. Verify ethical considerations, scientific integrity, diversity, and inclusivity aspects. Lastly, review the overall presentation, including the writing style, structure, visual aids, and identification of limitations. Keep your comments constructive, focusing on both the strengths and weaknesses of the paper, and always remember the importance of your role in maintaining the high quality of scientific discourse.",
    "fine_grained_reviews" : [
        ("Understanding the Research", "Begin by familiarizing yourself with the study's objectives, hypotheses, methodology, and results. Look for clarity, originality, and a significant contribution to the field. Consider the research's relevancy to real-world scenarios and its potential interdisciplinary implications. Do the methods align well with the objectives? Are the theory or models used sound and correct? Ensure to review the literature cited and check if it covers all relevant prior work. Finally, evaluate your confidence as a reviewer."),

        ("Analyzing the Research Design and Data", "Investigate the research's experimental design, data analysis, and reproducibility. Assess the complexity and novelty of the methods used. Ensure the experiments test the research questions appropriately and that the results can be generalized. Look for clear, accurate, and effective visual presentations of data. In terms of data transparency, all methods should be clearly explained, and data should be readily available. Check for robustness of results and propose improvements or alternative approaches, if necessary."),

        ("Evaluating the Impact and Implications", "Consider the study's potential impact on the field and broader society. Does the research address a critical problem? How significant is it, and how can the results be applied in practice or in future research? Review the discussion and conclusions drawn in the paper, and ensure they are relevant to the research question and results. Furthermore, consider if the research suggests avenues for future research."),

        ("Assessing the Ethics, Integrity, and Inclusivity", "Reflect on the ethical considerations presented in the study. Ensure that the research adheres to standards and guidelines. Verify if the paper upholds scientific rigor, including thoroughness, objectivity, and transparency. Pay attention to whether conflicts of interest have been declared. Lastly, consider the diversity and inclusion aspects in the research, and evaluate the potential environmental and social impacts of the study."),

        ("Reviewing the Presentation and Writing", "Review the overall presentation of the paper. Is the writing clear, concise, and well-organized? Does the narrative structure help you understand and follow the research process? Are tables, figures, and other visual aids well-designed and easy to interpret? Identify the strengths and weaknesses of the paper, including clarity, methodology, data analysis, and interpretation of results. Make sure that the paper identifies its own limitations and discuss their impact on the findings."),
    ],
    # "review_parameters_medium": [
    #     ("Contribution to the Field", "Does the research present novel findings, ideas, or approaches?"),
    #
    #     ("Methodology and Experimental Design",
    #      "How appropriate and valid are the methods used? Are the experimental setup and data analysis rigorous and reliable?"),
    #
    #     ("Data Analysis", "How is the statistical analysis handled?"),
    #
    #     ("Relevance and Significance",
    #      "Does the research address an important and relevant problem in the field? What is its potential impact?"),
    #
    #     ("Citations and References",
    #      "Is there an appropriate citation of previous work? How is the quality and relevance of the references?"),
    #
    #     ("Ethical Considerations", "Are ethical standards and guidelines upheld in the research?"),
    #
    #     ("Reproducibility",
    #      "Does the paper provide sufficient information for replication of the results or reproduction of the experiments?"),
    #
    #     ("Hypothesis and Objectives", "Is the research question or hypothesis clear and valuable?"),
    #
    #     ("Contextualisation",
    #      "Is the problem or research question well situated within the broader scientific discourse?"),
    #
    #     ("Use of Theories or Frameworks",
    #      "Is there an effective use of existing theories or frameworks to structure the research?"),
    #
    #     ("Results and Interpretation", "Are the results clear and are their conclusions justified by the data?"),
    #
    #     ("Robustness Checks",
    #      "Does the paper provide checks for its main results to see if they hold under different assumptions or slight changes in the methodology?"),
    #
    #     ("Visual Presentation of Data",
    #      "How clear and effective are the graphs, tables, and other visual presentations of data?"),
    #
    #     ("Discussion and Implications",
    #      "Are the results considered in the wider context of the field? Are implications for future research clearly outlined?"),
    #
    #     ("Identified Limitations",
    #      "Are the limitations of the paper and their impact on the findings and interpretations clearly outlined?"),
    #
    #     ("Scientific Rigour and Integrity",
    #      "Does the paper adhere to principles such as the appropriate use of statistics, transparent reporting of methods and data, declaration of conflicts of interest?"),
    #
    #     ("Importance and Application",
    #      "How significant is the research? Is it addressing a critical problem? Can the results be applied in practice or further research?"),
    #
    #     ("Strength and Weakness", "What are the strong and weak points of the paper?"),
    #
    #     ("Theoretical Validity",
    #      "Is the theory or model used in the research sound, logical, and based on established scientific principles?"),
    #
    #     ("Novelty", "Is the study introducing a new concept, theory, methodology, or application?"),
    #
    #     ("Complexity of Methods and Experiments", "Are they appropriately complex given the problem at hand?"),
    #
    #     ("Experimental Validity",
    #      "Do the experiments effectively test the research question or hypothesis? Can the results be generalized?"),
    #
    #     ("Literature Review", "Is the review thorough and up-to-date?"),
    #
    #     ("Suggestions for Improvement", "Are there potential improvements that can be made?"),
    #
    #     ("Transparency of Data and Methods", "Are the methods and data clearly explained and available?"),
    #
    #     ("Relevance of Discussion and Conclusion", "Are they directly relevant to the research question and results?"),
    #
    #     ("Applicability to Real-World Scenarios", "Can the research findings be applied in real-world contexts?"),
    #
    #     ("Reviewer's Confidence", "Is the reviewer familiar with the field and the paper's proposed ideas?"),
    #
    #     ("Proposal of Alternative Approaches",
    #      "Are there any alternative approaches proposed to overcome identified weaknesses or limitations?"),
    #
    #     ("Interdisciplinary Relevance", "Is the research relevant to other fields of study?"),
    #
    #     ("Diversity and Inclusion", "Does the research promote diversity and inclusion?"),
    #
    #     ("Environmental and Social Impact", "What are the potential environmental and social impacts of the research?"),
    #
    # ],
    # "review_parameters_large" : [
    #     ("Contribution to the field", "Evaluate the paper's contribution to the existing body of knowledge in the field. Assess whether it presents new findings, ideas, or approaches."),
    #
    #     ("Methodology and Experimental Design", "Review the paper's methodology and experimental design. Assess the appropriateness and validity of the methods used and evaluate the experimental setup for rigor and reliability."),
    #
    #     ("Data Analysis", "Evaluate the paper's data analysis methods. Consider the statistical techniques used, the appropriateness of the analysis for the research question, and the depth and clarity of the data analysis results."),
    #
    #     ("Clarity and Organization", "Assess the clarity and organization of the paper. Evaluate the writing style, structure, and coherence of the paper. Consider whether the paper is well-written, logically organized, and easy to follow."),
    #
    #     ("Relevance and Significance", "Consider the relevance and significance of the research. Evaluate whether the research addresses an important and relevant problem in the field and assess its potential impact on the field."),
    #
    #     ("Citations and References", "Evaluate the paper's use of citations and references. Check whether the paper appropriately cites relevant previous work and assess the quality and relevance of the cited references."),
    #
    #     ("Ethical Considerations", "Consider any ethical considerations related to the research presented in the paper. Evaluate whether the research adheres to ethical standards and guidelines."),
    #
    #     ("Reproducibility", "Assess the reproducibility of the research. Consider whether the paper provides sufficient information for others to replicate the results or reproduce the experiments."),
    #
    #     ("Hypothesis and Objectives", "Does the paper clearly state the research question or hypothesis? Are the objectives of the study clearly outlined? Is the hypothesis or research question novel and does it add value to the current literature?"),
    #
    #     ("Contextualisation", "Has the problem or research question been appropriately contextualized within the broader scientific discourse? Does the introduction effectively convey the significance of the research and its relevance to real-world problems or applications?"),
    #
    #     ("Use of Theories or Frameworks", "If applicable, does the paper make effective use of existing theories or frameworks to structure the research and guide the interpretation of the results?"),
    #
    #     ("Results and Interpretation", "Are the results clearly presented and interpreted? Are the conclusions drawn from the results justified by the data? Are alternative explanations for the results considered?"),
    #
    #     ("Robustness Checks", "If applicable (especially in fields like economics, social sciences), does the paper provide robustness checks for its main results? It's important to see if the results hold under different assumptions or slight changes in the methodology."),
    #
    #     ("Visual Presentation of Data", "Are graphs, tables, and other visual presentations of data clear, accurate, and well labeled? Do they effectively help the reader to understand the results?"),
    #
    #     ("Discussion and Implications", "Does the discussion adequately consider the results in the wider context of the field? Are implications of the findings for the field and for future research clearly outlined?"),
    #
    #     ("Limitations", "Does the paper clearly outline its limitations, and discuss the impact of these limitations on the findings and interpretations?"),
    #
    #     ("Language and Style", "Is the paper well-written, with clear and concise language, good grammar and spelling, and a coherent narrative structure that helps the reader to understand and follow the research process?"),
    #
    #     ("Scientific Rigour and Integrity", "Are the principles of scientific rigor and integrity adhered to? This can include issues such as the appropriate use of statistics, transparent reporting of methods and data, declaration of potential conflicts of interest, etc."),
    #
    #     ("Importance and Application", "Consider the relevance and utility of the research. Evaluate how significant the research is to the field. Is it addressing a critical problem or question? Can the results be applied in practice or further research? This could also cover societal or policy relevance."),
    #
    #     ("Strength", "Assess the strong points of the paper. This might include clear writing, rigorous methodology, innovative ideas, in-depth analysis, thorough interpretation of the results, etc."),
    #
    #     ("Weakness", "Identify the weak points of the paper. Weaknesses could be in various aspects, including writing clarity, methodology, data analysis, interpretation of results, or the depth of the literature review."),
    #
    #     ("Theoretical Validity and Correctness of Theory and Derivations", "Evaluate whether the theory or model used in the research is sound, logical, and based on established scientific principles. In mathematics or theory-heavy fields, check whether the mathematical derivations or theoretical arguments are correct."),
    #
    #     ("Idea Originality/Novelty", "Consider the originality of the research question or hypothesis. Is the study introducing a new concept, theory, methodology, or application? Are the results unexpected or surprising?"),
    #
    #     ("Methodology Originality/Novelty", "Evaluate the novelty of the research methods or approach. Does the study present a new way of collecting data, conducting experiments, or analyzing results?"),
    #
    #     ("Clarity", "Evaluate how clear and understandable the paper is. This includes writing style, the structure of the paper, clarity of figures and tables, clear definitions of terms, etc."),
    #
    #     ("Ablations and Teasing Out Their Contribution vs Prior Work", "Consider how well the paper differentiates its contribution from prior work. In machine learning, this often involves ablation studies that show the individual effect of different components of a system."),
    #
    #     ("Complexity of Methods and Experiments", "Evaluate the complexity of the methods and experiments. Are they appropriately complex given the problem at hand? Could simpler methods have achieved the same results?"),
    #
    #     ("Experimental Strength and Weakness", "Evaluate the strengths and weaknesses of the experimental design. Does the design allow for robust and reliable results? Are there any major limitations in the design?"),
    #
    #     ("Experimental Validity", "Evaluate whether the experiments effectively test the research question or hypothesis. Do they have internal validity (i.e., do they correctly test what they aim to test) and external validity (i.e., can the results be generalized to other settings)?"),
    #
    #     ("Literature Review and if it Covers Everything", "Assess whether the paper provides a thorough and up-to-date review of the relevant literature. Does it appropriately cite previous work and place its own contribution in the context of existing literature?"),
    #
    #     ("Suggestions for Improvement in Experiments by Adding More Datasets or Experiments", "If you identify potential improvements, suggest these to the authors. This might involve using additional datasets, conducting more experiments, using different methods, etc."),
    #
    #     ("Experimental Originality/Novelty", "Evaluate whether the experimental approach is original or novel. Does it introduce new ways of testing a hypothesis or gathering data?"),
    #
    #     ("Experimental Clarity", "Evaluate whether the methods and experiments are clearly explained. Could another researcher replicate the experiments based on the descriptions given?"),
    #
    #     ("Identification of Limitations", "Evaluate how well the paper identifies its own limitations. Does it adequately address potential sources of bias or error, limitations in data or methodology, or other weaknesses that might affect the interpretation of the results?"),
    #
    #     ("Suggestions for Future Research", "Consider whether the paper suggests avenues for future research. Does it identify unanswered questions or new questions raised by the research? Are there logical next steps that it suggests for other researchers to follow up on?"),
    #
    #     ("Transparency of Data and Methods", "Evaluate how transparent the paper is in its methods and data. Are all methods clearly explained, and is all data available for others to scrutinize or reproduce the results?"),
    #
    #     ("Relevance of Discussion and Conclusion", "Assess whether the discussion and conclusion are directly relevant to the research question and results. Does the paper avoid overgeneralization, and does it carefully interpret the results within the context of the research design and data?"),
    #
    #     ("Applicability to Real-World Scenarios", "Consider the practical applications of the research findings. Are there any real-world contexts where these findings can be applied? How can they be utilized to address real-world problems or enhance existing solutions?"),
    #
    #     ("Scientific Rigor", "Assess the overall scientific rigor of the paper. Does the paper uphold the standards of the scientific method, including thoroughness, reproducibility, objectivity, and transparency?"),
    #
    #     ("How confident you are as a reviewer", "Have you looked at relevant prior work and theory. Are you aware and understand the problem, the datasets used and proposed ideas in the paper. How familiar are you with the field."),
    #
    #     ("Proposal of Alternative Approaches", "When weaknesses or limitations are identified, propose alternative approaches that could overcome these limitations. These could include different experimental designs, alternative statistical techniques, different ways of interpreting the results, etc."),
    #
    #     ("Communication and Presentation", "Evaluate the paper's overall presentation. Is the paper well-organized, clear, and professional? Are figures and tables well-designed and easy to interpret?"),
    #
    #     ("Interdisciplinary Relevance", "Assess whether the research could be relevant to other fields of study. Does the research touch upon problems or methodologies that could have implications beyond the primary field of research?"),
    #
    #     ("Diversity and Inclusion", "Consider whether the research promotes diversity and inclusion. This could be in terms of the research topic (e.g., does it address a problem that affects underrepresented groups?) or in the research process itself (e.g., were diverse perspectives included in the research team or in the research design and methodology?)."),
    #
    #     ("Environmental and Social Impact", "Consider whether the research has potential environmental and social impacts. How does the research relate to broader societal goals, like the Sustainable Development Goals or the climate change agenda? If the research could have negative environmental or social impacts, are these addressed and mitigated?"),
    # ],
    "review_with_additional_instructions": "As a reviewer, your primary role is to provide a thoughtful and fair evaluation of the paper or research submitted. Follow any instructions given which suggest how to do this review.",

    "meta_review" : "As a meta-reviewer or area chair, your primary role is to provide a thoughtful and fair synthesis of the reviews submitted. Read the research work given along with the provided reviews written by reviewers to provide your meta review which gathers all the views presented in the reviews given. Start by understanding the research's objectives, methodology, results, and implications. Ensure that it offers clarity, originality, and contributes significantly to the field. Evaluate the validity of the experimental design, the robustness of the data analysis, and the transparency of the methods used. Look for potential impacts of the research on the field and society at large. Verify ethical considerations, scientific integrity, diversity, and inclusivity aspects. Lastly, review the overall presentation, including the writing style, structure, visual aids, and identification of limitations. Keep your comments constructive, focusing on both the strengths and weaknesses of the paper, and always remember the importance of your role in maintaining the high quality of scientific discourse.",

    # "review_accept_decision" : "You were reviewing a paper and you have decided that the paper should have accept decision for the conference. Your goal is to convey the acceptance of a paper effectively and respectfully. Start by familiarizing yourself with the paper's main objectives, methodology, and key findings. Highlight the novelty of the research, its contribution to the field, and the potential impact it may have. Acknowledge the strengths of the paper as identified by the reviewers and the area chair, and detail these in a concise manner. When discussing the paper's limitations, focus on how they can be addressed in future research rather than as shortcomings. Your communication should reinforce the paper's value, acknowledge the efforts of the authors, and express optimism about its potential to further the knowledge in the field.",
    # "review_reject_decision" : "You were reviewing a paper and you have decided that the paper should have reject decision for the conference. Your task is to communicate the reject decision in a constructive and empathetic manner. Read the paper thoroughly to understand its main ideas and aims. Highlight the areas of concern identified by the reviewers and the area chair, focusing on the shortcomings in methodology, data analysis, or theoretical framework. Frame these not as failures, but as areas for improvement, providing specific examples where possible. Also, emphasize the potential of the study, suggesting how future work could address these issues. Ensure your communication is clear, respectful, and encourages the authors to continue refining their work for future submissions. Always remember your role is not just to communicate a decision, but also to aid authors in their scientific journey.",
    "scores" : [(1, "reject"), (2, "weak reject"), (3, "neutral"), (4, "weak accept"), (5, "accept")]
}