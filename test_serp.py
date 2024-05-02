from base import serpapi, brightdata_google_serp, googleapi_v2
import json
from pprint import pprint
import time
def serp():
    query = "coffee mugs"
    key = None
    num = 10
    start_time = time.time()
    results = serpapi(query, key, num, our_datetime=None, only_pdf=False, only_science_sites=False)
    end_time = time.time()
    start_time = time.time()
    results = serpapi(query, key, num, our_datetime=None, only_pdf=False, only_science_sites=False)
    end_time = time.time()
    pprint(results[0].keys())
    print("Time taken: ", f"{(end_time - start_time):.2f}")

    key = None

    start_time = time.time()
    results = googleapi_v2(query, key, num,
                        our_datetime=None, only_pdf=False, only_science_sites=False)
    end_time = time.time()
    pprint(results[0].keys())
    print("Time taken: ", f"{(end_time - start_time):.2f}")

    # pprint(results)
    # pprint(results1)
    # pprint(results2)

if __name__ == "__main__":
    serp()


due_diligence_queries = [
    {"area": "Financial Health and Performance", "subarea": "Revenue and Profit Growth", "long_question": "What has been the trend in <company_name>'s revenue and profit growth over the past five years?", "search_query": "<company_name> revenue and profit growth last 5 years"},
    {"area": "Financial Health and Performance", "subarea": "Margins", "long_question": "How do <company_name>'s gross, operating, and net margins compare to industry averages?", "search_query": "<company_name> gross operating net margins vs industry average"},
    {"area": "Financial Health and Performance", "subarea": "Balance Sheet Analysis", "long_question": "What does <company_name>'s balance sheet tell us about its financial stability and asset quality?", "search_query": "<company_name> balance sheet analysis"},
    {"area": "Market Position and Competitive Advantage", "subarea": "Market Share", "long_question": "What is <company_name>'s current market share within its industry, and how has it changed over time?", "search_query": "<company_name> market share trend"},
    {"area": "Market Position and Competitive Advantage", "subarea": "Competitive Moat", "long_question": "What competitive advantages does <company_name> possess, and how sustainable are they against new entrants?", "search_query": "<company_name> competitive advantages sustainability"},
    {"area": "Management Quality and Governance", "subarea": "Leadership Team", "long_question": "Who are the key executives of <company_name>, and what are their backgrounds and track records?", "search_query": "<company_name> executive team backgrounds"},
    {"area": "Management Quality and Governance", "subarea": "Corporate Governance", "long_question": "How does <company_name> score in terms of corporate governance and transparency?", "search_query": "<company_name> corporate governance rating"},
    {"area": "Risks", "subarea": "Market and Industry-Specific Risks", "long_question": "What are the major market and industry-specific risks that could impact <company_name>'s future performance?", "search_query": "<company_name> market industry risks"},
    {"area": "Risks", "subarea": "Company-Specific Risks", "long_question": "What company-specific risks does <company_name> face, including operational, legal, and financial risks?", "search_query": "<company_name> company-specific risks analysis"},
    {"area": "Strategic Direction and Growth Prospects", "subarea": "Expansion Plans and R&D", "long_question": "What are <company_name>'s plans for growth, including new markets, products, and research and development investments?", "search_query": "<company_name> expansion plans R&D investments"},
    {"area": "Regulatory Environment", "subarea": "Compliance and Regulatory Changes", "long_question": "How does <company_name> ensure compliance with regulatory standards, and how might upcoming regulatory changes affect its operations?", "search_query": "<company_name> regulatory compliance upcoming changes"}
]
due_diligence_queries.extend([
    {"area": "Technological Innovation and Digital Transformation", "subarea": "Adoption of Emerging Technologies", "long_question": "How is <company_name> integrating emerging technologies like AI, blockchain, and IoT into its operations and product lines?", "search_query": "<company_name> adoption of AI blockchain IoT"},
    {"area": "Technological Innovation and Digital Transformation", "subarea": "Digital Transformation Initiatives", "long_question": "What digital transformation strategies has <company_name> implemented to stay competitive in the digital era?", "search_query": "<company_name> digital transformation strategies"},
    {"area": "Customer Base and Market Demand", "subarea": "Customer Diversity", "long_question": "How diverse is <company_name>'s customer base, and how does it mitigate the risk of dependency on a limited number of clients?", "search_query": "<company_name> customer base diversity"},
    {"area": "Customer Base and Market Demand", "subarea": "Market Demand Trends", "long_question": "What are the current trends in market demand for <company_name>'s products or services, and how is the company positioned to meet these demands?", "search_query": "<company_name> market demand trends"},
    {"area": "Supply Chain and Operational Efficiency", "subarea": "Supply Chain Resilience", "long_question": "How resilient is <company_name>'s supply chain to global disruptions such as pandemics or trade wars?", "search_query": "<company_name> supply chain resilience"},
    {"area": "Supply Chain and Operational Efficiency", "subarea": "Operational Efficiency", "long_question": "What measures has <company_name> taken to improve operational efficiency and reduce costs?", "search_query": "<company_name> operational efficiency measures"},
    {"area": "Intellectual Property and Innovation", "subarea": "Patent Portfolio", "long_question": "What does <company_name>'s patent portfolio look like, and how does it contribute to the company's competitive advantage?", "search_query": "<company_name> patent portfolio analysis"},
    {"area": "Intellectual Property and Innovation", "subarea": "R&D Investment", "long_question": "How much is <company_name> investing in research and development, and what are its key areas of focus?", "search_query": "<company_name> R&D investment focus"},
    {"area": "Sustainability and Social Responsibility", "subarea": "Environmental Impact", "long_question": "What initiatives has <company_name> undertaken to minimize its environmental impact and promote sustainability?", "search_query": "<company_name> environmental sustainability initiatives"},
    {"area": "Sustainability and Social Responsibility", "subarea": "Social Responsibility", "long_question": "How is <company_name> contributing to the social welfare of its community and employees?", "search_query": "<company_name> social responsibility initiatives"}
])
due_diligence_queries.extend([
    {"area": "Valuation Metrics and Models", "subarea": "Price-to-Earnings Ratio (P/E)", "long_question": "What is <company_name>'s current P/E ratio, and how does it compare to its historical average and industry peers?", "search_query": "<company_name> P/E ratio comparison historical industry"},
    {"area": "Valuation Metrics and Models", "subarea": "Discounted Cash Flow (DCF) Analysis", "long_question": "What are the latest DCF valuation estimates for <company_name>, and what assumptions are being used in these models?", "search_query": "<company_name> DCF valuation estimates assumptions"},
    {"area": "Market Timing and Entry Points", "subarea": "Technical Analysis Indicators", "long_question": "What do key technical indicators like moving averages and RSI suggest about the current entry points for <company_name>?", "search_query": "<company_name> technical analysis moving averages RSI entry points"},
    {"area": "Market Timing and Entry Points", "subarea": "Market Sentiment and News Analysis", "long_question": "How is recent news and market sentiment likely to affect <company_name>'s stock price in the short term?", "search_query": "<company_name> stock price impact recent news market sentiment"},
    {"area": "Economic Indicators and Market Cycles", "subarea": "Interest Rates and Inflation", "long_question": "How might current and projected interest rates and inflation levels impact the valuation and stock price of <company_name>?", "search_query": "<company_name> impact interest rates inflation stock price"},
    {"area": "Economic Indicators and Market Cycles", "subarea": "Economic Cycle Position", "long_question": "Where are we currently in the economic cycle, and how does this position typically affect companies like <company_name>?", "search_query": "economic cycle position impact on <company_name>"}
])
due_diligence_queries.extend([
    {"area": "Growth Drivers", "subarea": "Innovation and Product Development", "long_question": "How is <company_name> positioned in terms of innovation and product development to drive future growth?", "search_query": "<company_name> innovation product development future growth"},
    {"area": "Growth Drivers", "subarea": "Market Expansion and Penetration", "long_question": "What strategies is <company_name> employing to expand into new markets or increase penetration in existing markets?", "search_query": "<company_name> market expansion penetration strategies"},
    {"area": "Risks to Future Growth", "subarea": "Regulatory and Compliance Risks", "long_question": "What regulatory or compliance risks could potentially hinder <company_name>'s future growth?", "search_query": "<company_name> regulatory compliance risks future growth"},
    {"area": "Risks to Future Growth", "subarea": "Technological Disruption", "long_question": "How susceptible is <company_name> to technological disruption from emerging technologies or new market entrants?", "search_query": "<company_name> risk technological disruption"},
    {"area": "Competitive Landscape", "subarea": "Competitive Position and Market Share", "long_question": "How does <company_name>'s competitive position and market share look in the context of current and emerging competitors?", "search_query": "<company_name> competitive position market share analysis"},
    {"area": "Competitive Landscape", "subarea": "Threats from New Entrants and Substitutes", "long_question": "What is the threat level to <company_name> from new entrants and substitute products or services?", "search_query": "<company_name> threats new entrants substitutes"}
])
due_diligence_queries.extend([
    {"area": "Quarterly Results Impact", "subarea": "Anticipation and Market Reaction", "long_question": "How might the market react to <company_name>'s upcoming quarterly results, and what are the anticipated outcomes if the results are better or worse than expected?", "search_query": "<company_name> quarterly results anticipation market reaction"},
    {"area": "Analyst Predictions and Outlook", "subarea": "Stock Exchange Analysts Consensus", "long_question": "What are the current predictions and consensus among stock exchange analysts regarding <company_name>'s stock?", "search_query": "<company_name> stock exchange analysts predictions consensus"},
    {"area": "Analyst Predictions and Outlook", "subarea": "Banks and Fund Houses Outlook", "long_question": "What is the outlook of banks and fund houses on <company_name>, and how might this influence the stock price?", "search_query": "<company_name> banks fund houses outlook"},
    {"area": "Ownership Structure and Risk Analysis", "subarea": "Holding and Ownership Structure", "long_question": "What is the current holding and ownership structure of <company_name>, and are there any significant risks associated with it?", "search_query": "<company_name> holding ownership structure risks"}
])
due_diligence_queries.extend([
    {"area": "Operational and Financial Health", "subarea": "Sourcing and Cost Management", "long_question": "Are there any changing patterns in <company_name>'s sourcing and costs that could negatively impact their financial health?", "search_query": "<company_name> sourcing costs financial impact"},
    {"area": "Operational and Financial Health", "subarea": "Debt and Working Capital Analysis", "long_question": "How does <company_name>'s debt level and working capital situation position them for potential financial strain?", "search_query": "<company_name> debt working capital analysis"},
    {"area": "Operational and Financial Health", "subarea": "Cost Structure and Profitability", "long_question": "Is <company_name>'s cost structure sustainable, and how does it affect their profitability?", "search_query": "<company_name> cost structure profitability analysis"},
    {"area": "Market Position and Competitive Landscape", "subarea": "Product or Service Concentration", "long_question": "How could <company_name>'s concentration in specific products or services pose a risk to their market position?", "search_query": "<company_name> product service concentration risk"},
    {"area": "Market Position and Competitive Landscape", "subarea": "Emerging Competition", "long_question": "What is the threat level of new competition entering the market and impacting <company_name>'s market share?", "search_query": "<company_name> emerging competition market impact"},
    {"area": "Consumer Behavior and Market Trends", "subarea": "Changing Consumer Patterns", "long_question": "Are there any noticeable shifts in consumer behavior or patterns that could affect <company_name>'s sales and revenue?", "search_query": "<company_name> changing consumer patterns impact"},
    {"area": "Consumer Behavior and Market Trends", "subarea": "Novelty Factor and Product Lifecycle", "long_question": "Is there a risk of the novelty factor of <company_name>'s products or services wearing off, leading to decreased demand?", "search_query": "<company_name> novelty factor product lifecycle"},
    {"area": "Valuation and Market Sentiment", "subarea": "Overvaluation and Market Correction", "long_question": "Is <company_name> currently overvalued, and could a good quarterly result still lead to a market correction where shorting the stock would be advantageous?", "search_query": "<company_name> overvaluation market correction"}
])

due_diligence_queries.extend([
    {"area": "Macroeconomic Factors", "subarea": "Global Economic Trends", "long_question": "How do global economic trends impact the industry and <company_name>?", "search_query": "global economic trends impact on <industry>"},
    {"area": "Legal and Compliance", "subarea": "International Regulatory Landscape", "long_question": "What are the key legal and compliance challenges facing <company_name> in its international operations?", "search_query": "<company_name> international legal compliance challenges"},
    {"area": "Social Media and Branding", "subarea": "Online Reputation and Engagement", "long_question": "How does <company_name>'s social media presence and online reputation affect its brand value and customer loyalty?", "search_query": "<company_name> social media online reputation impact"},
    {"area": "International Supply Chain Dependencies", "subarea": "Geopolitical Risks and Supply Chain", "long_question": "How could geopolitical tensions affect <company_name>'s supply chain and cost structure?", "search_query": "<company_name> geopolitical risks supply chain impact"},
    {"area": "Geopolitical Factors", "subarea": "Impact of Geopolitical Events", "long_question": "What are the potential impacts of current geopolitical events on the global market and <company_name>?", "search_query": "geopolitical events impact global market <industry>"},
    {"area": "General Market or Trend Level Factors", "subarea": "Industry Trends and Innovations", "long_question": "What are the latest trends and innovations in <company_name>'s industry, and how is the company positioned relative to these trends?", "search_query": "<industry> trends innovations impact on <company_name>"},
    {"area": "Execution and Operational Efficiency", "subarea": "Execution Risks", "long_question": "What execution risks could potentially derail <company_name>'s strategic initiatives and growth plans?", "search_query": "<company_name> execution risks strategic initiatives"},
    {"area": "Outdated and Stagnant Practices", "subarea": "Adaptability to Market Changes", "long_question": "How adaptable is <company_name> to rapid market changes and technological advancements?", "search_query": "<company_name> adaptability market changes"},
    {"area": "People, Shareholder, and Management Dynamics", "subarea": "Management and Shareholder Alignment", "long_question": "How aligned are <company_name>'s management and shareholders with respect to the company's long-term vision and strategy?", "search_query": "<company_name> management shareholder alignment"}
])

