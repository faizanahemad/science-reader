import sys
from urllib.parse import unquote
from functools import wraps
import mmh3
import ast
import traceback
from flask import Flask, request, jsonify, send_file, session, redirect, url_for, render_template_string
from authlib.integrations.flask_client import OAuth
from flask_session import Session
from collections import defaultdict
import requests
from io import BytesIO
from langchain.vectorstores import FAISS
from langchain.embeddings.base import Embeddings
from langchain.embeddings import OpenAIEmbeddings
from langchain.vectorstores.base import VectorStore
from collections import defaultdict
from DocIndex import DocIndex, create_immediate_document_index, ImmediateDocIndex
import os
import time
import multiprocessing
import glob
import json
from rank_bm25 import BM25Okapi
from typing import List, Dict
from flask import Flask, Response, stream_with_context
import sys
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from DataModel import *
from sqlalchemy import func
import spacy
from spacy.lang.en import English
from spacy.pipeline import Lemmatizer


from base import get_embedding_model
sys.setrecursionlimit(sys.getrecursionlimit()*16)
import logging
import requests
from flask_caching import Cache
import argparse
from datetime import timedelta
import sqlite3
from sqlite3 import Error
from common import checkNoneOrEmpty
from sqlalchemy.orm.attributes import flag_modified

os.environ["BING_SEARCH_URL"] = "https://api.bing.microsoft.com/v7.0/search"
        
        
from datetime import datetime

def addUserToDoc(user_id, doc_id, sql_session=None):
    if sql_session is None:
        sql_session = SQLSession()
    # Create a new SQLAlchemy Session
    sql_session = SQLSession()

    # Query the User and Document objects
    user = sql_session.query(User).filter_by(id=user_id).one_or_none()
    document = sql_session.query(Document).filter_by(id=doc_id).one_or_none()

    # If the User or Document doesn't exist, handle the error
    if user is None or document is None:
        sql_session.close()
        raise ValueError("User or Document not found")

    # Add the Document to the User's documents
    user.documents.append(document)

    # Commit the changes to the database
    sql_session.commit()

    # Close the session
    sql_session.close()


def getDocsForUser(sql_session, user_id):
    # Query the User object with the given user_id, and join with the 'documents' table
    user: User = sql_session.query(User).options(joinedload(User.documents)).filter(User.id == user_id).one_or_none()
    # If the User object exists, return its associated documents
    docs = user.documents
    docs = DocIndex.convert_document_to_docindex(docs)
    if user:
        return docs

    else:
        return None
    
    

def addUpvoteOrDownvote(user_id, question_id, doc_id, upvote, downvote, type):
    sql_session = SQLSession()
    # Check if a Feedback entry already exists for this user and question
    
    assert type in ["question","review", "in_depth_reader", "message"]
    if type == "question":
        kws = dict(question_id=question_id)
    elif type == "review":
        kws = dict(review_id=question_id)
    elif type == "in_depth_reader":
        kws = dict(in_depth_reader_id=question_id)
    elif type == "message":
        kws = dict(message_id=question_id)
    feedback = sql_session.query(Feedback).filter_by(user_id=user_id, **kws).first()
    if feedback:
        # If it exists, update the upvote and downvote values
        feedback.addUpvoteOrDownvote(upvote, downvote)
    else:
        # If it doesn't exist, create a new Feedback entry
        feedback = Feedback(
            user_id=user_id,
            doc_id=doc_id,
            upvoted=upvote,
            downvoted=downvote,
            **kws
        )
        sql_session.add(feedback)

    sql_session.commit()
    sql_session.close()


def addGranularFeedback(user_id, question_id, feedback_type, feedback_items, comments, question_text):
    # Ensure that the user has already voted before updating the feedback
    sql_session = SQLSession()
    assert not checkNoneOrEmpty(user_id)
    assert not checkNoneOrEmpty(question_id)
    feedback: Feedback = sql_session.query(Feedback).filter(
        Feedback.user_id == user_id,
        Feedback.question_id == question_id
    ).first()
    
    if not feedback:
        raise ValueError("A vote must exist for the user and question before feedback can be provided")
    feedback.addGranularFeedback(feedback_type, feedback_items, comments, question_text)
    sql_session.commit()
    sql_session.close()

def getUpvotesDownvotesByUser(user_id):
    sql_session = SQLSession()
    result = sql_session.query(
        func.sum(Feedback.upvoted), 
        func.sum(Feedback.downvoted)
    ).filter(
        Feedback.user_id == user_id
    ).group_by(
        Feedback.user_id
    ).all()
    sql_session.close()
    return result

def getUpvotesDownvotesByQuestionId(question_id):
    sql_session = SQLSession()
    result = sql_session.query(
        func.sum(Feedback.upvoted), 
        func.sum(Feedback.downvoted)
    ).filter(
        Feedback.question_id == question_id
    ).group_by(
        Feedback.question_id
    ).all()
    sql_session.close()

    return result

