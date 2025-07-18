import tempfile
from functools import wraps
import ast
import traceback
from flask import Flask, render_template, request, jsonify, send_file, session, redirect, url_for, render_template_string
from flask_cors import CORS, cross_origin
from common import COMMON_SALT_STRING, USE_OPENAI_API

import secrets
from typing import Any, Optional
from flask_session import Session
from DocIndex import DocIndex, create_immediate_document_index, ImmediateDocIndex, ImageDocIndex

from Conversation import Conversation, TemporaryConversation

import os
import time
from typing import List, Dict
import sys

from very_common import get_async_future
sys.setrecursionlimit(sys.getrecursionlimit()*16)
import logging
import requests
from flask_caching import Cache
import argparse
from datetime import timedelta
import sqlite3
from sqlite3 import Error
from common import checkNoneOrEmpty, convert_http_to_https, DefaultDictQueue, convert_to_pdf_link_if_needed, \
    verify_openai_key_and_fetch_models

from flask.json.provider import JSONProvider
from common import SetQueue
import secrets
import string
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import tiktoken
alphabet = string.ascii_letters + string.digits
import typing as t
# try:
#     import ujson as json
# except ImportError:
#     import json



import json
from flask import Flask, redirect, url_for


class FlaskJSONProvider(JSONProvider):
    def dumps(self, obj: t.Any, **kwargs: t.Any) -> str:
        """Serialize data as JSON.

        :param obj: The data to serialize.
        :param kwargs: May be passed to the underlying JSON library.
        """
        return json.dumps(obj, **kwargs)
    def loads(self, s: str, **kwargs: t.Any) -> t.Any:
        """Deserialize data as JSON.

        :param s: Text or UTF-8 bytes.
        :param kwargs: May be passed to the underlying JSON library.
        """
        return json.loads(s, **kwargs)
    