due_diligence_queries.extend([
    # Financial Health and Performance
    {"area": "Financial Health and Performance", "subarea": "Revenue and Profit Decline",
     "long_question": "What factors have contributed to any recent declines in <company_name>'s revenue and profit?",
     "search_query": "<company_name> revenue profit decline reasons"},
    {"area": "Financial Health and Performance", "subarea": "Margins",
     "long_question": "What are the challenges faced by <company_name> in maintaining its margins, and how do they compare to industry averages?",
     "search_query": "<company_name> margin challenges vs industry average"},
    {"area": "Financial Health and Performance", "subarea": "Balance Sheet Weaknesses",
     "long_question": "What weaknesses can be identified in <company_name>'s balance sheet, and how do they impact its financial stability?",
     "search_query": "<company_name> balance sheet weaknesses"},

    # Market Position and Competitive Advantage
    {"area": "Market Position and Competitive Advantage", "subarea": "Market Share Loss",
     "long_question": "What factors have led to <company_name> losing market share within its industry?",
     "search_query": "<company_name> market share loss reasons"},
    {"area": "Market Position and Competitive Advantage", "subarea": "Eroding Competitive Moat",
     "long_question": "How are <company_name>'s competitive advantages being challenged by new entrants or technological advancements?",
     "search_query": "<company_name> competitive advantages erosion"},

    # Management Quality and Governance
    {"area": "Management Quality and Governance", "subarea": "Leadership Concerns",
     "long_question": "What are the major concerns regarding <company_name>'s leadership team and their decision-making?",
     "search_query": "<company_name> leadership team concerns"},
    {"area": "Management Quality and Governance", "subarea": "Corporate Governance Issues",
     "long_question": "What issues have been raised concerning <company_name>'s corporate governance and transparency?",
     "search_query": "<company_name> corporate governance issues"},

    # Risks
    {"area": "Risks", "subarea": "Market and Industry-Specific Risks",
     "long_question": "What recent market and industry-specific risks have negatively impacted <company_name>?",
     "search_query": "<company_name> recent market industry risks"},
    {"area": "Risks", "subarea": "Company-Specific Risks",
     "long_question": "What are the significant operational, legal, or financial risks currently facing <company_name>?",
     "search_query": "<company_name> significant company-specific risks"},

    # Strategic Direction and Growth Prospects
    {"area": "Strategic Direction and Growth Prospects", "subarea": "Failed Expansion Plans",
     "long_question": "What have been the outcomes of <company_name>'s recent expansion plans, and where have they failed?",
     "search_query": "<company_name> failed expansion plans outcomes"},

    # Regulatory Environment
    {"area": "Regulatory Environment", "subarea": "Compliance Failures",
     "long_question": "How has <company_name> failed to comply with regulatory standards, and what have been the consequences?",
     "search_query": "<company_name> regulatory compliance failures"},

    # Additional Areas with a Focus on Negativity and Quantification
    {"area": "Technological Innovation and Digital Transformation", "subarea": "Technology Adoption Challenges",
     "long_question": "What challenges has <company_name> faced in adopting new technologies, and how does it impact its competitive position?",
     "search_query": "<company_name> technology adoption challenges"},
    {"area": "Customer Base and Market Demand", "subarea": "Customer Loss and Market Demand Decline",
     "long_question": "What factors have contributed to a loss of customers or a decline in market demand for <company_name>'s products or services?",
     "search_query": "<company_name> customer loss market demand decline"},
    {"area": "Supply Chain and Operational Efficiency", "subarea": "Supply Chain Disruptions",
     "long_question": "How have recent global disruptions impacted <company_name>'s supply chain and operational efficiency?",
     "search_query": "<company_name> supply chain disruptions impact"},
    {"area": "Intellectual Property and Innovation", "subarea": "R&D Investment Inefficiencies",
     "long_question": "How effective has <company_name>'s investment in R&D been, and what inefficiencies have been identified?",
     "search_query": "<company_name> R&D investment inefficiencies"},
    {"area": "Sustainability and Social Responsibility", "subarea": "Environmental and Social Failures",
     "long_question": "What environmental or social responsibility failures has <company_name> been associated with?",
     "search_query": "<company_name> environmental social failures"}
])

due_diligence_queries.extend([
    # Insider Activity and Sentiment
    {"area": "Insider Activity and Sentiment", "subarea": "Insider Trading Patterns",
     "long_question": "What patterns can be observed in recent insider trading activity for <company_name>, and do they indicate any concerns or positive sentiment?",
     "search_query": "<company_name> insider trading patterns analysis"},
    {"area": "Insider Activity and Sentiment", "subarea": "Management and Employee Turnover",
     "long_question": "How has the turnover rate for key management positions and employees been at <company_name>, and what are the potential implications?",
     "search_query": "<company_name> management employee turnover rate implications"},

    # Investor Relations and Transparency
    {"area": "Investor Relations and Transparency", "subarea": "Quality and Frequency of Disclosures",
     "long_question": "How transparent and timely are <company_name>'s financial disclosures and communications with investors?",
     "search_query": "<company_name> investor relations transparency disclosures"},
    {"area": "Investor Relations and Transparency", "subarea": "Responsiveness to Investor Concerns",
     "long_question": "How responsive has <company_name> been to addressing investor concerns or inquiries?",
     "search_query": "<company_name> responsiveness investor concerns"},

    # Brand Reputation and Customer Perception
    {"area": "Brand Reputation and Customer Perception", "subarea": "Customer Reviews and Feedback",
     "long_question": "What insights can be gleaned from customer reviews and feedback about <company_name>'s products or services?",
     "search_query": "<company_name> customer reviews feedback insights"},
    {"area": "Brand Reputation and Customer Perception", "subarea": "Brand Controversies and PR Crises",
     "long_question": "Has <company_name> faced any significant brand controversies or PR crises recently, and how were they handled?",
     "search_query": "<company_name> brand controversies PR crises"},

    # Cybersecurity and Data Privacy
    {"area": "Cybersecurity and Data Privacy", "subarea": "Data Breaches and Security Incidents",
     "long_question": "Has <company_name> experienced any major data breaches or cybersecurity incidents, and what were the financial and reputational impacts?",
     "search_query": "<company_name> data breaches cybersecurity incidents impact"},
    {"area": "Cybersecurity and Data Privacy", "subarea": "Compliance with Data Privacy Regulations",
     "long_question": "How compliant is <company_name> with relevant data privacy regulations like GDPR or CCPA?",
     "search_query": "<company_name> data privacy regulation compliance"},

    # Litigation and Legal Risks
    {"area": "Litigation and Legal Risks", "subarea": "Ongoing Lawsuits and Investigations",
     "long_question": "What significant ongoing lawsuits, investigations, or legal proceedings is <company_name> currently involved in?",
     "search_query": "<company_name> ongoing lawsuits investigations legal proceedings"},
    {"area": "Litigation and Legal Risks", "subarea": "Potential Legal Liabilities",
     "long_question": "Are there any potential legal liabilities or risks that could materially impact <company_name>'s financial performance or reputation?",
     "search_query": "<company_name> potential legal liabilities risks"},

    # Auditor Opinion and Accounting Quality
    {"area": "Auditor Opinion and Accounting Quality", "subarea": "Auditor Reports and Opinions",
     "long_question": "What opinions have <company_name>'s external auditors expressed in their recent reports, and were any issues or uncertainties highlighted?",
     "search_query": "<company_name> auditor reports opinions issues"},
    {"area": "Auditor Opinion and Accounting Quality", "subarea": "Accounting Irregularities or Restatements",
     "long_question": "Has <company_name> been subject to any accounting irregularities, financial restatements, or SEC investigations in the past?",
     "search_query": "<company_name> accounting irregularities restatements SEC investigations"}
])

due_diligence_queries.extend([
    # Promoter and Insider Activity
    {"area": "Promoter and Insider Activity", "subarea": "Pledging of Shares",
     "long_question": "What percentage of <company_name>'s promoter holdings are pledged, and how does this compare to industry peers?",
     "search_query": "<company_name> promoter share pledging percentage vs peers"},
    {"area": "Promoter and Insider Activity", "subarea": "Insider Trading and SEBI Violations",
     "long_question": "Have any of <company_name>'s promoters or insiders been involved in insider trading or SEBI violations?",
     "search_query": "<company_name> promoter insider trading SEBI violations"},
    # Related Party Transactions
    {"area": "Related Party Transactions", "subarea": "Nature and Materiality of Transactions",
     "long_question": "What is the nature and materiality of <company_name>'s related party transactions, and do they raise any red flags?",
     "search_query": "<company_name> related party transactions nature materiality red flags"},
    {"area": "Related Party Transactions", "subarea": "Impact on Financial Statements",
     "long_question": "How do related party transactions impact <company_name>'s financial statements and key ratios?",
     "search_query": "<company_name> related party transactions impact financial statements ratios"},
    # Corporate Governance and Board Composition
    {"area": "Corporate Governance and Board Composition", "subarea": "Independent Director Representation",
     "long_question": "What is the proportion of independent directors on <company_name>'s board, and how does it compare to best practices?",
     "search_query": "<company_name> board composition independent directors proportion best practices"},
    {"area": "Corporate Governance and Board Composition", "subarea": "Board Member Qualifications and Track Record",
     "long_question": "What are the qualifications and track records of <company_name>'s board members, and do they raise any concerns?",
     "search_query": "<company_name> board member qualifications track record concerns"},
    # Dividend Policy and Capital Allocation
    {"area": "Dividend Policy and Capital Allocation", "subarea": "Dividend Payout and Yield",
     "long_question": "What is <company_name>'s dividend payout ratio and yield, and how does it compare to industry averages?",
     "search_query": "<company_name> dividend payout ratio yield vs industry average"},
    {"area": "Dividend Policy and Capital Allocation", "subarea": "Capital Allocation Decisions",
     "long_question": "How effectively has <company_name> allocated capital in the past, and what are its future capital allocation plans?",
     "search_query": "<company_name> capital allocation decisions effectiveness future plans"},
    # Analyst Coverage and Recommendations
    {"area": "Analyst Coverage and Recommendations", "subarea": "Analyst Ratings and Price Targets",
     "long_question": "What is the current distribution of analyst ratings and price targets for <company_name>, and how has it changed over time?",
     "search_query": "<company_name> analyst ratings price targets distribution change over time"},
    {"area": "Analyst Coverage and Recommendations", "subarea": "Quality and Accuracy of Analyst Coverage",
     "long_question": "How accurate and reliable have analyst forecasts and recommendations been for <company_name> in the past?",
     "search_query": "<company_name> analyst forecast recommendation accuracy reliability track record"},
    # Industry-Specific Metrics and Benchmarks
    {"area": "Industry-Specific Metrics and Benchmarks", "subarea": "Key Performance Indicators (KPIs)",
     "long_question": "What are the most important industry-specific KPIs for <company_name>, and how does the company perform on these metrics?",
     "search_query": "<company_name> <industry> key performance indicators KPIs performance"},
    {"area": "Industry-Specific Metrics and Benchmarks", "subarea": "Peer Comparison and Benchmarking",
     "long_question": "How does <company_name>'s performance on industry-specific metrics compare to its closest competitors and peers?",
     "search_query": "<company_name> <industry> metrics performance vs competitors peers benchmarking"},
    # Shareholding Pattern and Institutional Ownership
    {"area": "Shareholding Pattern and Institutional Ownership", "subarea": "Promoter and FII/DII Holdings",
     "long_question": "What is the current shareholding pattern for <company_name>, including promoter stake and FII/DII holdings?",
     "search_query": "<company_name> shareholding pattern promoter stake FII DII holdings"},
    {"area": "Shareholding Pattern and Institutional Ownership", "subarea": "Changes in Institutional Ownership",
     "long_question": "How has institutional ownership in <company_name> changed over time, and what do these changes suggest about investor confidence?",
     "search_query": "<company_name> institutional ownership changes over time investor confidence implications"},
    # Taxation and Regulatory Factors
    {"area": "Taxation and Regulatory Factors", "subarea": "Tax Litigations and Disputes",
     "long_question": "Is <company_name> involved in any significant tax litigations or disputes, and what potential impact could these have?",
     "search_query": "<company_name> tax litigations disputes potential impact"},
    {"area": "Taxation and Regulatory Factors", "subarea": "GST and Other Regulatory Changes",
     "long_question": "How have recent changes in GST rates or other regulatory factors affected <company_name>'s operations and profitability?",
     "search_query": "<company_name> GST regulatory changes impact operations profitability"},
    # Debt Profile and Credit Ratings
    {"area": "Debt Profile and Credit Ratings", "subarea": "Debt Maturity Profile and Refinancing Risks",
     "long_question": "What is the maturity profile of <company_name>'s outstanding debt, and are there any significant refinancing risks?",
     "search_query": "<company_name> debt maturity profile refinancing risks"},
    {"area": "Debt Profile and Credit Ratings", "subarea": "Credit Rating Trends and Outlooks",
     "long_question": "What are the current credit ratings for <company_name>, and what are the rating outlooks provided by major agencies?",
     "search_query": "<company_name> credit ratings trends outlooks major agencies"},
    # Foreign Exchange and Commodity Price Risks
    {"area": "Foreign Exchange and Commodity Price Risks", "subarea": "Forex Exposure and Hedging Strategies",
     "long_question": "What is the extent of <company_name>'s foreign exchange exposure, and how effectively does it manage this risk through hedging?",
     "search_query": "<company_name> forex exposure hedging strategies effectiveness"},
    {"area": "Foreign Exchange and Commodity Price Risks", "subarea": "Sensitivity to Commodity Price Fluctuations",
     "long_question": "How sensitive is <company_name>'s profitability to fluctuations in key commodity prices, and how does it mitigate this risk?",
     "search_query": "<company_name> sensitivity commodity price fluctuations risk mitigation strategies"},
    # Contingent Liabilities and Off-Balance Sheet Risks
    {"area": "Contingent Liabilities and Off-Balance Sheet Risks", "subarea": "Guarantees and Contingent Liabilities",
     "long_question": "What guarantees or contingent liabilities does <company_name> have, and how do they impact its risk profile?",
     "search_query": "<company_name> guarantees contingent liabilities impact risk profile"},
    {"area": "Contingent Liabilities and Off-Balance Sheet Risks", "subarea": "Off-Balance Sheet Arrangements",
     "long_question": "Does <company_name> engage in any significant off-balance sheet arrangements, and what are the associated risks?",
     "search_query": "<company_name> off-balance sheet arrangements associated risks"}
])
due_diligence_queries.extend([
    # Promoter and Management Integrity
    {"area": "Promoter and Management Integrity", "subarea": "Background and Reputation Check",
     "long_question": "Are there any red flags in the background or reputation of <company_name>'s promoters or key management personnel?",
     "search_query": "<company_name> promoter management background reputation red flags"},
    {"area": "Promoter and Management Integrity", "subarea": "Related Party Transactions and Conflicts of Interest",
     "long_question": "Do <company_name>'s related party transactions or potential conflicts of interest raise concerns about management integrity?",
     "search_query": "<company_name> related party transactions conflicts of interest management integrity concerns"},
    # Auditor Quality and Independence
    {"area": "Auditor Quality and Independence", "subarea": "Auditor Reputation and Track Record",
     "long_question": "What is the reputation and track record of <company_name>'s auditor, and have they been associated with any audit failures or controversies?",
     "search_query": "<company_name> auditor reputation track record audit failures controversies"},
    {"area": "Auditor Quality and Independence", "subarea": "Auditor Rotation and Tenure",
     "long_question": "How long has <company_name>'s current auditor been engaged, and does the lack of auditor rotation raise concerns about independence?",
     "search_query": "<company_name> auditor rotation tenure independence concerns"},
    # Earnings Quality and Manipulation
    {"area": "Earnings Quality and Manipulation", "subarea": "Aggressive Revenue Recognition and Accounting Practices",
     "long_question": "Does <company_name> engage in aggressive revenue recognition or accounting practices that could be masking underlying weaknesses?",
     "search_query": "<company_name> aggressive revenue recognition accounting practices earnings quality concerns"},
    {"area": "Earnings Quality and Manipulation", "subarea": "Frequent Changes in Accounting Policies",
     "long_question": "Has <company_name> made frequent changes to its accounting policies, and could these changes be attempts to manipulate reported earnings?",
     "search_query": "<company_name> frequent accounting policy changes earnings manipulation concerns"},
    # Cash Flow and Liquidity Analysis
    {"area": "Cash Flow and Liquidity Analysis", "subarea": "Cash Flow Trends and Sustainability",
     "long_question": "What are the trends in <company_name>'s operating, investing, and financing cash flows, and are they sustainable?",
     "search_query": "<company_name> operating investing financing cash flow trends sustainability analysis"},
    {"area": "Cash Flow and Liquidity Analysis", "subarea": "Working Capital Management and Liquidity Ratios",
     "long_question": "How effectively does <company_name> manage its working capital, and what do its liquidity ratios reveal about its short-term financial health?",
     "search_query": "<company_name> working capital management liquidity ratios analysis"},
    # Competitor and Industry Analysis
    {"area": "Competitor and Industry Analysis", "subarea": "Competitive Positioning and Market Share Trends",
     "long_question": "How has <company_name>'s competitive positioning and market share changed over time, and what are the implications for its future prospects?",
     "search_query": "<company_name> competitive positioning market share trends analysis"},
    {"area": "Competitor and Industry Analysis", "subarea": "Industry Disruption and Technological Threats",
     "long_question": "Is <company_name>'s industry vulnerable to disruption or technological threats, and how well-positioned is the company to navigate these challenges?",
     "search_query": "<company_name> <industry> disruption technological threats vulnerability analysis"},
    # Corporate Governance Red Flags
    {"area": "Corporate Governance Red Flags", "subarea": "Board Independence and Effectiveness",
     "long_question": "Are there any concerns about the independence or effectiveness of <company_name>'s board of directors?",
     "search_query": "<company_name> board of directors independence effectiveness concerns"},
    {"area": "Corporate Governance Red Flags", "subarea": "Executive Compensation and Alignment",
     "long_question": "Is <company_name>'s executive compensation structure aligned with shareholder interests, or are there any red flags?",
     "search_query": "<company_name> executive compensation shareholder alignment red flags"},
    # Whistleblower Complaints and Employee Sentiment
    {"area": "Whistleblower Complaints and Employee Sentiment", "subarea": "History of Whistleblower Complaints",
     "long_question": "Has <company_name> faced any significant whistleblower complaints in the past, and how were they handled?",
     "search_query": "<company_name> whistleblower complaints history handling"},
    {"area": "Whistleblower Complaints and Employee Sentiment", "subarea": "Employee Reviews and Glassdoor Ratings",
     "long_question": "What insights can be gleaned from employee reviews and Glassdoor ratings about <company_name>'s work culture and employee sentiment?",
     "search_query": "<company_name> employee reviews Glassdoor ratings work culture sentiment insights"},
    # Environmental, Social, and Governance (ESG) Risks
    {"area": "Environmental, Social, and Governance (ESG) Risks", "subarea": "Environmental Compliance and Sustainability",
     "long_question": "How well does <company_name> manage its environmental impact and comply with relevant regulations?",
     "search_query": "<company_name> environmental impact compliance sustainability performance"},
    {"area": "Environmental, Social, and Governance (ESG) Risks", "subarea": "Social Responsibility and Ethical Concerns",
     "long_question": "Are there any concerns about <company_name>'s social responsibility practices or ethical conduct?",
     "search_query": "<company_name> social responsibility ethical concerns"},
    # Quantitative Metrics and Red Flags
    {"area": "Quantitative Metrics and Red Flags", "subarea": "Earnings Manipulation Indicators",
     "long_question": "Do quantitative metrics like the Beneish M-Score or Altman Z-Score suggest potential earnings manipulation at <company_name>?",
     "search_query": "<company_name> Beneish M-Score Altman Z-Score earnings manipulation indicators"},
    {"area": "Quantitative Metrics and Red Flags", "subarea": "Financial Ratios and Industry Benchmarking",
     "long_question": "How do <company_name>'s key financial ratios compare to industry benchmarks, and are there any red flags?",
     "search_query": "<company_name> financial ratios industry benchmarking red flags"},
    # Short Selling Indicators and Sentiment
    {"area": "Short Selling Indicators and Sentiment", "subarea": "Short Interest and Short Squeeze Potential",
     "long_question": "What is the current level of short interest in <company_name>, and is there potential for a short squeeze?",
     "search_query": "<company_name> short interest ratio short squeeze potential"},
    {"area": "Short Selling Indicators and Sentiment", "subarea": "Bearish Analyst Reports and Sentiment",
     "long_question": "Have any reputable analysts issued bearish reports or expressed negative sentiment about <company_name>?",
     "search_query": "<company_name> bearish analyst reports negative sentiment"},
    # Sector-Specific Risks and Challenges
    {"area": "Sector-Specific Risks and Challenges", "subarea": "Regulatory and Policy Risks",
     "long_question": "What are the key regulatory and policy risks facing <company_name>'s sector, and how is the company positioned to navigate them?",
     "search_query": "<company_name> <sector> regulatory policy risks challenges"},
    {"area": "Sector-Specific Risks and Challenges", "subarea": "Cyclicality and Demand Volatility",
     "long_question": "Is <company_name>'s sector prone to cyclicality or demand volatility, and how well can the company withstand downturns?",
     "search_query": "<company_name> <sector> cyclicality demand volatility resilience"}
])

