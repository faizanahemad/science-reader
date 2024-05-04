from common import *
from datetime import datetime, timedelta
import sys
import random
from functools import partial
import glob
import traceback
from operator import itemgetter
import itertools
from queue import Empty
import re
import inspect
import random

import concurrent.futures
import pandas as pd
pd.set_option('display.max_rows', None)
pd.set_option('display.max_columns', None)
pd.set_option('display.width', 1000)
import tiktoken
from copy import deepcopy, copy
import requests

import json
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed, FIRST_COMPLETED, wait
import urllib3
urllib3.disable_warnings()
import requests
import re
import traceback

from loggers import getLoggers
logger, time_logger, error_logger, success_logger, log_memory_usage = getLoggers(__name__, logging.DEBUG, logging.INFO, logging.ERROR, logging.INFO)

def get_ticker_from_company_name(query, conversation):
    f"""We want to get the ticker symbol for a company name. For this we will perform web search and gather a few results then we will read those results and get the ticker symbol from them.
The user message for which we want the ticker symbol is given below.
User message: {query}
Write the ticker name inside <ticker> </ticker> tags like <ticker>GOOG</ticker>. If you are not able to find the ticker symbol, write "not found".
"""
    agent_reply = conversation.agent_level_one_websearch_helper(query, {"field": "Finance"})
    # get ticker name from agent reply
    ticker = None
    tickers = re.findall(r'<ticker>(.*?)</ticker>', agent_reply)
    if tickers:
        ticker = tickers[0]
    return ticker

def get_year_quarter_from_text(text):
    pass


from nsepython import *
from nsepython import nse_marketStatus, nse_fiidii, nse_index, niftyindices_headers
from dateparser import parse
logging.basicConfig(level=logging.DEBUG)

indices_headers = headers = {
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
    # "Content-Length": "70", # This is usually calculated automatically by the requests library
    "Content-Type": "application/json; charset=UTF-8",
    "Host": "niftyindices.com",
    "Origin": "https://niftyindices.com",
    "Referer": "https://niftyindices.com/market-data/advanced-charting?Iname=Nifty%20100",
    "Sec-Ch-Ua": "\"Google Chrome\";v=\"123\", \"Not:A-Brand\";v=\"8\", \"Chromium\";v=\"123\"",
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": "\"macOS\"",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "X-Requested-With": "XMLHttpRequest"
}
niftyindices_headers.update(indices_headers)

@CacheResults(cache=FixedSizeFIFODict(10), dtype_filters=[str, int, tuple, bool], enabled=True)
def run_nse_fetch():
    positions = nsefetch('https://www.nseindia.com/api/equity-stockIndices?index=SECURITIES%20IN%20F%26O')
    return positions

def nse_custom_function_secfno(symbol):
    positions = nsefetch('https://www.nseindia.com/api/equity-stockIndices?index=SECURITIES%20IN%20F%26O')
    endp = len(positions['data'])
    for x in range(0, endp):
        if(positions['data'][x]['symbol']==symbol.upper()):
            return positions['data'][x]

def get_dates(start_date = None, end_date = None):
    from datetime import datetime, timedelta
    # Assuming you meant to use the datetime module to calculate dates
    # start date 2 years ago
    if start_date is None:
        start_date = datetime.now() - timedelta(days=365 * 2)
    if end_date is None or end_date == "now":
        end_date = datetime.now()

        # Convert dates to strings in the format expected by equity_history function
    # start date could be like 3 months ago , or like 2 years ago, or like 3 years 6 months ago. Lets parse such strings
    if isinstance(start_date, str):
        start_date = parse(start_date)
    if isinstance(end_date, str) and end_date != "now":
        end_date = parse(end_date)
    start_date_str = start_date.strftime("%d-%m-%Y")
    end_date_str = end_date.strftime("%d-%m-%Y")
    return start_date_str, end_date_str