class OurFlask(Flask):
    json_provider_class = FlaskJSONProvider

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

    sql_create_user_to_conversation_id_table = """CREATE TABLE IF NOT EXISTS UserToConversationId (
                                    user_email text,
                                    conversation_id text,
                                    created_at text,
                                    updated_at text
                                ); """
                                
    sql_create_user_details_table = """CREATE TABLE IF NOT EXISTS UserDetails (
                                    user_email text PRIMARY KEY,
                                    user_preferences text,
                                    user_memory text,
                                    created_at text,
                                    updated_at text
                                ); """

    # create a database connection
    conn = create_connection(database)
    
    # create tables
    if conn is not None:
        # create UserToVotes table
        create_table(conn, sql_create_user_to_conversation_id_table)
        # create UserDetails table
        create_table(conn, sql_create_user_details_table)
    else:
        print("Error! cannot create the database connection.")
        
    cur = conn.cursor()
    cur.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_UserToConversationId_email_doc ON UserToConversationId (user_email, conversation_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_User_email_doc_conversation ON UserToConversationId (user_email)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_UserDetails_email ON UserDetails (user_email)")
    conn.commit()
        
        
from datetime import datetime

    
def addConversationToUser(user_email, conversation_id):
    conn = create_connection("{}/users.db".format(users_dir))
    cur = conn.cursor()
    cur.execute(
        """
        INSERT OR IGNORE INTO UserToConversationId
        (user_email, conversation_id, created_at, updated_at)
        VALUES(?,?,?,?)
        """, 
        (user_email, conversation_id, datetime.now(), datetime.now())
    )
    conn.commit()
    conn.close()



def getCoversationsForUser(user_email):
    conn = create_connection("{}/users.db".format(users_dir))
    cur = conn.cursor()
    cur.execute("SELECT * FROM UserToConversationId WHERE user_email=?", (user_email,))
    rows = cur.fetchall()
    conn.close()
    return rows

def deleteConversationForUser(user_email, conversation_id):
    conn = create_connection("{}/users.db".format(users_dir))
    cur = conn.cursor()
    cur.execute("DELETE FROM UserToConversationId WHERE user_email=? AND conversation_id=?", (user_email, conversation_id,))
    conn.commit()
    conn.close()

def getAllCoversations():
    conn = create_connection("{}/users.db".format(users_dir))
    cur = conn.cursor()
    cur.execute("SELECT * FROM UserToConversationId")
    rows = cur.fetchall()
    conn.close()
    return rows

def getConversationById(conversation_id):
    conn = create_connection("{}/users.db".format(users_dir))
    cur = conn.cursor()
    cur.execute("SELECT * FROM UserToConversationId WHERE conversation_id=?", (conversation_id,))
    rows = cur.fetchall()
    conn.close()
    return rows

    
def removeUserFromConversation(user_email, conversation_id):
    conn = create_connection("{}/users.db".format(users_dir))
    cur = conn.cursor()
    cur.execute("DELETE FROM UserToConversationId WHERE user_email=? AND conversation_id=?", (user_email, conversation_id,))
    conn.commit()
    conn.close()



def addUserToUserDetailsTable(user_email, user_preferences=None, user_memory=None):
    """
    Add a new user to the UserDetails table or update if it already exists
    
    Args:
        user_email (str): User's email address
        user_preferences (str): JSON string of user preferences
        user_memory (str): JSON string of what we know about the user
    """
    conn = create_connection("{}/users.db".format(users_dir))
    if conn is None:
        logger.error("Failed to connect to database when adding user details")
        return False
    
    cur = conn.cursor()
    try:
        # Check if user exists
        cur.execute("SELECT user_email FROM UserDetails WHERE user_email=?", (user_email,))
        exists = cur.fetchone()
        
        current_time = datetime.now()
        
        if exists:
            # Update existing user
            cur.execute(
                """
                UPDATE UserDetails
                SET user_preferences=?, user_memory=?, updated_at=?
                WHERE user_email=?
                """,
                (user_preferences, user_memory, current_time, user_email)
            )
        else:
            # Insert new user
            cur.execute(
                """
                INSERT INTO UserDetails
                (user_email, user_preferences, user_memory, created_at, updated_at)
                VALUES(?,?,?,?,?)
                """,
                (user_email, user_preferences, user_memory, current_time, current_time)
            )
        
        conn.commit()
        return True
    except Error as e:
        logger.error(f"Database error when adding user details: {e}")
        return False
    finally:
        conn.close()

def getUserFromUserDetailsTable(user_email):
    """
    Retrieve user details from the UserDetails table
    
    Args:
        user_email (str): User's email address
        
    Returns:
        dict: User details or None if not found
    """
    conn = create_connection("{}/users.db".format(users_dir))
    if conn is None:
        logger.error("Failed to connect to database when retrieving user details")
        return None
    
    cur = conn.cursor()
    try:
        cur.execute("SELECT * FROM UserDetails WHERE user_email=?", (user_email,))
        row = cur.fetchone()
        
        if row:
            return {
                "user_email": row[0],
                "user_preferences": row[1],
                "user_memory": row[2],
                "created_at": row[3],
                "updated_at": row[4]
            }
        else:
            return None
    except Error as e:
        logger.error(f"Database error when retrieving user details: {e}")
        return None
    finally:
        conn.close()

def updateUserInfoInUserDetailsTable(user_email, user_preferences=None, user_memory=None):
    """
    Update user information in the UserDetails table
    
    Args:
        user_email (str): User's email address
        user_preferences (str, optional): JSON string of user preferences
        user_memory (str, optional): JSON string of what we know about the user
        
    Returns:
        bool: True if successful, False otherwise
    """
    conn = create_connection("{}/users.db".format(users_dir))
    if conn is None:
        logger.error("Failed to connect to database when updating user details")
        return False
    
    cur = conn.cursor()
    try:
        # Get current values to only update what's provided
        cur.execute("SELECT user_preferences, user_memory FROM UserDetails WHERE user_email=?", (user_email,))
        row = cur.fetchone()
        
        if not row:
            # User doesn't exist, add them instead
            return addUserToUserDetailsTable(user_email, user_preferences, user_memory)
        
        current_preferences, current_memory = row
        
        # Use provided values or keep existing ones
        update_preferences = user_preferences if user_preferences is not None else current_preferences
        update_memory = user_memory if user_memory is not None else current_memory
        
        cur.execute(
            """
            UPDATE UserDetails
            SET user_preferences=?, user_memory=?, updated_at=?
            WHERE user_email=?
            """,
            (update_preferences, update_memory, datetime.now(), user_email)
        )
        
        conn.commit()
        return True
    except Error as e:
        logger.error(f"Database error when updating user details: {e}")
        return False
    finally:
        conn.close()


def keyParser(session):
    keyStore = {
        "openAIKey": os.getenv("openAIKey", ''),
        "jinaAIKey": os.getenv("jinaAIKey", ''),
        "elevenLabsKey": os.getenv("elevenLabsKey", ''),
        "ASSEMBLYAI_API_KEY": os.getenv("ASSEMBLYAI_API_KEY", ''),
        "mathpixId": os.getenv("mathpixId", ''),
        "mathpixKey": os.getenv("mathpixKey", ''),
        "cohereKey": os.getenv("cohereKey", ''),
        "ai21Key": os.getenv("ai21Key", ''),
        "bingKey": os.getenv("bingKey", ''),
        "serpApiKey": os.getenv("serpApiKey", ''),
        "googleSearchApiKey":os.getenv("googleSearchApiKey", ''),
        "googleSearchCxId":os.getenv("googleSearchCxId", ''),
        "openai_models_list": os.getenv("openai_models_list", '[]'),
        "scrapingBrowserUrl": os.getenv("scrapingBrowserUrl", ''),
        "vllmUrl": os.getenv("vllmUrl", ''),
        "vllmLargeModelUrl": os.getenv("vllmLargeModelUrl", ''),
        "vllmSmallModelUrl": os.getenv("vllmSmallModelUrl", ''),
        "tgiUrl": os.getenv("tgiUrl", ''),
        "tgiLargeModelUrl": os.getenv("tgiLargeModelUrl", ''),
        "tgiSmallModelUrl": os.getenv("tgiSmallModelUrl", ''),
        "embeddingsUrl": os.getenv("embeddingsUrl", ''),
        "zenrows": os.getenv("zenrows", ''),
        "scrapingant": os.getenv("scrapingant", ''),
        "brightdataUrl": os.getenv("brightdataUrl", ''),
        "brightdataProxy": os.getenv("brightdataProxy", ''),
        "OPENROUTER_API_KEY": os.getenv("OPENROUTER_API_KEY", ''),
        "LOGIN_BEARER_AUTH": os.getenv("LOGIN_BEARER_AUTH", ''),
    }
    if keyStore["vllmUrl"].strip() != "" or keyStore["vllmLargeModelUrl"].strip() != "" or keyStore["vllmSmallModelUrl"].strip() != "":
        keyStore["openai_models_list"] = ast.literal_eval(keyStore["openai_models_list"])
    for k, v in keyStore.items():
        key = session.get(k, v)
        if key is None or (isinstance(key, str) and key.strip() == "") or (isinstance(key, list) and len(key) == 0):
            key = v
        if key is not None and ((isinstance(key, str) and len(key.strip())>0) or (isinstance(key, list) and len(key)>0)):
            keyStore[k] = key
        else:
            keyStore[k] = None
    return keyStore



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
log = logging.getLogger('werkzeug')
log.setLevel(logging.INFO)
log = logging.getLogger('faiss.loader')
log.setLevel(logging.INFO)
logger.setLevel(logging.INFO)
time_logger = logging.getLogger(__name__ + " | TIMING")
time_logger.setLevel(logging.INFO)  # Set log level for this logger

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

def limiter_key_func():
    # logger.info(f"limiter_key_func called with {session.get('email')}")
    email = None
    if session:
        email = session.get('email')
    if email:
        return email
    # Here, you might want to use a different fallback or even raise an error
    return get_remote_address()

import platform
import faulthandler
faulthandler.enable()

def check_environment():
    logger.info(f"Python version: {sys.version}")
    logger.info(f"Platform: {platform.platform()}")
    logger.info(f"CPU Architecture: {platform.machine()}")
    logger.info(f"System: {platform.system()}")

if __name__ == '__main__':
    try:
        check_environment()
        app = OurFlask(__name__)
        app.config['SESSION_PERMANENT'] = True
        app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)
        app.config.update(
            SESSION_COOKIE_SECURE=True,
            SESSION_COOKIE_HTTPONLY=True,
            SESSION_COOKIE_SAMESITE='Lax',
            SESSION_REFRESH_EACH_REQUEST=True, 
            SESSION_COOKIE_NAME='session_id',
            SESSION_COOKIE_PATH='/',   
            PERMANENT_SESSION_LIFETIME=timedelta(days=30)  # Max lifetime for remembered sessions
        )
        app.config['SESSION_TYPE'] = 'filesystem'
        app.config["GOOGLE_CLIENT_ID"] = os.environ.get("GOOGLE_CLIENT_ID")
        app.config["GOOGLE_CLIENT_SECRET"] = os.environ.get("GOOGLE_CLIENT_SECRET")
        app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY")
        app.secret_key = os.environ.get("SECRET_KEY")
        app.config["RATELIMIT_STRATEGY"] = "moving-window"
        app.config["RATELIMIT_STORAGE_URL"] = "memory://"

        limiter = Limiter(
            app=app,
            key_func=limiter_key_func,
            default_limits=["200 per hour", "10 per minute"]
        )
        # app.config['PREFERRED_URL_SCHEME'] = 'http' if login_not_needed else 'https'
        Session(app)
        CORS(app, resources={
            r"/get_conversation_output_docs/*": {
                "origins": ["https://laingsimon.github.io", "https://app.diagrams.net/", "https://draw.io/", "https://www.draw.io/"]
            }
        })
        log = logging.getLogger('werkzeug')
        log.setLevel(logging.INFO)
        log = logging.getLogger('__main__')
        log.setLevel(logging.INFO)
        log = logging.getLogger('DocIndex')
        log.setLevel(logging.INFO)
        log = logging.getLogger('Conversation')
        log.setLevel(logging.INFO)
        log = logging.getLogger('base')
        log.setLevel(logging.INFO)
        log = logging.getLogger('faiss.loader')
        log.setLevel(logging.INFO)
        os.makedirs(os.path.join(os.getcwd(), folder), exist_ok=True)
        cache_dir = os.path.join(os.getcwd(), folder, "cache")
        users_dir = os.path.join(os.getcwd(), folder, "users")
        pdfs_dir = os.path.join(os.getcwd(), folder, "pdfs")
        os.makedirs(cache_dir, exist_ok=True)
        os.makedirs(users_dir, exist_ok=True)
        os.makedirs(pdfs_dir, exist_ok=True)
        os.makedirs(os.path.join(folder, "locks"), exist_ok=True)
        # nlp = English()  # just the language with no model
        # _ = nlp.add_pipe("lemmatizer")
        # nlp.initialize()
        conversation_folder = os.path.join(os.getcwd(), folder, "conversations")
        folder = os.path.join(os.getcwd(), folder, "documents")
        os.makedirs(folder, exist_ok=True)
        os.makedirs(conversation_folder, exist_ok=True)

        cache = Cache(app, config={'CACHE_TYPE': 'filesystem', 'CACHE_DIR': cache_dir,
                                   'CACHE_DEFAULT_TIMEOUT': 7 * 24 * 60 * 60})

    except Exception as e:
        logger.error(f"Failed to start server: {e}")