due_diligence_queries.extend([
    # Previous queries here...
    # New queries with subarea included:
    {
        "area": "Annual and Quarterly Reports",
        "subarea": "Financial Statements Analysis",
        "long_question": "What insights can be gained from analyzing <company_name>'s financial statements (balance sheet, income statement, cash flow statement) over the past 3-5 years? Are there any concerning trends, discrepancies, or red flags?",
        "search_query": "<company_name> financial statements analysis balance sheet income statement cash flow trends discrepancies red flags"
    },
    {
        "area": "Annual and Quarterly Reports",
        "subarea": "Management Discussion and Analysis (MD&A)",
        "long_question": "What key information is provided in <company_name>'s MD&A section? Are there any significant changes, challenges, or opportunities discussed by management? How does the company's strategy and outlook align with its financial performance?",
        "search_query": "<company_name> management discussion and analysis MD&A key information changes challenges opportunities strategy outlook alignment financial performance"
    },
    {
        "area": "Annual and Quarterly Reports",
        "subarea": "Risk Factors",
        "long_question": "What are the major risk factors disclosed by <company_name> in its annual report? How have these risks evolved over time, and what steps is the company taking to mitigate them? Are there any new or emerging risks that could materially impact the company's operations or financial health?",
        "search_query": "<company_name> risk factors annual report evolution mitigation steps new emerging risks material impact operations financial health"
    },
    {
        "area": "Annual and Quarterly Reports",
        "subarea": "Auditor's Report",
        "long_question": "What is the opinion of <company_name>'s independent auditor on its financial statements? Are there any qualifications, disclaimers, or emphasis of matter paragraphs in the auditor's report? Has the company changed auditors recently, and if so, what were the reasons behind the change?",
        "search_query": "<company_name> auditor's report opinion qualifications disclaimers emphasis matter paragraphs auditor change reasons"
    },
    {
        "area": "Annual and Quarterly Reports",
        "subarea": "Related Party Transactions",
        "long_question": "What related party transactions has <company_name> disclosed in its annual report? Are these transactions conducted at arm's length, and do they raise any concerns about potential conflicts of interest or corporate governance issues?",
        "search_query": "<company_name> related party transactions annual report arm's length concerns conflicts interest corporate governance issues"
    },
    {
        "area": "Annual and Quarterly Reports",
        "subarea": "Contingent Liabilities and Off-Balance Sheet Arrangements",
        "long_question": "What contingent liabilities and off-balance sheet arrangements has <company_name> disclosed in its annual report? How significant are these items, and what potential impact could they have on the company's financial position?",
        "search_query": "<company_name> contingent liabilities off-balance sheet arrangements annual report significance potential impact financial position"
    },
    {
        "area": "Annual and Quarterly Reports",
        "subarea": "Segment Reporting",
        "long_question": "How does <company_name> report its financial results by business segment or geography? Are there any segments that are underperforming or facing significant challenges? How do the segment results compare to the company's overall performance and its peers?",
        "search_query": "<company_name> segment reporting business geography underperforming challenges comparison overall performance peers"
    },
    {
        "area": "Annual and Quarterly Reports",
        "subarea": "Key Performance Indicators (KPIs)",
        "long_question": "What are the key performance indicators (KPIs) that <company_name> uses to measure its success? How have these KPIs trended over time, and how do they compare to industry benchmarks? Are there any KPIs that the company has stopped reporting or changed the definition of?",
        "search_query": "<company_name> key performance indicators KPIs success measurement trends industry benchmarks stopped reporting changed definition"
    },
    {
        "area": "Annual and Quarterly Reports",
        "subarea": "Earnings Quality and Manipulation",
        "long_question": "Are there any signs of earnings manipulation or aggressive accounting practices in <company_name>'s financial statements? How do the company's non-GAAP financial measures compare to its GAAP results? Are there any unusual or one-time items that are distorting the company's reported earnings?",
        "search_query": "<company_name> earnings manipulation aggressive accounting practices financial statements non-GAAP GAAP comparison unusual one-time items distorting reported earnings"
    },
    {
        "area": "Annual and Quarterly Reports",
        "subarea": "Management Compensation and Incentives",
        "long_question": "How is <company_name>'s management team compensated, and what are the key performance metrics that determine their bonuses or stock awards? Do these incentives align with long-term shareholder interests, or do they encourage short-term thinking or excessive risk-taking?",
        "search_query": "<company_name> management compensation incentives performance metrics bonuses stock awards alignment long-term shareholder interests short-term thinking excessive risk-taking"
    }
])

due_diligence_queries.extend([
    {
        "area": "Conference Call Analysis",
        "subarea": "Growth Prospects",
        "long_question": "What growth prospects were discussed in <company_name>'s latest conference call? Were any specific markets, products, or services highlighted as key drivers of future growth?",
        "search_query": "<company_name> conference call growth prospects markets products services future drivers"
    },
    {
        "area": "Conference Call Analysis",
        "subarea": "Competitive Moat and Strategy",
        "long_question": "How does <company_name> describe its competitive moat and strategy during the conference call? Are there any unique strengths or capabilities mentioned that could sustain its competitive advantage?",
        "search_query": "<company_name> conference call competitive moat strategy strengths capabilities competitive advantage"
    },
    {
        "area": "Conference Call Analysis",
        "subarea": "Long-term Vision",
        "long_question": "What long-term vision or goals were articulated by <company_name>'s management during the conference call? How does the company plan to achieve these goals?",
        "search_query": "<company_name> conference call long-term vision goals management achievement plan"
    },
    {
        "area": "Conference Call Analysis",
        "subarea": "Quarterly Vision and Operational Efficiency",
        "long_question": "During the conference call, how did <company_name>'s management discuss the quarterly performance in relation to operational efficiency? Were any specific challenges or successes mentioned?",
        "search_query": "<company_name> conference call quarterly performance operational efficiency challenges successes"
    },
    {
        "area": "Conference Call Analysis",
        "subarea": "Debt and Financial Health",
        "long_question": "What insights were provided about <company_name>'s debt levels and overall financial health during the conference call? Were any strategies for debt management or financial improvement discussed?",
        "search_query": "<company_name> conference call debt levels financial health debt management strategies financial improvement"
    },
    {
        "area": "Conference Call Analysis",
        "subarea": "Management's Confidence and Tone",
        "long_question": "How confident did <company_name>'s management sound during the conference call? Were there any discrepancies between the tone of the management and the actual financial performance?",
        "search_query": "<company_name> conference call management confidence tone discrepancies financial performance"
    },
    {
        "area": "Conference Call Analysis",
        "subarea": "Future Challenges and Opportunities",
        "long_question": "What future challenges and opportunities were discussed by <company_name>'s management during the conference call? How is the company positioned to address these challenges and capitalize on opportunities?",
        "search_query": "<company_name> conference call future challenges opportunities management positioning"
    },
    {
        "area": "Conference Call Analysis",
        "subarea": "Investor Questions and Management Responses",
        "long_question": "What were the key concerns or questions raised by investors during <company_name>'s conference call, and how did management respond? Were the responses satisfactory and confidence-inspiring?",
        "search_query": "<company_name> conference call investor questions management responses satisfactory confidence"
    },
    {
        "area": "Conference Call Analysis",
        "subarea": "Non-Financial Metrics",
        "long_question": "Were any non-financial metrics or key performance indicators discussed during <company_name>'s conference call that could impact the company's future performance?",
        "search_query": "<company_name> conference call non-financial metrics key performance indicators future performance impact"
    },
    {
        "area": "Conference Call Analysis",
        "subarea": "Guidance and Forecast",
        "long_question": "What guidance or forecast was provided by <company_name>'s management during the conference call regarding future earnings, revenue, or other financial metrics?",
        "search_query": "<company_name> conference call guidance forecast future earnings revenue financial metrics"
    }
])


due_diligence_queries.extend([
    {
        "area": "Conference Call Analysis",
        "subarea": "Industry Trends and Market Share",
        "long_question": "What insights did <company_name>'s management provide about industry trends and the company's market share during the conference call? Are there any significant changes or disruptions expected in the industry landscape?",
        "search_query": "<company_name> conference call industry trends market share changes disruptions landscape"
    },
    {
        "area": "Conference Call Analysis",
        "subarea": "Regulatory Environment and Legal Matters",
        "long_question": "Were any regulatory changes, legal matters, or compliance issues discussed during <company_name>'s conference call that could impact the company's operations or financial performance?",
        "search_query": "<company_name> conference call regulatory changes legal matters compliance issues impact operations financial performance"
    },
    {
        "area": "Conference Call Analysis",
        "subarea": "Mergers, Acquisitions, and Partnerships",
        "long_question": "Did <company_name>'s management discuss any recent or planned mergers, acquisitions, or strategic partnerships during the conference call? How might these impact the company's growth prospects and competitive position?",
        "search_query": "<company_name> conference call mergers acquisitions strategic partnerships impact growth prospects competitive position"
    },
    {
        "area": "Conference Call Analysis",
        "subarea": "Research and Development (R&D) and Innovation",
        "long_question": "What updates did <company_name>'s management provide on the company's R&D efforts and innovation pipeline during the conference call? Are there any new products or services expected to drive future growth?",
        "search_query": "<company_name> conference call research development R&D innovation pipeline new products services future growth"
    },
    {
        "area": "Conference Call Analysis",
        "subarea": "Sustainability and Environmental, Social, and Governance (ESG) Factors",
        "long_question": "Were any sustainability initiatives or ESG factors discussed during <company_name>'s conference call? How is the company addressing environmental and social concerns, and what impact might these have on its long-term performance?",
        "search_query": "<company_name> conference call sustainability initiatives ESG factors environmental social concerns impact long-term performance"
    },
    {
        "area": "Conference Call Analysis",
        "subarea": "Human Capital Management",
        "long_question": "What insights did <company_name>'s management provide about the company's human capital management during the conference call? Were there any discussions about employee retention, talent acquisition, or workforce planning?",
        "search_query": "<company_name> conference call human capital management employee retention talent acquisition workforce planning"
    },
    {
        "area": "Conference Call Analysis",
        "subarea": "Supply Chain and Logistics",
        "long_question": "Did <company_name>'s management discuss any supply chain or logistics challenges during the conference call? How is the company managing these issues, and what impact might they have on its operations and financial performance?",
        "search_query": "<company_name> conference call supply chain logistics challenges management impact operations financial performance"
    },
    {
        "area": "Conference Call Analysis",
        "subarea": "Shareholder Returns and Capital Allocation",
        "long_question": "What did <company_name>'s management say about shareholder returns and capital allocation during the conference call? Were any plans for dividends, share buybacks, or capital expenditures discussed?",
        "search_query": "<company_name> conference call shareholder returns capital allocation dividends share buybacks capital expenditures"
    }
])

