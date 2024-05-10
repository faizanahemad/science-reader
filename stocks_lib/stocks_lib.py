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



@CacheResults(cache=FixedSizeFIFODict(100), dtype_filters=[str, int, tuple, bool], enabled=True)
def get_quote_ltp_meta(symbol, *args):
    quote_meta = nse_quote_meta(symbol,"latest","Fut")
    quote_ltp = nse_quote_ltp(symbol, *args)
    return {"meta": quote_meta, "ltp": quote_ltp}




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

from nsepython import *
from common_stock_functions import get_dates


def get_index_history(symbol,start_date=None, end_date=None):
    start_date_str, end_date_str = get_dates(start_date, end_date, format="%m-%d-%Y")
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
    start_date_str, end_date_str = get_dates(start_date, end_date, format="%m-%d-%Y")
    assert symbol in get_nse_get_index_list(), f"Symbol {symbol} not found in NSE Index list"
    index_total_returns = None # get_index_total_returns(symbol, start_date_str, end_date_str)
    index_pe_pb_div = None # get_index_pe_pb_div(symbol, start_date_str, end_date_str)
    index_history = get_index_history(symbol, start_date_str, end_date_str)
    index_quote = get_index_quote(symbol)
    return dict(index_total_returns=index_total_returns, index_pe_pb_div=index_pe_pb_div, index_history=index_history, index_quote=index_quote)




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
    # print(get_index_details("NIFTY 50"))
    # print(get_index_total_returns("NIFTY 50"))

    # print(get_index_quote("NIFTY 50"))
    # print(get_index_history("NIFTY 50"))
    # print(get_index_pe_pb_div("NIFTY 50"))
    # print(get_index_total_returns("NIFTY 50"))
    # print(get_index_details("NIFTY 50"))
    # print(get_equity_history("reliance"))
    # print(get_nse_past_results("SBIN"))
    # print(get_daily_bhav_copy("03-03-2024"))
    print(get_quote_ltp_meta("RELIANCE"))