def check_login(session):
    email = dict(session).get('email', None)
    name = dict(session).get('name', None)
    logger.debug(f"Check Login for email {session.get('email')} and name {session.get('name')}")
    return email, name, email is not None and name is not None

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        logger.debug(f"Login Required call for email {session.get('email')} and name {session.get('name')}")
        if session.get('email') is None or session.get('name') is None:
            return redirect('/login', code=302)
        return f(*args, **kwargs)
    return decorated_function

def check_credentials(username, password):
    return os.getenv("PASSWORD", "XXXX") == password


from hashlib import sha256
import secrets
import json
import os

def generate_remember_token(email: str) -> str:
    """
    Generate a secure remember-me token for the user.
    If a valid token already exists for this email, return that instead.
    
    Args:
        email (str): User's email address
        
    Returns:
        str: A secure token string
    """
    tokens_file = os.path.join(users_dir, "remember_tokens.json")
    
    try:
        current_time = datetime.now()
        # Load existing tokens
        tokens = None
        if os.path.exists(tokens_file):
            with open(tokens_file, 'r') as f:
                tokens = json.load(f)
                
            # Check if user has any valid existing tokens
            for token, data in tokens.items():
                if (data['email'] == email and 
                    datetime.fromisoformat(data['expires_at']) > current_time):
                    # Return existing valid token
                    return token
                
        # If no valid token exists, generate a new one
        random_token = secrets.token_hex(32)
        combined = f"{email}:{random_token}:{int(current_time.timestamp())}"
        token = sha256(combined.encode()).hexdigest()
        
        # Store the token mapping
        if not tokens:
            tokens = {}
            
        tokens[token] = {
            'email': email,
            'created_at': current_time.isoformat(),
            'expires_at': (current_time + timedelta(days=30)).isoformat()
        }
        
        # Save updated tokens
        with open(tokens_file, 'w') as f:
            json.dump(tokens, f)
            
        return token
            
    except Exception as e:
        logger.error(f"Failed to generate/retrieve remember token: {e}")
        raise

def verify_remember_token(token: str) -> Optional[str]:
    """
    Verify a remember-me token and return the associated email if valid.
    
    Args:
        token (str): Token to verify
        
    Returns:
        Optional[str]: Associated email if token is valid, None otherwise
    """
    tokens_file = os.path.join(users_dir, "remember_tokens.json")
    
    try:
        # Load tokens
        if not os.path.exists(tokens_file):
            return None
            
        with open(tokens_file, 'r') as f:
            tokens = json.load(f)
        
        # Check if token exists
        if token not in tokens:
            return None
            
        token_data = tokens[token]
        
        # Check if token has expired
        expires_at = datetime.fromisoformat(token_data['expires_at'])
        if datetime.now() > expires_at:
            # Only remove this specific expired token
            del tokens[token]
            with open(tokens_file, 'w') as f:
                json.dump(tokens, f)
            return None
            
        return token_data['email']
        
    except Exception as e:
        logger.error(f"Failed to verify remember token: {e}")
        return None

def store_remember_token(email: str, token: str) -> None:
    """
    Store the remember-me token mapping.
    
    Args:
        email (str): User's email address
        token (str): Generated remember token
    """
    tokens_file = os.path.join(users_dir, "remember_tokens.json")
    
    try:
        # Load existing tokens
        if os.path.exists(tokens_file):
            with open(tokens_file, 'r') as f:
                tokens = json.load(f)
        else:
            tokens = {}
        
        # Store new token with timestamp
        tokens[token] = {
            'email': email,
            'created_at': datetime.now().isoformat(),
            'expires_at': (datetime.now() + timedelta(days=30)).isoformat()
        }
        
        # Save updated tokens
        with open(tokens_file, 'w') as f:
            json.dump(tokens, f)
            
    except Exception as e:
        logger.error(f"Failed to store remember token: {e}")
        raise


def cleanup_tokens() -> None:
    """Clean up expired tokens and rotate tokens that are close to expiring."""
    tokens_file = os.path.join(users_dir, "remember_tokens.json")
    
    try:
        if not os.path.exists(tokens_file):
            return
            
        with open(tokens_file, 'r') as f:
            tokens = json.load(f)
        
        current_time = datetime.now()
        tokens_to_delete = []
        
        for token, data in tokens.items():
            expires_at = datetime.fromisoformat(data['expires_at'])
            
            # Remove expired tokens
            if current_time > expires_at:
                tokens_to_delete.append(token)
                
        # Remove expired tokens
        for token in tokens_to_delete:
            del tokens[token]
            
        # Save updated tokens
        with open(tokens_file, 'w') as f:
            json.dump(tokens, f)
            
    except Exception as e:
        logger.error(f"Failed to cleanup tokens: {e}")
    
@app.before_request
def check_remember_token():
    """Check for remember-me token if session is not active."""
    if 'email' not in session:
        remember_token = request.cookies.get('remember_token')
        if remember_token:
            email = verify_remember_token(remember_token)
            if email:
                session.permanent = True
                session['email'] = email
                session['name'] = email
                session['created_at'] = datetime.now().isoformat()
                session['user_agent'] = request.user_agent.string

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        remember = request.form.get('remember') == 'on'  # Check if remember checkbox is checked
        
        if check_credentials(email, password):
            # Set session permanent before adding any values
            session.permanent = True
            # Create the response object
            response = redirect(url_for('interface'))
            
            # Only set remember token if remember me was checked
            if remember:
                response.set_cookie('remember_token', 
                                  value=generate_remember_token(email),
                                  expires=datetime.now() + timedelta(days=30),
                                  secure=True,
                                  httponly=True,
                                  samesite='Lax')
            
            session['email'] = email
            session['name'] = email
            session['created_at'] = datetime.now().isoformat()
            session['user_agent'] = request.user_agent.string
            return response
        else:
            error = "Invalid credentials"
    return render_template_string(
        open('interface/login.html').read(),
        error=error
    )