def parse_date(date_str):
    from dateparser import parse
    return parse(date_str)


@CacheResults(cache=FixedSizeFIFODict(100), dtype_filters=[str, int, tuple, bool], enabled=True)
def get_equity_history(symbol, start_date=None, end_date=None):
    start_date_str, end_date_str = get_dates(start_date, end_date)

    # Assuming the recursive call was a mistake and you meant to fetch equity history
    # Replace the following line with the actual code to fetch the equity history
    # For demonstration, I'll just return the symbol, start_date_str, and end_date_str
    # Corrected the function call to use the string formatted dates
    return equity_history(symbol.upper(), "EQ", start_date_str, end_date_str)


@CacheResults(cache=FixedSizeFIFODict(100), dtype_filters=[str, int, tuple, bool], enabled=True)
def get_nse_eq(symbol):
    assert symbol in get_nse_eq_symbols(), f"Symbol {symbol} not found in NSE Equity list"
    return nse_eq(symbol)


@CacheResults(cache=FixedSizeFIFODict(100), dtype_filters=[str, int, tuple, bool], enabled=True)
def get_fno_list():
    return fnolist()

@CacheResults(cache=FixedSizeFIFODict(100), dtype_filters=[str, int, tuple, bool], enabled=True)
def get_nse_fno(symbol):
    assert symbol in get_fno_list(), f"Symbol {symbol} not found in F&O list"
    return nse_fno(symbol)


@CacheResults(cache=FixedSizeFIFODict(100), dtype_filters=[str, int, tuple, bool], enabled=True)
def nse_quote(symbol, section=""):
#https://forum.unofficed.com/t/nsetools-get-quote-is-not-fetching-delivery-data-and-delivery-can-you-include-this-as-part-of-feature-request/1115/4
    symbol = nsesymbolpurify(symbol)

    if(section==""):
        if any(x in symbol for x in fnolist()):
            payload = nsefetch('https://www.nseindia.com/api/quote-derivative?symbol='+symbol)
        else:
            payload = nsefetch('https://www.nseindia.com/api/quote-equity?symbol='+symbol)
        return payload

    if(section!=""):
        payload = nsefetch('https://www.nseindia.com/api/quote-equity?symbol='+symbol+'&section='+section)
        return payload


def get_delivery_info(symbol):
    return nse_quote(symbol, "trade_info")

@CacheResults(cache=FixedSizeFIFODict(100), dtype_filters=[str, int, tuple, bool], enabled=True)
def get_quote_ltp_meta(symbol, *args):
    quote_meta = nse_quote_meta(symbol,"latest","Fut")
    quote_ltp = nse_quote_ltp(symbol, *args)
    return {"meta": quote_meta, "ltp": quote_ltp}


@CacheResults(cache=FixedSizeFIFODict(100), dtype_filters=[str, int, tuple, bool], enabled=True)
def get_expiry_list(symbol):
    return expiry_list(symbol)

def get_nse_past_results(symbol):
    return nse_past_results(symbol)

def get_nse_results():
    return nse_results("equities", "Quarterly")

def get_beta(symbol, days=365, symbol2="NIFTY 50"):
    # Beta is a coefficient is a measure of its volatility over time compared to a market benchmark. Market benchmark has a beta of 1. Shortly, if volatility is 1.5 it means it is 50% more volatile than the market.
    # symbol – The stock/index of whose beta has to be checked.
    # days – Time period of comparison. It’s optional with a default value of 365.
    # symbol2 – The stock/index against which beta has to be checked. It’s optional with a default value of NIFTY 50.
    """
    Beta is a measure of the volatility of a stock or portfolio in comparison to a benchmark. A beta of 1 indicates that the stock's price will move with the market.
    A beta of less than 1 means that the stock will be less volatile than the market, and a beta of more than 1 means that the stock will be more volatile than the market.

    :param symbol: The stock/index of whose beta has to be checked.
    :param days: Time period of comparison. It’s optional with a default value of 365.
    :param symbol2: The stock/index against which beta has to be checked. It’s optional with a default value of NIFTY 50.
    :return:
    """

    return get_beta(symbol, days, symbol2)