due_diligence_queries.extend([
    {
        "area": "Social Media Analysis",
        "subarea": "Market Sentiment",
        "long_question": "What is the overall market sentiment towards <company_name> on Twitter and Reddit? Are there any notable trends or shifts in sentiment over time?",
        "search_query": "<company_name> Twitter Reddit market sentiment trends shifts"
    },
    {
        "area": "Social Media Analysis",
        "subarea": "Investor Opinions",
        "long_question": "What are the prevailing investor opinions about <company_name> on investment and market-focused subreddits? Are there any specific concerns or bullish views expressed by the investor community?",
        "search_query": "<company_name> investment market subreddits investor opinions concerns bullish views"
    },
    {
        "area": "Social Media Analysis",
        "subarea": "Product or Service Feedback",
        "long_question": "What feedback or experiences are customers sharing about <company_name>'s products or services on Twitter and Reddit? Are there any recurring issues or praise that could impact the company's reputation and growth prospects?",
        "search_query": "<company_name> Twitter Reddit customer feedback experiences product service issues praise reputation growth prospects"
    },
    {
        "area": "Social Media Analysis",
        "subarea": "Competitive Landscape",
        "long_question": "How do discussions on Twitter and Reddit compare <company_name> to its competitors? Are there any insights into the company's competitive advantages or disadvantages?",
        "search_query": "<company_name> Twitter Reddit competitive landscape competitors advantages disadvantages"
    },
    {
        "area": "Social Media Analysis",
        "subarea": "Management and Leadership",
        "long_question": "What are people saying about <company_name>'s management and leadership on Twitter and Reddit? Are there any concerns about their vision, strategy, or execution?",
        "search_query": "<company_name> Twitter Reddit management leadership vision strategy execution concerns"
    },
    {
        "area": "Social Media Analysis",
        "subarea": "Financial Health and Debt",
        "long_question": "Are there any discussions on Twitter or Reddit about <company_name>'s financial health, debt levels, or cash flow? Do these discussions raise any red flags or point to potential opportunities?",
        "search_query": "<company_name> Twitter Reddit financial health debt levels cash flow red flags opportunities"
    },
    {
        "area": "Social Media Analysis",
        "subarea": "Operational Efficiency and Innovation",
        "long_question": "What insights can be gleaned from Twitter and Reddit about <company_name>'s operational efficiency and innovation efforts? Are there any notable successes or challenges being discussed?",
        "search_query": "<company_name> Twitter Reddit operational efficiency innovation successes challenges"
    },
    {
        "area": "Social Media Analysis",
        "subarea": "ESG and Sustainability",
        "long_question": "How is <company_name> perceived on Twitter and Reddit in terms of its ESG (Environmental, Social, and Governance) practices and sustainability efforts? Are there any concerns or positive sentiments expressed?",
        "search_query": "<company_name> Twitter Reddit ESG environmental social governance sustainability concerns positive sentiments"
    },
    {
        "area": "Social Media Analysis",
        "subarea": "Rumors and Speculation",
        "long_question": "Are there any notable rumors or speculations about <company_name> circulating on Twitter or Reddit that could impact its stock price or future prospects? How credible are these rumors, and what potential impact could they have?",
        "search_query": "<company_name> Twitter Reddit rumors speculation stock price future prospects credibility impact"
    },
    {
        "area": "Social Media Analysis",
        "subarea": "Investor Sentiment and Market Trends",
        "long_question": "What is the general sentiment among investors on Twitter and Reddit regarding the broader market trends and macroeconomic factors that could impact <company_name>? Are there any specific concerns or opportunities identified?",
        "search_query": "<company_name> Twitter Reddit investor sentiment market trends macroeconomic factors concerns opportunities"
    }
])

due_diligence_queries.extend([
    {
        "area": "Social Media Analysis",
        "subarea": "Customer Satisfaction",
        "long_question": "What is the level of customer satisfaction for <company_name> based on discussions on Twitter and Reddit? Are there any common complaints or praises that could indicate the quality of the company's products or services?",
        "search_query": "<company_name> Twitter Reddit customer satisfaction complaints praises"
    },
    {
        "area": "Social Media Analysis",
        "subarea": "Employee Satisfaction",
        "long_question": "Are there any discussions from current or former employees of <company_name> on Twitter and Reddit that could provide insights into the company's culture, management style, and employee satisfaction?",
        "search_query": "<company_name> Twitter Reddit employee satisfaction culture management"
    },
    {
        "area": "Social Media Analysis",
        "subarea": "Brand Reputation",
        "long_question": "How is <company_name>'s brand reputation perceived on Twitter and Reddit? Are there any recent events or news that have significantly impacted the company's reputation?",
        "search_query": "<company_name> Twitter Reddit brand reputation events news"
    },
    {
        "area": "Social Media Analysis",
        "subarea": "Crisis Management",
        "long_question": "Are there any discussions on Twitter and Reddit about how <company_name> has handled crises or controversies? How has the company's response been perceived by the public?",
        "search_query": "<company_name> Twitter Reddit crisis management controversies response"
    },
    {
        "area": "Social Media Analysis",
        "subarea": "Product Innovation",
        "long_question": "What are the discussions on Twitter and Reddit about <company_name>'s product innovation? Are there any upcoming products or services that the market is particularly excited about?",
        "search_query": "<company_name> Twitter Reddit product innovation upcoming products services"
    },
    {
        "area": "Social Media Analysis",
        "subarea": "Strategic Partnerships",
        "long_question": "Are there any discussions on Twitter and Reddit about <company_name>'s strategic partnerships? How are these partnerships perceived and what impact could they have on the company's future growth?",
        "search_query": "<company_name> Twitter Reddit strategic partnerships impact future growth"
    },
    {
        "area": "Social Media Analysis",
        "subarea": "Regulatory Changes",
        "long_question": "What are the discussions on Twitter and Reddit about any regulatory changes that could impact <company_name>? How might these changes affect the company's operations or financial performance?",
        "search_query": "<company_name> Twitter Reddit regulatory changes impact operations financial performance"
    },
    {
        "area": "Social Media Analysis",
        "subarea": "Industry Disruptions",
        "long_question": "Are there any discussions on Twitter and Reddit about potential industry disruptions that could impact <company_name>? How is the company positioned to handle these disruptions?",
        "search_query": "<company_name> Twitter Reddit industry disruptions impact company position"
    }
])

due_diligence_queries.extend([
    {
        "area": "Social Media Analysis",
        "subarea": "Influencer and Analyst Opinions",
        "long_question": "What are the opinions of key influencers and financial analysts about <company_name> on Twitter and Reddit? How do these opinions sway market sentiment or stock performance?",
        "search_query": "<company_name> Twitter Reddit influencer analyst opinions market sentiment stock performance"
    },
    {
        "area": "Social Media Analysis",
        "subarea": "Meme Stocks and Viral Trends",
        "long_question": "Has <company_name> been subject to meme stock phenomena or viral trends on platforms like Reddit? What impact have these trends had on the company's stock volatility and investor interest?",
        "search_query": "<company_name> Reddit meme stock viral trends stock volatility investor interest"
    },
    {
        "area": "Social Media Analysis",
        "subarea": "Community Engagement and Loyalty",
        "long_question": "How engaged is <company_name>'s community on social media platforms? Are there signs of strong brand loyalty or community support that could indicate a resilient customer base?",
        "search_query": "<company_name> Twitter Reddit community engagement brand loyalty customer base"
    },
    {
        "area": "Social Media Analysis",
        "subarea": "Social Media Campaigns and Marketing Effectiveness",
        "long_question": "How effective are <company_name>'s social media campaigns and marketing strategies on platforms like Twitter and Reddit? Are these campaigns positively influencing brand perception and sales?",
        "search_query": "<company_name> Twitter Reddit social media campaigns marketing effectiveness brand perception sales"
    },
    {
        "area": "Social Media Analysis",
        "subarea": "Public Relations and Media Coverage",
        "long_question": "What is the nature of media coverage and public relations efforts of <company_name> as discussed on Twitter and Reddit? How do these efforts affect the company's public image and investor confidence?",
        "search_query": "<company_name> Twitter Reddit public relations media coverage public image investor confidence"
    },
    {
        "area": "Social Media Analysis",
        "subarea": "Legal Challenges and Litigation",
        "long_question": "Are there any discussions about current or potential legal challenges and litigation facing <company_name> on Twitter and Reddit? How could these legal matters impact the company's financial health and reputation?",
        "search_query": "<company_name> Twitter Reddit legal challenges litigation financial health reputation"
    },
    {
        "area": "Social Media Analysis",
        "subarea": "Technological Advancements and R&D",
        "long_question": "What are the discussions around <company_name>'s technological advancements and research & development efforts on Twitter and Reddit? How are these advancements perceived in terms of driving future growth?",
        "search_query": "<company_name> Twitter Reddit technological advancements research development future growth"
    },
    {
        "area": "Social Media Analysis",
        "subarea": "Global Expansion and Market Penetration",
        "long_question": "How is <company_name>'s global expansion and market penetration strategy discussed on Twitter and Reddit? What insights can be gathered about the company's growth potential in new markets?",
        "search_query": "<company_name> Twitter Reddit global expansion market penetration growth potential"
    },
    {
        "area": "Social Media Analysis",
        "subarea": "Supply Chain and Logistics",
        "long_question": "Are there any insights or concerns regarding <company_name>'s supply chain and logistics as discussed on Twitter and Reddit? How might these factors affect the company's operational efficiency and profitability?",
        "search_query": "<company_name> Twitter Reddit supply chain logistics operational efficiency profitability"
    },
    {
        "area": "Social Media Analysis",
        "subarea": "Geopolitical Risks and Economic Factors",
        "long_question": "What discussions are there on Twitter and Reddit about geopolitical risks and economic factors affecting <company_name>? How do these external factors potentially impact the company's performance?",
        "search_query": "<company_name> Twitter Reddit geopolitical risks economic factors performance impact"
    }
])

due_diligence_queries.extend([
    {
        "area": "Quantitative Social Media Analysis",
        "subarea": "Return on Ad Spend (ROAS)",
        "long_question": "What is the estimated Return on Ad Spend (ROAS) for <company_name>'s social media campaigns on platforms like Twitter and Reddit? How does this compare to industry benchmarks?",
        "search_query": "<company_name> Twitter Reddit ROAS comparison industry benchmarks"
    },
    {
        "area": "Quantitative Social Media Analysis",
        "subarea": "Influencer Engagement Metrics",
        "long_question": "How many influencers and financial analysts are talking about <company_name> on Twitter and Reddit? What is the average engagement rate (likes, shares, comments) of these discussions?",
        "search_query": "<company_name> Twitter Reddit influencer engagement rate"
    },
    {
        "area": "Quantitative Social Media Analysis",
        "subarea": "Sentiment Analysis",
        "long_question": "What is the sentiment analysis score of discussions about <company_name> on Twitter and Reddit? How does sentiment correlate with stock price movements?",
        "search_query": "<company_name> Twitter Reddit sentiment analysis stock price correlation"
    },
    {
        "area": "Quantitative Social Media Analysis",
        "subarea": "Brand Loyalty and Community Engagement",
        "long_question": "What metrics can quantify brand loyalty and community engagement for <company_name> on social media platforms? How do these metrics trend over time?",
        "search_query": "<company_name> Twitter Reddit brand loyalty community engagement metrics trend"
    },
    {
        "area": "Quantitative Social Media Analysis",
        "subarea": "Viral Trends and Meme Stock Analysis",
        "long_question": "How many times has <company_name> been mentioned in the context of meme stocks or viral trends on Reddit? What is the volatility index of the stock during these periods?",
        "search_query": "<company_name> Reddit meme stock mentions volatility index"
    },
    {
        "area": "Quantitative Social Media Analysis",
        "subarea": "Crisis Impact Analysis",
        "long_question": "Can we quantify the impact of a specific crisis or controversy on <company_name>'s social media sentiment and stock performance? What recovery patterns are observed?",
        "search_query": "<company_name> Twitter Reddit crisis impact analysis stock performance recovery patterns"
    },
    {
        "area": "Quantitative Social Media Analysis",
        "subarea": "Product Launch and Innovation Buzz",
        "long_question": "What is the volume of discussions and engagement rate around new product launches or innovations by <company_name> on Twitter and Reddit? How does this buzz correlate with sales or stock performance?",
        "search_query": "<company_name> Twitter Reddit product launch innovation buzz sales stock correlation"
    },
    {
        "area": "Quantitative Social Media Analysis",
        "subarea": "Competitive Analysis",
        "long_question": "How does <company_name>'s social media presence and engagement metrics compare with its main competitors? What insights can be drawn from comparative sentiment analysis?",
        "search_query": "<company_name> Twitter Reddit competitive analysis sentiment"
    },
    {
        "area": "Quantitative Social Media Analysis",
        "subarea": "Legal and Regulatory Discussion Volume",
        "long_question": "What is the volume and sentiment of discussions related to legal challenges or regulatory changes affecting <company_name> on Twitter and Reddit? How do these discussions impact investor sentiment?",
        "search_query": "<company_name> Twitter Reddit legal regulatory discussion volume sentiment investor impact"
    },
    {
        "area": "Quantitative Social Media Analysis",
        "subarea": "Geopolitical and Economic Discussion Impact",
        "long_question": "Can we quantify the volume and sentiment of discussions on Twitter and Reddit about geopolitical or economic factors affecting <company_name>? How do these factors correlate with market performance?",
        "search_query": "<company_name> Twitter Reddit geopolitical economic discussion volume sentiment market performance correlation"
    }
])

due_diligence_queries.extend([
    {
        "area": "Quantitative Social Media Analysis",
        "subarea": "Return on Ad Spend (ROAS)",
        "long_question": "What is the estimated Return on Ad Spend (ROAS) for <company_name>'s social media campaigns on platforms like Twitter and Reddit? How does this compare to industry benchmarks?",
        "search_query": "<company_name> Twitter Reddit ROAS comparison industry benchmarks"
    },
    {
        "area": "Quantitative Social Media Analysis",
        "subarea": "Influencer Engagement Metrics",
        "long_question": "How many influencers and financial analysts are talking about <company_name> on Twitter and Reddit? What is the average engagement rate (likes, shares, comments) of these discussions?",
        "search_query": "<company_name> Twitter Reddit influencer engagement rate"
    },
    {
        "area": "Quantitative Social Media Analysis",
        "subarea": "Sentiment Analysis",
        "long_question": "What is the sentiment analysis score of discussions about <company_name> on Twitter and Reddit? How does sentiment correlate with stock price movements?",
        "search_query": "<company_name> Twitter Reddit sentiment analysis stock price correlation"
    },
    {
        "area": "Quantitative Social Media Analysis",
        "subarea": "Brand Loyalty and Community Engagement",
        "long_question": "What metrics can quantify brand loyalty and community engagement for <company_name> on social media platforms? How do these metrics trend over time?",
        "search_query": "<company_name> Twitter Reddit brand loyalty community engagement metrics trend"
    },
    {
        "area": "Quantitative Social Media Analysis",
        "subarea": "Viral Trends and Meme Stock Analysis",
        "long_question": "How many times has <company_name> been mentioned in the context of meme stocks or viral trends on Reddit? What is the volatility index of the stock during these periods?",
        "search_query": "<company_name> Reddit meme stock mentions volatility index"
    },
    {
        "area": "Quantitative Social Media Analysis",
        "subarea": "Crisis Impact Analysis",
        "long_question": "Can we quantify the impact of a specific crisis or controversy on <company_name>'s social media sentiment and stock performance? What recovery patterns are observed?",
        "search_query": "<company_name> Twitter Reddit crisis impact analysis stock performance recovery patterns"
    },
    {
        "area": "Quantitative Social Media Analysis",
        "subarea": "Product Launch and Innovation Buzz",
        "long_question": "What is the volume of discussions and engagement rate around new product launches or innovations by <company_name> on Twitter and Reddit? How does this buzz correlate with sales or stock performance?",
        "search_query": "<company_name> Twitter Reddit product launch innovation buzz sales stock correlation"
    },
    {
        "area": "Quantitative Social Media Analysis",
        "subarea": "Competitive Analysis",
        "long_question": "How does <company_name>'s social media presence and engagement metrics compare with its main competitors? What insights can be drawn from comparative sentiment analysis?",
        "search_query": "<company_name> Twitter Reddit competitive analysis sentiment"
    },
    {
        "area": "Quantitative Social Media Analysis",
        "subarea": "Legal and Regulatory Discussion Volume",
        "long_question": "What is the volume and sentiment of discussions related to legal challenges or regulatory changes affecting <company_name> on Twitter and Reddit? How do these discussions impact investor sentiment?",
        "search_query": "<company_name> Twitter Reddit legal regulatory discussion volume sentiment investor impact"
    },
    {
        "area": "Quantitative Social Media Analysis",
        "subarea": "Geopolitical and Economic Discussion Impact",
        "long_question": "Can we quantify the volume and sentiment of discussions on Twitter and Reddit about geopolitical or economic factors affecting <company_name>? How do these factors correlate with market performance?",
        "search_query": "<company_name> Twitter Reddit geopolitical economic discussion volume sentiment market performance correlation"
    }
])