def getUpvotesDownvotesByQuestionIdAndUser(question_id, user_id):
    sql_session = SQLSession()
    result = sql_session.query(
        func.sum(Feedback.upvoted), 
        func.sum(Feedback.downvoted)
    ).filter(
        Feedback.question_id == question_id,
        Feedback.user_id == user_id
    ).group_by(
        Feedback.question_id,
        Feedback.user_id
    ).all()
    sql_session.close()
    return result


def removeUserFromDoc(user_email, doc_id):
    sql_session = SQLSession()
    user = sql_session.query(User).get(user_email)
    document = sql_session.query(Document).get(doc_id)
    user.documents.remove(document)
    document.users.remove(user)
    sql_session.commit()

def keyParser(session):
    keyStore = {
        "openAIKey": '',
        "mathpixId": '',
        "mathpixKey": '',
        "cohereKey": '',
        "ai21Key": '',
        "bingKey": '',
        "serpApiKey": '',
        "googleSearchApiKey":'',
        "googleSearchCxId":'',
        "openai_models_list": '',
        "scrapingBrowserUrl": '',
        "email": '',
    }
    for k, _ in keyStore.items():
        key = session.get(k)
        keyStore[k] = key
        if key is not None and ((isinstance(key, str) and len(key.strip())>0) or (isinstance(key, list) and len(key)>0)):
            keyStore[k] = key
        else:
            keyStore[k] = None
    openai_embed = get_embedding_model(keyStore)
    keyStore["openai_embed"] = openai_embed
    return keyStore
    

def generate_ngrams(tokens, n):
    ngrams = zip(*[tokens[i:] for i in range(n)])
    return [" ".join(ngram) for ngram in ngrams]


logger = logging.getLogger(__name__)
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    datefmt="%m/%d/%Y %H:%M:%S",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(os.path.join(os.getcwd(), "log.txt"))
    ]
)
logging.getLogger('sqlalchemy.engine').setLevel(logging.INFO)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--folder', help='The folder where the DocIndex files are stored', required=False, default=None)
    parser.add_argument('--login_not_needed', help='Whether we use google login or not.', action="store_true")
    args = parser.parse_args()
    login_not_needed = args.login_not_needed
    folder = args.folder
    
    if not args.folder:
        folder = "storage"
else:
    folder = "storage"
    login_not_needed = True
app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY')
# app.secret_key = os.urandom(24)
# app.secret_key = 'your_secret_key_here'
app.config['SESSION_PERMANENT'] = False
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
app.config['SESSION_TYPE'] = 'filesystem'
app.config["GOOGLE_CLIENT_ID"] = "829412467201-koo2d873vemgtg7g92m2ffkkl9r97ubp.apps.googleusercontent.com"
app.config["GOOGLE_CLIENT_SECRET"] = "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"
Session(app)
oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=app.config.get("GOOGLE_CLIENT_ID"),
    client_secret=app.config.get("GOOGLE_CLIENT_SECRET"),
    access_token_url='https://accounts.google.com/o/oauth2/token',
    access_token_params=None,
    authorize_url='https://accounts.google.com/o/oauth2/auth',
    authorize_params=None,
    api_base_url='https://www.googleapis.com/oauth2/v1/',
    userinfo_endpoint='https://openidconnect.googleapis.com/v1/userinfo',  # This is only needed if using openId to fetch user info
    client_kwargs={'scope': 'email profile'},
    server_metadata_url= 'https://accounts.google.com/.well-known/openid-configuration',
)
os.makedirs(os.path.join(os.getcwd(), folder), exist_ok=True)
cache_dir = os.path.join(os.getcwd(), folder, "cache")
users_dir = os.path.join(os.getcwd(), folder, "sqlite")
pdfs_dir = os.path.join(os.getcwd(), folder, "pdfs")
os.makedirs(cache_dir, exist_ok=True)
os.makedirs(users_dir, exist_ok=True)
os.makedirs(pdfs_dir, exist_ok=True)
engine = create_engine(f'sqlite:///{users_dir}/main.db')
Base.metadata.create_all(engine)
SQLSession = sessionmaker(bind=engine)
nlp = English()  # just the language with no model
_ = nlp.add_pipe("lemmatizer")
nlp.initialize()

cache = Cache(app, config={'CACHE_TYPE': 'filesystem', 'CACHE_DIR': cache_dir, 'CACHE_DEFAULT_TIMEOUT': 7 * 24 * 60 * 60})

def check_login(session):
    email = dict(session).get('email', None)
    name = dict(session).get('name', None)
    logger.info(f"Check Login for email {session.get('email')} and name {session.get('name')}")
    sql_session = SQLSession()
    user: User = sql_session.query(User).filter(User.id == email).one_or_none()
    if user is None:
        user = User(id=email, name=name)
        sql_session.add(user)
        sql_session.commit()
    sql_session.close()
    return email, name, email is not None and name is not None

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        logger.info(f"Login Required call for email {session.get('email')} and name {session.get('name')}")
        if session.get('email') is None or session.get('name') is None:
            return redirect('/login', code=302)
        return f(*args, **kwargs)
    return decorated_function

