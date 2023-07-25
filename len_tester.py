import copy
from tqdm.auto import tqdm

from transformers import AutoTokenizer
repo_id = 'TheBloke/Llama-2-70B-Chat-fp16'
tokenizer = AutoTokenizer.from_pretrained(repo_id, use_fast=True)

text = """
Amazon.com, Inc.[1] (/ˈæməzɒn/ AM-ə-zon, UK also /ˈæməzən/ AM-ə-zən) is an American multinational technology company focusing on e-commerce, cloud computing, online advertising, digital streaming, and artificial intelligence. It has been often referred to as "one of the most influential economic and cultural forces in the world,"[5] and is often regarded as one of the world's most valuable brands.[6] It is considered one of the Big Five American technology companies, alongside Alphabet (parent company of Google), Apple, Meta (formerly Facebook, Inc.) and Microsoft.

Amazon was founded by Jeff Bezos from his garage in Bellevue, Washington,[7] on July 5, 1994. Initially an online marketplace for books, it has expanded into a multitude of product categories, a strategy that has earned it the moniker The Everything Store.[8] It has multiple subsidiaries including Amazon Web Services (cloud computing), Zoox (autonomous vehicles), Kuiper Systems (satellite Internet), and Amazon Lab126 (computer hardware R&D). Its other subsidiaries include Ring, Twitch, IMDb, and Whole Foods Market. Its acquisition of Whole Foods in August 2017 for US$13.4 billion substantially increased its footprint as a physical retailer.[9]

Amazon has earned a reputation as a disruptor of well-established industries through technological innovation and "aggressive" reinvestment of profits into capital expenditures.[10][11][12][13] As of 2023, it is the world's largest online retailer and marketplace, smart speaker provider, cloud computing service through AWS,[14] live-streaming service through Twitch, and Internet company as measured by revenue and market share.[15] In 2021, it surpassed Walmart as the world's largest retailer outside of China, driven in large part by its paid subscription plan, Amazon Prime, which has over 200 million subscribers worldwide.[16][17] It is the second-largest private employer in the United States.[18]

Amazon also distributes a variety of downloadable and streaming content through its Amazon Prime Video, Amazon Music, Twitch, and Audible units. It publishes books through its publishing arm, Amazon Publishing, film and television content through Amazon Studios, and has been the owner of film and television studio Metro-Goldwyn-Mayer since March 2022. It also produces consumer electronics—most notably, Kindle e-readers, Echo devices, Fire tablets, and Fire TVs.

Amazon was founded on July 5, 1994, by Jeff Bezos, who chose the Seattle area for its abundance of technical talent, as Microsoft was in the area.[25]

Amazon went public in May 1997. It began selling music and videos in 1998, and began international operations by acquiring online sellers of books in the United Kingdom and Germany. The following year, it began selling music, video games, consumer electronics, home improvement items, software, games, and toys.[26][27]

In 2002, it launched Amazon Web Services (AWS), which initially focused on providing APIs for web developers to build web applications on top of Amazon's ecommerce platform.[28][29] In 2004, AWS was expanded to provide website popularity statistics and web crawler data from the Alexa Web Information Service.[30] AWS later shifted toward providing enterprise services with Simple Storage Service (S3) in 2006,[31] and Elastic Compute Cloud (EC2) in 2008,[32] allowing companies to rent data storage and computing power from Amazon. In 2006, Amazon also launched the Fulfillment by Amazon program, which allowed individuals and small companies (called "third-party sellers") to sell products through Amazon's warehouses and fulfillment infrastructure.[33]

In 2012, Amazon bought Kiva Systems to automate its inventory-management business, purchasing Whole Foods Market supermarket chain five years later in 2017.[34] In 2018, Bezos announced that its two-day delivery service, Amazon Prime, had surpassed 100 million subscribers worldwide.[35] In 2019, Amazon surpassed Walmart as the world's largest retailer outside of China.[36] In 2020, Amazon reported US$386 billion in revenue and US$21.3 billion in net profit.[37] In 2021, Amazon surpassed Walmart as the world's largest retailer.[38]

Amazon purchased the Whole Foods Market supermarket chain in 2017.[34] It is the leading e-retailer in the United States with approximately US$178 billion net sales in 2017. It has over 300 million active customer accounts globally.[35]

Amazon saw large growth during the COVID-19 pandemic, hiring more than 100,000 staff in the United States and Canada.[36] Some Amazon workers in the US, France, and Italy protested the company's decision to "run normal shifts" due to COVID-19's ease of spread in warehouses.[37][38] In Spain, the company faced legal complaints over its policies,[39] while a group of US Senators wrote an open letter to Bezos expressing concerns about workplace safety.[40]

On February 2, 2021, Bezos announced that would step down as CEO to become executive chair of Amazon's board. The transition officially took place on July 5, 2021, with former CEO of AWS Andy Jassy replacing him as CEO.[41][42] In January 2023, Amazon cut over 18,000 jobs, primarily in consumer retail and its human resources division in an attempt to cut costs.[43]

In 2000, U.S. toy retailer Toys "R" Us entered into a 10-year agreement with Amazon, valued at $50 million per year plus a cut of sales, under which Toys "R" Us would be the exclusive supplier of toys and baby products on the service, and the chain's website would redirect to Amazon's Toys & Games category. In 2004, Toys "R" Us sued Amazon, claiming that because of a perceived lack of variety in Toys "R" Us stock, Amazon had knowingly allowed third-party sellers to offer items on the service in categories that Toys "R" Us had been granted exclusivity. In 2006, a court ruled in favor of Toys "R" Us, giving it the right to unwind its agreement with Amazon and establish its independent e-commerce website. The company was later awarded $51 million in damages.[59][60][61]

In 2001, Amazon entered into a similar agreement with Borders Group, under which Amazon would comanage Borders.com as a co-branded service.[62] Borders pulled out of the arrangement in 2007, with plans to also launch its own online store.[63]

On October 18, 2011, Amazon.com announced a partnership with DC Comics for the exclusive digital rights to many popular comics, including Superman, Batman, Green Lantern, The Sandman, and Watchmen. The partnership has caused well-known bookstores like Barnes & Noble to remove these titles from their shelves.[64]

In November 2013, Amazon announced a partnership with the United States Postal Service to begin delivering orders on Sundays. The service, included in Amazon's standard shipping rates, initiated in metropolitan areas of Los Angeles and New York because of the high-volume and inability to deliver in a timely way, with plans to expand into Dallas, Houston, New Orleans and Phoenix by 2014.[65]

In June 2017, Nike agreed to sell products through Amazon in exchange for better policing of counterfeit goods.[66][67] This proved unsuccessful and Nike withdrew from the partnership in November 2019.[67][68] Companies including IKEA and Birkenstock also stopped selling through Amazon around the same time, citing similar frustrations over business practices and counterfeit goods.[69]

In September 2017, Amazon ventured with one of its sellers JV Appario Retail owned by Patni Group which has recorded a total income of US$ 104.44 million (₹759  crore) in financial year 2017–2018.[70]

As of October 11, 2017, AmazonFresh sold a range of Booths branded products for home delivery in selected areas.[71]

In November 2018, Amazon reached an agreement with Apple Inc. to sell selected products through the service, via the company and selected Apple Authorized Resellers. As a result of this partnership, only Apple Authorized Resellers may sell Apple products on Amazon effective January 4, 2019.

Amazon sells many products under its own brand names, including phone chargers, batteries, and diaper wipes. The AmazonBasics brand was introduced in 2009, and now features hundreds of product lines, including smartphone cases, computer mice, batteries, dumbbells, and dog crates. Amazon owned 34 private-label brands as of 2019. These brands account for 0.15% of Amazon's global sales, whereas the average for other large retailers is 18%.[74] Other Amazon retail brands include Presto!, Mama Bear, and Amazon Essentials.

Amazon allows users to submit reviews to the web page of each product. Reviewers must rate the product on a rating scale from one to five stars. Amazon provides a badging option for reviewers which indicates the real name of the reviewer (based on confirmation of a credit card account) or which indicates that the reviewer is one of the top reviewers by popularity. As of December 16, 2020, Amazon removed the ability of sellers and customers to comment on product reviews and purged their websites of all posted product review comments. In an email to sellers Amazon gave its rationale for removing this feature: "... the comments feature on customer reviews was rarely used." The remaining review response options are to indicate whether the reader finds the review helpful or to report that it violates Amazon policies (abuse). If a review is given enough "helpful" hits, it appears on the front page of the product. In 2010, Amazon was reported as being the largest single source of Internet consumer reviews.[82]

When publishers asked Bezos why Amazon would publish negative reviews, he defended the practice by claiming that Amazon.com was "taking a different approach ... we want to make every book available—the good, the bad and the ugly ... to let truth loose".[83]

There have been cases of positive reviews being written and posted by public relations companies on behalf of their clients[84] and instances of writers using pseudonyms to leave negative reviews of their rivals' works.

The Amazon sales rank (ASR) indicates the popularity of a product sold on any Amazon locale. It is a relative indicator of popularity that is updated hourly. Effectively, it is a "best sellers list" for the millions of products stocked by Amazon.[85] While the ASR has no direct effect on the sales of a product, it is used by Amazon to determine which products to include in its bestsellers lists.[85] Products that appear in these lists enjoy additional exposure on the Amazon website and this may lead to an increase in sales. In particular, products that experience large jumps (up or down) in their sales ranks may be included within Amazon's lists of "movers and shakers"; such a listing provides additional exposure that might lead to an increase in sales.[86] For competitive reasons, Amazon does not release actual sales figures to the public. However, Amazon has now begun to release point of sale data via the Nielsen BookScan service to verified authors.[87] While the ASR has been the source of much speculation by publishers, manufacturers, and marketers, Amazon itself does not release the details of its sales rank calculation algorithm. 
"""