due_diligence_queries.extend([
    {
        "area": "Financial Performance Trends",
        "subarea": "Revenue Growth",
        "long_question": "What is the year-over-year (YoY) and quarter-over-quarter (QoQ) revenue growth for <company_name>? How does this compare to the industry average and key competitors?",
        "search_query": "<company_name> YoY QoQ revenue growth comparison industry competitors"
    },
    {
        "area": "Financial Performance Trends",
        "subarea": "Profitability Trends",
        "long_question": "How have <company_name>'s profit margins (gross, operating, net) changed YoY and QoQ? Are there any concerning trends or deviations from industry norms?",
        "search_query": "<company_name> YoY QoQ profit margin trends gross operating net industry norms"
    },
    {
        "area": "Financial Performance Trends",
        "subarea": "Cash Flow Analysis",
        "long_question": "Analyze <company_name>'s cash flow statements YoY and QoQ. Are there any significant changes in operating, investing, or financing cash flows that warrant further investigation?",
        "search_query": "<company_name> YoY QoQ cash flow analysis operating investing financing"
    },
    {
        "area": "Competitive Positioning",
        "subarea": "Market Share Trends",
        "long_question": "How has <company_name>'s market share evolved YoY and QoQ in its key business segments? Are there any notable gains or losses relative to competitors?",
        "search_query": "<company_name> YoY QoQ market share trends business segments competitors"
    },
    {
        "area": "Competitive Positioning",
        "subarea": "Pricing Power and Margins",
        "long_question": "Analyze <company_name>'s pricing power and margin trends YoY and QoQ. Is the company able to maintain or expand margins in the face of competition?",
        "search_query": "<company_name> YoY QoQ pricing power margin trends competition"
    },
    {
        "area": "Competitive Positioning",
        "subarea": "Competitive Moat",
        "long_question": "Evaluate the strength and sustainability of <company_name>'s competitive moat. Have there been any changes YoY or QoQ that could impact its long-term competitive advantage?",
        "search_query": "<company_name> YoY QoQ competitive moat strength sustainability changes"
    },
    {
        "area": "Operational Efficiency",
        "subarea": "Operating Metrics",
        "long_question": "Analyze key operating metrics for <company_name> YoY and QoQ (e.g., inventory turnover, receivables turnover, payables turnover). Are there any efficiency improvements or deteriorations?",
        "search_query": "<company_name> YoY QoQ operating metrics inventory receivables payables turnover efficiency"
    },
    {
        "area": "Operational Efficiency",
        "subarea": "Cost Structure",
        "long_question": "How has <company_name>'s cost structure changed YoY and QoQ? Are there any significant shifts in fixed vs. variable costs or operating leverage?",
        "search_query": "<company_name> YoY QoQ cost structure changes fixed variable operating leverage"
    },
    {
        "area": "Debt and Capital Structure",
        "subarea": "Leverage Ratios",
        "long_question": "Analyze <company_name>'s leverage ratios (e.g., debt-to-equity, interest coverage) YoY and QoQ. Are there any concerning trends or deviations from industry norms?",
        "search_query": "<company_name> YoY QoQ leverage ratios debt-to-equity interest coverage trends industry norms"
    },
    {
        "area": "Debt and Capital Structure",
        "subarea": "Debt Maturity Profile",
        "long_question": "Review <company_name>'s debt maturity profile. Have there been any significant changes YoY or QoQ that could impact liquidity or refinancing risk?",
        "search_query": "<company_name> YoY QoQ debt maturity profile changes liquidity refinancing risk"
    },
    {
        "area": "Growth and Investment",
        "subarea": "Capital Expenditure",
        "long_question": "Analyze <company_name>'s capital expenditure (CapEx) trends YoY and QoQ. Are investments being made in line with the company's long-term strategy and growth objectives?",
        "search_query": "<company_name> YoY QoQ capital expenditure CapEx trends strategy growth objectives"
    },
    {
        "area": "Growth and Investment",
        "subarea": "Research and Development",
        "long_question": "How have <company_name>'s R&D expenses trended YoY and QoQ? Is the company investing sufficiently in innovation to support long-term growth and competitiveness?",
        "search_query": "<company_name> YoY QoQ R&D expenses trends innovation long-term growth competitiveness"
    },
    {
        "area": "Growth and Investment",
        "subarea": "Mergers and Acquisitions",
        "long_question": "Review <company_name>'s M&A activity YoY and QoQ. Do the acquisitions align with the company's strategic objectives, and how have they impacted financial performance?",
        "search_query": "<company_name> YoY QoQ M&A activity strategic objectives financial performance impact"
    },
    {
        "area": "Valuation Metrics",
        "subarea": "Earnings Multiples",
        "long_question": "Analyze <company_name>'s earnings multiples (e.g., P/E, EV/EBITDA) YoY and QoQ. How do they compare to historical levels and industry peers?",
        "search_query": "<company_name> YoY QoQ earnings multiples P/E EV/EBITDA historical levels industry peers"
    },
    {
        "area": "Valuation Metrics",
        "subarea": "Dividend Yield and Payout Ratio",
        "long_question": "How have <company_name>'s dividend yield and payout ratio trended YoY and QoQ? Are the dividends sustainable and growing in line with earnings?",
        "search_query": "<company_name> YoY QoQ dividend yield payout ratio trends sustainability earnings growth"
    }
])

due_diligence_queries.extend([
    {
        "area": "Market Dynamics",
        "subarea": "Customer Acquisition Cost",
        "long_question": "How has the Customer Acquisition Cost (CAC) evolved for <company_name> YoY and QoQ? What does this indicate about the company's marketing efficiency and market saturation levels?",
        "search_query": "<company_name> YoY QoQ Customer Acquisition Cost CAC marketing efficiency market saturation"
    },
    {
        "area": "Market Dynamics",
        "subarea": "Lifetime Value of a Customer",
        "long_question": "Analyze the changes in the Lifetime Value (LTV) of a customer for <company_name> YoY and QoQ. How does this compare with the CAC, and what implications does it have for long-term profitability?",
        "search_query": "<company_name> YoY QoQ Lifetime Value LTV Customer Acquisition Cost CAC profitability"
    },
    {
        "area": "Innovation and R&D",
        "subarea": "Patent Filings",
        "long_question": "Review the trend in patent filings by <company_name> YoY and QoQ. What does this indicate about the company's focus on innovation and R&D?",
        "search_query": "<company_name> YoY QoQ patent filings innovation R&D"
    },
    {
        "area": "Innovation and R&D",
        "subarea": "R&D Spending as a Percentage of Revenue",
        "long_question": "How has R&D spending as a percentage of revenue changed for <company_name> YoY and QoQ? Does this align with the company's strategic priorities and industry benchmarks?",
        "search_query": "<company_name> YoY QoQ R&D spending percentage revenue strategic priorities industry benchmarks"
    },
    {
        "area": "Sustainability and ESG",
        "subarea": "ESG Score Trends",
        "long_question": "Analyze the ESG (Environmental, Social, Governance) score trends for <company_name> YoY and QoQ. How do these trends impact investor perception and potential regulatory risks?",
        "search_query": "<company_name> YoY QoQ ESG score trends investor perception regulatory risks"
    },
    {
        "area": "Sustainability and ESG",
        "subarea": "Sustainability Initiatives",
        "long_question": "Evaluate the progress and impact of sustainability initiatives undertaken by <company_name> YoY and QoQ. How do these initiatives align with global sustainability goals and affect the company's operational efficiency?",
        "search_query": "<company_name> YoY QoQ sustainability initiatives progress impact global goals operational efficiency"
    },
    {
        "area": "Employee and Culture",
        "subarea": "Employee Turnover Rate",
        "long_question": "What is the trend in the employee turnover rate for <company_name> YoY and QoQ? What does this indicate about the company culture and employee satisfaction?",
        "search_query": "<company_name> YoY QoQ employee turnover rate company culture satisfaction"
    },
    {
        "area": "Employee and Culture",
        "subarea": "Diversity and Inclusion Metrics",
        "long_question": "Analyze the diversity and inclusion metrics for <company_name> YoY and QoQ. How do these metrics influence the company's innovation, employee engagement, and public image?",
        "search_query": "<company_name> YoY QoQ diversity inclusion metrics innovation employee engagement public image"
    },
    {
        "area": "Regulatory and Legal",
        "subarea": "Regulatory Compliance Costs",
        "long_question": "How have regulatory compliance costs changed for <company_name> YoY and QoQ? What implications do these changes have on the company's operational costs and legal risk profile?",
        "search_query": "<company_name> YoY QoQ regulatory compliance costs operational legal risk"
    },
    {
        "area": "Regulatory and Legal",
        "subarea": "Litigation and Legal Disputes",
        "long_question": "Review any significant litigation or legal disputes involving <company_name> YoY and QoQ. How do these disputes affect the company's financial health and reputation?",
        "search_query": "<company_name> YoY QoQ litigation legal disputes financial health reputation"
    },
    {
        "area": "Technology and Digital Transformation",
        "subarea": "Digital Transformation Initiatives",
        "long_question": "Evaluate the progress and impact of digital transformation initiatives for <company_name> YoY and QoQ. How do these initiatives enhance operational efficiency, customer experience, and competitive positioning?",
        "search_query": "<company_name> YoY QoQ digital transformation initiatives progress impact operational efficiency customer experience competitive positioning"
    },
    {
        "area": "Technology and Digital Transformation",
        "subarea": "Technology Adoption and Integration",
        "long_question": "Analyze the level of technology adoption and integration within <company_name>'s operations and product offerings YoY and QoQ. What impact does this have on the company's innovation capabilities and market differentiation?",
        "search_query": "<company_name> YoY QoQ technology adoption integration operations product offerings innovation market differentiation"
    }
])

due_diligence_queries.extend([
    {
        "area": "Market Sentiment Analysis",
        "subarea": "News Impact",
        "long_question": "How do significant news events correlate with changes in the opening and closing prices of <company_name>? Can we identify patterns of price movement in response to specific types of news?",
        "search_query": "<company_name> news impact on stock prices correlation analysis"
    },
    {
        "area": "Market Sentiment Analysis",
        "subarea": "Social Media Sentiment",
        "long_question": "Analyze the correlation between social media sentiment regarding <company_name> and daily stock price movements. Does increased social media activity predict upward or downward price trends?",
        "search_query": "<company_name> social media sentiment stock price correlation"
    },
    {
        "area": "Investor Behavior",
        "subarea": "Institutional vs Retail Trading Volume",
        "long_question": "Distinguish between institutional and retail investor trading volumes for <company_name>. How do these volumes impact price movements, and what can they tell us about investor confidence?",
        "search_query": "<company_name> institutional retail trading volumes impact analysis"
    },
    {
        "area": "Market Anomalies",
        "subarea": "Flash Crashes and Spikes",
        "long_question": "Identify any instances of flash crashes or spikes in the stock price of <company_name>. What were the immediate and long-term effects on trading volumes and price stability?",
        "search_query": "<company_name> flash crashes spikes analysis"
    },
    {
        "area": "Liquidity Analysis",
        "subarea": "Bid-Ask Spread",
        "long_question": "Examine the bid-ask spread for <company_name> over time. How does the spread correlate with traded and delivered volumes, and what does it indicate about market liquidity?",
        "search_query": "<company_name> bid-ask spread correlation traded delivered volumes liquidity"
    },
    {
        "area": "Technical Analysis Enhancements",
        "subarea": "Fibonacci Retracements",
        "long_question": "Apply Fibonacci retracement levels to the price movements of <company_name> to identify potential support and resistance levels. How do these levels align with actual price movements and traded volumes?",
        "search_query": "<company_name> Fibonacci retracement support resistance levels alignment"
    },
    {
        "area": "Pattern Recognition",
        "subarea": "Chart Patterns",
        "long_question": "Identify and analyze chart patterns (e.g., head and shoulders, double tops/bottoms) in the historical price data of <company_name>. How have these patterns historically correlated with subsequent price movements?",
        "search_query": "<company_name> chart patterns analysis price movement correlation"
    },
    {
        "area": "Comparative Analysis",
        "subarea": "Sector vs Company Performance",
        "long_question": "Compare the performance of <company_name> with the overall sector performance. How does the company's price volatility and volume changes stand in relation to sector averages?",
        "search_query": "<company_name> vs sector performance comparison volatility volume changes"
    },
    {
        "area": "Event-Driven Strategies",
        "subarea": "Earnings Announcements",
        "long_question": "Analyze the impact of earnings announcements on the stock price and volumes of <company_name>. Do earnings beats or misses significantly affect investor behavior and stock performance?",
        "search_query": "<company_name> earnings announcements impact stock price volumes"
    },
    {
        "area": "Market Efficiency",
        "subarea": "Price Adjustment Speed",
        "long_question": "Assess how quickly the stock price of <company_name> adjusts to new information. Are there delays that can be exploited for arbitrage opportunities?",
        "search_query": "<company_name> price adjustment speed analysis arbitrage opportunities"
    },
    {
        "area": "Risk Management",
        "subarea": "Value at Risk (VaR)",
        "long_question": "Calculate the Value at Risk (VaR) for an investment in <company_name> based on historical price movements. How does this risk metric compare to industry benchmarks?",
        "search_query": "<company_name> Value at Risk VaR calculation industry comparison"
    },
    {
        "area": "Predictive Modeling",
        "subarea": "Machine Learning Predictions",
        "long_question": "Utilize machine learning models to predict future price movements of <company_name> based on historical data. How accurate are these models, and what features are most predictive?",
        "search_query": "<company_name> machine learning predictions accuracy features"
    }
])

due_diligence_queries.extend([
    {
        "area": "Technical Analysis",
        "subarea": "Price Trends and Patterns",
        "long_question": "What do the historical price trends and patterns of <company_name> indicate about potential future movements, and how can these inform our decision on entry or exit points?",
        "search_query": "<company_name> historical price trends patterns analysis entry exit"
    },
    {
        "area": "Volume Analysis",
        "subarea": "Investor Interest and Market Sentiment",
        "long_question": "How do the traded and delivered volumes of <company_name> correlate with price movements, and what does this say about investor interest and market sentiment?",
        "search_query": "<company_name> traded delivered volumes price correlation investor interest market sentiment"
    },
    {
        "area": "Volatility Analysis",
        "subarea": "Risk Assessment",
        "long_question": "What does the volatility of <company_name>'s stock price say about the risk profile of the company, and how does this influence our risk management strategies?",
        "search_query": "<company_name> stock price volatility risk assessment management"
    },
    {
        "area": "Financial Health",
        "subarea": "Debt and Liquidity",
        "long_question": "Assess the debt levels and liquidity of <company_name> to understand its financial health. How sustainable is the company's capital structure in the long term?",
        "search_query": "<company_name> debt levels liquidity financial health capital structure sustainability"
    },
    {
        "area": "Operational Efficiency",
        "subarea": "Cost Management",
        "long_question": "How efficient is <company_name> in managing its operational costs, and what does this indicate about its operational efficiency and margin sustainability?",
        "search_query": "<company_name> operational costs efficiency margin sustainability analysis"
    },
    {
        "area": "Market Position",
        "subarea": "Competitive Moat and Strategy",
        "long_question": "What is the competitive moat of <company_name>, and how does its strategy ensure long-term growth and market leadership?",
        "search_query": "<company_name> competitive moat strategy long-term growth market leadership"
    },
    {
        "area": "Growth Prospects",
        "subarea": "Revenue and Earnings Growth",
        "long_question": "Analyze the revenue and earnings growth of <company_name> to assess its growth prospects. How sustainable is this growth in the context of its industry and the broader market?",
        "search_query": "<company_name> revenue earnings growth sustainability industry market context"
    },
    {
        "area": "Innovation and R&D",
        "subarea": "Future Proofing",
        "long_question": "How is <company_name> investing in innovation and R&D to future-proof its business against technological advancements and market changes?",
        "search_query": "<company_name> innovation R&D investment future proofing technological advancements market changes"
    },
    {
        "area": "Regulatory Compliance",
        "subarea": "Legal Risks",
        "long_question": "What are the regulatory compliance challenges facing <company_name>, and how do these impact its legal risk profile and operational costs?",
        "search_query": "<company_name> regulatory compliance challenges legal risk profile operational costs impact"
    },
    {
        "area": "Sustainability and ESG",
        "subarea": "Long-term Viability",
        "long_question": "Evaluate the ESG practices of <company_name> to understand its commitment to sustainability. How do these practices impact its long-term viability and investor appeal?",
        "search_query": "<company_name> ESG practices sustainability commitment long-term viability investor appeal"
    },
    {
        "area": "Corporate Governance",
        "subarea": "Management and Strategy Execution",
        "long_question": "Assess the effectiveness of <company_name>'s corporate governance, including management's ability to execute strategy and drive shareholder value.",
        "search_query": "<company_name> corporate governance effectiveness management strategy execution shareholder value"
    }
])

