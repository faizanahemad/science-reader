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
from DocIndex import DocFAISS, DocIndex, create_immediate_document_index, ImmediateDocIndex
import os
import time
import multiprocessing
import glob
import json
from rank_bm25 import BM25Okapi
from typing import List, Dict
from flask import Flask, Response, stream_with_context
import sys
sys.setrecursionlimit(sys.getrecursionlimit()*16)
import logging
import requests
from flask_caching import Cache
import argparse
from datetime import timedelta
import sqlite3
from sqlite3 import Error
from common import checkNoneOrEmpty
import spacy
from spacy.lang.en import English
from spacy.pipeline import Lemmatizer

os.environ["BING_SEARCH_URL"] = "https://api.bing.microsoft.com/v7.0/search"

def create_connection(db_file):
    """ create a database connection to a SQLite database """
    conn = None;
    try:
        conn = sqlite3.connect(db_file)
    except Error as e:
        print(e)
    return conn

def create_table(conn, create_table_sql):
    """ create a table from the create_table_sql statement """
    try:
        c = conn.cursor()
        c.execute(create_table_sql)
    except Error as e:
        print(e)

def create_tables():
    database = "{}/users.db".format(users_dir)

    sql_create_user_to_doc_id_table = """CREATE TABLE IF NOT EXISTS UserToDocId (
                                    user_email text,
                                    doc_id text,
                                    created_at text,
                                    updated_at text,
                                    doc_source_url text
                                ); """

    sql_create_user_to_votes_table = """CREATE TABLE IF NOT EXISTS UserToVotes (
                                    user_email text,
                                    question_id text,
                                    doc_id text,
                                    upvoted integer,
                                    downvoted integer,
                                    feedback_type text,
                                    feedback_items text,
                                    comments text,
                                    question_text text,
                                    created_at text,
                                    updated_at text
                                );"""


    # create a database connection
    conn = create_connection(database)
    

    # create tables
    if conn is not None:
        # create UserToDocId table
        create_table(conn, sql_create_user_to_doc_id_table)
        # create UserToVotes table
        create_table(conn, sql_create_user_to_votes_table)
    else:
        print("Error! cannot create the database connection.")
        
    cur = conn.cursor()
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_UserToVotes_email_question ON UserToVotes (user_email, question_id)")
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_UserToDocId_email_doc ON UserToDocId (user_email, doc_id)")
    conn.commit()
        
        
from datetime import datetime

def addUserToDoc(user_email, doc_id, doc_source_url):
    conn = create_connection("{}/users.db".format(users_dir))
    cur = conn.cursor()
    cur.execute(
        """
        INSERT OR IGNORE INTO UserToDocId
        (user_email, doc_id, created_at, updated_at, doc_source_url)
        VALUES(?,?,?,?,?)
        """, 
        (user_email, doc_id, datetime.now(), datetime.now(), doc_source_url)
    )
    conn.commit()
    conn.close()


def getDocsForUser(user_email):
    conn = create_connection("{}/users.db".format(users_dir))
    cur = conn.cursor()
    cur.execute("SELECT * FROM UserToDocId WHERE user_email=?", (user_email,))
    rows = cur.fetchall()
    conn.close()
    return rows

def addUpvoteOrDownvote(user_email, question_id, doc_id, upvote, downvote):
    assert not checkNoneOrEmpty(question_id)
    assert not checkNoneOrEmpty(user_email)
    assert not checkNoneOrEmpty(doc_id)
    conn = create_connection("{}/users.db".format(users_dir))
    cur = conn.cursor()
    cur.execute(
        """
        INSERT OR REPLACE INTO UserToVotes
        (user_email, question_id, doc_id, upvoted, downvoted, feedback_type, feedback_items, comments, question_text, created_at, updated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?)
        """, 
        (user_email, question_id, doc_id, upvote, downvote, None, None, None, None, datetime.now(), datetime.now())
    )
    conn.commit()
    conn.close()

def addGranularFeedback(user_email, question_id, feedback_type, feedback_items, comments, question_text):
    assert not checkNoneOrEmpty(question_id)
    assert not checkNoneOrEmpty(user_email)
    conn = create_connection("{}/users.db".format(users_dir))
    cur = conn.cursor()

    # Ensure that the user has already voted before updating the feedback
    cur.execute("SELECT 1 FROM UserToVotes WHERE user_email = ? AND question_id = ?", (user_email, question_id))
    if not cur.fetchone():
        raise ValueError("A vote must exist for the user and question before feedback can be provided")

    cur.execute(
        """
        UPDATE UserToVotes 
        SET feedback_type = ?, feedback_items = ?, comments = ?, question_text = ?, updated_at = ?
        WHERE user_email = ? AND question_id = ?
        """,
        (feedback_type, ','.join(feedback_items), comments, question_text, datetime.now(), user_email, question_id)
    )
    conn.commit()
    conn.close()