@app.route('/addUpvoteOrDownvote', methods=['POST'])
@login_required
def add_upvote_downvote():
    email, name, _ = check_login(session)
    data = request.get_json()
    logger.info(f"Get upvote-downvote request with {data}")
    assert "type" in data
    if "question_text" in data:
        question_id = str(mmh3.hash(indexed_docs[data['doc_id']].doc_source + data["question_text"], signed=False))
        logger.info(f"'/addUpvoteOrDownvote' -> generated question_id = {question_id}, Received q_id = {data['question_id']}, both same = {data['question_id'] == question_id}")
        if checkNoneOrEmpty(data['question_id']):
            data['question_id'] = question_id
    if checkNoneOrEmpty(data['question_id']) or checkNoneOrEmpty(data['doc_id']):
        return "Question Id and Doc Id are needed for `/addUpvoteOrDownvote`", 400
    addUpvoteOrDownvote(email, data['question_id'], data['doc_id'], data['upvote'], data['downvote'], data["type"])
    return jsonify({'status': 'success'}), 200

@app.route('/getUpvotesDownvotesByUser', methods=['GET'])
@login_required
def get_votes_by_user():
    email, name, _ = check_login(session)
    rows = getUpvotesDownvotesByUser(email)
    logger.info(f"called , response = {rows}")
    return jsonify(rows), 200

@app.route('/getUpvotesDownvotesByQuestionId/<question_id>', methods=['GET'])
@login_required
def get_votes_by_question(question_id):
    if checkNoneOrEmpty(question_id) or question_id.strip().lower() == "null":
        data = ast.literal_eval(unquote(request.query_string))
        logger.info(f"'/getUpvotesDownvotesByQuestionId' -> data = {data}")
        if "question_text" in data and "doc_id" in data:
            question_id = str(mmh3.hash(indexed_docs[data['doc_id']].doc_source + data["question_text"], signed=False))
            logger.info(f"'/getUpvotesDownvotesByQuestionId' -> generated question_id = {question_id}")
        else:
            return "Question Id empty", 400
    email, name, _ = check_login(session)
    rows = getUpvotesDownvotesByQuestionId(question_id)
    logger.info(f"'/getUpvotesDownvotesByQuestionId' called with question_id = {question_id}, response = {rows}")
    return jsonify(rows), 200

@app.route('/getUpvotesDownvotesByQuestionIdAndUser', methods=['GET'])
@login_required
def get_votes_by_question_and_user():
    email, name, _ = check_login(session)
    question_id = request.args.get('question_id')
    
    if checkNoneOrEmpty(question_id) or question_id.strip().lower() == "null":
        data = ast.literal_eval(unquote(request.query_string))
        logger.info(f"'/getUpvotesDownvotesByQuestionIdAndUser' -> data = {data}")
        if "question_text" in data and "doc_id" in data:
            question_id = str(mmh3.hash(indexed_docs[data['doc_id']].doc_source + data["question_text"], signed=False))
            logger.info(f"'/getUpvotesDownvotesByQuestionIdAndUser' -> generated question_id = {question_id}")
        else:
            return "Question Id empty", 400
    rows = getUpvotesDownvotesByQuestionIdAndUser(question_id, email)
    logger.info(f"'/getUpvotesDownvotesByQuestionIdAndUser' called with question_id = {question_id}, response = {rows}")
    return jsonify(rows), 200


@app.route('/addUserQuestionFeedback', methods=['POST'])
@login_required
def add_user_question_feedback():
    email, name, _ = check_login(session)
    data = request.get_json()
    logger.info(f"GEt granular feedback request with {data}")
    if "question_text" in data:
        question_id = str(mmh3.hash(indexed_docs[data['doc_id']].doc_source + data["question_text"], signed=False))
        logger.info(f"'/addUserQuestionFeedback' -> generated question_id = {question_id}, Received q_id = {data['question_id']}, both same = {data['question_id'] == question_id}")
        if checkNoneOrEmpty(data['question_id']):
            data['question_id'] = question_id
    if checkNoneOrEmpty(data['question_id']) or checkNoneOrEmpty(data['doc_id']):
        return "Question Id and Doc Id are needed for `/addUserQuestionFeedback`", 400
    try:
        addGranularFeedback(email, data['question_id'], data['feedback_type'], data['feedback_items'], data['comments'], data['question_text'])
        return jsonify({'status': 'success'}), 200
    except ValueError as e:
        return str(e), 400


