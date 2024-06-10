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