@app.route('/logout')
@limiter.limit("10 per minute")
@login_required
def logout():
    session.pop('name', None)
    session.pop('email', None)
    return render_template_string("""
            <h1>Logged out</h1>
            <p><a href="{{ url_for('login') }}">Click here</a> to log in again. You can now close this Tab/Window.</p>
        """)


@app.route('/get_user_info')
@limiter.limit("100 per minute")
@login_required
def get_user_info():
    if 'email' in session and "name" in session:
        return jsonify(name=session['name'], email=session['email'])
    else:
        return "Not logged in", 401

def load_conversation(conversation_id):
    path = os.path.join(conversation_folder, conversation_id)
    conversation = Conversation.load_local(path)
    return conversation

conversation_cache = DefaultDictQueue(maxsize=100, default_factory=load_conversation)
    
def set_keys_on_docs(docs, keys):
    logger.debug(f"Attaching keys to doc")
    if isinstance(docs, dict):
        # docs = {k: v.copy() for k, v in docs.items()}
        for k, v in docs.items():
            v.set_api_keys(keys)
    elif isinstance(docs, (list, tuple, set)):
        # docs = [d.copy() for d in docs]
        for d in docs:
            d.set_api_keys(keys)
    else:
        try:
            assert isinstance(docs, (DocIndex, ImmediateDocIndex, ImageDocIndex, Conversation, TemporaryConversation)) or hasattr(docs, "set_api_keys")
            docs.set_api_keys(keys)
        except Exception as e:
            logger.error(f"Failed to set keys on docs: {e}, type = {type(docs)}")
            raise
    return docs
    



@app.route('/clear_session', methods=['GET'])
@limiter.limit("1000 per minute")
@login_required
def clear_session():
    # clear the session
    session.clear()
    return jsonify({'result': 'session cleared'})


def delayed_execution(func, delay, *args):
    time.sleep(delay)
    return func(*args)




from multiprocessing import Lock

lock = Lock()

    
from flask import send_from_directory, send_file

@app.route('/favicon.ico')
@limiter.limit("300 per minute")
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static'),
                               'favicon.ico', mimetype='image/vnd.microsoft.icon')
    
@app.route('/loader.gif')
@limiter.limit("100 per minute")
def loader():
    return send_from_directory(os.path.join(app.root_path, 'static'),
                               'gradient-loader.gif', mimetype='image/gif')



@app.route('/interface')
@limiter.limit("200 per minute")
@login_required
def interface():
    return send_from_directory('interface', 'interface.html', max_age=0)


@app.route('/interface/<path:path>')  
@limiter.limit("1000 per minute")  
def interface_combined(path):
    # Check login status  
    email, name, loggedin = check_login(session)  

    # custom path logic
    if not loggedin or email is None:
        return redirect('/login', code=302)
    
    if email is not None and path.startswith(email) and path.count('/') >= 2:
        path = '/'.join(path.split('/')[1:])
    

    # First, handle potential conversation IDs  
    if loggedin:  
        try:  
            # Get user's conversations  
            conversation_ids = [c[1] for c in getCoversationsForUser(email)]  
            conversation_id = path.split('/')[0]
            if conversation_id in conversation_ids:  
                # Valid conversation ID, serve the interface  
                return send_from_directory('interface', 'interface.html', max_age=0)  
        except Exception as e:  
            logger.error(f"Error checking conversation access: {str(e)}")  
            # Continue to static file handling on error  
    else:  
        # Heuristic to detect if path might be a conversation ID  
        # Adjust this logic based on your conversation ID format  
        if path.isalnum() and len(path) >= 8 and '.' not in path:  
            # Looks like a conversation ID attempt, redirect to login  
            return redirect('/login', code=302)
      
    # If we get here, treat as static file request  
    try:  
        return send_from_directory('interface', path.replace('interface/', '').replace('interface/interface/', ''), max_age=0)  
    except FileNotFoundError:  
        return "File not found", 404  



@app.route('/shared/<conversation_id>')
@limiter.limit("200 per minute")
def shared(conversation_id):
    # Path to your shared.html file
    html_file_path = os.path.join('interface', 'shared.html')

    # Read the HTML file
    with open(html_file_path, 'r', encoding='utf-8') as file:
        html_content = file.read()
    # Insert the <div> element before the closing </body> tag
    div_element = f'<div id="conversation_id" data-conversation_id="{conversation_id}" style="display: none;"></div>'
    modified_html = html_content.replace('</body>', f'{div_element}</body>')

    # Return the modified HTML content
    return Response(modified_html, mimetype='text/html')


from flask import Response, stream_with_context

@app.route('/proxy', methods=['GET'])
@login_required
def proxy():
    file_url = request.args.get('file')
    logger.debug(f"Proxying file {file_url}, exists on disk = {os.path.exists(file_url)}")
    return Response(stream_with_context(cached_get_file(file_url)), mimetype='application/pdf')

@app.route('/proxy_shared', methods=['GET'])
def proxy_shared():
    file_url = request.args.get('file')
    logger.debug(f"Proxying file {file_url}, exists on disk = {os.path.exists(file_url)}")
    return Response(stream_with_context(cached_get_file(file_url)), mimetype='application/pdf')

@app.route('/')
@limiter.limit("200 per minute")
@login_required
def index():
    return redirect('/interface')


@app.route('/upload_doc_to_conversation/<conversation_id>', methods=['POST'])
@limiter.limit("10 per minute")
@login_required
def upload_doc_to_conversation(conversation_id):
    keys = keyParser(session)
    email, name, loggedin = check_login(session)
    pdf_file = request.files.get('pdf_file')
    conversation: Conversation = conversation_cache[conversation_id]
    conversation = set_keys_on_docs(conversation, keys)
    if pdf_file and conversation_id:
        try:
            # save file to disk at pdfs_dir.
            pdf_file.save(os.path.join(pdfs_dir, pdf_file.filename))
            full_pdf_path = os.path.join(pdfs_dir, pdf_file.filename)
            conversation.add_uploaded_document(full_pdf_path)
            conversation.save_local()
            return jsonify({'status': 'Indexing started'})
        except Exception as e:
            traceback.print_exc()
            return jsonify({'error': str(e)}), 400

    pdf_url = request.json.get('pdf_url')
    pdf_url = convert_to_pdf_link_if_needed(pdf_url)
    if pdf_url:
        try:
            conversation.add_uploaded_document(pdf_url)
            conversation.save_local()
            return jsonify({'status': 'Indexing started'})
        except Exception as e:
            traceback.print_exc()
            return jsonify({'error': str(e)}), 400
    else:
        return jsonify({'error': 'No pdf_url or pdf_file provided'}), 400