@app.route('/write_review/<doc_id>/<tone>', methods=['GET'])
@login_required
def write_review(doc_id, tone):
    keys = keyParser(session)
    email, name, _ = check_login(session)
    assert tone in ["positive", "negative", "neutral", "none"]
    review_topic = request.args.get('review_topic') # Has top level key and then an index variable
    review_topic = review_topic.split(",")
    review_topic = [r for r in review_topic if len(r.strip()) > 0 and r.strip()!='null']
    if len(review_topic) > 1:
        review_topic = [str(review_topic[0]), int(review_topic[1])]
    else:
        review_topic = review_topic[0]
    additional_instructions = request.args.get('instruction')
    use_previous_reviews = int(request.args.get('use_previous_reviews'))
    score_this_review = int(request.args.get('score_this_review'))
    is_meta_review = int(request.args.get('is_meta_review'))
    
    # Create a new SQLAlchemy Session
    sql_session = SQLSession()

    # Query the User and Document objects
    user = sql_session.query(User).filter_by(id=email).one_or_none()
    document = sql_session.query(Document).filter_by(id=doc_id).one_or_none()
    document = DocIndex.convert_document_to_docindex(document)
    try:
        review = set_keys_on_docs(document, keys).get_review(tone, review_topic, additional_instructions, score_this_review, use_previous_reviews, is_meta_review)
        return Response(stream_with_context(review), content_type='text/plain')
    except Exception as e:
        traceback.print_exc()
        logger.error(f"Error in getting review {e}")
        if sql_session.is_active:
            sql_session.rollback()
            sql_session.close()
        return "Error in getting review", 500
    finally:
        if sql_session.is_active:
            sql_session.rollback()
            sql_session.close()

@app.route('/get_reviews/<doc_id>', methods=['GET'])
@login_required
def get_all_reviews(doc_id):
    keys = keyParser(session)
    email, name, _ = check_login(session)
    sql_session = SQLSession()
    document = sql_session.query(Document).filter_by(id=doc_id).one_or_none()
    document = DocIndex.convert_document_to_docindex(document)
    reviews = set_keys_on_docs(document, keys).get_all_reviews()
    # lets send json response
    reviews = jsonify(reviews)
    sql_session.close()
    return reviews
    
    
@app.route('/login')
def login():
    redirect_uri = url_for('authorize', _external=True)
    if login_not_needed:
        email = request.args.get('email')
        if email is None:
            return send_from_directory('interface', 'login.html', max_age=0)
        session['email'] = email
        session['name'] = email
        return redirect('/interface', code=302)
    else:
        return google.authorize_redirect(redirect_uri)

@app.route('/logout')
@login_required
def logout():
    
    if 'token' in session: 
        access_token = session['token']['access_token'] 
        logger.info(f"Called /logout with token as {access_token} for logging out.")
        requests.post('https://accounts.google.com/o/oauth2/revoke',
            params={'token': access_token},
            headers = {'content-type': 'application/x-www-form-urlencoded'})
    
    session.clear() # clears the session
    return render_template_string("""
        <h1>Logged out</h1>
        <p><a href="{{ url_for('login') }}">Click here</a> to log in again. You can now close this Tab/Window.</p>
    """)

@app.route('/authorize')
def authorize():
    logger.info(f"Authorize for email {session.get('email')} and name {session.get('name')}")
    token = google.authorize_access_token()
    resp = google.get('userinfo')
    if resp.ok:
        user_info = resp.json()
        session['email'] = user_info['email']
        session['name'] = user_info['name']
        session['token'] = token
        return redirect('/interface')
    else:
        return "Failed to log in", 401

@app.route('/get_user_info')
@login_required
def get_user_info():
    if 'email' in session and "name" in session:
        return jsonify(name=session['name'], email=session['email'])
    elif google.authorized:
        resp = google.get('userinfo')
        if resp.ok:
            session['email'] = resp.json()['email']
            session['name'] = resp.json()['name']
            return jsonify(name=resp.json()["name"], email=resp.json()["email"])
    else:
        return "Not logged in", 401

class IndexDict(dict):
    def __getitem__(self, key):
        item = super().__getitem__(key)
        item = item.load_fresh_self()
        super().__setitem__(key, item)
        return item

    def get(self, key, default=None):
        if key in self:
            item = super().get(key)
            item = item.load_fresh_self()
            super().__setitem__(key, item)
            return item
        return default
indexed_docs: IndexDict[str, DocIndex] = {}

    
def set_keys_on_docs(docs, keys):
    logger.info(f"Attaching keys to doc")
    if isinstance(docs, dict):
        for k, v in docs.items():
            v.set_api_keys(keys)
            for i, j in vars(v).items():
                if isinstance(j,  (FAISS, VectorStore)):
                    j.embedding_function.__self__.openai_api_key = keys["openAIKey"]
                    setattr(j.embedding_function.__self__, "openai_api_key", keys["openAIKey"])
    elif isinstance(docs, (list, tuple, set)):
        for d in docs:
            d.set_api_keys(keys)
            for i, j in vars(d).items():
                if isinstance(j, (FAISS, VectorStore)):
                    j.embedding_function.__self__.openai_api_key = keys["openAIKey"]
                    setattr(j.embedding_function.__self__, "openai_api_key", keys["openAIKey"])
    else:
        assert isinstance(docs, (DocIndex, ImmediateDocIndex))
        for i, j in vars(docs).items():
            if isinstance(j,  (FAISS, VectorStore)):
                
                j.embedding_function.__self__.openai_api_key = keys["openAIKey"]
                setattr(j.embedding_function.__self__, "openai_api_key", keys["openAIKey"])
                
        docs.set_api_keys(keys)
    return docs
    