def get_nse_most_active():
    securities_by_value = nse_most_active(type="securities", sort="value")
    securities_by_volume = nse_most_active(type="securities", sort="volume")

    sme_by_value = nse_most_active(type="sme", sort="value")
    sme_by_volume = nse_most_active(type="sme", sort="volume")
    return dict(securities_by_value=securities_by_value, securities_by_volume=securities_by_volume, sme_by_value=sme_by_value, sme_by_volume=sme_by_volume)

@CacheResults(cache=FixedSizeFIFODict(100), dtype_filters=[str, int, tuple, bool], enabled=True)
def get_nse_eq_symbols():
    return nse_eq_symbols()

@CacheResults(cache=FixedSizeFIFODict(100), dtype_filters=[str, int, tuple, bool], enabled=True)
def get_nse_get_index_list():
    return nse_get_index_list()

def get_index_quote(symbol):
    assert symbol in get_nse_get_index_list(), f"Symbol {symbol} not found in NSE Index list"
    return nse_get_index_quote(symbol)

def get_top_gainers_losers():
    top_gainers = nse_get_top_gainers()
    top_losers = nse_get_top_losers()
    return dict(top_gainers=top_gainers, top_losers=top_losers)

def get_daily_bhav_copy():
    return get_bhavcopy()

def get_index_history(symbol,start_date=None, end_date=None):
    start_date_str, end_date_str = get_dates(start_date, end_date)
    assert symbol in get_nse_get_index_list(), f"Symbol {symbol} not found in NSE Index list"
    return index_history(symbol, start_date_str, end_date_str)

def get_index_pe_pb_div(symbol, start_date=None, end_date=None):
    start_date_str, end_date_str = get_dates(start_date, end_date)
    assert symbol in get_nse_get_index_list(), f"Symbol {symbol} not found in NSE Index list"
    return index_pe_pb_div(symbol, start_date_str, end_date_str)

def get_index_total_returns(symbol, start_date=None, end_date=None):
    start_date_str, end_date_str = get_dates(start_date, end_date)
    assert symbol in get_nse_get_index_list(), f"Symbol {symbol} not found in NSE Index list"
    return index_total_returns(symbol, start_date_str, end_date_str)

def get_index_details(symbol, start_date=None, end_date=None):
    start_date_str, end_date_str = get_dates(start_date, end_date)
    assert symbol in get_nse_get_index_list(), f"Symbol {symbol} not found in NSE Index list"
    index_total_returns = None # get_index_total_returns(symbol, start_date_str, end_date_str)
    index_pe_pb_div = get_index_pe_pb_div(symbol, start_date_str, end_date_str)
    index_history = get_index_history(symbol, start_date_str, end_date_str)
    index_quote = get_index_quote(symbol)
    return dict(index_total_returns=index_total_returns, index_pe_pb_div=index_pe_pb_div, index_history=index_history, index_quote=index_quote)

def get_get_bhavcopy_by_date(date=None):
    if date is None:
        date = datetime.now().strftime("%d-%m-%Y")
    date = parse(date).strftime("%d-%m-%Y")
    return get_bhavcopy(date)




if __name__ == "__main__":
    # print(run_nse_fetch())

    # print(nse_custom_function_secfno('reliance'))

    #
    # eqh = get_equity_history('reliance')
    # print(type(eqh))
    # print(eqh.columns)
    # print()

    # print(help(nsesymbolpurify))
    # print(get_nse_eq('reliance'))

    # print(get_nse_past_results('SBIN'))
    # print(get_nse_results())
    print(get_index_details("NIFTY 50"))
    # print(get_index_total_returns("NIFTY 50"))