def getUpvotesDownvotesByUser(user_email):
    conn = create_connection("{}/users.db".format(users_dir))
    cur = conn.cursor()
    cur.execute("SELECT SUM(upvoted), SUM(downvoted) FROM UserToVotes WHERE user_email=? GROUP BY user_email ", (user_email,))
    rows = cur.fetchall()
    conn.close()
    return rows

def getUpvotesDownvotesByQuestionId(question_id):
    conn = create_connection("{}/users.db".format(users_dir))
    cur = conn.cursor()
    cur.execute("SELECT SUM(upvoted), SUM(downvoted) FROM UserToVotes WHERE question_id=? GROUP BY question_id", (question_id,))
    rows = cur.fetchall()
    conn.close()
    return rows

def getUpvotesDownvotesByQuestionIdAndUser(question_id, user_email):
    conn = create_connection("{}/users.db".format(users_dir))
    cur = conn.cursor()
    cur.execute("SELECT SUM(upvoted), SUM(downvoted) FROM UserToVotes WHERE question_id=? AND user_email=? GROUP BY question_id,user_email", (question_id, user_email,))
    rows = cur.fetchall()
    conn.close()
    return rows


def removeUserFromDoc(user_email, doc_id):
    conn = create_connection("{}/users.db".format(users_dir))
    cur = conn.cursor()
    cur.execute("DELETE FROM UserToDocId WHERE user_email=? AND doc_id=?", (user_email, doc_id,))
    conn.commit()
    conn.close()


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
    }
    for k, _ in keyStore.items():
        key = session.get(k)
        keyStore[k] = key
        if key is not None and ((isinstance(key, str) and len(key.strip())>0) or (isinstance(key, list) and len(key)>0)):
            keyStore[k] = key
        else:
            keyStore[k] = None
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
users_dir = os.path.join(os.getcwd(), folder, "users")
pdfs_dir = os.path.join(os.getcwd(), folder, "pdfs")
os.makedirs(cache_dir, exist_ok=True)
os.makedirs(users_dir, exist_ok=True)
os.makedirs(pdfs_dir, exist_ok=True)
os.makedirs(os.path.join(folder, "locks"), exist_ok=True)
nlp = English()  # just the language with no model
_ = nlp.add_pipe("lemmatizer")
nlp.initialize()


cache = Cache(app, config={'CACHE_TYPE': 'filesystem', 'CACHE_DIR': cache_dir, 'CACHE_DEFAULT_TIMEOUT': 7 * 24 * 60 * 60})

def check_login(session):
    email = dict(session).get('email', None)
    name = dict(session).get('name', None)
    logger.info(f"Check Login for email {session.get('email')} and name {session.get('name')}")
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
    logger.info(f"GEt upvote-downvote request with {data}")
    if "question_text" in data:
        question_id = str(mmh3.hash(indexed_docs[data['doc_id']].doc_source + data["question_text"], signed=False))
        logger.info(f"'/addUpvoteOrDownvote' -> generated question_id = {question_id}, Received q_id = {data['question_id']}, both same = {data['question_id'] == question_id}")
        if checkNoneOrEmpty(data['question_id']):
            data['question_id'] = question_id
    if checkNoneOrEmpty(data['question_id']) or checkNoneOrEmpty(data['doc_id']):
        return "Question Id and Doc Id are needed for `/addUpvoteOrDownvote`", 400
    addUpvoteOrDownvote(email, data['question_id'], data['doc_id'], data['upvote'], data['downvote'])
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
    
    review = set_keys_on_docs(indexed_docs[doc_id], keys).get_review(tone, review_topic, additional_instructions, score_this_review, use_previous_reviews, is_meta_review)
    return Response(stream_with_context(review), content_type='text/plain')

@app.route('/get_reviews/<doc_id>', methods=['GET'])
@login_required
def get_all_reviews(doc_id):
    keys = keyParser(session)
    email, name, _ = check_login(session)
    reviews = set_keys_on_docs(indexed_docs[doc_id], keys).get_all_reviews()
    # lets send json response
    return jsonify(reviews)
    
    
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
        item = item.copy()
        super().__setitem__(key, item)
        return item
    
    def __setitem__(self, __key: str, __value: DocIndex) -> None:
        __value = __value.copy()
        return super().__setitem__(__key, __value)