# Initialize an empty list of documents for BM25
bm25_corpus: Dict[str, List[str]] = {}
    
def add_to_bm25_corpus(doc_index: DocIndex):
    global bm25_corpus
    assert isinstance(doc_index, DocIndex)
    
    try:
        doc_info = doc_index.get_short_info()
        text = doc_info['title'].lower() + " " + doc_info['short_summary'].lower() + " " + doc_info['summary'].lower()
    except Exception as e:
        logger.info(f"Error in getting text for doc_id = {doc_index.doc_id}, error = {e}")
        text = doc_index.indices["chunks"][0]
    unigrams = text.split()
    bigrams = generate_ngrams(unigrams, 2)
    trigrams = generate_ngrams(unigrams, 3)
    doc = nlp(text)
    lemmas = [token.lemma_ for token in doc]
    bigrams_lemma = generate_ngrams(lemmas, 2)
    trigrams_lemma = generate_ngrams(lemmas, 3)
    
    bm25_corpus[doc_index.doc_id] =  unigrams + bigrams + trigrams + lemmas + bigrams_lemma + trigrams_lemma

def load_documents(folder):
    global bm25_corpus
    sql_session = SQLSession()
    documents = sql_session.query(Document).all()
    documents = DocIndex.convert_document_to_docindex(documents)
    for doc_index in documents:
        add_to_bm25_corpus(doc_index)
    sql_session.close()



@app.route('/search_document', methods=['GET'])
@login_required
def search_document():
    keys = keyParser(session)
    email, name, loggedin = check_login(session)
    sql_session = SQLSession()
    docs = getDocsForUser(sql_session, email)
    
    search_text = request.args.get('text')
    if search_text:
        search_text = search_text.strip().lower()
        user_bm25_corpus = [bm25_corpus[doc.doc_id] for doc in docs]
        doc_ids = [doc.doc_id for doc in docs]
        bm = BM25Okapi(user_bm25_corpus)
        
        search_tokens = search_text.split()
        search_unigrams = search_tokens
        search_bigrams = generate_ngrams(search_tokens, 2)
        search_trigrams = generate_ngrams(search_tokens, 3)
        
        doc = nlp(search_text)
        lemmas = [token.lemma_ for token in doc]
        bigrams_lemma = generate_ngrams(lemmas, 2)
        trigrams_lemma = generate_ngrams(lemmas, 3)
        
        scores = bm.get_scores(search_unigrams + search_bigrams + search_trigrams +  lemmas + bigrams_lemma + trigrams_lemma)
        results = sorted([(score, doc_id) for doc_id, score in zip(doc_ids, scores)], reverse=True)
        top_results = [set_keys_on_docs(docs, keys).get_short_info() for score, doc_id in results[:5] if doc_id in doc_ids]
        logger.info(f"Search results = {[(score, doc_id) for score, doc_id in results[:5]]}")
        sql_session.commit()
        sql_session.close()
        return jsonify(top_results)
    else:
        return jsonify({'error': 'No search text provided'}), 400


@app.route('/list_all', methods=['GET'])
@login_required
def list_all():
    keys = keyParser(session)
    email, name, loggedin = check_login(session)
    sql_session = SQLSession()
    docs = getDocsForUser(sql_session, email)
    docs = set_keys_on_docs(docs, keys)
    return jsonify([doc.get_short_info() for doc in docs])


@app.route('/get_document_detail', methods=['GET'])
@login_required
def get_document_detail():
    keys = keyParser(session)
    doc_id = request.args.get('doc_id')
    sql_session = SQLSession()
    document = sql_session.query(Document).filter_by(id=doc_id).one_or_none()
    document = DocIndex.convert_document_to_docindex(document)
    logger.info(f"/get_document_detail for doc_id = {doc_id}, doc present = {document is not None}")
    details = set_keys_on_docs(document, keys).get_all_details()
    sql_session.close()
    if document is not None:
        return jsonify(details)
    else:
        return jsonify({'error': 'Document not found'}), 404
    
    


@app.route('/index_document', methods=['POST'])
@login_required
def index_document():
    keys = keyParser(session)
    email, name, loggedin = check_login(session)
    
    pdf_url = request.json.get('pdf_url')
    if "arxiv.org" not in pdf_url:
        return jsonify({'error': 'Only arxiv urls are supported at this moment.'}), 400
    if pdf_url:
        try:
            sql_session=SQLSession()
            doc_index = immediate_create_and_save_index(pdf_url, keys, sql_session)
            addUserToDoc(email, doc_index.doc_id, sql_session)
            return jsonify({'status': 'Indexing started', 'doc_id': doc_index.doc_id, "properly_indexed": doc_index.doc_id in indexed_docs})
        except Exception as e:
            traceback.print_exc()
            return jsonify({'error': str(e)}), 400
    else:
        return jsonify({'error': 'No pdf_url provided'}), 400