due_diligence_queries.extend([
    {
        "area": "Price Volatility",
        "subarea": "Market Stability",
        "long_question": "What patterns of volatility can be observed in the historic price data of <company_name>, and what do these patterns indicate about the company's market stability and investor sentiment?",
        "search_query": "<company_name> historic price volatility patterns market stability investor sentiment"
    },
    {
        "area": "Volume Analysis",
        "subarea": "Liquidity and Interest",
        "long_question": "How do the traded and delivered volumes of <company_name> correlate with its price movements, and what does this reveal about the stock's liquidity and the level of investor interest?",
        "search_query": "<company_name> traded delivered volumes price correlation liquidity investor interest"
    },
    {
        "area": "Trend Analysis",
        "subarea": "Price Momentum",
        "long_question": "What trends can be identified in the historic price movements of <company_name>, and how can these trends inform predictions about future price momentum?",
        "search_query": "<company_name> price trends analysis future momentum prediction"
    },
    {
        "area": "Technical Indicators",
        "subarea": "Buy or Sell Signals",
        "long_question": "Which technical indicators can be derived from the opening, closing, traded, and delivered volumes data of <company_name>, and how do these indicators signal potential buy or sell opportunities?",
        "search_query": "<company_name> technical indicators buy sell signals analysis"
    },
    {
        "area": "Comparative Analysis",
        "subarea": "Industry Benchmarking",
        "long_question": "How does <company_name>'s price volatility and volume data compare with industry averages, and what does this comparison reveal about the company's performance relative to its peers?",
        "search_query": "<company_name> price volatility volume comparison industry benchmark"
    },
    {
        "area": "Event-Driven Analysis",
        "subarea": "Impact Assessment",
        "long_question": "Can specific market or company events be correlated with significant changes in the price or volumes of <company_name>, and what does this correlation reveal about the company's resilience or vulnerability to external events?",
        "search_query": "<company_name> event impact analysis price volume changes"
    },
    {
        "area": "Risk Management",
        "subarea": "Volatility Assessment",
        "long_question": "What does the analysis of price volatility and traded volumes over time tell us about the risk profile of investing in <company_name>, and how can this information be used to manage investment risk?",
        "search_query": "<company_name> price volatility traded volumes risk profile assessment"
    },
    {
        "area": "Market Sentiment",
        "subarea": "Investor Behavior",
        "long_question": "What insights can be drawn from the correlation between daily price movements and traded/delivered volumes of <company_name> regarding market sentiment and investor behavior?",
        "search_query": "<company_name> price movements traded delivered volumes market sentiment investor behavior"
    },
    {
        "area": "Liquidity Analysis",
        "subarea": "Market Depth",
        "long_question": "How does the analysis of traded and delivered volumes of <company_name> inform us about the depth of the market for its shares, and what implications does this have for liquidity risk?",
        "search_query": "<company_name> traded delivered volumes market depth liquidity risk"
    },
    {
        "area": "Predictive Modeling",
        "subarea": "Price Forecasting",
        "long_question": "How can historical price and volume data of <company_name> be used in predictive modeling to forecast future price movements, and what are the limitations of such models?",
        "search_query": "<company_name> predictive modeling price forecasting historical data limitations"
    }
])

due_diligence_queries.extend([
    {
        "area": "Market Anomalies",
        "subarea": "Unusual Trading Patterns",
        "long_question": "Are there any instances of unusual trading patterns or market anomalies in the historic price and volume data of <company_name>, and what might these anomalies indicate about potential market manipulation or insider trading?",
        "search_query": "<company_name> unusual trading patterns market anomalies manipulation insider trading"
    },
    {
        "area": "Technical Analysis Enhancements",
        "subarea": "Advanced Indicators",
        "long_question": "Beyond basic technical indicators, what advanced or custom indicators can be derived from the historic price and volume data of <company_name> to provide deeper insights into potential future price movements?",
        "search_query": "<company_name> advanced custom technical indicators price volume analysis"
    },
    {
        "area": "Pattern Recognition",
        "subarea": "Chart Patterns",
        "long_question": "What specific chart patterns, such as head and shoulders, cup and handle, or triangles, can be identified in the historic price data of <company_name>, and what do these patterns suggest about potential trend reversals or continuations?",
        "search_query": "<company_name> chart patterns trend reversal continuation analysis"
    },
    {
        "area": "Comparative Analysis",
        "subarea": "Sector Correlation",
        "long_question": "How closely do the price movements and trading volumes of <company_name> correlate with those of other companies in the same sector, and what insights can be gained from this correlation analysis?",
        "search_query": "<company_name> sector correlation price volume analysis insights"
    },
    {
        "area": "Event-Driven Strategies",
        "subarea": "Earnings Announcements",
        "long_question": "How have the price and trading volumes of <company_name> typically responded to quarterly earnings announcements, and can this information be used to develop an event-driven trading strategy?",
        "search_query": "<company_name> earnings announcements price volume response event-driven strategy"
    },
    {
        "area": "Market Efficiency",
        "subarea": "Anomaly Detection",
        "long_question": "Do the historic price and volume data of <company_name> exhibit any persistent anomalies or inefficiencies that could be exploited for generating alpha, and how robust are these anomalies to changes in market conditions?",
        "search_query": "<company_name> market efficiency anomalies alpha generation robustness"
    },
    {
        "area": "Risk Management",
        "subarea": "Drawdown Analysis",
        "long_question": "Based on the historic price data, what is the maximum drawdown that an investment in <company_name> would have experienced, and how does this drawdown compare to the overall market or sector?",
        "search_query": "<company_name> maximum drawdown analysis comparison market sector"
    },
    {
        "area": "Investor Behavior",
        "subarea": "Herd Mentality",
        "long_question": "Do the trading volumes of <company_name> exhibit any patterns that suggest herd mentality or irrational exuberance among investors, and how can these behavioral insights inform contrarian investment strategies?",
        "search_query": "<company_name> herd mentality irrational exuberance contrarian investment strategies"
    },
    {
        "area": "Liquidity Risk",
        "subarea": "Volume Spikes",
        "long_question": "Are there any instances of sudden spikes or drops in the trading volumes of <company_name>, and what do these volume anomalies indicate about potential liquidity risks or market instability?",
        "search_query": "<company_name> volume spikes drops liquidity risk market instability analysis"
    },
    {
        "area": "Machine Learning Applications",
        "subarea": "Predictive Modeling",
        "long_question": "How can machine learning algorithms be applied to the historic price and volume data of <company_name> to uncover hidden patterns, predict future trends, or optimize trading strategies, and what are the potential pitfalls of relying on such models?",
        "search_query": "<company_name> machine learning predictive modeling price volume patterns trends strategies pitfalls"
    }
])

due_diligence_queries.extend([
    {
        "area": "Price Volatility",
        "subarea": "Market Stability",
        "long_question": "What is the average daily price volatility of <company_name> over the past year?",
        "search_query": "<company_name> average daily price volatility past year"
    },
    {
        "area": "Price Volatility",
        "subarea": "Market Stability",
        "long_question": "How does the price volatility of <company_name> compare to the overall market volatility?",
        "search_query": "<company_name> price volatility comparison market"
    },
    {
        "area": "Price Volatility",
        "subarea": "Market Stability",
        "long_question": "Are there any periods of exceptionally high or low price volatility for <company_name>, and what events might have triggered these periods?",
        "search_query": "<company_name> periods high low price volatility events triggers"
    },
    {
        "area": "Volume Analysis",
        "subarea": "Liquidity and Interest",
        "long_question": "What is the average daily trading volume of <company_name> over the past year?",
        "search_query": "<company_name> average daily trading volume past year"
    },
    {
        "area": "Volume Analysis",
        "subarea": "Liquidity and Interest",
        "long_question": "How does the trading volume of <company_name> correlate with its price movements on a daily basis?",
        "search_query": "<company_name> trading volume price correlation daily"
    },
    {
        "area": "Volume Analysis",
        "subarea": "Liquidity and Interest",
        "long_question": "Are there any notable differences between the traded and delivered volumes of <company_name>, and what might these differences indicate about market liquidity?",
        "search_query": "<company_name> differences traded delivered volumes market liquidity"
    },
    {
        "area": "Trend Analysis",
        "subarea": "Price Momentum",
        "long_question": "What is the overall price trend of <company_name> over the past year, and how does this trend compare to the broader market or sector?",
        "search_query": "<company_name> overall price trend past year comparison market sector"
    },
    {
        "area": "Trend Analysis",
        "subarea": "Price Momentum",
        "long_question": "Are there any notable instances of trend reversals or breakouts in the price history of <company_name>, and what factors might have contributed to these changes?",
        "search_query": "<company_name> trend reversals breakouts price history contributing factors"
    },
    {
        "area": "Trend Analysis",
        "subarea": "Price Momentum",
        "long_question": "Can the price momentum of <company_name> be used to generate reliable trading signals, and if so, what are the optimal parameters for such a momentum strategy?",
        "search_query": "<company_name> price momentum trading signals optimal parameters strategy"
    },
    {
        "area": "Technical Indicators",
        "subarea": "Buy or Sell Signals",
        "long_question": "What are the key technical indicators that can be derived from the price and volume data of <company_name>, such as moving averages, RSI, or MACD?",
        "search_query": "<company_name> key technical indicators price volume moving averages RSI MACD"
    },
    {
        "area": "Technical Indicators",
        "subarea": "Buy or Sell Signals",
        "long_question": "How accurate are the buy or sell signals generated by these technical indicators for <company_name>, and what is the optimal timeframe for using these indicators?",
        "search_query": "<company_name> accuracy buy sell signals technical indicators optimal timeframe"
    },
    {
        "area": "Technical Indicators",
        "subarea": "Buy or Sell Signals",
        "long_question": "Can multiple technical indicators be combined to generate more robust trading signals for <company_name>, and if so, what is the best way to combine these indicators?",
        "search_query": "<company_name> combining multiple technical indicators robust trading signals best approach"
    },
    {
        "area": "Comparative Analysis",
        "subarea": "Industry Benchmarking",
        "long_question": "How does the price performance of <company_name> compare to its main competitors or industry benchmarks over various time periods?",
        "search_query": "<company_name> price performance comparison competitors industry benchmarks time periods"
    },
    {
        "area": "Comparative Analysis",
        "subarea": "Industry Benchmarking",
        "long_question": "Are there any notable differences in the trading volumes or liquidity of <company_name> compared to its peers, and what might these differences indicate about investor interest or market positioning?",
        "search_query": "<company_name> trading volumes liquidity differences peers investor interest market positioning"
    },
    {
        "area": "Comparative Analysis",
        "subarea": "Industry Benchmarking",
        "long_question": "Can the relative performance of <company_name> be used to identify potential market leaders or laggards within its industry, and how reliable are these indicators?",
        "search_query": "<company_name> relative performance market leaders laggards industry reliability indicators"
    },
    {
        "area": "Event-Driven Analysis",
        "subarea": "Impact Assessment",
        "long_question": "How do the price and volume of <company_name> typically respond to major corporate events, such as earnings releases, mergers and acquisitions, or leadership changes?",
        "search_query": "<company_name> price volume response corporate events earnings mergers acquisitions leadership changes"
    },
    {
        "area": "Event-Driven Analysis",
        "subarea": "Impact Assessment",
        "long_question": "Are there any notable instances of insider trading or unusual trading activity in the history of <company_name> prior to major corporate announcements?",
        "search_query": "<company_name> insider trading unusual activity prior corporate announcements"
    },
    {
        "area": "Event-Driven Analysis",
        "subarea": "Impact Assessment",
        "long_question": "Can the impact of corporate events on <company_name>'s stock be quantified, and how does this impact compare to the overall market reaction to similar events?",
        "search_query": "<company_name> quantifying impact corporate events stock comparison market reaction"
    },
    {
        "area": "Risk Management",
        "subarea": "Volatility Assessment",
        "long_question": "What is the historical volatility of <company_name>'s stock price, and how does this volatility compare to the overall market or industry?",
        "search_query": "<company_name> historical volatility stock price comparison market industry"
    },
    {
        "area": "Risk Management",
        "subarea": "Volatility Assessment",
        "long_question": "Are there any periods of unusually high or low volatility in the history of <company_name>, and what factors might have contributed to these periods?",
        "search_query": "<company_name> periods high low volatility history contributing factors"
    },
    {
        "area": "Risk Management",
        "subarea": "Volatility Assessment",
        "long_question": "How can the volatility of <company_name> be used to estimate potential downside risk or to set appropriate stop-loss levels for trading positions?",
        "search_query": "<company_name> volatility estimating downside risk setting stop-loss levels trading positions"
    },
    {
        "area": "Market Sentiment",
        "subarea": "Investor Behavior",
        "long_question": "How do changes in the trading volume of <company_name> reflect shifts in overall market sentiment or investor behavior?",
        "search_query": "<company_name> changes trading volume reflecting market sentiment investor behavior"
    },
    {
        "area": "Market Sentiment",
        "subarea": "Investor Behavior",
        "long_question": "Are there any notable instances of herd behavior or panic selling in the history of <company_name>, and how did these events impact the stock price?",
        "search_query": "<company_name> instances herd behavior panic selling history impact stock price"
    },
    {
        "area": "Market Sentiment",
        "subarea": "Investor Behavior",
        "long_question": "Can sentiment analysis of news articles or social media mentions related to <company_name> provide additional insights into investor behavior or market perception?",
        "search_query": "<company_name> sentiment analysis news social media investor behavior market perception insights"
    },
    {
        "area": "Liquidity Analysis",
        "subarea": "Market Depth",
        "long_question": "What is the average daily trading volume of <company_name> relative to its outstanding shares, and how does this ratio compare to other companies in the same industry?",
        "search_query": "<company_name> average daily trading volume relative outstanding shares ratio comparison industry"
    },
    {
        "area": "Liquidity Analysis",
        "subarea": "Market Depth",
        "long_question": "Are there any notable trends or changes in the market depth of <company_name> over time, and what factors might be driving these changes?",
        "search_query": "<company_name> trends changes market depth over time driving factors"
    },
    {
        "area": "Liquidity Analysis",
        "subarea": "Market Depth",
        "long_question": "How might the liquidity or market depth of <company_name> impact the ability to execute large trades without significant price impact?",
        "search_query": "<company_name> liquidity market depth impact executing large trades price impact"
    },
    {
        "area": "Predictive Modeling",
        "subarea": "Price Forecasting",
        "long_question": "What machine learning algorithms or statistical models can be applied to the historical price and volume data of <company_name> to forecast future price movements?",
        "search_query": "<company_name> machine learning algorithms statistical models historical price volume data forecasting future price movements"
    },
    {
        "area": "Predictive Modeling",
        "subarea": "Price Forecasting",
        "long_question": "How accurate are these predictive models in forecasting the future price of <company_name>, and what are the key factors that impact the model's performance?",
        "search_query": "<company_name> accuracy predictive models forecasting future price key factors impacting performance"
    },
    {
        "area": "Predictive Modeling",
        "subarea": "Price Forecasting",
        "long_question": "Can ensemble methods or combining multiple predictive models improve the accuracy and robustness of price forecasts for <company_name>?",
        "search_query": "<company_name> ensemble methods combining predictive models improving accuracy robustness price forecasts"
    }
])

