"""
Shared endpoint helpers.

As we extract routes from `server.py`, we will move cross-cutting helper
functions (used by multiple blueprints) into this module.
"""

from __future__ import annotations

import ast
import os
from typing import Any, Mapping

from Conversation import Conversation, TemporaryConversation
from DocIndex import DocIndex, ImmediateDocIndex, ImageDocIndex


def keyParser(session) -> dict[str, Any]:
    """
    Resolve all API keys and runtime model/config URLs from Flask session and environment.

    This is a direct extraction of the legacy `server.py` helper.

    Parameters
    ----------
    session:
        Flask session proxy.

    Returns
    -------
    dict[str, Any]
        Dict containing all configured keys/URLs and (optionally) a parsed list
        of models in `openai_models_list`.
    """

    keyStore: dict[str, Any] = {
        "openAIKey": os.getenv("openAIKey", ""),
        "jinaAIKey": os.getenv("jinaAIKey", ""),
        "elevenLabsKey": os.getenv("elevenLabsKey", ""),
        "ASSEMBLYAI_API_KEY": os.getenv("ASSEMBLYAI_API_KEY", ""),
        "mathpixId": os.getenv("mathpixId", ""),
        "mathpixKey": os.getenv("mathpixKey", ""),
        "cohereKey": os.getenv("cohereKey", ""),
        "ai21Key": os.getenv("ai21Key", ""),
        "bingKey": os.getenv("bingKey", ""),
        "serpApiKey": os.getenv("serpApiKey", ""),
        "googleSearchApiKey": os.getenv("googleSearchApiKey", ""),
        "googleSearchCxId": os.getenv("googleSearchCxId", ""),
        "openai_models_list": os.getenv("openai_models_list", "[]"),
        "scrapingBrowserUrl": os.getenv("scrapingBrowserUrl", ""),
        "vllmUrl": os.getenv("vllmUrl", ""),
        "vllmLargeModelUrl": os.getenv("vllmLargeModelUrl", ""),
        "vllmSmallModelUrl": os.getenv("vllmSmallModelUrl", ""),
        "tgiUrl": os.getenv("tgiUrl", ""),
        "tgiLargeModelUrl": os.getenv("tgiLargeModelUrl", ""),
        "tgiSmallModelUrl": os.getenv("tgiSmallModelUrl", ""),
        "embeddingsUrl": os.getenv("embeddingsUrl", ""),
        "zenrows": os.getenv("zenrows", ""),
        "scrapingant": os.getenv("scrapingant", ""),
        "brightdataUrl": os.getenv("brightdataUrl", ""),
        "brightdataProxy": os.getenv("brightdataProxy", ""),
        "OPENROUTER_API_KEY": os.getenv("OPENROUTER_API_KEY", ""),
        "LOGIN_BEARER_AUTH": os.getenv("LOGIN_BEARER_AUTH", ""),
    }

    if (
        str(keyStore["vllmUrl"]).strip() != ""
        or str(keyStore["vllmLargeModelUrl"]).strip() != ""
        or str(keyStore["vllmSmallModelUrl"]).strip() != ""
    ):
        keyStore["openai_models_list"] = ast.literal_eval(keyStore["openai_models_list"])

    for k, v in keyStore.items():
        key = session.get(k, v)
        if key is None or (isinstance(key, str) and key.strip() == "") or (isinstance(key, list) and len(key) == 0):
            key = v
        if key is not None and ((isinstance(key, str) and len(key.strip()) > 0) or (isinstance(key, list) and len(key) > 0)):
            keyStore[k] = key
        else:
            keyStore[k] = None

    return keyStore


def set_keys_on_docs(docs: Any, keys: Mapping[str, Any], *, logger=None) -> Any:
    """
    Attach API keys to various doc/conversation objects.

    This mirrors `server.py:set_keys_on_docs` but lives in `endpoints/utils.py`
    so extracted blueprints can reuse it without importing `server.py`.
    """

    log = logger
    if docs is None:
        return docs

    if isinstance(docs, dict):
        for _k, v in docs.items():
            v.set_api_keys(keys)
    elif isinstance(docs, (list, tuple, set)):
        for d in docs:
            d.set_api_keys(keys)
    else:
        try:
            assert isinstance(
                docs, (DocIndex, ImmediateDocIndex, ImageDocIndex, Conversation, TemporaryConversation)
            ) or hasattr(docs, "set_api_keys")
            docs.set_api_keys(keys)
        except Exception as e:
            if log is not None:
                log.error(f"Failed to set keys on docs: {e}, type = {type(docs)}")
            raise
    return docs


