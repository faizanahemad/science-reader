from base import serpapi
import json
from pprint import pprint

def serp():
    query = "coffee"
    key = "XXX"
    num = 10
    results = serpapi(query, key, num, our_datetime=None, only_pdf=False, only_science_sites=False)
    pprint(results)

if __name__ == "__main__":
    serp()