@app.route('/delete_document_from_conversation/<conversation_id>/<document_id>', methods=['DELETE'])
@limiter.limit("100 per minute")
@login_required
def delete_document_from_conversation(conversation_id, document_id):
    keys = keyParser(session)
    email, name, loggedin = check_login(session)
    conversation: Conversation = conversation_cache[conversation_id]
    conversation = set_keys_on_docs(conversation, keys)
    doc_id = document_id
    if doc_id:
        try:
            conversation.delete_uploaded_document(doc_id)
            return jsonify({'status': 'Document deleted'})
        except Exception as e:
            traceback.print_exc()
            return jsonify({'error': str(e)}), 400
    else:
        return jsonify({'error': 'No doc_id provided'}), 400

@app.route('/list_documents_by_conversation/<conversation_id>', methods=['GET'])
@limiter.limit("30 per minute")
@login_required
def list_documents_by_conversation(conversation_id):
    keys = keyParser(session)
    conversation: Conversation = conversation_cache[conversation_id]
    conversation = set_keys_on_docs(conversation, keys)
    if conversation:
        docs:List[DocIndex] = conversation.get_uploaded_documents(readonly=True)
        # filter out None documents
        docs = [d for d in docs if d is not None]
        docs = set_keys_on_docs(docs, keys)
        docs = [d.get_short_info() for d in docs]
        # sort by doc_id
        # docs = sorted(docs, key=lambda x: x['doc_id'], reverse=True)
        return jsonify(docs)
    else:
        return jsonify({'error': 'Conversation not found'}), 404

@app.route('/download_doc_from_conversation/<conversation_id>/<doc_id>', methods=['GET'])
@limiter.limit("30 per minute")
@login_required
def download_doc_from_conversation(conversation_id, doc_id):
    keys = keyParser(session)
    conversation: Conversation = conversation_cache[conversation_id]
    if conversation:
        conversation = set_keys_on_docs(conversation, keys)
        doc:DocIndex = conversation.get_uploaded_documents(doc_id, readonly=True)[0]
        if doc and os.path.exists(doc.doc_source):
            file_dir, file_name = os.path.split(doc.doc_source)
            print(os.path.dirname(os.path.abspath(file_dir)))
            file_dir = file_dir.replace(os.path.dirname(__file__) + "/", "")
            return send_from_directory(file_dir, file_name)
        elif doc:
            return redirect(doc.doc_source)
        else:
            return jsonify({'error': 'Document not found'}), 404
    else:
        return jsonify({'error': 'Conversation not found'}), 404

def cached_get_file(file_url):
    chunk_size = 1024  # Define your chunk size
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
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36'}
            req = requests.get(file_url, stream=True,
                               verify=False, headers=headers)
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to download file: {e}")
            req = requests.get(file_url, stream=True, verify=False)
        # TODO: save the downloaded file to disk.
        
        for chunk in req.iter_content(chunk_size=chunk_size):
            file_data.append(chunk)
            yield chunk
        cache.set(file_url, file_data)