@app.route('/set_keys', methods=['POST'])
@login_required
def set_keys():
    email, name, _ = check_login(session)
    keys = request.json  # Assuming keys are sent as JSON in the request body
    for key, value in keys.items():
        session[key] = value
    return jsonify({'result': 'success'})

@app.route('/clear_session', methods=['GET'])
@login_required
def clear_session():
    # clear the session
    session.clear()
    return jsonify({'result': 'session cleared'})


def delayed_execution(func, delay, *args):
    time.sleep(delay)
    return func(*args)

    
def immediate_create_and_save_index(pdf_url, keys, sql_session=None):
    close = False
    if sql_session is None:
        sql_session = SQLSession()
        close = True
    pdf_url = pdf_url.strip()
    matching_docs = sql_session.query(Document).filter_by(doc_source=pdf_url).all()
    matching_docs = DocIndex.convert_document_to_docindex(matching_docs)
    
    if len(matching_docs) == 0:
        doc_index = create_immediate_document_index(pdf_url, keys, folder)
        doc_index = set_keys_on_docs(doc_index, keys)
        save_index(doc_index, folder)
        sql_session.add(doc_index.document)
        sql_session.commit()
        if close:
            sql_session.close()
    else:
        logger.info(f"{pdf_url} is already indexed")
        doc_index = matching_docs[0]
        matching_docs = DocIndex.convert_document_to_docindex(matching_docs)
        doc_index = set_keys_on_docs(doc_index, keys)
    return doc_index
    
def save_index(doc_index: DocIndex, folder):
    assert isinstance(doc_index, DocIndex)
    add_to_bm25_corpus(doc_index)
    doc_index.save_local(folder)

    
@app.route('/streaming_get_answer', methods=['POST'])
@login_required
def streaming_get_answer():
    sql_session = SQLSession()
    keys = keyParser(session)
    additional_docs_to_read = request.json.get("additional_docs_to_read", [])
    a = use_multiple_docs = request.json.get("use_multiple_docs", False) and isinstance(additional_docs_to_read, (tuple, list)) and len(additional_docs_to_read) > 0
    b = use_references_and_citations = request.json.get("use_references_and_citations", False)
    c = provide_detailed_answers = request.json.get("provide_detailed_answers", False)
    d = perform_web_search = request.json.get("perform_web_search", False)
    if not (sum([a, b, c, d]) == 0 or sum([a, b, c, d]) == 1):
        return Response("Invalid answering strategy passed.", status=400,  content_type='text/plain')
    if use_multiple_docs:
        matching_docs = sql_session.query(Document).filter(Document.id.in_(additional_docs_to_read)).all()
        matching_docs = DocIndex.convert_document_to_docindex(matching_docs)
        additional_docs_to_read = set_keys_on_docs(matching_docs, keys)
        
    meta_fn = defaultdict(lambda: False, dict(additional_docs_to_read=additional_docs_to_read, use_multiple_docs=use_multiple_docs, use_references_and_citations=use_references_and_citations, provide_detailed_answers=provide_detailed_answers, perform_web_search=perform_web_search))
    
    doc_id = request.json.get('doc_id')
    query = request.json.get('query')
    matching_doc = sql_session.query(Document).filter_by(id=doc_id).one_or_none()
    matching_doc = DocIndex.convert_document_to_docindex(matching_doc)
    try:
        if matching_doc is not None:
            answer = set_keys_on_docs(matching_doc, keys).streaming_get_short_answer(query, meta_fn)
            return Response(stream_with_context(answer), content_type='text/plain')
        else:
            return Response("Error Document not found", status=404,  content_type='text/plain')
    except Exception as e:
        traceback.print_exc()
        logger.error(f"Error in getting review {e}")
        if sql_session.is_active:
            sql_session.rollback()
            sql_session.close()
        return "Error in getting review", 500
    finally:
        if sql_session.is_active:
            sql_session.rollback()
            sql_session.close()
    
@app.route('/streaming_summary', methods=['GET'])
@login_required
def streaming_summary():
    keys = keyParser(session)
    doc_id = request.args.get('doc_id')
    sql_session = SQLSession()
    document = sql_session.query(Document).filter_by(id=doc_id).one_or_none()
    document = DocIndex.convert_document_to_docindex(document)
    try:
        if doc_id in indexed_docs:
            answer = set_keys_on_docs(document, keys).streaming_build_summary()
            p = multiprocessing.Process(target=delayed_execution, args=(save_index, 180, document, folder))
            p.start()
            return Response(stream_with_context(answer), content_type='text/plain')
        else:
            return Response("Error Document not found", content_type='text/plain')
    except Exception as e:
        traceback.print_exc()
        logger.error(f"Error in getting review {e}")
        if sql_session.is_active:
            sql_session.rollback()
            sql_session.close()
        return "Error in getting review", 500
    finally:
        if sql_session.is_active:
            sql_session.rollback()
            sql_session.close()
    
    