def get_text_len(expected_len):
    inner_text = copy.deepcopy(text)
    prompt = f"Summarise: \n'''{inner_text}''' \nSummary:\n"
    actual_len = len(tokenizer(prompt, return_tensors="pt")["input_ids"][0])
    if expected_len < actual_len:
        while expected_len < actual_len:
            inner_text = inner_text[:-20]
            prompt = f"Summarise: \n'''{inner_text}''' \nSummary:\n"
            actual_len = len(tokenizer(prompt, return_tensors="pt")["input_ids"][0])
    return prompt

results = []
# 4bit/Llama-2-70b-chat-hf
for repo_id in ["TheBloke/Llama-2-70B-Chat-fp16", "4bit/Llama-2-13b-chat-hf", "TheBloke/Llama-2-7b-Chat-GPTQ", "tiiuae/falcon-40b-instruct", "tiiuae/falcon-7b-instruct", "mosaicml/mpt-30b-instruct"]:
    tokenizer = AutoTokenizer.from_pretrained(repo_id, use_fast=True)
    for op_len in tqdm([8, 16, 32, 64, 96, 128]):

        for i in [64-op_len, 128-op_len, 256-op_len, 512-op_len, 1024-op_len, 1536-op_len, 2048-op_len]:
            if i < 8:
                continue
            prompt = get_text_len(i-2)
            results.append((repo_id, i+op_len, len(tokenizer(prompt, return_tensors="pt")["input_ids"][0]), op_len, prompt))

import pandas as pd
df = pd.DataFrame(results, columns=["model_id", "total_len", "prompt_len", "expected_result_len", "prompt"])
df.to_csv("len_tester.csv", index=False)