### chat apis
@app.route('/list_conversation_by_user/<domain>', methods=['GET'])
@limiter.limit("500 per minute")
@login_required
def list_conversation_by_user(domain:str):
    # TODO: sort by last_updated
    domain = domain.strip().lower()
    email, name, loggedin = check_login(session)
    keys = keyParser(session)
    last_n_conversations = request.args.get('last_n_conversations', 10)
    # TODO: add ability to get only n conversations
    conversation_ids = [c[1] for c in getCoversationsForUser(email)]
    conversations = [conversation_cache[conversation_id] for conversation_id in conversation_ids]
    # stateless_conversations = [conversation for conversation in conversations if conversation is not None and conversation.stateless]
    # for conversation in stateless_conversations:
    #     removeUserFromConversation(email, conversation.conversation_id)
    #     del conversation_cache[conversation.conversation_id]
    #     deleteConversationForUser(email, conversation.conversation_id)
    #     conversation.delete_conversation()

    for conversation_id, conversation in zip(conversation_ids, conversations):
        if conversation is None:
            removeUserFromConversation(email, conversation_id)
            del conversation_cache[conversation_id]
            deleteConversationForUser(email, conversation_id)
            

    conversations = [conversation for conversation in conversations if conversation is not None and conversation.domain==domain] #  and not conversation.stateless
    conversations = [set_keys_on_docs(conversation, keys) for conversation in conversations]
    data = [[conversation.get_metadata(), conversation] for conversation in conversations]
    sorted_data_reverse = sorted(data, key=lambda x: x[0]['last_updated'], reverse=True)
    # TODO: if any conversation has 0 messages then just make it the latest. IT should also have a zero length summary.

    if len(sorted_data_reverse) > 0 and len(sorted_data_reverse[0][0]["summary_till_now"].strip()) > 0:
        sorted_data_reverse = sorted(sorted_data_reverse, key=lambda x: len(x[0]['summary_till_now'].strip()), reverse=False)
        if sorted_data_reverse[0][0]["summary_till_now"].strip() == "" and len(sorted_data_reverse[0][1].get_message_list()) == 0:
            new_conversation = sorted_data_reverse[0][1]
            sorted_data_reverse = sorted_data_reverse[1:]
            sorted_data_reverse = sorted(sorted_data_reverse, key=lambda x: x[0]['last_updated'], reverse=True)
            new_conversation.set_field("memory", {"last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
        else:
            new_conversation = create_conversation_simple(session, domain)
        sorted_data_reverse.insert(0, [new_conversation.get_metadata(), new_conversation])
    if len(sorted_data_reverse) == 0:
        new_conversation = create_conversation_simple(session, domain)
        sorted_data_reverse.insert(0, [new_conversation.get_metadata(), new_conversation])
    sorted_data_reverse = [sd[0] for sd in sorted_data_reverse]
    return jsonify(sorted_data_reverse)

@app.route('/create_conversation/<domain>', methods=['POST'])
@limiter.limit("500 per minute")
@login_required
def create_conversation(domain: str):
    domain = domain.strip().lower()
    conversation = create_conversation_simple(session, domain)
    data = conversation.get_metadata()
    return jsonify(data)

def create_conversation_simple(session, domain: str):
    email, name, loggedin = check_login(session)
    keys = keyParser(session)
    from base import get_embedding_model
    # str(mmh3.hash(email, signed=False))
    conversation_id = email + "_" + ''.join(secrets.choice(alphabet) for i in range(36))
    conversation = Conversation(email, openai_embed=get_embedding_model(keys), storage=conversation_folder,
                                conversation_id=conversation_id, domain=domain)
    conversation = set_keys_on_docs(conversation, keys)
    addConversationToUser(email, conversation.conversation_id)
    conversation.save_local()
    return conversation

@app.route('/shared_chat/<conversation_id>', methods=['GET'])
@limiter.limit("100 per minute")
def shared_chat(conversation_id):
    conversation_ids = [c[1] for c in getConversationById(conversation_id)]
    if conversation_id not in conversation_ids:
        return jsonify({"message": "Conversation not found"}), 404
    else:
        conversation = conversation_cache[conversation_id]
    data = conversation.get_metadata()
    messages = conversation.get_message_list()
    if conversation:
        docs: List[DocIndex] = conversation.get_uploaded_documents(readonly=True)
        docs = [d.get_short_info() for d in docs]
        return jsonify({"messages": messages, "documents": docs, "metadata": data})
    return jsonify({"messages": messages, "metadata": data, "documents": []})




@app.route('/list_messages_by_conversation/<conversation_id>', methods=['GET'])
@limiter.limit("1000 per minute")
@login_required
def list_messages_by_conversation(conversation_id):
    keys = keyParser(session)
    email, name, loggedin = check_login(session)
    last_n_messages = request.args.get('last_n_messages', 10)
    # TODO: add capability to get only last n messages
    conversation_ids = [c[1] for c in getCoversationsForUser(email)]
    if conversation_id not in conversation_ids:
        return jsonify({"message": "Conversation not found"}), 404
    else:
        conversation = conversation_cache[conversation_id]
        conversation = set_keys_on_docs(conversation, keys)
    messages = conversation.get_message_list()
    return jsonify(messages)

@app.route('/list_messages_by_conversation_shareable/<conversation_id>', methods=['GET'])
@limiter.limit("100 per minute")
def list_messages_by_conversation_shareable(conversation_id):
    keys = keyParser(session)
    email, name, loggedin = check_login(session)
    conversation_ids = [c[1] for c in getAllCoversations()]
    if conversation_id not in conversation_ids:
        return jsonify({"message": "Conversation not found"}), 404
    else:
        conversation: Conversation = conversation_cache[conversation_id]

    if conversation:
        docs: List[DocIndex] = conversation.get_uploaded_documents(readonly=True)
        docs = [d.get_short_info() for d in docs]
        messages = conversation.get_message_list()
        return jsonify({"messages": messages, "docs": docs})
    else:
        return jsonify({'error': 'Conversation not found'}), 404

@app.route('/send_message/<conversation_id>', methods=['POST'])
@limiter.limit("50 per minute")
@login_required
def send_message(conversation_id):
    keys = keyParser(session)
    email, name, loggedin = check_login(session)
    # check if the user has a user_details row
    user_details = getUserFromUserDetailsTable(email)
    
    conversation_ids = [c[1] for c in getCoversationsForUser(email)]
    if conversation_id not in conversation_ids:
        return jsonify({"message": "Conversation not found"}), 404
    else:
        conversation: Conversation = conversation_cache[conversation_id]
        conversation: Conversation = set_keys_on_docs(conversation, keys)

    query = request.json

    # We don't process the request data in this mockup, but we would normally send a new message here

    # import queue
    from queue import Queue
    response_queue = Queue()
    from flask import copy_current_request_context

    @copy_current_request_context
    def generate_response():
        for chunk in conversation(query, user_details):
            response_queue.put(chunk)
        response_queue.put("<--END-->")

    future = get_async_future(generate_response)

    def run_queue():
        try:
            while True:
                chunk = response_queue.get()
                if chunk == "<--END-->":
                    break
                yield chunk
        except GeneratorExit:
            # Client disconnected - we'll still finish our background task
            print("Client disconnected, but continuing background processing")
    

    # future.result()

    return Response(run_queue(), content_type='text/plain')


@app.route('/get_conversation_details/<conversation_id>', methods=['GET'])
@limiter.limit("1000 per minute")
@login_required
def get_conversation_details(conversation_id):
    keys = keyParser(session)
    email, name, loggedin = check_login(session)

    conversation_ids = [c[1] for c in getCoversationsForUser(email)]
    if conversation_id not in conversation_ids:
        return jsonify({"message": "Conversation not found"}), 404
    else:
        conversation = conversation_cache[conversation_id]
        conversation = set_keys_on_docs(conversation, keys)
    # Dummy data
    data = conversation.get_metadata()
    return jsonify(data)

@app.route('/make_conversation_stateless/<conversation_id>', methods=['DELETE'])
@limiter.limit("25 per minute")
@login_required
def make_conversation_stateless(conversation_id):
    email, name, loggedin = check_login(session)
    keys = keyParser(session)
    conversation_ids = [c[1] for c in getCoversationsForUser(email)]
    if conversation_id not in conversation_ids:
        return jsonify({"message": "Conversation not found"}), 404
    else:
        conversation = conversation_cache[conversation_id]
        conversation = set_keys_on_docs(conversation, keys)
    conversation.make_stateless()
    # In a real application, you'd delete the conversation here
    return jsonify({'message': f'Conversation {conversation_id} stateless now.'})

@app.route('/make_conversation_stateful/<conversation_id>', methods=['PUT'])
@limiter.limit("25 per minute")
@login_required
def make_conversation_stateful(conversation_id):
    email, name, loggedin = check_login(session)
    keys = keyParser(session)
    conversation_ids = [c[1] for c in getCoversationsForUser(email)]
    if conversation_id not in conversation_ids:
        return jsonify({"message": "Conversation not found"}), 404
    else:
        conversation = conversation_cache[conversation_id]
        conversation = set_keys_on_docs(conversation, keys)
    conversation.make_stateful()
    # In a real application, you'd delete the conversation here
    return jsonify({'message': f'Conversation {conversation_id} deleted'})


@app.route('/edit_message_from_conversation/<conversation_id>/<message_id>/<index>', methods=['POST'])
@limiter.limit("30 per minute")
@login_required
def edit_message_from_conversation(conversation_id, message_id, index):
    email, name, loggedin = check_login(session)
    keys = keyParser(session)
    conversation_ids = [c[1] for c in getCoversationsForUser(email)]
    message_text = request.json.get('text')
    if conversation_id not in conversation_ids:
        return jsonify({"message": "Conversation not found"}), 404
    else:
        conversation = conversation_cache[conversation_id]
        conversation = set_keys_on_docs(conversation, keys)
    conversation.edit_message(message_id, index, message_text)
    # In a real application, you'd delete the conversation here
    return jsonify({'message': f'Message {message_id} deleted'})

@app.route('/move_messages_up_or_down/<conversation_id>', methods=['POST'])
@limiter.limit("30 per minute")
@login_required
def move_messages_up_or_down(conversation_id):
    email, name, loggedin = check_login(session)
    keys = keyParser(session)
    conversation_ids = [c[1] for c in getCoversationsForUser(email)]
    message_ids = request.json.get('message_ids')
    assert isinstance(message_ids, list)
    assert all(isinstance(m, str) for m in message_ids)
    direction = request.json.get('direction')
    assert direction in ["up", "down"]
    if conversation_id not in conversation_ids:
        return jsonify({"message": "Conversation not found"}), 404
    else:
        conversation = conversation_cache[conversation_id]
        conversation = set_keys_on_docs(conversation, keys)
    conversation.move_messages_up_or_down(message_ids, direction)
    return jsonify({'message': f'Messages {message_ids} moved {direction}'})


@app.route('/show_hide_message_from_conversation/<conversation_id>/<message_id>/<index>', methods=['POST'])
@limiter.limit("30 per minute")
@login_required
def show_hide_message_from_conversation(conversation_id, message_id, index):
    email, name, loggedin = check_login(session)
    keys = keyParser(session)
    conversation_ids = [c[1] for c in getCoversationsForUser(email)]
    show_hide = request.json.get('show_hide')
    if conversation_id not in conversation_ids:
        return jsonify({"message": "Conversation not found"}), 404
    else:
        conversation = conversation_cache[conversation_id]
        conversation = set_keys_on_docs(conversation, keys)
    conversation.show_hide_message(message_id, index, show_hide)
    # In a real application, you'd delete the conversation here
    return jsonify({'message': f'Message {message_id} state changed to {show_hide}'})

@app.route('/clone_conversation/<conversation_id>', methods=['POST'])
@limiter.limit("25 per minute")
@login_required
def clone_conversation(conversation_id):
    email, name, loggedin = check_login(session)
    keys = keyParser(session)
    conversation = conversation_cache[conversation_id]
    conversation = set_keys_on_docs(conversation, keys)
    new_conversation: Conversation = conversation.clone_conversation()
    new_conversation.save_local()
    addConversationToUser(email, new_conversation.conversation_id)
    conversation_cache[new_conversation.conversation_id] = new_conversation
    return jsonify({'message': f'Conversation {conversation_id} cloned', 'conversation_id': new_conversation.conversation_id})

@app.route('/delete_conversation/<conversation_id>', methods=['DELETE'])
@limiter.limit("5000 per minute")
@login_required
def delete_conversation(conversation_id):
    email, name, loggedin = check_login(session)
    keys = keyParser(session)
    conversation_ids = [c[1] for c in getCoversationsForUser(email)]
    if conversation_id not in conversation_ids:
        return jsonify({"message": "Conversation not found"}), 404
    else:
        conversation = conversation_cache[conversation_id]
        del conversation_cache[conversation_id]
        conversation.delete_conversation()
        deleteConversationForUser(email, conversation_id)
    removeUserFromConversation(email, conversation_id)
    # In a real application, you'd delete the conversation here
    return jsonify({'message': f'Conversation {conversation_id} deleted'})
@app.route('/delete_message_from_conversation/<conversation_id>/<message_id>/<index>', methods=['DELETE'])
@limiter.limit("300 per minute")
@login_required
def delete_message_from_conversation(conversation_id, message_id, index):
    email, name, loggedin = check_login(session)
    keys = keyParser(session)
    conversation_ids = [c[1] for c in getCoversationsForUser(email)]
    if conversation_id not in conversation_ids:
        return jsonify({"message": "Conversation not found"}), 404
    else:
        conversation = conversation_cache[conversation_id]
        conversation = set_keys_on_docs(conversation, keys)
    conversation.delete_message(message_id, index)
    # In a real application, you'd delete the conversation here
    return jsonify({'message': f'Message {message_id} deleted'})

@app.route('/delete_last_message/<conversation_id>', methods=['DELETE'])
@limiter.limit("30 per minute")
@login_required
def delete_last_message(conversation_id):
    message_id=1
    email, name, loggedin = check_login(session)
    keys = keyParser(session)
    conversation_ids = [c[1] for c in getCoversationsForUser(email)]
    if conversation_id not in conversation_ids:
        return jsonify({"message": "Conversation not found"}), 404
    else:
        conversation = conversation_cache[conversation_id]
        conversation: Conversation = set_keys_on_docs(conversation, keys)
    conversation.delete_last_turn()
    # In a real application, you'd delete the conversation here
    return jsonify({'message': f'Message {message_id} deleted'})

@app.route('/set_memory_pad/<conversation_id>', methods=['POST'])
@limiter.limit("25 per minute")
@login_required
def set_memory_pad(conversation_id):
    email, name, loggedin = check_login(session)
    keys = keyParser(session)
    conversation_ids = [c[1] for c in getCoversationsForUser(email)]
    if conversation_id not in conversation_ids:
        return jsonify({"message": "Conversation not found"}), 404
    else:
        conversation = conversation_cache[conversation_id]
        conversation = set_keys_on_docs(conversation, keys)
    memory_pad = request.json.get('text')
    conversation.set_memory_pad(memory_pad)
    return jsonify({'message': f'Memory pad set'})

@app.route('/fetch_memory_pad/<conversation_id>', methods=['GET'])
@limiter.limit("25 per minute")
@login_required
def fetch_memory_pad(conversation_id):
    email, name, loggedin = check_login(session)
    keys = keyParser(session)
    conversation_ids = [c[1] for c in getCoversationsForUser(email)]
    if conversation_id not in conversation_ids:
        return jsonify({"message": "Conversation not found"}), 404
    else:
        conversation = conversation_cache[conversation_id]
        conversation = set_keys_on_docs(conversation, keys)
    memory_pad = conversation.memory_pad
    return jsonify({'text': memory_pad})

@app.route(f'/get_conversation_output_docs/{COMMON_SALT_STRING}/<conversation_id>/<document_file_name>', methods=['GET'])
@limiter.limit("25 per minute")
def get_conversation_output_docs(conversation_id, document_file_name):
    conversation = conversation_cache[conversation_id]  
    if os.path.exists(os.path.join(conversation.documents_path, document_file_name)):
        response = send_from_directory(conversation.documents_path, document_file_name)
        # Add CORS headers
        # Get the Origin header from the request
        origin = request.headers.get('Origin')
        # Check if origin matches any of our allowed domains
        allowed_origins = ['https://laingsimon.github.io', 'https://app.diagrams.net', 'https://draw.io', 'https://www.draw.io']
        if origin in allowed_origins:
            response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Access-Control-Allow-Methods'] = 'GET'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        return response
    else:
        return jsonify({"message": "Document not found"}), 404


@app.route('/tts/<conversation_id>/<message_id>', methods=['POST'])
@login_required
def tts(conversation_id, message_id):
    """
    Updated route to perform streaming TTS if requested.
    Otherwise, we can keep the existing single-file logic 
    or entirely switch to streaming. Here we'll assume 
    streaming is the new desired behavior by default. 
    """
    email, name, loggedin = check_login(session)
    keys = keyParser(session)
    text = request.json.get('text', '')
    recompute = request.json.get('recompute', False)
    message_index = request.json.get('message_index', None)
    streaming = request.json.get('streaming', True)
    shortTTS = request.json.get('shortTTS', False)
    podcastTTS = request.json.get('podcastTTS', False)
    # Optional param to decide if we do the old single-file approach or new streaming approach:
    # But let's assume we do streaming permanently now.
    # stream_tts = request.json.get('streaming', True)

    conversation_ids = [c[1] for c in getCoversationsForUser(email)]
    if conversation_id not in conversation_ids:
        return jsonify({"message": "Conversation not found"}), 404
    else:
        conversation = conversation_cache[conversation_id]
        conversation = set_keys_on_docs(conversation, keys)

    if streaming:
        # For streaming approach, we get a generator
        audio_generator = conversation.convert_to_audio_streaming(text, message_id, message_index, recompute, shortTTS, podcastTTS)

        # We define a function that yields the chunks of mp3 data to the client
        def generate_audio():
            for chunk in audio_generator:
                # chunk is mp3 data; yield it as part of the response
                yield chunk

        # Return a streaming Response
        return Response(generate_audio(), mimetype='audio/mpeg')
    else:
        location = conversation.convert_to_audio(text, message_id, message_index, recompute, shortTTS, podcastTTS)
        return send_file(location, mimetype='audio/mpeg')

@app.route('/is_tts_done/<conversation_id>/<message_id>', methods=['POST'])
def is_tts_done(conversation_id, message_id):
    text = request.json.get('text')
    return jsonify({"is_done": True}), 200

@app.route('/transcribe', methods=['POST'])
def transcribe_audio():
    from werkzeug.utils import secure_filename

    if 'audio' not in request.files:
        return jsonify({"error": "No audio file provided"}), 400

    audio_file = request.files['audio']

    if audio_file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    if audio_file:
        # Create a temporary file to store the uploaded audio
        with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as temp_audio_file:
            audio_file.save(temp_audio_file.name)

        try:
            if USE_OPENAI_API:
                from openai import OpenAI
                client = OpenAI(api_key=os.environ.get("openAIKey"))
                # Open the temporary file and send it to OpenAI for transcription
                with open(temp_audio_file.name, "rb") as audio:
                    transcription = client.audio.transcriptions.create(
                        model="whisper-1",
                        file=audio,
                        response_format="text",
                        language='en'
                    )

                return jsonify({"transcription": transcription.strip()})
            else:
                import assemblyai as aai
                # Configure AssemblyAI
                aai.settings.api_key = os.environ.get("ASSEMBLYAI_API_KEY")
                
                # Initialize transcriber
                transcriber = aai.Transcriber()
                
                # Start transcription
                transcript = transcriber.transcribe(temp_audio_file.name)

                # Check status and return result
                if transcript.status == aai.TranscriptStatus.error:
                    return jsonify({"error": f"Transcription failed: {transcript.error}"}), 500

                # Return the transcribed text
                return jsonify({"transcription": transcript.text.strip()})

        except Exception as e:
            traceback.print_exc()
            return jsonify({"error": str(e)}), 500

        finally:
            # Clean up the temporary file
            os.unlink(temp_audio_file.name)

    return jsonify({"error": "Failed to process audio file"}), 500



@app.route('/get_user_detail', methods=['GET'])
@limiter.limit("25 per minute")
@login_required
def get_user_detail():
    """
    GET API endpoint to retrieve user memory/details
    
    Returns:
        JSON with the user's memory information
    """
    email, name, loggedin = check_login(session)
    
    if not loggedin:
        return jsonify({"error": "User not logged in"}), 401
    
    user_details = getUserFromUserDetailsTable(email)
    
    if user_details is None:
        # If user doesn't exist in the details table yet, return empty
        return jsonify({"text": ""})
    
    # Return the user_memory field
    return jsonify({"text": user_details.get("user_memory", "")})

@app.route('/get_user_preference', methods=['GET'])
@limiter.limit("25 per minute")
@login_required
def get_user_preference():
    """
    GET API endpoint to retrieve user preferences
    
    Returns:
        JSON with the user's preference information
    """
    email, name, loggedin = check_login(session)
    
    if not loggedin:
        return jsonify({"error": "User not logged in"}), 401
    
    user_details = getUserFromUserDetailsTable(email)
    
    if user_details is None:
        # If user doesn't exist in the details table yet, return empty
        return jsonify({"text": ""})
    
    # Return the user_preferences field
    return jsonify({"text": user_details.get("user_preferences", "")})

@app.route('/modify_user_detail', methods=['POST'])
@limiter.limit("15 per minute")
@login_required
def modify_user_detail():
    """
    POST API endpoint to update user memory/details
    
    Expects:
        JSON with "text" field containing the new user memory data
        
    Returns:
        JSON with success/error message
    """
    email, name, loggedin = check_login(session)
    
    if not loggedin:
        return jsonify({"error": "User not logged in"}), 401
    
    try:
        # Get the new memory text from request
        memory_text = request.json.get('text')
        
        if memory_text is None:
            return jsonify({"error": "Missing 'text' field in request"}), 400
        
        # Update only the user_memory field
        success = updateUserInfoInUserDetailsTable(email, user_memory=memory_text)
        
        if success:
            return jsonify({"message": "User details updated successfully"})
        else:
            return jsonify({"error": "Failed to update user details"}), 500
    
    except Exception as e:
        logger.error(f"Error in modify_user_detail: {e}")
        return jsonify({"error": f"An error occurred: {str(e)}"}), 500

@app.route('/modify_user_preference', methods=['POST'])
@limiter.limit("15 per minute")
@login_required
def modify_user_preference():
    """
    POST API endpoint to update user preferences
    
    Expects:
        JSON with "text" field containing the new user preferences data
        
    Returns:
        JSON with success/error message
    """
    email, name, loggedin = check_login(session)
    
    if not loggedin:
        return jsonify({"error": "User not logged in"}), 401
    
    try:
        # Get the new preferences text from request
        preferences_text = request.json.get('text')
        
        if preferences_text is None:
            return jsonify({"error": "Missing 'text' field in request"}), 400
        
        # Update only the user_preferences field
        success = updateUserInfoInUserDetailsTable(email, user_preferences=preferences_text)
        
        if success:
            return jsonify({"message": "User preferences updated successfully"})
        else:
            return jsonify({"error": "Failed to update user preferences"}), 500
    
    except Exception as e:
        logger.error(f"Error in modify_user_preference: {e}")
        return jsonify({"error": f"An error occurred: {str(e)}"}), 500
    

@app.route('/run_code_once', methods=['POST'])
@limiter.limit("10 per minute")
@login_required
def run_code():
    code_string = request.json.get('code_string')
    from code_runner import run_code_once
    return run_code_once(code_string)






# Next we build - create_session,
# Within session the below API can be used - create_document_from_link, create_document_from_link_and_ask_question, list_created_documents, delete_created_document, get_created_document_details

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

# def removeAllUsersFromConversation():
#     conn = create_connection("{}/users.db".format(users_dir))
#     cur = conn.cursor()
#     cur.execute("DELETE FROM UserToConversationId")
#     conn.commit()
#     conn.close()
#
# removeAllUsersFromConversation()
if __name__=="__main__":
    cleanup_tokens()
    port = 443
   # app.run(host="0.0.0.0", port=port,threaded=True, ssl_context=('cert-ext.pem', 'key-ext.pem'))
    app.run(host="0.0.0.0", port=5000,threaded=True) # ssl_context="adhoc"