indexed_docs: IndexDict[str, DocIndex] = {}

    
def set_keys_on_docs(docs, keys):
    logger.info(f"Attaching keys to doc")
    if isinstance(docs, dict):
        docs = {k: v.copy() for k, v in docs.items()}
        for k, v in docs.items():
            v.set_api_keys(keys)
            for i, j in vars(v).items():
                if isinstance(j,  (FAISS, VectorStore)):
                    j.embedding_function.__self__.openai_api_key = keys["openAIKey"]
                    setattr(j.embedding_function.__self__, "openai_api_key", keys["openAIKey"])
    elif isinstance(docs, (list, tuple, set)):
        docs = [d.copy() for d in docs]
        for d in docs:
            d.set_api_keys(keys)
            for i, j in vars(d).items():
                if isinstance(j, (FAISS, VectorStore)):
                    j.embedding_function.__self__.openai_api_key = keys["openAIKey"]
                    setattr(j.embedding_function.__self__, "openai_api_key", keys["openAIKey"])
    else:
        assert isinstance(docs, (DocIndex, ImmediateDocIndex))
        docs = docs.copy()
        for i, j in vars(docs).items():
            if isinstance(j,  (DocFAISS, FAISS, VectorStore)):
                
                j.embedding_function.__self__.openai_api_key = keys["openAIKey"]
                setattr(j.embedding_function.__self__, "openai_api_key", keys["openAIKey"])
                
        docs.set_api_keys(keys)
    return docs
    

# Initialize an empty list of documents for BM25
bm25_corpus: List[List[str]] = []
doc_id_to_bm25_index: Dict[str, int] = {}
bm25 = [None]
    
def get_bm25_grams(text):
    unigrams = text.split()
    bigrams = generate_ngrams(unigrams, 2)
    trigrams = generate_ngrams(unigrams, 3)
    doc = nlp(text)
    lemmas = [token.lemma_ for token in doc]
    bigrams_lemma = generate_ngrams(lemmas, 2)
    trigrams_lemma = generate_ngrams(lemmas, 3)
    return unigrams + bigrams + trigrams + lemmas + bigrams_lemma + trigrams_lemma

def add_to_bm25_corpus(doc_index: DocIndex):
    global bm25_corpus, doc_id_to_bm25_index
    try:
        doc_info = doc_index.get_short_info()
        text = doc_info['title'].lower() + " " + doc_info['short_summary'].lower() + " " + doc_info['summary'].lower()
    except Exception as e:
        logger.info(f"Error in getting text for doc_id = {doc_index.doc_id}, error = {e}")
        text = doc_index.indices["chunks"][0].lower()
    bm25_corpus.append(get_bm25_grams(text))
    doc_id_to_bm25_index[doc_index.doc_id] = len(bm25_corpus) - 1
    bm25[0] = BM25Okapi(bm25_corpus)

def load_documents(folder):
    global indexed_docs, bm25_corpus, doc_id_to_bm25_index
    for filepath in glob.glob(os.path.join(folder, '*.index')):
        filename = os.path.basename(filepath)
        doc_index = DocIndex.load_local(folder, filename).copy()
        
        indexed_docs[doc_index.doc_id] = doc_index
        add_to_bm25_corpus(doc_index)



@app.route('/search_document', methods=['GET'])
@login_required
def search_document():
    keys = keyParser(session)
    email, name, loggedin = check_login(session)
    docs = getDocsForUser(email)
    docs = getDocsForUser(email)
    doc_ids = [d[1] for d in docs]
    
    search_text = request.args.get('text')
    if search_text:
        search_text = search_text.strip().lower()
        bm = bm25[0]
        search_tokens = get_bm25_grams(search_text)
        scores = bm.get_scores(search_tokens)
        results = sorted([(score, doc_id) for doc_id, score in zip(indexed_docs.keys(), scores)], reverse=True)
        docs = [set_keys_on_docs(indexed_docs[doc_id], keys) for score, doc_id in results[:4] if doc_id in doc_ids]
        scores = [score for score, doc_id in results[:4] if doc_id in doc_ids]
        top_results = [doc.get_short_info() for score, doc in zip(scores, docs)]
        logger.info(f"Search results = {[(score, doc.doc_source) for score, doc in zip(scores, docs)]}")
        return jsonify(top_results)
    else:
        return jsonify({'error': 'No search text provided'}), 400