due_diligence_queries.extend([
    {
        "area": "Sector Identification",
        "subarea": "Industry Classification",
        "long_question": "What are the primary sectors and industries in which <company_name> operates?",
        "search_query": "<company_name> primary sectors industries classification"
    },
    {
        "area": "Sector Identification",
        "subarea": "Industry Classification",
        "long_question": "Are there any secondary or tertiary sectors in which <company_name> has a presence, and how significant are these operations?",
        "search_query": "<company_name> secondary tertiary sectors presence significance"
    },
    {
        "area": "Competitor Identification",
        "subarea": "Market Mapping",
        "long_question": "Who are the main competitors of <company_name> in each of its primary sectors and industries?",
        "search_query": "<company_name> main competitors primary sectors industries"
    },
    {
        "area": "Competitor Identification",
        "subarea": "Market Mapping",
        "long_question": "Are there any emerging or potential competitors that could disrupt <company_name>'s market position in the future?",
        "search_query": "<company_name> emerging potential competitors disrupt market position future"
    },
    {
        "area": "Fundamental Analysis",
        "subarea": "Financial Strength",
        "long_question": "How do the key financial metrics (revenue, profit, growth) of <company_name> compare to its main competitors?",
        "search_query": "<company_name> financial metrics revenue profit growth comparison competitors"
    },
    {
        "area": "Fundamental Analysis",
        "subarea": "Financial Strength",
        "long_question": "Does <company_name> have any unique financial strengths or weaknesses compared to its rivals, such as a stronger balance sheet or higher debt levels?",
        "search_query": "<company_name> unique financial strengths weaknesses rivals balance sheet debt levels"
    },
    {
        "area": "Strategic Analysis",
        "subarea": "Competitive Advantage",
        "long_question": "What are the key elements of <company_name>'s business strategy, and how do these compare to the strategies of its main competitors?",
        "search_query": "<company_name> key elements business strategy comparison competitors"
    },
    {
        "area": "Strategic Analysis",
        "subarea": "Competitive Advantage",
        "long_question": "Does <company_name> have any sustainable competitive advantages, such as economies of scale, network effects, or proprietary technology?",
        "search_query": "<company_name> sustainable competitive advantages economies scale network effects proprietary technology"
    },
    {
        "area": "Debt and Leverage",
        "subarea": "Financial Risk",
        "long_question": "How does the debt profile and leverage of <company_name> compare to its competitors, and what are the implications for financial risk?",
        "search_query": "<company_name> debt profile leverage comparison competitors implications financial risk"
    },
    {
        "area": "Debt and Leverage",
        "subarea": "Financial Risk",
        "long_question": "Are there any notable differences in the debt maturity, interest rates, or covenant restrictions of <company_name> compared to its peers?",
        "search_query": "<company_name> differences debt maturity interest rates covenant restrictions peers"
    },
    {
        "area": "Ratio Analysis",
        "subarea": "Profitability and Efficiency",
        "long_question": "How do the key profitability ratios (gross margin, operating margin, ROE) of <company_name> compare to its competitors?",
        "search_query": "<company_name> profitability ratios gross operating margin ROE comparison competitors"
    },
    {
        "area": "Ratio Analysis",
        "subarea": "Profitability and Efficiency",
        "long_question": "Does <company_name> demonstrate superior efficiency ratios (asset turnover, inventory turnover) compared to its peers?",
        "search_query": "<company_name> superior efficiency ratios asset inventory turnover peers"
    },
    {
        "area": "Market Perception",
        "subarea": "Brand and Reputation",
        "long_question": "How is <company_name> perceived by customers, investors, and other stakeholders relative to its competitors?",
        "search_query": "<company_name> perception customers investors stakeholders relative competitors"
    },
    {
        "area": "Market Perception",
        "subarea": "Brand and Reputation",
        "long_question": "Are there any notable differences in brand strength, customer loyalty, or reputation between <company_name> and its rivals?",
        "search_query": "<company_name> differences brand strength customer loyalty reputation rivals"
    },
    {
        "area": "Customer Metrics",
        "subarea": "Market Share and Growth",
        "long_question": "How does the market share and customer base of <company_name> compare to its competitors in each of its key markets?",
        "search_query": "<company_name> market share customer base comparison competitors key markets"
    },
    {
        "area": "Customer Metrics",
        "subarea": "Market Share and Growth",
        "long_question": "Is <company_name> gaining or losing market share relative to its peers, and what are the key drivers of these changes?",
        "search_query": "<company_name> gaining losing market share relative peers key drivers changes"
    },
    {
        "area": "Growth Analysis",
        "subarea": "Expansion Opportunities",
        "long_question": "What are the main growth drivers and expansion opportunities for <company_name> compared to its competitors?",
        "search_query": "<company_name> main growth drivers expansion opportunities compared competitors"
    },
    {
        "area": "Growth Analysis",
        "subarea": "Expansion Opportunities",
        "long_question": "Does <company_name> have any unique growth strategies or initiatives that differentiate it from its rivals?",
        "search_query": "<company_name> unique growth strategies initiatives differentiate rivals"
    },
    {
        "area": "Research and Development",
        "subarea": "Innovation and Technology",
        "long_question": "How do the R&D investments and innovation capabilities of <company_name> compare to its competitors?",
        "search_query": "<company_name> R&D investments innovation capabilities comparison competitors"
    },
    {
        "area": "Research and Development",
        "subarea": "Innovation and Technology",
        "long_question": "Does <company_name> have any proprietary technologies, patents, or research initiatives that give it an edge over its rivals?",
        "search_query": "<company_name> proprietary technologies patents research initiatives edge rivals"
    }
])



due_diligence_queries.extend([
    {
        "area": "Sector Identification",
        "subarea": "Market Trends",
        "long_question": "What are the current trends and future projections for the sectors and industries in which <company_name> operates?",
        "search_query": "<company_name> sector industry trends future projections"
    },
    {
        "area": "Competitor Identification",
        "subarea": "Competitor Performance",
        "long_question": "How have the main competitors of <company_name> performed over the past five years in terms of revenue, profit, and market share growth?",
        "search_query": "<company_name> competitors performance five years revenue profit market share growth"
    },
    {
        "area": "Fundamental Analysis",
        "subarea": "Cash Flow",
        "long_question": "How does <company_name>'s cash flow generation compare to its main competitors, and what does this imply about its financial health and sustainability?",
        "search_query": "<company_name> cash flow comparison competitors financial health sustainability"
    },
    {
        "area": "Strategic Analysis",
        "subarea": "Strategic Initiatives",
        "long_question": "What strategic initiatives has <company_name> undertaken recently, and how do these compare to the initiatives of its main competitors?",
        "search_query": "<company_name> recent strategic initiatives comparison competitors"
    },
    {
        "area": "Debt and Leverage",
        "subarea": "Debt Structure",
        "long_question": "How does the structure of <company_name>'s debt (short-term vs. long-term, fixed vs. variable interest rate) compare to its competitors?",
        "search_query": "<company_name> debt structure comparison competitors"
    },
    {
        "area": "Ratio Analysis",
        "subarea": "Liquidity Ratios",
        "long_question": "How do the liquidity ratios (current ratio, quick ratio) of <company_name> compare to its competitors?",
        "search_query": "<company_name> liquidity ratios current quick ratio comparison competitors"
    },
    {
        "area": "Market Perception",
        "subarea": "Investor Sentiment",
        "long_question": "What is the current investor sentiment towards <company_name> compared to its competitors?",
        "search_query": "<company_name> investor sentiment comparison competitors"
    },
    {
        "area": "Customer Metrics",
        "subarea": "Customer Satisfaction",
        "long_question": "How does <company_name>'s customer satisfaction ratings compare to its competitors?",
        "search_query": "<company_name> customer satisfaction comparison competitors"
    },
    {
        "area": "Growth Analysis",
        "subarea": "Market Expansion",
        "long_question": "What new markets or segments is <company_name> targeting for growth, and how does this compare to its competitors' growth strategies?",
        "search_query": "<company_name> new markets segments growth comparison competitors"
    },
    {
        "area": "Research and Development",
        "subarea": "Patent Portfolio",
        "long_question": "What is the size and quality of <company_name>'s patent portfolio compared to its competitors?",
        "search_query": "<company_name> patent portfolio size quality comparison competitors"
    }
])

due_diligence_queries.extend([
    {
        "area": "Sector Identification",
        "subarea": "Regulatory Environment",
        "long_question": "How does the regulatory environment impact <company_name> and its competitors within its primary sectors, and what future regulatory changes could potentially affect their operations?",
        "search_query": "<company_name> regulatory environment impact competitors future changes"
    },
    {
        "area": "Competitor Identification",
        "subarea": "Competitor Strategies",
        "long_question": "What are the long-term strategies of <company_name>'s main competitors, and how might these strategies impact <company_name>'s market position?",
        "search_query": "<company_name> competitors long-term strategies impact market position"
    },
    {
        "area": "Fundamental Analysis",
        "subarea": "Operational Efficiency",
        "long_question": "How does <company_name>'s operational efficiency, measured by metrics such as cost of goods sold (COGS) and operating expenses, compare to its main competitors?",
        "search_query": "<company_name> operational efficiency COGS operating expenses comparison competitors"
    },
    {
        "area": "Strategic Analysis",
        "subarea": "Market Adaptability",
        "long_question": "How adaptable is <company_name> in responding to market changes and challenges compared to its competitors?",
        "search_query": "<company_name> market adaptability response changes challenges competitors"
    },
    {
        "area": "Debt and Leverage",
        "subarea": "Interest Coverage",
        "long_question": "How does <company_name>'s interest coverage ratio compare to its competitors, and what does this indicate about its ability to manage debt?",
        "search_query": "<company_name> interest coverage ratio comparison competitors"
    },
    {
        "area": "Ratio Analysis",
        "subarea": "Solvency Ratios",
        "long_question": "How do the solvency ratios (debt to equity, debt to assets) of <company_name> compare to its competitors, and what implications does this have for its financial stability?",
        "search_query": "<company_name> solvency ratios debt equity assets comparison competitors"
    },
    {
        "area": "Market Perception",
        "subarea": "Media Coverage",
        "long_question": "How does the media coverage of <company_name> compare to its competitors, and what impact does this have on public and investor perception?",
        "search_query": "<company_name> media coverage comparison competitors impact perception"
    },
    {
        "area": "Customer Metrics",
        "subarea": "Customer Retention",
        "long_question": "What are the customer retention rates of <company_name> compared to its competitors, and what strategies are in place to improve these rates?",
        "search_query": "<company_name> customer retention rates comparison competitors strategies improvement"
    },
    {
        "area": "Growth Analysis",
        "subarea": "Diversification Strategies",
        "long_question": "What diversification strategies are being employed by <company_name> and its competitors, and how do these strategies impact their growth potential?",
        "search_query": "<company_name> diversification strategies competitors impact growth potential"
    },
    {
        "area": "Research and Development",
        "subarea": "Collaborations and Partnerships",
        "long_question": "What are the significant collaborations and partnerships <company_name> has entered into for R&D purposes compared to its competitors, and how do these alliances enhance its innovation capabilities?",
        "search_query": "<company_name> R&D collaborations partnerships comparison competitors innovation capabilities"
    }
])

due_diligence_queries.extend([
    {
        "area": "Research and Development",
        "subarea": "Investment Strategy",
        "long_question": "What is the overall investment strategy of <company_name> in research and development, particularly in technology, software, and AI?",
        "search_query": "<company_name> research development investment strategy technology software AI"
    },
    {
        "area": "Research and Development",
        "subarea": "In-House Solutions",
        "long_question": "How does <company_name> invest in developing in-house solutions, and what impact does this have on its operational efficiency and product offerings?",
        "search_query": "<company_name> in-house solutions development investment impact"
    },
    {
        "area": "Manufacturing and Hardware",
        "subarea": "Innovation and Investment",
        "long_question": "What are the key innovations and investments <company_name> has made in hardware and manufacturing technologies?",
        "search_query": "<company_name> hardware manufacturing innovations investments"
    },
    {
        "area": "Intellectual Property",
        "subarea": "Patents and Assets",
        "long_question": "How does <company_name> manage its intellectual property, particularly patents, and how does this contribute to its competitive moat?",
        "search_query": "<company_name> intellectual property patents management competitive moat"
    },
    {
        "area": "Research and Development",
        "subarea": "Long-Term Investments",
        "long_question": "What long-term investments in research and development is <company_name> making, and how are these expected to impact the company and its consumers?",
        "search_query": "<company_name> long-term investments research development impact"
    },
    {
        "area": "Sector Expansion",
        "subarea": "Technology-Driven Access",
        "long_question": "How are <company_name>'s investments in technology enabling it to gain access to new sectors or expand its market reach?",
        "search_query": "<company_name> technology investments sector expansion market reach"
    },
    {
        "area": "Consumer Impact",
        "subarea": "Innovation Benefits",
        "long_question": "What are the direct benefits of <company_name>'s technological innovations to its consumers, and how do these innovations enhance customer satisfaction?",
        "search_query": "<company_name> technological innovations benefits consumers satisfaction"
    },
    {
        "area": "Competitive Moat",
        "subarea": "Sustainability Through Technology",
        "long_question": "How do <company_name>'s technological investments contribute to the sustainability of its competitive moat in the industry?",
        "search_query": "<company_name> technological investments competitive moat sustainability"
    },
    {
        "area": "Future Outlook",
        "subarea": "Technological Advancements",
        "long_question": "What future technological advancements is <company_name> focusing on, and how might these shape the industry and the company's position within it?",
        "search_query": "<company_name> future technological advancements focus industry impact"
    },
    {
        "area": "Strategic Partnerships",
        "subarea": "Collaborative Innovation",
        "long_question": "What strategic partnerships or collaborations has <company_name> entered into for the purpose of enhancing its research and technological capabilities?",
        "search_query": "<company_name> strategic partnerships collaborations research technology enhancement"
    }
])