@app.route('/streaming_get_followup_answer', methods=['POST'])
@login_required
def streaming_get_followup_answer():
    keys = keyParser(session)
    additional_docs_to_read = request.json.get("additional_docs_to_read", [])
    a = use_multiple_docs = request.json.get("use_multiple_docs", False) and isinstance(additional_docs_to_read, (tuple, list)) and len(additional_docs_to_read) > 0
    b = use_references_and_citations = request.json.get("use_references_and_citations", False)
    c = provide_detailed_answers = request.json.get("provide_detailed_answers", False)
    d = perform_web_search = request.json.get("perform_web_search", False)
    sql_session = SQLSession()
    if not (sum([a, b, c, d]) == 0 or sum([a, b, c, d]) == 1):
        return Response("Invalid answering strategy passed.", status=400,  content_type='text/plain')
    
    if use_multiple_docs:
        matching_docs = sql_session.query(Document).filter(Document.id.in_(additional_docs_to_read)).all()
        matching_docs = DocIndex.convert_document_to_docindex(matching_docs)
        additional_docs_to_read = set_keys_on_docs(matching_docs, keys)
    meta_fn = defaultdict(lambda: False, dict(additional_docs_to_read=additional_docs_to_read, use_multiple_docs=use_multiple_docs, use_references_and_citations=use_references_and_citations, provide_detailed_answers=provide_detailed_answers, perform_web_search=perform_web_search))
    
    doc_id = request.json.get('doc_id')
    query = request.json.get('query')
    previous_answer = request.json.get('previous_answer')
    matching_doc = sql_session.query(Document).filter_by(id=doc_id).one_or_none()
    matching_doc = DocIndex.convert_document_to_docindex(matching_doc)
    try:
        if doc_id in indexed_docs:
            answer = set_keys_on_docs(matching_doc, keys).streaming_ask_follow_up(query, previous_answer, meta_fn)
            return Response(stream_with_context(answer), content_type='text/plain')
        else:
            return Response("Error Document not found", content_type='text/plain')
    except Exception as e:
        traceback.print_exc()
        logger.error(f"Error in getting review {e}")
        if sql_session.is_active:
            sql_session.rollback()
            sql_session.close()
        return "Error in getting review", 500
    finally:
        if sql_session.is_active:
            sql_session.rollback()
            sql_session.close()
    
@app.route('/streaming_get_more_details', methods=['POST'])
@login_required
def streaming_get_more_details():
    keys = keyParser(session)
    sql_session = SQLSession()
    print(request, request.get_json())
    doc_id = request.json.get('doc_id')
    query = request.json.get('query')
    previous_answer = request.json.get('previous_answer')
    counter = request.json.get('more_details_count')
    matching_doc = sql_session.query(Document).filter_by(id=doc_id).one_or_none()
    matching_doc = DocIndex.convert_document_to_docindex(matching_doc)
    try:
        if matching_doc is not None:
            answer = set_keys_on_docs(matching_doc, keys).streaming_get_more_details(query, previous_answer, counter)
            return Response(stream_with_context(answer), content_type='text/plain')
        else:
            return Response("Error Document not found", content_type='text/plain')
    except Exception as e:
        traceback.print_exc()
        logger.error(f"Error in getting review {e}")
        if sql_session.is_active:
            sql_session.rollback()
            sql_session.close()
        return "Error in getting review", 500
    finally:
        if sql_session.is_active:
            sql_session.rollback()
            sql_session.close()
    
from multiprocessing import Lock

lock = Lock()

@app.route('/delete_document', methods=['DELETE'])
@login_required
def delete_document():
    email, name, loggedin = check_login(session)
    doc_id = request.args.get('doc_id')
    sql_session = SQLSession()
    matching_doc = sql_session.query(Document).filter_by(id=doc_id).one_or_none()
    matching_doc = DocIndex.convert_document_to_docindex(matching_doc)
    if not doc_id or matching_doc is None:
        return jsonify({'error': 'Document not found'}), 404
    removeUserFromDoc(email, doc_id)
    sql_session.close()

    return jsonify({'status': 'Document deleted successfully'}), 200

@app.route('/get_paper_details', methods=['GET'])
@login_required
def get_paper_details():
    keys = keyParser(session)
    sql_session = SQLSession()
    doc_id = request.args.get('doc_id')
    matching_doc = sql_session.query(Document).filter_by(id=doc_id).one_or_none()
    matching_doc = DocIndex.convert_document_to_docindex(matching_doc)
    if matching_doc is not None:
        paper_details = set_keys_on_docs(matching_doc, keys).paper_details
        sql_session.close()
        return jsonify(paper_details)
    else:
        return jsonify({'error': 'Document not found'}), 404

@app.route('/refetch_paper_details', methods=['GET'])
@login_required
def refetch_paper_details():
    keys = keyParser(session)
    doc_id = request.args.get('doc_id')
    sql_session = SQLSession()
    matching_doc = sql_session.query(Document).filter_by(id=doc_id).one_or_none()
    matching_doc = DocIndex.convert_document_to_docindex(matching_doc)
    if matching_doc is not None:
        paper_details = set_keys_on_docs(matching_doc, keys).refetch_paper_details()
        sql_session.close()
        return jsonify(paper_details)
    else:
        return jsonify({'error': 'Document not found'}), 404