@app.route('/list_all', methods=['GET'])
@login_required
def list_all():
    keys = keyParser(session)
    email, name, loggedin = check_login(session)
    docs = getDocsForUser(email)
    doc_ids = set([d[1] for d in docs])
    return jsonify([set_keys_on_docs(indexed_docs[docId], keys).get_short_info() for docId in doc_ids if docId in indexed_docs])


@app.route('/get_document_detail', methods=['GET'])
@login_required
def get_document_detail():
    keys = keyParser(session)
    doc_id = request.args.get('doc_id')
    logger.info(f"/get_document_detail for doc_id = {doc_id}, doc present = {doc_id in indexed_docs}")
    if doc_id in indexed_docs:
        
        return jsonify(set_keys_on_docs(indexed_docs[doc_id], keys).get_all_details())
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
            doc_index = immediate_create_and_save_index(pdf_url, keys)
            addUserToDoc(email, doc_index.doc_id, doc_index.doc_source)
            return jsonify({'status': 'Indexing started', 'doc_id': doc_index.doc_id, "properly_indexed": doc_index.doc_id in indexed_docs})
        except Exception as e:
            traceback.print_exc()
            return jsonify({'error': str(e)}), 400
    else:
        return jsonify({'error': 'No pdf_url provided'}), 400

@app.route('/set_keys', methods=['POST'])
@login_required
def set_keys():
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

    
def immediate_create_and_save_index(pdf_url, keys):
    pdf_url = pdf_url.strip()
    matching_docs = [v for k, v in indexed_docs.items() if v.doc_source==pdf_url]
    if len(matching_docs) == 0:
        doc_index = create_immediate_document_index(pdf_url, folder, keys)
        doc_index = set_keys_on_docs(doc_index, keys)
        save_index(doc_index, folder)
    else:
        logger.info(f"{pdf_url} is already indexed")
        doc_index = matching_docs[0]
    return doc_index
    
def save_index(doc_index: DocIndex, folder):
    indexed_docs[doc_index.doc_id] = doc_index
    add_to_bm25_corpus(doc_index)
    doc_index.save_local(folder)

    
@app.route('/streaming_get_answer', methods=['POST'])
@login_required
def streaming_get_answer():
    keys = keyParser(session)
    additional_docs_to_read = request.json.get("additional_docs_to_read", [])
    a = use_multiple_docs = request.json.get("use_multiple_docs", False) and isinstance(additional_docs_to_read, (tuple, list)) and len(additional_docs_to_read) > 0
    b = use_references_and_citations = request.json.get("use_references_and_citations", False)
    c = provide_detailed_answers = request.json.get("provide_detailed_answers", False)
    d = perform_web_search = request.json.get("perform_web_search", False)
    if not (sum([a, b, c, d]) == 0 or sum([a, b, c, d]) == 1):
        return Response("Invalid answering strategy passed.", status=400,  content_type='text/plain')
    if use_multiple_docs:
        additional_docs_to_read = [set_keys_on_docs(indexed_docs[doc_id], keys) for doc_id in additional_docs_to_read]
    meta_fn = defaultdict(lambda: False, dict(additional_docs_to_read=additional_docs_to_read, use_multiple_docs=use_multiple_docs, use_references_and_citations=use_references_and_citations, provide_detailed_answers=provide_detailed_answers, perform_web_search=perform_web_search))
    
    doc_id = request.json.get('doc_id')
    query = request.json.get('query')
    if doc_id in indexed_docs:
        answer = set_keys_on_docs(indexed_docs[doc_id], keys).streaming_get_short_answer(query, meta_fn)
        return Response(stream_with_context(answer), content_type='text/plain')
    else:
        return Response("Error Document not found", status=404,  content_type='text/plain')
    
@app.route('/streaming_summary', methods=['GET'])
@login_required
def streaming_summary():
    keys = keyParser(session)
    doc_id = request.args.get('doc_id')
    if doc_id in indexed_docs:
        doc = set_keys_on_docs(indexed_docs[doc_id], keys)
        answer = doc.streaming_build_summary()
        p = multiprocessing.Process(target=delayed_execution, args=(save_index, 180, doc, folder))
        p.start()
        return Response(stream_with_context(answer), content_type='text/plain')
    else:
        return Response("Error Document not found", content_type='text/plain')
    
    