due_diligence_queries.extend([
    {
        "area": "Technology Stack",
        "subarea": "Core Technologies",
        "long_question": "What are the core technologies that form the foundation of <company_name>'s technology stack, and how do these technologies provide a competitive edge?",
        "search_query": "<company_name> core technologies foundation competitive edge"
    },
    {
        "area": "Software Development",
        "subarea": "Agile Methodologies",
        "long_question": "How does <company_name> employ agile software development methodologies, and what impact does this have on its ability to innovate and respond to market needs?",
        "search_query": "<company_name> agile software development methodologies impact innovation market response"
    },
    {
        "area": "Artificial Intelligence",
        "subarea": "AI Applications",
        "long_question": "In what specific applications or products is <company_name> leveraging artificial intelligence, and how do these AI-powered solutions enhance customer value?",
        "search_query": "<company_name> artificial intelligence applications products customer value enhancement"
    },
    {
        "area": "In-House Solutions",
        "subarea": "Proprietary Technologies",
        "long_question": "What proprietary technologies has <company_name> developed in-house, and how do these technologies differentiate the company from its competitors?",
        "search_query": "<company_name> proprietary technologies in-house development differentiation competitors"
    },
    {
        "area": "Hardware Innovation",
        "subarea": "Next-Generation Components",
        "long_question": "What investments is <company_name> making in next-generation hardware components, and how might these investments shape the future of its products?",
        "search_query": "<company_name> next-generation hardware components investments future products impact"
    },
    {
        "area": "Manufacturing Processes",
        "subarea": "Automation and Robotics",
        "long_question": "How is <company_name> leveraging automation and robotics in its manufacturing processes, and what efficiency gains or cost savings are realized through these technologies?",
        "search_query": "<company_name> manufacturing automation robotics efficiency gains cost savings"
    },
    {
        "area": "Research Collaborations",
        "subarea": "Academic Partnerships",
        "long_question": "What research collaborations or academic partnerships has <company_name> established, and how do these collaborations enhance its innovation capabilities?",
        "search_query": "<company_name> research collaborations academic partnerships innovation capabilities enhancement"
    },
    {
        "area": "Patent Portfolio",
        "subarea": "Licensing and Monetization",
        "long_question": "How does <company_name> monetize its patent portfolio through licensing or other means, and what impact does this have on its revenue streams?",
        "search_query": "<company_name> patent portfolio monetization licensing revenue impact"
    },
    {
        "area": "Intellectual Property Strategy",
        "subarea": "IP Litigation",
        "long_question": "What is <company_name>'s strategy for defending its intellectual property through litigation, and how successful has this strategy been in protecting its competitive position?",
        "search_query": "<company_name> intellectual property litigation defense strategy success competitive position"
    },
    {
        "area": "Technology Acquisitions",
        "subarea": "Strategic Investments",
        "long_question": "What strategic technology acquisitions or investments has <company_name> made, and how have these acquisitions enhanced its technological capabilities or market reach?",
        "search_query": "<company_name> strategic technology acquisitions investments capabilities market reach enhancement"
    }
])

company_specific_sector_queries = [
    {
        "area": "Sector Identification",
        "subarea": "Primary Sectors",
        "long_question": "What are the primary sectors that <company_name> operates in?",
        "search_query": "<company_name> primary sectors"
    },
    {
        "area": "Sector Identification",
        "subarea": "Secondary Sectors",
        "long_question": "Apart from its primary sectors, what other secondary or ancillary sectors does <company_name> have a presence in?",
        "search_query": "<company_name> secondary ancillary sectors"
    },
    {
        "area": "Sector Identification",
        "subarea": "Sector Revenue Contribution",
        "long_question": "What is the revenue contribution of each sector to <company_name>'s overall revenue?",
        "search_query": "<company_name> sector revenue contribution breakdown"
    },
    {
        "area": "Sector Identification",
        "subarea": "Sector Growth Strategies",
        "long_question": "What are <company_name>'s strategies for growth within each of its sectors?",
        "search_query": "<company_name> sector growth strategies"
    },
    {
        "area": "Sector Identification",
        "subarea": "Sector-Specific Investments",
        "long_question": "What significant investments or acquisitions has <company_name> made in each of its sectors?",
        "search_query": "<company_name> sector-specific investments acquisitions"
    },
{
        "area": "Sector Identification",
        "subarea": "Emerging Sectors",
        "long_question": "What emerging or nascent sectors is <company_name> exploring or investing in for future growth?",
        "search_query": "<company_name> emerging nascent sectors investments"
    },
    {
        "area": "Sector Identification",
        "subarea": "Sector Synergies",
        "long_question": "How do <company_name>'s different sectors complement each other, and what synergies exist across its sectoral presence?",
        "search_query": "<company_name> sector synergies complementary presence"
    },
    {
        "area": "Sector Identification",
        "subarea": "Sector Divestments",
        "long_question": "Has <company_name> divested from any sectors in recent years, and what were the reasons behind these decisions?",
        "search_query": "<company_name> sector divestments reasons"
    },
    {
        "area": "Sector Identification",
        "subarea": "Sector Profitability",
        "long_question": "How do the profit margins and return on investment vary across <company_name>'s different sectors?",
        "search_query": "<company_name> sector profitability margins ROI comparison"
    },
    {
        "area": "Sector Identification",
        "subarea": "Sector Risk Exposure",
        "long_question": "What is <company_name>'s relative risk exposure across its different sectors, and how is it managing these risks?",
        "search_query": "<company_name> sector risk exposure management"
    },
{
        "area": "Sector Identification",
        "subarea": "Sector-Specific Initiatives",
        "long_question": "What specific initiatives has <company_name> undertaken in each of its sectors to drive growth and competitiveness?",
        "search_query": "<company_name> sector-specific initiatives growth competitiveness"
    },
    {
        "area": "Sector Identification",
        "subarea": "Sectoral Challenges and Opportunities",
        "long_question": "What are the key challenges and opportunities <company_name> faces in each of its sectors, and how is it responding to them?",
        "search_query": "<company_name> sectoral challenges opportunities response"
    },
    {
        "area": "Sector Identification",
        "subarea": "Sectoral Resource Allocation",
        "long_question": "How is <company_name> allocating its resources (such as capital, talent, and technology) across its different sectors?",
        "search_query": "<company_name> sectoral resource allocation"
    },
    {
        "area": "Sector Identification",
        "subarea": "Sectoral Performance Targets",
        "long_question": "What performance targets has <company_name> set for each of its sectors, and how is it tracking against these targets?",
        "search_query": "<company_name> sectoral performance targets tracking"
    },
    {
        "area": "Sector Identification",
        "subarea": "Sectoral Value Proposition",
        "long_question": "What is <company_name>'s value proposition in each of its sectors, and how does it differentiate from its competitors?",
        "search_query": "<company_name> sectoral value proposition differentiation"
    },
{
        "area": "Technological Advancements",
        "subarea": "Competitive Edge",
        "long_question": "What technological advancements is <company_name> leveraging or developing within its sectors to maintain or gain a competitive edge?",
        "search_query": "<company_name> sector technological advancements competitive edge"
    },
    {
        "area": "Global Market Expansion",
        "subarea": "Strategy and Challenges",
        "long_question": "How is <company_name> strategizing its expansion into global markets within its sectors, and what challenges and opportunities does it face in this endeavor?",
        "search_query": "<company_name> global market expansion strategy challenges opportunities"
    },
    {
        "area": "Consumer Behavior Trends",
        "subarea": "Adaptation Initiatives",
        "long_question": "How is <company_name> adapting to changing consumer behavior trends within its sectors, and what initiatives are being taken to align with these trends?",
        "search_query": "<company_name> adapting consumer behavior trends initiatives"
    },
    {
        "area": "Geopolitical Impact",
        "subarea": "Operations and Strategy",
        "long_question": "How do geopolitical factors impact <company_name>'s operations and strategic decisions across its sectors?",
        "search_query": "<company_name> geopolitical impact operations strategy"
    },
    {
        "area": "Digital Transformation",
        "subarea": "Strategy Implementation",
        "long_question": "What role is digital transformation playing in <company_name>'s strategy across its sectors, and how is it being implemented?",
        "search_query": "<company_name> digital transformation strategy implementation"
    }
]

sector_specific_queries = [
    {
        "area": "Sector Dynamics",
        "subarea": "Current Performance",
        "long_question": "How is the <sector_name> sector currently performing in terms of growth, profitability, and other key metrics?",
        "search_query": "<sector_name> sector current performance growth profitability metrics"
    },
    {
        "area": "Sector Dynamics",
        "subarea": "Future Prospects",
        "long_question": "What are the future growth prospects for the <sector_name> sector, and what factors are driving these projections?",
        "search_query": "<sector_name> sector future growth prospects drivers"
    },
    {
        "area": "Regulatory Environment",
        "subarea": "Current Regulations",
        "long_question": "What are the current key regulations governing the <sector_name> sector, and how do they impact the sector's dynamics?",
        "search_query": "<sector_name> sector current regulations impact"
    },
    {
        "area": "Regulatory Environment",
        "subarea": "Regulatory Changes",
        "long_question": "What potential regulatory changes are on the horizon for the <sector_name> sector, and how might these changes affect the sector's future?",
        "search_query": "<sector_name> sector potential regulatory changes impact future"
    },
    {
        "area": "Competitive Landscape",
        "subarea": "Major Players",
        "long_question": "Who are the major players in the <sector_name> sector, and what are their market shares?",
        "search_query": "<sector_name> sector major players market shares"
    },
    {
        "area": "Competitive Landscape",
        "subarea": "Competitive Intensity",
        "long_question": "How intense is the competition within the <sector_name> sector, and how is it evolving?",
        "search_query": "<sector_name> sector competition intensity evolution"
    },
    {
        "area": "Competitive Landscape",
        "subarea": "Barriers to Entry",
        "long_question": "What are the barriers to entry in the <sector_name> sector, and how do they affect the competitive dynamics?",
        "search_query": "<sector_name> sector barriers to entry impact competition"
    },
    {
        "area": "Company Positioning",
        "subarea": "Market Share",
        "long_question": "What is <company_name>'s market share within the <sector_name> sector, and how has it evolved over time?",
        "search_query": "<company_name> market share <sector_name> sector evolution"
    },
    {
        "area": "Company Positioning",
        "subarea": "Competitive Advantages",
        "long_question": "What are <company_name>'s key competitive advantages within the <sector_name> sector, and how sustainable are they?",
        "search_query": "<company_name> competitive advantages <sector_name> sector sustainability"
    },
    {
        "area": "Company Positioning",
        "subarea": "Sector-Specific Risks",
        "long_question": "What are the specific risks faced by <company_name> within the <sector_name> sector, and how is the company mitigating these risks?",
        "search_query": "<company_name> risks <sector_name> sector mitigation strategies"
    },
    {
        "area": "Sector Dynamics",
        "subarea": "Sector Trends",
        "long_question": "What are the key trends shaping the <sector_name> sector, and how are they likely to evolve in the future?",
        "search_query": "<sector_name> sector key trends future evolution"
    },
    {
        "area": "Sector Dynamics",
        "subarea": "Sector Disruption",
        "long_question": "What disruptive forces or technologies could potentially alter the dynamics of the <sector_name> sector?",
        "search_query": "<sector_name> sector potential disruption forces technologies"
    },
    {
        "area": "Regulatory Environment",
        "subarea": "Regulatory Compliance",
        "long_question": "How well are the major players in the <sector_name> sector complying with the current regulations, and what are the implications of non-compliance?",
        "search_query": "<sector_name> sector regulatory compliance implications non-compliance"
    },
    {
        "area": "Regulatory Environment",
        "subarea": "Regulatory Lobbying",
        "long_question": "What lobbying efforts are the major players in the <sector_name> sector engaged in to influence the regulatory environment?",
        "search_query": "<sector_name> sector lobbying efforts regulatory influence"
    },
    {
        "area": "Competitive Landscape",
        "subarea": "Competitor Strategies",
        "long_question": "What are the key strategies employed by <company_name>'s major competitors in the <sector_name> sector, and how effective have they been?",
        "search_query": "<company_name> competitors strategies effectiveness <sector_name> sector"
    },
    {
        "area": "Competitive Landscape",
        "subarea": "Sector Consolidation",
        "long_question": "Is the <sector_name> sector experiencing consolidation, and what are the implications for competition and market dynamics?",
        "search_query": "<sector_name> sector consolidation implications competition market dynamics"
    },
    {
        "area": "Competitive Landscape",
        "subarea": "Sector Partnerships",
        "long_question": "What strategic partnerships or alliances are common in the <sector_name> sector, and how do they impact the competitive landscape?",
        "search_query": "<sector_name> sector strategic partnerships alliances impact competition"
    },
    {
        "area": "Company Positioning",
        "subarea": "Sector Innovation",
        "long_question": "How does <company_name>'s innovation capabilities and investments compare to its peers in the <sector_name> sector?",
        "search_query": "<company_name> innovation capabilities investments comparison peers <sector_name> sector"
    },
    {
        "area": "Company Positioning",
        "subarea": "Sector Reputation",
        "long_question": "What is <company_name>'s reputation and brand strength within the <sector_name> sector, and how does it impact its competitive position?",
        "search_query": "<company_name> reputation brand strength impact competition <sector_name> sector"
    },
    {
        "area": "Company Positioning",
        "subarea": "Sector Adaptability",
        "long_question": "How adaptable is <company_name> to the changing dynamics of the <sector_name> sector, and what examples demonstrate this adaptability?",
        "search_query": "<company_name> adaptability changing dynamics examples <sector_name> sector"
    },
{
        "area": "Sector Dynamics",
        "subarea": "Macroeconomic Influences",
        "long_question": "What macroeconomic factors are influencing the <sector_name> sector, and how are they shaping its future prospects?",
        "search_query": "<sector_name> sector macroeconomic influences future prospects"
    },
    {
        "area": "Sector Dynamics",
        "subarea": "Sectoral Supply Chain",
        "long_question": "What are the key elements of the supply chain in the <sector_name> sector, and how are they impacting the sector's dynamics?",
        "search_query": "<sector_name> sector supply chain impact dynamics"
    },
    {
        "area": "Regulatory Environment",
        "subarea": "Regulatory Risks",
        "long_question": "What are the key regulatory risks in the <sector_name> sector, and how are they being managed by the major players?",
        "search_query": "<sector_name> sector regulatory risks management"
    },
    {
        "area": "Competitive Landscape",
        "subarea": "Competitor Collaborations",
        "long_question": "What collaborations or partnerships exist among <company_name>'s competitors in the <sector_name> sector, and how are they influencing the competitive dynamics?",
        "search_query": "<company_name> competitors collaborations <sector_name> sector impact"
    },
    {
        "area": "Company Positioning",
        "subarea": "Sectoral Customer Perception",
        "long_question": "How do customers perceive <company_name> in the <sector_name> sector, and how does this perception influence its competitive position?",
        "search_query": "<company_name> customer perception <sector_name> sector impact competition"
    },
    {
        "area": "Company Positioning",
        "subarea": "Sectoral Sustainability Practices",
        "long_question": "What sustainability practices has <company_name> implemented in the <sector_name> sector, and how do they contribute to its competitive advantage?",
        "search_query": "<company_name> sustainability practices <sector_name> sector competitive advantage"
    },

{
        "area": "Technological Disruption",
        "subarea": "Emerging Technologies",
        "long_question": "What emerging technologies have the potential to disrupt the <sector_name> sector, and how are companies preparing for this disruption?",
        "search_query": "<sector_name> sector emerging technologies disruption preparation"
    },
    {
        "area": "Global Market Dynamics",
        "subarea": "International Trends",
        "long_question": "How are global market dynamics affecting the <sector_name> sector, and what trends are evident in international trade, investment, and regulation?",
        "search_query": "<sector_name> sector global market dynamics international trends"
    },
    {
        "area": "Consumer Preferences Shift",
        "subarea": "Product and Service Adaptation",
        "long_question": "What shifts in consumer preferences are being observed in the <sector_name> sector, and how are companies adapting their products and services accordingly?",
        "search_query": "<sector_name> sector consumer preferences shifts adaptation"
    },
    {
        "area": "Geopolitical Factors",
        "subarea": "Competitive Landscape",
        "long_question": "How are geopolitical factors shaping the competitive landscape and regulatory environment of the <sector_name> sector?",
        "search_query": "<sector_name> sector geopolitical factors competitive landscape"
    },
    {
        "area": "Sustainability and ESG",
        "subarea": "Compliance and Innovations",
        "long_question": "How is the <sector_name> sector responding to increasing demands for sustainability and ESG (Environmental, Social, Governance) compliance, and what innovations are being introduced?",
        "search_query": "<sector_name> sector sustainability ESG compliance innovations"
    }
]
