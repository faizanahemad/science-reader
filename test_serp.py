from base import serpapi, googleapi, brightdata_google_serp, googleapi_v2
import json
from pprint import pprint
import time
def serp():
    query = "coffee mugs"
    key = "f6b1b5668e05db3f400e798ffebad2a26c107ef3a97b48d11f9bbb38ea5d90f5"
    num = 10
    start_time = time.time()
    results = serpapi(query, key, num, our_datetime=None, only_pdf=False, only_science_sites=False)
    end_time = time.time()
    start_time = time.time()
    results = serpapi(query, key, num, our_datetime=None, only_pdf=False, only_science_sites=False)
    end_time = time.time()
    pprint(results[0].keys())
    print("Time taken: ", f"{(end_time - start_time):.2f}")

    start_time = time.time()
    results = googleapi(query, {"cx": "f47a96c4f436c40ad", "api_key": "AIzaSyBsCe-8MeLWn0AJGpxg6tszc4Dz3Y-LQ2Q"}, num, our_datetime=None, only_pdf=False, only_science_sites=False)
    end_time = time.time()
    pprint(results[0].keys())
    print("Time taken: ", f"{(end_time - start_time):.2f}")

    start_time = time.time()
    results = googleapi_v2(query, {"cx": "f47a96c4f436c40ad", "api_key": "AIzaSyBsCe-8MeLWn0AJGpxg6tszc4Dz3Y-LQ2Q"}, num,
                        our_datetime=None, only_pdf=False, only_science_sites=False)
    end_time = time.time()
    pprint(results[0].keys())
    print("Time taken: ", f"{(end_time - start_time):.2f}")

    # pprint(results)
    # pprint(results1)
    # pprint(results2)

if __name__ == "__main__":
    serp()