@app.route('/streaming_get_followup_answer', methods=['POST'])
@login_required
def streaming_get_followup_answer():
    keys = keyParser(session)
    additional_docs_to_read = request.json.get("additional_docs_to_read", [])
    a = use_multiple_docs = request.json.get("use_multiple_docs", False) and isinstance(additional_docs_to_read, (tuple, list)) and len(additional_docs_to_read) > 0
    b = use_references_and_citations = request.json.get("use_references_and_citations", False)
    c = provide_detailed_answers = request.json.get("provide_detailed_answers", False)
    d = perform_web_search = request.json.get("perform_web_search", False)
    if not (sum([a, b, c, d]) == 0 or sum([a, b, c, d]) == 1):
        return Response("Invalid answering strategy passed.", status=400,  content_type='text/plain')
    if use_multiple_docs:
        additional_docs_to_read = [set_keys_on_docs(indexed_docs[doc_id], keys) for doc_id in additional_docs_to_read]
    meta_fn = defaultdict(lambda: False, dict(additional_docs_to_read=additional_docs_to_read, use_multiple_docs=use_multiple_docs, use_references_and_citations=use_references_and_citations, provide_detailed_answers=provide_detailed_answers, perform_web_search=perform_web_search))
    
    doc_id = request.json.get('doc_id')
    query = request.json.get('query')
    previous_answer = request.json.get('previous_answer')
    if doc_id in indexed_docs:
        answer = set_keys_on_docs(indexed_docs[doc_id], keys).streaming_ask_follow_up(query, previous_answer, meta_fn)
        return Response(stream_with_context(answer), content_type='text/plain')
    else:
        return Response("Error Document not found", content_type='text/plain')
    
@app.route('/streaming_get_more_details', methods=['POST'])
@login_required
def streaming_get_more_details():
    keys = keyParser(session)
    print(request, request.get_json())
    doc_id = request.json.get('doc_id')
    query = request.json.get('query')
    previous_answer = request.json.get('previous_answer')
    counter = request.json.get('more_details_count')
    if doc_id in indexed_docs:
        answer = set_keys_on_docs(indexed_docs[doc_id], keys).streaming_get_more_details(query, previous_answer, counter)
        return Response(stream_with_context(answer), content_type='text/plain')
    else:
        return Response("Error Document not found", content_type='text/plain')
    
from multiprocessing import Lock

lock = Lock()

@app.route('/delete_document', methods=['DELETE'])
@login_required
def delete_document():
    email, name, loggedin = check_login(session)
    doc_id = request.args.get('doc_id')
    if not doc_id or doc_id not in indexed_docs:
        return jsonify({'error': 'Document not found'}), 404
    removeUserFromDoc(email, doc_id)

    return jsonify({'status': 'Document deleted successfully'}), 200

@app.route('/get_paper_details', methods=['GET'])
@login_required
def get_paper_details():
    keys = keyParser(session)
    doc_id = request.args.get('doc_id')
    if doc_id in indexed_docs:
        paper_details = set_keys_on_docs(indexed_docs[doc_id], keys).paper_details
        return jsonify(paper_details)
    else:
        return jsonify({'error': 'Document not found'}), 404

@app.route('/refetch_paper_details', methods=['GET'])
@login_required
def refetch_paper_details():
    keys = keyParser(session)
    doc_id = request.args.get('doc_id')
    if doc_id in indexed_docs:
        paper_details = set_keys_on_docs(indexed_docs[doc_id], keys).refetch_paper_details()
        return jsonify(paper_details)
    else:
        return jsonify({'error': 'Document not found'}), 404

@app.route('/get_extended_abstract', methods=['GET'])
@login_required
def get_extended_abstract():
    keys = keyParser(session)
    doc_id = request.args.get('doc_id')
    paper_id = request.args.get('paper_id')
    if doc_id in indexed_docs:
        extended_abstract = set_keys_on_docs(indexed_docs[doc_id], keys).get_extended_abstract_for_ref_or_cite(paper_id)
        return Response(stream_with_context(extended_abstract), content_type='text/plain')
    else:
        return Response("Error Document not found", content_type='text/plain')
    
@app.route('/get_fixed_details', methods=['GET'])
@login_required
def get_fixed_details():
    keys = keyParser(session)
    doc_id = request.args.get('doc_id')
    detail_key = request.args.get('detail_key')
    if doc_id in indexed_docs:
        fixed_details = set_keys_on_docs(indexed_docs[doc_id], keys).get_fixed_details(detail_key)
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
            addUserToDoc(email, doc_index.doc_id, doc_index.doc_source)
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
    
create_tables()
load_documents(folder)

if __name__ == '__main__':
    
    port = 443
   # app.run(host="0.0.0.0", port=port,threaded=True, ssl_context=('cert-ext.pem', 'key-ext.pem'))
    app.run(host="0.0.0.0", port=5000,threaded=True)