@app.route('/get_extended_abstract', methods=['GET'])
@login_required
def get_extended_abstract():
    keys = keyParser(session)
    doc_id = request.args.get('doc_id')
    sql_session = SQLSession()
    matching_doc = sql_session.query(Document).filter_by(id=doc_id).one_or_none()
    matching_doc = DocIndex.convert_document_to_docindex(matching_doc)
    paper_id = request.args.get('paper_id')
    if matching_doc is not None:
        extended_abstract = set_keys_on_docs(matching_doc, keys).get_extended_abstract_for_ref_or_cite(paper_id)
        return Response(stream_with_context(extended_abstract), content_type='text/plain')
    else:
        return Response("Error Document not found", content_type='text/plain')
    
@app.route('/get_fixed_details', methods=['GET'])
@login_required
def get_fixed_details():
    keys = keyParser(session)
    sql_session = SQLSession()
    doc_id = request.args.get('doc_id')
    detail_key = request.args.get('detail_key')
    matching_doc = sql_session.query(Document).filter_by(id=doc_id).one_or_none()
    matching_doc = DocIndex.convert_document_to_docindex(matching_doc)
    if matching_doc is not None:
        fixed_details = set_keys_on_docs(matching_doc, keys).get_fixed_details(detail_key)
        return Response(stream_with_context(fixed_details), content_type='text/plain')
    else:
        return Response("Error: Document not found", content_type='text/plain')


    
from flask import send_from_directory

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static'),
                               'favicon.ico', mimetype='image/vnd.microsoft.icon')

@app.route('/interface/<path:path>')
def send_static(path):
    return send_from_directory('interface', path, max_age=0)

@app.route('/interface')
@login_required
def interface():
    return send_from_directory('interface', 'interface.html', max_age=0)

from flask import Response, stream_with_context

@app.route('/proxy', methods=['GET'])
@login_required
def proxy():
    file_url = request.args.get('file')
    logger.info(f"Proxying file {file_url}, exists on disk = {os.path.exists(file_url)}")
    return Response(stream_with_context(cached_get_file(file_url)), mimetype='application/pdf')

@app.route('/')
def index():
    return redirect('/interface')

@app.route('/upload_pdf', methods=['POST'])
@login_required
def upload_pdf():
    keys = keyParser(session)
    email, name, loggedin = check_login(session)
    pdf_file = request.files.get('pdf_file')
    if pdf_file:
        try:
            # save file to disk at pdfs_dir.
            pdf_file.save(os.path.join(pdfs_dir, pdf_file.filename))
            
            # lets get the full path of the file
            full_pdf_path = os.path.join(pdfs_dir, pdf_file.filename)
            
            doc_index = immediate_create_and_save_index(full_pdf_path, keys)
            addUserToDoc(email, doc_index.doc_id)
            return jsonify({'status': 'Indexing started', 'doc_id': doc_index.doc_id, "properly_indexed": doc_index.doc_id in indexed_docs})
        except Exception as e:
            traceback.print_exc()
            return jsonify({'error': str(e)}), 400
    else:
        return jsonify({'error': 'No pdf_file provided'}), 400


def cached_get_file(file_url):
    
    chunk_size = 1024  # Define your chunk size
    logger.info(f"cached_get_file for {file_url}")
    file_data = cache.get(file_url)

    # If the file is not in the cache, read it from disk and save it to the cache
    if file_data is not None:
        logger.info(f"cached_get_file for {file_url} found in cache")
        for chunk in file_data:
            yield chunk
        # how do I chunk with chunk size?
        
        
    elif os.path.exists(file_url):
        file_data = []
        with open(file_url, 'rb') as f:
            while True:
                chunk = f.read(chunk_size)
                if chunk:
                    file_data.append(chunk)
                    yield chunk
                if not chunk:
                    break
        cache.set(file_url, file_data)
    else:   
        file_data = []
        try:
            req = requests.get(file_url, stream=True)
        except requests.exceptions.RequestException as e:
            app.logger.error(f"Failed to download file: {e}")
            req = requests.get(file_url, stream=True, verify=False)
        # TODO: save the downloaded file to disk.
        
        for chunk in req.iter_content(chunk_size=chunk_size):
            file_data.append(chunk)
            yield chunk
        cache.set(file_url, file_data)


def open_browser(url):
    import webbrowser
    import subprocess
    if sys.platform.startswith('linux'):
        subprocess.call(['xdg-open', url])
    elif sys.platform.startswith('darwin'):
        subprocess.call(['open', url])
    else:
        webbrowser.open(url)
    
load_documents(folder)

if __name__ == '__main__':
    
    port = 443
   # app.run(host="0.0.0.0", port=port,threaded=True, ssl_context=('cert-ext.pem', 'key-ext.pem'))
    app.run(host="0.0.0.0", port=5000,threaded=True)

