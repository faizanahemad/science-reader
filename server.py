import tempfile
from functools import wraps
import ast
import traceback
from flask import Flask, render_template, request, jsonify, send_file, session, redirect, url_for, render_template_string, Response
from flask_cors import CORS, cross_origin
from common import COMMON_SALT_STRING, USE_OPENAI_API
from transcribe_audio import transcribe_audio as run_transcribe_audio

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


def delete_table(conn, table_name):
    """ delete a table from the database """
    try:
        c = conn.cursor()
        c.execute(f"DROP TABLE IF EXISTS {table_name}")
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
    
    # ConversationId to WorkspaceId
    sql_create_conversation_id_to_workspace_id_table = """CREATE TABLE IF NOT EXISTS ConversationIdToWorkspaceId (
                                    conversation_id text PRIMARY KEY,
                                    user_email text,
                                    workspace_id text,
                                    created_at text,
                                    updated_at text
                                ); """
    
    # workspace metadata table
    sql_create_workspace_metadata_table = """CREATE TABLE IF NOT EXISTS WorkspaceMetadata (
                                    workspace_id text PRIMARY KEY,
                                    workspace_name text,
                                    workspace_color text,
                                    domain text,
                                    expanded boolean,
                                    created_at text,
                                    updated_at text
                                ); """
    
    # doubts clearing table
    sql_create_doubts_clearing_table = """CREATE TABLE IF NOT EXISTS DoubtsClearing (
                                    doubt_id text PRIMARY KEY,
                                    conversation_id text,
                                    user_email text,
                                    message_id text,
                                    doubt_text text,
                                    doubt_answer text,
                                    parent_doubt_id text,
                                    is_root_doubt boolean DEFAULT 1,
                                    created_at text,
                                    updated_at text,
                                    FOREIGN KEY (parent_doubt_id) REFERENCES DoubtsClearing (doubt_id)
                                ); """
    
    # section hidden details table
    sql_create_section_hidden_details_table = """CREATE TABLE IF NOT EXISTS SectionHiddenDetails (
                                    conversation_id text,
                                    section_id text,
                                    hidden boolean DEFAULT 0,
                                    created_at text,
                                    updated_at text,
                                    PRIMARY KEY (conversation_id, section_id)
                                ); """
    
    conn = create_connection(database)
    # delete_table(conn, "ConversationIdToWorkspaceId")
    # delete_table(conn, "WorkspaceMetadata")

    
    
    # create tables
    if conn is not None:
        # create UserToVotes table
        create_table(conn, sql_create_user_to_conversation_id_table)
        # create UserDetails table
        create_table(conn, sql_create_user_details_table)
        # create ConversationIdToWorkspaceId table
        create_table(conn, sql_create_conversation_id_to_workspace_id_table)
        # create WorkspaceMetadata table
        create_table(conn, sql_create_workspace_metadata_table)
        # create DoubtsClearing table
        create_table(conn, sql_create_doubts_clearing_table)
        # create SectionHiddenDetails table
        create_table(conn, sql_create_section_hidden_details_table)
    else:
        print("Error! cannot create the database connection.")
        
    cur = conn.cursor()
    cur.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_UserToConversationId_email_doc ON UserToConversationId (user_email, conversation_id)")
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_ConversationIdToWorkspaceId_conversation_id ON ConversationIdToWorkspaceId (conversation_id)")
    # create index on workspace_id
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ConversationIdToWorkspaceId_workspace_id ON ConversationIdToWorkspaceId (workspace_id)")
    # create index on domain
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ConversationIdToWorkspaceId_user_email ON ConversationIdToWorkspaceId (user_email)")

    cur.execute("CREATE INDEX IF NOT EXISTS idx_WorkspaceMetadata_workspace_id ON WorkspaceMetadata (workspace_id)")

    # Add child_doubt_id column if it doesn't exist (for bidirectional pointers)
    try:
        cur.execute("ALTER TABLE DoubtsClearing ADD COLUMN child_doubt_id text")
        logger.info("Added child_doubt_id column to DoubtsClearing table")
    except Exception as e:
        # Column already exists or other error - this is fine
        pass

    # create indexes for DoubtsClearing table
    cur.execute("CREATE INDEX IF NOT EXISTS idx_DoubtsClearing_conversation_id ON DoubtsClearing (conversation_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_DoubtsClearing_user_email ON DoubtsClearing (user_email)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_DoubtsClearing_message_id ON DoubtsClearing (message_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_DoubtsClearing_conv_msg ON DoubtsClearing (conversation_id, message_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_DoubtsClearing_parent_doubt_id ON DoubtsClearing (parent_doubt_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_DoubtsClearing_child_doubt_id ON DoubtsClearing (child_doubt_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_DoubtsClearing_is_root ON DoubtsClearing (is_root_doubt)")
    
    # create indexes for SectionHiddenDetails table
    cur.execute("CREATE INDEX IF NOT EXISTS idx_SectionHiddenDetails_conversation_id ON SectionHiddenDetails (conversation_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_SectionHiddenDetails_section_id ON SectionHiddenDetails (section_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_SectionHiddenDetails_hidden ON SectionHiddenDetails (hidden)")
    
    cur.execute("CREATE INDEX IF NOT EXISTS idx_User_email_doc_conversation ON UserToConversationId (user_email)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_UserDetails_email ON UserDetails (user_email)")
    conn.commit()
    conn.close()  # Close the database connection
        
        
from datetime import datetime

def load_workspaces_for_user(user_email, domain):
    """
    Retrieve all unique workspaces for a user, including workspace name and color,
    using a single database query with a join.
    Ensures a default workspace exists and is included in the results.

    Args:
        user_email (str): The user's email address.
        domain (str): The domain to filter workspaces by.

    Returns:
        list of dict: Each dict contains workspace_id, workspace_name, workspace_color, and domain.
    """
    conn = create_connection("{}/users.db".format(users_dir))
    cur = conn.cursor()
    
    # Use a single query to get unique workspace_ids for the user, with workspace name and color
    cur.execute("""
        SELECT DISTINCT c.workspace_id, 
                        wm.workspace_name, 
                        wm.workspace_color, 
                        wm.domain,
                        wm.expanded
        FROM ConversationIdToWorkspaceId c
        LEFT JOIN WorkspaceMetadata wm ON c.workspace_id = wm.workspace_id
        WHERE c.user_email = ? AND c.workspace_id IS NOT NULL AND wm.domain = ?
    """, (user_email, domain))
    rows = cur.fetchall()
    
    # Convert to list of dicts for easier manipulation
    workspaces = [
        {
            "workspace_id": row[0],
            "workspace_name": row[1],
            "workspace_color": row[2],
            "domain": row[3],
            "expanded": row[4]
        }
        for row in rows
    ]
    
    # Check if default workspace exists
    default_workspace_id = f'default_{user_email}_{domain}'
    default_workspace_name = f'default_{user_email}_{domain}'
    
    has_default = any(ws["workspace_id"] == default_workspace_id for ws in workspaces)
    
    if not has_default:
        now = datetime.now()
        
        # Insert into WorkspaceMetadata (if not exists)
        cur.execute("""
            INSERT OR IGNORE INTO WorkspaceMetadata
            (workspace_id, workspace_name, workspace_color, domain, expanded, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (default_workspace_id, default_workspace_name, None, domain, True, now, now))
        
        # Insert into ConversationIdToWorkspaceId for the workspace itself (no conversation_id)
        cur.execute("""
            INSERT OR IGNORE INTO ConversationIdToWorkspaceId
            (conversation_id, user_email, workspace_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
        """, (None, user_email, default_workspace_id, now, now))
        
        conn.commit()
        
        # Add default workspace to the results
        workspaces.append({
            "workspace_id": default_workspace_id,
            "workspace_name": default_workspace_name,
            "workspace_color": None,
            "domain": domain,
            "expanded": True
        })
    
    conn.close()
    return workspaces

def addConversationToWorkspace(user_email, conversation_id, workspace_id):
    conn = create_connection("{}/users.db".format(users_dir))
    cur = conn.cursor()
    cur.execute(
        """
        INSERT OR IGNORE INTO ConversationIdToWorkspaceId
        (conversation_id, user_email, workspace_id, created_at, updated_at)
        VALUES(?,?,?,?)
        """,
        (conversation_id, user_email, workspace_id, datetime.now(), datetime.now())
    )
    conn.commit()
    conn.close()

def moveConversationToWorkspace(user_email, conversation_id, workspace_id):
    conn = create_connection("{}/users.db".format(users_dir))
    cur = conn.cursor()
    cur.execute("UPDATE ConversationIdToWorkspaceId SET workspace_id=? WHERE user_email=? AND conversation_id=?", (workspace_id, user_email, conversation_id,))
    conn.commit()
    conn.close()

def removeConversationFromWorkspace(user_email, conversation_id):
    conn = create_connection("{}/users.db".format(users_dir))
    cur = conn.cursor()
    cur.execute("DELETE FROM ConversationIdToWorkspaceId WHERE user_email=? AND conversation_id=?", (user_email, conversation_id,))
    conn.commit()
    conn.close()

def getWorkspaceForConversation(conversation_id):
    """
    Retrieve the workspace metadata associated with a given conversation_id.

    Args:
        conversation_id (str): The conversation ID.

    Returns:
        dict or None: Dictionary containing workspace and its metadata, or None if not found.
    """
    conn = create_connection("{}/users.db".format(users_dir))
    try:
        cur = conn.cursor()
        # Get the workspace_id and user_email for the conversation
        cur.execute(
            "SELECT workspace_id, user_email FROM ConversationIdToWorkspaceId WHERE conversation_id=?",
            (conversation_id,)
        )
        row = cur.fetchone()
        if not row or not row[0]:
            return None  # No workspace associated

        workspace_id, user_email = row

        # Get the workspace metadata
        cur.execute(
            """
            SELECT workspace_id, workspace_name, workspace_color, domain, expanded, created_at, updated_at
            FROM WorkspaceMetadata
            WHERE workspace_id=?
            """,
            (workspace_id,)
        )
        meta_row = cur.fetchone()
        if not meta_row:
            # If metadata not found, return minimal info
            return {
                "workspace_id": workspace_id,
                "user_email": user_email
            }

        return {
            "workspace_id": meta_row[0],
            "workspace_name": meta_row[1],
            "workspace_color": meta_row[2],
            "domain": meta_row[3],
            "expanded": meta_row[4],
            "created_at": meta_row[5],
            "updated_at": meta_row[6],
            "user_email": user_email
        }
    finally:
        conn.close()

def getConversationsForWorkspace(workspace_id, user_email):
    conn = create_connection("{}/users.db".format(users_dir))
    cur = conn.cursor()
    cur.execute("SELECT * FROM ConversationIdToWorkspaceId WHERE workspace_id=? AND user_email=?", (workspace_id, user_email,))
    rows = cur.fetchall()
    conn.close()
    return rows

def createWorkspace(user_email, workspace_id, domain, workspace_name, workspace_color):
    """
    Create a new workspace for a user.
    This function inserts a workspace record into both ConversationIdToWorkspaceId (for user-workspace mapping)
    and WorkspaceMetadata (for workspace metadata), ensuring both are created atomically.

    Args:
        user_email (str): The user's email address.
        workspace_id (str): The unique workspace ID.
        domain (str): The domain for the workspace.
        workspace_name (str): The name of the workspace.
        workspace_color (str): The color for the workspace.
    """
    conn = create_connection("{}/users.db".format(users_dir))
    try:
        cur = conn.cursor()
        now = datetime.now()

        # Insert into WorkspaceMetadata (if not exists)
        cur.execute("""
            INSERT OR IGNORE INTO WorkspaceMetadata
            (workspace_id, workspace_name, workspace_color, domain, expanded, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (workspace_id, workspace_name, workspace_color, domain, True, now, now))

        # Insert into ConversationIdToWorkspaceId for the workspace itself (no conversation_id)
        cur.execute("""
            INSERT INTO ConversationIdToWorkspaceId
            (conversation_id, user_email, workspace_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
        """, (None, user_email, workspace_id, now, now))

        conn.commit()
    finally:
        conn.close()

def add_doubt(conversation_id, user_email, message_id, doubt_text, doubt_answer, parent_doubt_id=None):
    """
    Add a new doubt clearing record.
    
    Args:
        conversation_id (str): The conversation ID
        user_email (str): The user's email address
        message_id (str): The message ID
        doubt_text (str): The user's doubt/question
        doubt_answer (str): The AI's answer to the doubt
        parent_doubt_id (str, optional): Parent doubt ID for follow-ups
        
    Returns:
        str: The generated doubt_id
    """
    import hashlib
    import uuid
    
    conn = create_connection("{}/users.db".format(users_dir))
    try:
        cur = conn.cursor()
        now = datetime.now().isoformat()
        
        # Generate doubt_id as hash of conversation_id + message_id + doubt_text + doubt_answer + timestamp + parent_id
        doubt_content = f"{conversation_id}_{message_id}_{doubt_text}_{doubt_answer}_{now}_{parent_doubt_id or ''}"
        doubt_id = hashlib.md5(doubt_content.encode()).hexdigest()
        
        # Determine if this is a root doubt
        is_root_doubt = parent_doubt_id is None
        
        # Insert new doubt record
        cur.execute("""
            INSERT INTO DoubtsClearing
            (doubt_id, conversation_id, user_email, message_id, doubt_text, doubt_answer, 
             parent_doubt_id, is_root_doubt, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (doubt_id, conversation_id, user_email, message_id, doubt_text, doubt_answer, 
              parent_doubt_id, is_root_doubt, now, now))
        
        # If this doubt has a parent, update the parent's child_doubt_id to point to this doubt
        if parent_doubt_id:
            cur.execute("""
                UPDATE DoubtsClearing 
                SET child_doubt_id = ?, updated_at = ?
                WHERE doubt_id = ?
            """, (doubt_id, now, parent_doubt_id))
        
        conn.commit()
        
        doubt_type = "root doubt" if is_root_doubt else f"follow-up to {parent_doubt_id}"
        logger.info(f"Added {doubt_type} with ID {doubt_id} for conversation {conversation_id}, message {message_id}")
        
        return doubt_id
        
    except Exception as e:
        logger.error(f"Error adding doubt clearing: {str(e)}")
        raise e
    finally:
        conn.close()

def delete_doubt(doubt_id):
    """
    Delete a doubt clearing record by doubt_id with tree restructuring.
    When deleting a node, attach its children to its parent (linked list style deletion).
    
    Args:
        doubt_id (str): The doubt ID
        
    Returns:
        bool: True if a record was deleted, False if no record was found
    """
    conn = create_connection("{}/users.db".format(users_dir))
    try:
        cur = conn.cursor()
        
        # First, get the doubt to be deleted and its parent
        cur.execute("""
            SELECT parent_doubt_id FROM DoubtsClearing 
            WHERE doubt_id = ?
        """, (doubt_id,))
        
        row = cur.fetchone()
        if not row:
            logger.warning(f"No doubt clearing found with ID {doubt_id}")
            return False
            
        parent_doubt_id = row[0]
        
        # Get all children of the doubt to be deleted
        cur.execute("""
            SELECT doubt_id FROM DoubtsClearing 
            WHERE parent_doubt_id = ?
        """, (doubt_id,))
        
        children = cur.fetchall()
        child_doubt_ids = [child[0] for child in children]
        
        # Update all children to point to the parent of the deleted doubt
        # This effectively removes the deleted doubt from the chain
        for child_doubt_id in child_doubt_ids:
            cur.execute("""
                UPDATE DoubtsClearing 
                SET parent_doubt_id = ?, is_root_doubt = ?
                WHERE doubt_id = ?
            """, (parent_doubt_id, parent_doubt_id is None, child_doubt_id))
        
        # Now delete the original doubt
        cur.execute("""
            DELETE FROM DoubtsClearing 
            WHERE doubt_id = ?
        """, (doubt_id,))
        
        deleted_count = cur.rowcount
        conn.commit()
        
        if deleted_count > 0:
            logger.info(f"Deleted doubt clearing with ID {doubt_id} and restructured {len(child_doubt_ids)} children")
            return True
        else:
            logger.warning(f"Failed to delete doubt clearing with ID {doubt_id}")
            return False
            
    except Exception as e:
        logger.error(f"Error deleting doubt clearing: {str(e)}")
        raise e
    finally:
        conn.close()

def get_doubt(doubt_id):
    """
    Retrieve a doubt clearing record by doubt_id.
    
    Args:
        doubt_id (str): The doubt ID
        
    Returns:
        dict or None: Dictionary containing doubt clearing data, or None if not found
    """
    conn = create_connection("{}/users.db".format(users_dir))
    try:
        cur = conn.cursor()
        
        # Get the doubt clearing record
        cur.execute("""
            SELECT doubt_id, conversation_id, user_email, message_id, doubt_text, doubt_answer, 
                   parent_doubt_id, is_root_doubt, created_at, updated_at
            FROM DoubtsClearing 
            WHERE doubt_id = ?
        """, (doubt_id,))
        
        row = cur.fetchone()
        
        if row:
            return {
                "doubt_id": row[0],
                "conversation_id": row[1],
                "user_email": row[2],
                "message_id": row[3],
                "doubt_text": row[4],
                "doubt_answer": row[5],
                "parent_doubt_id": row[6],
                "is_root_doubt": bool(row[7]),
                "created_at": row[8],
                "updated_at": row[9]
            }
        else:
            return None
            
    except Exception as e:
        logger.error(f"Error getting doubt clearing: {str(e)}")
        raise e
    finally:
        conn.close()

def get_doubts_for_message(conversation_id, message_id, user_email=None):
    """
    Retrieve all doubt clearing records for a specific message in hierarchical structure.
    
    Args:
        conversation_id (str): The conversation ID
        message_id (str): The message ID
        user_email (str, optional): Filter by user email
        
    Returns:
        list: List of root doubt trees with nested children
    """
    conn = create_connection("{}/users.db".format(users_dir))
    try:
        cur = conn.cursor()
        
        # First, get only root doubts (is_root_doubt = 1)
        if user_email:
            cur.execute("""
                SELECT doubt_id, conversation_id, user_email, message_id, doubt_text, doubt_answer, 
                       parent_doubt_id, is_root_doubt, created_at, updated_at
                FROM DoubtsClearing 
                WHERE conversation_id = ? AND message_id = ? AND user_email = ? AND is_root_doubt = 1
                ORDER BY created_at DESC
            """, (conversation_id, message_id, user_email))
        else:
            cur.execute("""
                SELECT doubt_id, conversation_id, user_email, message_id, doubt_text, doubt_answer, 
                       parent_doubt_id, is_root_doubt, created_at, updated_at
                FROM DoubtsClearing 
                WHERE conversation_id = ? AND message_id = ? AND is_root_doubt = 1
                ORDER BY created_at DESC
            """, (conversation_id, message_id))
        
        rows = cur.fetchall()
        
        root_doubts = [
            {
                "doubt_id": row[0],
                "conversation_id": row[1],
                "user_email": row[2],
                "message_id": row[3],
                "doubt_text": row[4],
                "doubt_answer": row[5],
                "parent_doubt_id": row[6],
                "is_root_doubt": bool(row[7]),
                "created_at": row[8],
                "updated_at": row[9]
            }
            for row in rows
        ]
        
        # Build tree structure for each root doubt
        doubt_trees = []
        for root_doubt in root_doubts:
            doubt_tree = build_doubt_tree(root_doubt)
            doubt_trees.append(doubt_tree)
        
        return doubt_trees
            
    except Exception as e:
        logger.error(f"Error getting doubts for message: {str(e)}")
        raise e
    finally:
        conn.close()

def get_doubt_history(doubt_id):
    """
    Get the complete history of a doubt thread from root to the specified doubt.
    
    Args:
        doubt_id (str): The doubt ID to trace back from
        
    Returns:
        list: List of doubt records from root to current, ordered chronologically
    """
    conn = create_connection("{}/users.db".format(users_dir))
    try:
        cur = conn.cursor()
        
        # Traverse up the tree to find all parent doubts
        doubt_chain = []
        current_doubt_id = doubt_id
        
        while current_doubt_id:
            cur.execute("""
                SELECT doubt_id, conversation_id, user_email, message_id, doubt_text, doubt_answer, 
                       parent_doubt_id, is_root_doubt, created_at, updated_at
                FROM DoubtsClearing 
                WHERE doubt_id = ?
            """, (current_doubt_id,))
            
            row = cur.fetchone()
            if not row:
                break
                
            doubt_record = {
                "doubt_id": row[0],
                "conversation_id": row[1],
                "user_email": row[2],
                "message_id": row[3],
                "doubt_text": row[4],
                "doubt_answer": row[5],
                "parent_doubt_id": row[6],
                "is_root_doubt": bool(row[7]),
                "created_at": row[8],
                "updated_at": row[9]
            }
            
            doubt_chain.append(doubt_record)
            current_doubt_id = row[6]  # parent_doubt_id
        
        # Reverse to get chronological order (root first)
        doubt_chain.reverse()
        return doubt_chain
            
    except Exception as e:
        logger.error(f"Error getting doubt history: {str(e)}")
        raise e
    finally:
        conn.close()

def get_doubt_children(doubt_id):
    """
    Get all direct children of a doubt.
    
    Args:
        doubt_id (str): The parent doubt ID
        
    Returns:
        list: List of child doubt records
    """
    conn = create_connection("{}/users.db".format(users_dir))
    try:
        cur = conn.cursor()
        
        cur.execute("""
            SELECT doubt_id, conversation_id, user_email, message_id, doubt_text, doubt_answer, 
                   parent_doubt_id, is_root_doubt, created_at, updated_at
            FROM DoubtsClearing 
            WHERE parent_doubt_id = ?
            ORDER BY created_at ASC
        """, (doubt_id,))
        
        rows = cur.fetchall()
        
        return [
            {
                "doubt_id": row[0],
                "conversation_id": row[1],
                "user_email": row[2],
                "message_id": row[3],
                "doubt_text": row[4],
                "doubt_answer": row[5],
                "parent_doubt_id": row[6],
                "is_root_doubt": bool(row[7]),
                "created_at": row[8],
                "updated_at": row[9]
            }
            for row in rows
        ]
            
    except Exception as e:
        logger.error(f"Error getting doubt children: {str(e)}")
        raise e
    finally:
        conn.close()

def build_doubt_tree(doubt_record):
    """
    Recursively build a tree structure for a doubt and all its descendants.
    
    Args:
        doubt_record (dict): The root doubt record
        
    Returns:
        dict: Doubt record with 'children' array containing nested structure
    """
    doubt_tree = doubt_record.copy()
    children = get_doubt_children(doubt_record["doubt_id"])
    
    doubt_tree["children"] = []
    for child in children:
        child_tree = build_doubt_tree(child)
        doubt_tree["children"].append(child_tree)
    
    return doubt_tree


def get_section_hidden_details(conversation_id, section_ids):
    """
    Retrieve hidden details for multiple sections in a conversation.
    
    Args:
        conversation_id (str): The conversation ID
        section_ids (list): List of section IDs to retrieve details for
        
    Returns:
        dict: Dictionary mapping section_id to hidden status
    """
    if not section_ids:
        return {}
        
    conn = create_connection("{}/users.db".format(users_dir))
    try:
        cur = conn.cursor()
        
        # Build placeholder string for IN clause
        placeholders = ','.join('?' * len(section_ids))
        
        # Query for all requested sections
        query = f"""
            SELECT section_id, hidden, created_at, updated_at
            FROM SectionHiddenDetails 
            WHERE conversation_id = ? AND section_id IN ({placeholders})
        """
        
        # Prepare parameters: conversation_id + all section_ids
        params = [conversation_id] + section_ids
        
        cur.execute(query, params)
        rows = cur.fetchall()
        
        # Build result dictionary
        section_details = {}
        for row in rows:
            section_details[row[0]] = {
                "hidden": bool(row[1]),
                "created_at": row[2],
                "updated_at": row[3]
            }
        
        # For sections not found in database, default to not hidden
        for section_id in section_ids:
            if section_id not in section_details:
                section_details[section_id] = {
                    "hidden": False,
                    "created_at": None,
                    "updated_at": None
                }
        
        logger.info(f"Retrieved hidden details for {len(section_ids)} sections in conversation {conversation_id}")
        
        return section_details
        
    except Exception as e:
        logger.error(f"Error getting section hidden details: {str(e)}")
        raise e
    finally:
        conn.close()


def bulk_update_section_hidden_detail(conversation_id, section_updates):
    """
    Bulk update or create section hidden details for multiple sections.
    
    Args:
        conversation_id (str): The conversation ID
        section_updates (dict): Dictionary mapping section_id to hidden status (bool)
        
    Returns:
        None
    """
    if not section_updates:
        return
        
    conn = create_connection("{}/users.db".format(users_dir))
    try:
        cur = conn.cursor()
        now = datetime.now().isoformat()
        
        # Process each section update
        for section_id, hidden_state in section_updates.items():
            # Use INSERT OR REPLACE to handle both new and existing records
            cur.execute("""
                INSERT OR REPLACE INTO SectionHiddenDetails
                (conversation_id, section_id, hidden, created_at, updated_at)
                VALUES (
                    ?,  -- conversation_id
                    ?,  -- section_id  
                    ?,  -- hidden
                    COALESCE((SELECT created_at FROM SectionHiddenDetails 
                              WHERE conversation_id = ? AND section_id = ?), ?),  -- preserve created_at if exists
                    ?   -- updated_at (always new)
                )
            """, (
                conversation_id,
                section_id,
                hidden_state,
                conversation_id,
                section_id,
                now,  # default created_at if new record
                now   # updated_at
            ))
        
        conn.commit()
        
        logger.info(f"Bulk updated {len(section_updates)} section hidden details for conversation {conversation_id}")
        
    except Exception as e:
        logger.error(f"Error in bulk updating section hidden details: {str(e)}")
        conn.rollback()
        raise e
    finally:
        conn.close()


def collapseWorkspaces(workspace_ids: list[str]):
    """
    Collapse (set expanded=0) for all workspaces whose IDs are in the provided list.
    """
    if not workspace_ids:
        return  # Nothing to do

    conn = create_connection("{}/users.db".format(users_dir))
    try:
        cur = conn.cursor()
        # Create the correct number of placeholders for the IN clause
        placeholders = ','.join(['?'] * len(workspace_ids))
        sql = f"UPDATE WorkspaceMetadata SET expanded=0 WHERE workspace_id IN ({placeholders})"
        cur.execute(sql, tuple(workspace_ids))
        conn.commit()
    finally:
        conn.close()

def updateWorkspace(user_email, workspace_id, workspace_name=None, workspace_color=None, expanded=None):
    """
    Update the name and/or color of a workspace in the WorkspaceMetadata table.

    Args:
        user_email (str): The email of the user performing the update (for auditing or future use).
        workspace_id (str): The unique ID of the workspace to update.
        workspace_name (str, optional): The new name for the workspace.
        workspace_color (str, optional): The new color for the workspace.

    Raises:
        ValueError: If neither workspace_name nor workspace_color is provided.
    """
    if workspace_name is None and workspace_color is None and expanded is None:
        raise ValueError("At least one of workspace_name or workspace_color or expanded must be provided.")

    conn = create_connection("{}/users.db".format(users_dir))
    try:
        cur = conn.cursor()
        fields = []
        values = []
        now = datetime.now()

        if workspace_name is not None:
            fields.append("workspace_name=?")
            values.append(workspace_name)
        if workspace_color is not None:
            fields.append("workspace_color=?")
            values.append(workspace_color)
        if expanded is not None:
            fields.append("expanded=?")
            values.append(expanded)
        fields.append("updated_at=?")
        values.append(now)
        values.append(workspace_id)

        sql = f"UPDATE WorkspaceMetadata SET {', '.join(fields)} WHERE workspace_id=?"
        cur.execute(sql, values)
        conn.commit()
    finally:
        conn.close()

def deleteWorkspace(workspace_id, user_email, domain):
    """
    Deletes a workspace for a user.
    All conversations in the workspace are moved to the user's default workspace before deletion.
    Removes the workspace from both ConversationIdToWorkspaceId and WorkspaceMetadata tables.
    Assumes that each user has a default workspace with id 'default' and name 'default'.
    """
    conn = create_connection("{}/users.db".format(users_dir))
    try:
        cur = conn.cursor()

        # Fetch all conversations in the workspace to be deleted
        cur.execute(
            "SELECT conversation_id FROM ConversationIdToWorkspaceId WHERE workspace_id=? AND user_email=?",
            (workspace_id, user_email)
        )
        conversations = cur.fetchall()

        # Ensure the default workspace exists for the user
        default_workspace_id = f'default_{user_email}_{domain}'
        default_workspace_name = f'default_{user_email}_{domain}'
        cur.execute(
            "SELECT 1 FROM ConversationIdToWorkspaceId WHERE workspace_id=? AND user_email=? LIMIT 1",
            (default_workspace_id, user_email)
        )
        if not cur.fetchone():
            # Create a default workspace entry for the user if it doesn't exist
            cur.execute(
                """
                INSERT INTO ConversationIdToWorkspaceId
                (conversation_id, user_email, workspace_id, domain, workspace_name, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    None,  # No conversation_id for the workspace itself
                    user_email,
                    default_workspace_id,
                    None,  # domain unknown here
                    default_workspace_name,
                    datetime.now(),
                    datetime.now()
                )
            )
            # Also ensure WorkspaceMetadata exists for the default workspace
            cur.execute(
                """
                INSERT OR IGNORE INTO WorkspaceMetadata
                (workspace_id, workspace_name, workspace_color, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    default_workspace_id,
                    default_workspace_name,
                    None,
                    datetime.now(),
                    datetime.now()
                )
            )

        # Move all conversations to the default workspace
        for row in conversations:
            conversation_id = row[0]
            if conversation_id is not None:
                cur.execute(
                    """
                    UPDATE ConversationIdToWorkspaceId
                    SET workspace_id=?, workspace_name=?, updated_at=?
                    WHERE conversation_id=? AND user_email=?
                    """,
                    (
                        default_workspace_id,
                        default_workspace_name,
                        datetime.now(),
                        conversation_id,
                        user_email
                    )
                )

        # Delete the workspace from ConversationIdToWorkspaceId (all rows with this workspace_id and user_email)
        cur.execute(
            "DELETE FROM ConversationIdToWorkspaceId WHERE workspace_id=? AND user_email=?",
            (workspace_id, user_email)
        )

        # Delete the workspace from WorkspaceMetadata (if no other user is using it)
        # If you want to delete the workspace metadata only if no other user is using it:
        cur.execute(
            "SELECT 1 FROM ConversationIdToWorkspaceId WHERE workspace_id=? LIMIT 1",
            (workspace_id,)
        )
        if not cur.fetchone():
            cur.execute(
                "DELETE FROM WorkspaceMetadata WHERE workspace_id=?",
                (workspace_id,)
            )

        conn.commit()
    finally:
        conn.close()
    
def addConversation(user_email, conversation_id, workspace_id=None, domain=None):
    """
    Adds a conversation for a user, associating it with a workspace and domain.
    Inserts into both UserToConversationId and ConversationIdToWorkspaceId in a single transaction.
    If workspace_id is None, assigns to the default workspace.

    Args:
        user_email (str): The user's email.
        conversation_id (str): The conversation ID.
        workspace_id (str, optional): The workspace ID. Defaults to 'default' if None.
        domain (str, optional): The domain for the conversation.
    Returns:
        bool: True if successful, False otherwise.
    """
    # Requirements:
    # - If workspace_id is None, use 'default' for both ID and name.
    # - If workspace_id is provided, fetch the workspace_name for this workspace_id from the DB.
    # - Never insert None as workspace_name.

    DEFAULT_WORKSPACE_ID = f'default_{user_email}_{domain}'
    DEFAULT_WORKSPACE_NAME = f'default_{user_email}_{domain}'
    now = datetime.now()

    # Use default workspace if not provided
    workspace_id_to_use = workspace_id if workspace_id is not None else DEFAULT_WORKSPACE_ID

    conn = create_connection("{}/users.db".format(users_dir))
    if conn is None:
        logger.error("Failed to connect to database when adding conversation")
        return False

    try:
        cur = conn.cursor()

        

        # Insert into UserToConversationId
        cur.execute(
            """
            INSERT OR IGNORE INTO UserToConversationId
            (user_email, conversation_id, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (user_email, conversation_id, now, now)
        )
        # Insert into ConversationIdToWorkspaceId
        cur.execute(
            """
            INSERT OR IGNORE INTO ConversationIdToWorkspaceId
            (conversation_id, user_email, workspace_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                conversation_id,
                user_email,
                workspace_id_to_use,
                now,
                now
            )
        )
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error adding conversation for user {user_email}: {e}")
        return False
    finally:
        conn.close()



def checkConversationExists(user_email: str, conversation_id: str):
    conn = create_connection("{}/users.db".format(users_dir))
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM UserToConversationId WHERE user_email=? AND conversation_id=?", (user_email, conversation_id,))
    exists = cur.fetchone() is not None
    conn.close()
    return exists

def getCoversationsForUser(user_email: str, domain: str):
    """
    Fetch all conversations for a user, along with their associated workspace info.

    Returns:
        List of tuples: (user_email, conversation_id, created_at, updated_at, workspace_id, workspace_name, workspace_color)
    """
    conn = create_connection("{}/users.db".format(users_dir))
    cur = conn.cursor()
    # Join UserToConversationId with ConversationIdToWorkspaceId and WorkspaceMetadata to get workspace info
    cur.execute("""
        SELECT 
            uc.user_email, 
            uc.conversation_id, 
            uc.created_at, 
            uc.updated_at,
            cw.workspace_id,
            wm.workspace_name,
            wm.workspace_color
        FROM UserToConversationId uc
        LEFT JOIN ConversationIdToWorkspaceId cw
            ON uc.conversation_id = cw.conversation_id AND uc.user_email = cw.user_email
        LEFT JOIN WorkspaceMetadata wm
            ON cw.workspace_id = wm.workspace_id
        WHERE uc.user_email=?
    """, (user_email,))
    rows = cur.fetchall()

    # Find all conversation_ids where workspace_id is None
    conversation_ids_to_update = [row[1] for row in rows if row[4] is None]
    if conversation_ids_to_update:
        # Perform one UPDATE for all relevant conversation_ids in ConversationIdToWorkspaceId
        placeholders = ','.join(['?'] * len(conversation_ids_to_update))
        cur.execute(
            f"UPDATE ConversationIdToWorkspaceId SET workspace_id=? WHERE conversation_id IN ({placeholders})",
            [f'default_{user_email}_{domain}'] + conversation_ids_to_update
        )
        # Also update WorkspaceMetadata for the default workspace if not already present
        # Check if default workspace exists
        cur.execute("SELECT 1 FROM WorkspaceMetadata WHERE workspace_id=? AND domain=?", (f'default_{user_email}_{domain}', domain))
        if not cur.fetchone():
            from datetime import datetime
            now = datetime.now()
            cur.execute(
                "INSERT INTO WorkspaceMetadata (workspace_id, workspace_name, workspace_color, domain, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (f'default_{user_email}_{domain}', f'default_{user_email}_{domain}', None, domain, now, now)
            )
        conn.commit()
        # Update the in-memory rows as well
        updated_rows = []
        for row in rows:
            row = list(row)
            if row[4] is None:
                row[4] = f'default_{user_email}_{domain}'
                row[5] = f'default_{user_email}_{domain}'
                row[6] = None  # workspace_color unknown for default
            updated_rows.append(tuple(row))
        rows = updated_rows
    conn.close()
    return rows

def deleteConversationForUser(user_email, conversation_id):
    """
    Deletes a conversation for a user from both UserToConversationId and ConversationIdToWorkspaceId tables.

    Args:
        user_email (str): The user's email address.
        conversation_id (str): The conversation ID to delete.
    """
    conn = create_connection("{}/users.db".format(users_dir))
    try:
        cur = conn.cursor()
        # Remove from UserToConversationId
        cur.execute(
            "DELETE FROM UserToConversationId WHERE user_email=? AND conversation_id=?",
            (user_email, conversation_id,)
        )
        # Remove from ConversationIdToWorkspaceId
        cur.execute(
            "DELETE FROM ConversationIdToWorkspaceId WHERE user_email=? AND conversation_id=?",
            (user_email, conversation_id,)
        )
        conn.commit()
    finally:
        conn.close()


def cleanup_deleted_conversations(conversation_ids):
    """Clean up database entries for deleted stateless conversations"""
    if not conversation_ids:
        return
        
    conn = create_connection("{}/users.db".format(users_dir))
    if conn is None:
        logger.error("Error! cannot create the database connection for cleanup.")
        return
        
    try:
        cur = conn.cursor()
        placeholders = ','.join(['?' for _ in conversation_ids])
        
        # Delete from tables in proper order (respecting foreign key constraints)
        cur.execute(f"DELETE FROM SectionHiddenDetails WHERE conversation_id IN ({placeholders})", conversation_ids)
        cur.execute(f"DELETE FROM DoubtsClearing WHERE conversation_id IN ({placeholders})", conversation_ids)
        cur.execute(f"DELETE FROM ConversationIdToWorkspaceId WHERE conversation_id IN ({placeholders})", conversation_ids)
        cur.execute(f"DELETE FROM UserToConversationId WHERE conversation_id IN ({placeholders})", conversation_ids)
        
        # Note: WorkspaceMetadata doesn't have conversation_id column based on schema
        # Note: UserDetails is keyed by user_email, not conversation_id, so shouldn't be deleted here
        
        conn.commit()
        logger.info(f"Cleaned up database entries for {len(conversation_ids)} deleted conversations")
    except Exception as e:
        logger.error(f"Error cleaning up deleted conversations: {e}")
        conn.rollback()
    finally:
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
        locks_dir = os.path.join(folder, "locks")
        os.makedirs(cache_dir, exist_ok=True)
        os.makedirs(users_dir, exist_ok=True)
        os.makedirs(pdfs_dir, exist_ok=True)
        os.makedirs(locks_dir, exist_ok=True)
        # clear the locks directory
        for file in os.listdir(locks_dir):
            os.remove(os.path.join(locks_dir, file))
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
    conversation: Conversation = Conversation.load_local(path)
    conversation.clear_lockfile("")
    conversation.clear_lockfile("all")
    conversation.clear_lockfile("message_operations")
    conversation.clear_lockfile("memory")
    conversation.clear_lockfile("messages")
    conversation.clear_lockfile("uploaded_documents_list")
    return conversation

conversation_cache = DefaultDictQueue(maxsize=200, default_factory=load_conversation)
    
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



@app.route('/clear_locks')
@limiter.limit("100 per minute")
@login_required
def clear_locks():
    # clear the locks directory
    for file in os.listdir(locks_dir):
        os.remove(os.path.join(locks_dir, file))
    return jsonify({'result': 'locks cleared'})


@app.route('/interface', strict_slashes=False)
@limiter.limit("200 per minute")
@login_required
def interface():
    return send_from_directory('interface', 'interface.html', max_age=0)

@app.route('/static/<path:filename>')
@limiter.limit("1000 per minute")
def static_files(filename):
    return send_from_directory(os.path.join(app.root_path, 'static'), filename)


@app.route('/interface/<path:path>', strict_slashes=False)  
@limiter.limit("1000 per minute")  
def interface_combined(path):
    # Check login status  
    email, name, loggedin = check_login(session)  

    # custom path logic
    if not loggedin or email is None:
        return redirect('/login', code=302)

    # Handle empty path (edge case)
    if not path or path == '':
        return send_from_directory('interface', 'interface.html', max_age=0)
    
    
    if email is not None and path.startswith(email) and path.count('/') >= 2:
        path = '/'.join(path.split('/')[1:])
    

    # First, handle potential conversation IDs  
    if loggedin:  
        try:  
            # Get user's conversations  
            conversation_id = path.split('/')[0]
            if checkConversationExists(email, conversation_id):
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
            if os.path.dirname(__file__).strip() != "":
                root_dir = os.path.dirname(__file__) + "/"
                file_dir = file_dir.replace(root_dir, "")
            return send_from_directory(file_dir, file_name)
        elif doc:
            return redirect(doc.doc_source)
        else:
            return jsonify({'error': 'Document not found'}), 404
    else:
        return jsonify({'error': 'Conversation not found'}), 404

def cached_get_file(file_url):
    """
    Retrieve a file from cache, disk, or remote URL and stream it as chunks.
    
    This function always returns PDF content. If the requested file is not a PDF,
    it will be converted to PDF first using the convert_any_to_pdf utility.
    
    Args:
        file_url (str): Path to a local file or URL to a remote file.
        
    Yields:
        bytes: Chunks of file data.
        
    Note:
        - Files are cached after first access for faster subsequent retrievals.
        - Non-PDF files are automatically converted to PDF before serving.
        - The cache key is based on the original file_url, not the converted PDF path.
    """
    from converters import convert_any_to_pdf
    
    chunk_size = 1024  # Define your chunk size
    file_data = cache.get(file_url)

    # If the file is not in the cache, read it from disk and save it to the cache
    if file_data is not None:
        logger.info(f"cached_get_file for {file_url} found in cache")
        for chunk in file_data:
            yield chunk
        # how do I chunk with chunk size?

    elif os.path.exists(file_url):
        # Convert to PDF if not already a PDF (UI can only render PDFs)
        try:
            pdf_file_url = convert_any_to_pdf(file_url)
            logger.info(f"cached_get_file: serving PDF file {pdf_file_url} (original: {file_url})")
        except Exception as e:
            logger.error(f"cached_get_file: failed to convert {file_url} to PDF: {e}")
            # Fallback to original file if conversion fails
            pdf_file_url = file_url
        
        file_data = []
        with open(pdf_file_url, 'rb') as f:
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



@app.route('/cancel_response/<conversation_id>', methods=['POST'])
@limiter.limit("100 per minute")
@login_required
def cancel_response(conversation_id):
    """Cancel an ongoing streaming response"""
    from base import cancellation_requests
    email, name, loggedin = check_login(session)
    
    if not checkConversationExists(email, conversation_id):
        return jsonify({"message": "Conversation not found"}), 404
    
    # Set cancellation flag
    cancellation_requests[conversation_id] = {
        'cancelled': True, 
        'timestamp': time.time()
    }
    
    logger.info(f"Cancellation requested for conversation {conversation_id} by user {email}")
    return jsonify({"message": "Cancellation requested successfully"}), 200



# Optional: Add cleanup route to remove old cancellation requests
@app.route('/cleanup_cancellations', methods=['POST'])
def cleanup_cancellations():
    """Remove old cancellation requests (older than 1 hour)"""
    from base import cancellation_requests
    current_time = time.time()
    to_remove = []
    
    for conv_id, data in cancellation_requests.items():
        if current_time - data.get('timestamp', 0) > 3600:  # 1 hour
            to_remove.append(conv_id)
    
    for conv_id in to_remove:
        del cancellation_requests[conv_id]
    
    return jsonify({"message": f"Cleaned up {len(to_remove)} old cancellation requests"}), 200

@app.route('/cancel_coding_hint/<conversation_id>', methods=['POST'])
@limiter.limit("100 per minute")
@login_required
def cancel_coding_hint(conversation_id):
    """Cancel an ongoing coding hint generation"""
    email, name, loggedin = check_login(session)
    
    if not checkConversationExists(email, conversation_id):
        return jsonify({"message": "Conversation not found"}), 404
    
    # Import here to avoid circular imports
    from base import coding_hint_cancellation_requests
    
    # Set cancellation flag
    coding_hint_cancellation_requests[conversation_id] = {
        'cancelled': True, 
        'timestamp': time.time()
    }
    
    logger.info(f"Coding hint cancellation requested for conversation {conversation_id} by user {email}")
    return jsonify({"message": "Coding hint cancellation requested successfully"}), 200

@app.route('/cancel_coding_solution/<conversation_id>', methods=['POST'])
@limiter.limit("100 per minute")
@login_required
def cancel_coding_solution(conversation_id):
    """Cancel an ongoing coding solution generation"""
    email, name, loggedin = check_login(session)
    
    if not checkConversationExists(email, conversation_id):
        return jsonify({"message": "Conversation not found"}), 404
    
    # Import here to avoid circular imports
    from base import coding_solution_cancellation_requests
    
    # Set cancellation flag
    coding_solution_cancellation_requests[conversation_id] = {
        'cancelled': True, 
        'timestamp': time.time()
    }
    
    logger.info(f"Coding solution cancellation requested for conversation {conversation_id} by user {email}")
    return jsonify({"message": "Coding solution cancellation requested successfully"}), 200

@app.route('/cancel_doubt_clearing/<conversation_id>', methods=['POST'])
@limiter.limit("100 per minute")
@login_required
def cancel_doubt_clearing(conversation_id):
    """Cancel an ongoing doubt clearing"""
    email, name, loggedin = check_login(session)
    
    if not checkConversationExists(email, conversation_id):
        return jsonify({"message": "Conversation not found"}), 404
    
    # Import here to avoid circular imports
    from base import doubt_cancellation_requests
    
    # Set cancellation flag
    doubt_cancellation_requests[conversation_id] = {
        'cancelled': True, 
        'timestamp': time.time()
    }
    
    logger.info(f"Doubt clearing cancellation requested for conversation {conversation_id} by user {email}")
    return jsonify({"message": "Doubt clearing cancellation requested successfully"}), 200


@app.route('/set_flag/<conversation_id>/<flag>', methods=['POST'])
@limiter.limit("100 per minute")
@login_required
def set_flag(conversation_id, flag):
    email, name, loggedin = check_login(session)
    if not checkConversationExists(email, conversation_id):
        return jsonify({"message": "Conversation not found"}), 404
    else:
        conversation = conversation_cache[conversation_id]
    if conversation is None:
        return jsonify({"message": "Conversation not found"}), 404
    # Define valid colors for conversation flags
    valid_colors = ["red", "blue", "green", "yellow", "orange", "purple", "pink", "cyan", "magenta", "lime", "indigo", "teal", "brown", "gray", "black", "white"]
    
    # Handle "none" as a special case to clear the flag
    if flag is not None and flag.strip().lower() == "none":
        conversation.flag = None
        return jsonify({"message": "Flag cleared successfully"}), 200
    
    assert flag is not None and len(flag.strip()) > 0 and flag.strip().lower() in valid_colors
    conversation.flag = flag.strip().lower()
    return jsonify({"message": "Flag set successfully"}), 200

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
    conv_db = getCoversationsForUser(email, domain)
    conversation_ids = [c[1] for c in conv_db]
    conversations = [conversation_cache[conversation_id] for conversation_id in conversation_ids]
    conversation_id_to_workspace_id = {c[1]: {"workspace_id": c[4], "workspace_name": c[5]} for c in conv_db if c[4] is not None}
    
    stateless_conversations = [conversation for conversation in conversations if conversation is not None and conversation.stateless]
    stateless_conversation_ids = [conversation.conversation_id for conversation in stateless_conversations]
    for conversation in stateless_conversations:
        removeUserFromConversation(email, conversation.conversation_id)
        del conversation_cache[conversation.conversation_id]
        deleteConversationForUser(email, conversation.conversation_id)
        conversation.delete_conversation()

    none_conversation_ids = []
    for conversation_id, conversation in zip(conversation_ids, conversations):
        if conversation is None:
            removeUserFromConversation(email, conversation_id)
            del conversation_cache[conversation_id]
            deleteConversationForUser(email, conversation_id)
            none_conversation_ids.append(conversation_id)

    # Clean up database entries for deleted none conversations
    cleanup_deleted_conversations(none_conversation_ids + stateless_conversation_ids)

    conversations = [conversation for conversation in conversations if conversation is not None and conversation.domain==domain] #  and not conversation.stateless
    conversations = [set_keys_on_docs(conversation, keys) for conversation in conversations]
    data = [[conversation.get_metadata(), conversation] for conversation in conversations]
    for metadata, conversation in data:
        assert conversation.conversation_id in conversation_id_to_workspace_id, f"Conversation {conversation.conversation_id} not found in conversation_id_to_workspace_id"
        metadata["workspace_id"] = conversation_id_to_workspace_id[conversation.conversation_id]["workspace_id"]
        metadata["workspace_name"] = conversation_id_to_workspace_id[conversation.conversation_id]["workspace_name"]
        metadata["domain"] = conversation.domain
    sorted_data_reverse = sorted(data, key=lambda x: x[0]['last_updated'], reverse=True)
    # TODO: if any conversation has 0 messages then just make it the latest. IT should also have a zero length summary.

    if len(sorted_data_reverse) > 0 and len(sorted_data_reverse[0][0]["summary_till_now"].strip()) > 0:
        sorted_data_reverse = sorted(sorted_data_reverse, key=lambda x: len(x[0]['summary_till_now'].strip()), reverse=False)
        if sorted_data_reverse[0][0]["summary_till_now"].strip() == "" and len(sorted_data_reverse[0][1].get_message_list()) == 0:
            new_conversation = sorted_data_reverse[0][1]
            sorted_data_reverse = sorted_data_reverse[1:]
            sorted_data_reverse = sorted(sorted_data_reverse, key=lambda x: x[0]['last_updated'], reverse=True)
            # new_conversation.set_field("memory", {"last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
        else:
            new_conversation = create_conversation_simple(session, domain)
        sorted_data_reverse.insert(0, [new_conversation.get_metadata(), new_conversation])
    if len(sorted_data_reverse) == 0:
        new_conversation = create_conversation_simple(session, domain)
        sorted_data_reverse.insert(0, [new_conversation.get_metadata(), new_conversation])
    sorted_metadata_reverse = [sd[0] for sd in sorted_data_reverse]
    return jsonify(sorted_metadata_reverse)

@app.route('/create_conversation/<domain>/', defaults={'workspace_id': None}, methods=['POST'])
@app.route('/create_conversation/<domain>/<workspace_id>', methods=['POST'])
@limiter.limit("500 per minute")
@login_required
def create_conversation(domain: str, workspace_id: str = None):
    domain = domain.strip().lower()
    conversation = create_conversation_simple(session, domain, workspace_id)
    data = conversation.get_metadata()
    data['workspace'] = getWorkspaceForConversation(conversation.conversation_id)
    return jsonify(data)

@app.route('/create_workspace/<domain>/<workspace_name>', methods=['POST'])
@limiter.limit("500 per minute")
@login_required
def create_workspace(domain: str, workspace_name: str):
    email, name, loggedin = check_login(session)
    
    # Get color from request body if provided, default to 'primary'
    workspace_color = 'primary'
    if request.is_json and request.json and 'workspace_color' in request.json:
        workspace_color = request.json['workspace_color']
    
    workspace_id = email + "_" + ''.join(secrets.choice(alphabet) for i in range(16))
    createWorkspace(email, workspace_id, domain, workspace_name, workspace_color)  # Now includes color
    return jsonify({
        "workspace_id": workspace_id, 
        "workspace_name": workspace_name,
        "workspace_color": workspace_color
    })

@app.route('/list_workspaces/<domain>', methods=['GET'])
@limiter.limit("200 per minute")
@login_required
def list_workspaces(domain):
    """
    Returns a list of workspaces for the given domain that the current user has access to.
    """
    email, name, loggedin = check_login(session)
    if not loggedin:
        return jsonify({"error": "User not logged in"}), 401

    # Load all workspaces for the user
    all_workspaces = load_workspaces_for_user(email, domain)
    
    return jsonify(all_workspaces)

@app.route('/update_workspace/<workspace_id>', methods=['PUT'])
@limiter.limit("500 per minute")
@login_required
def update_workspace(workspace_id):
    email, name, loggedin = check_login(session)
    workspace_name = request.json.get('workspace_name', None)
    workspace_color = request.json.get('workspace_color', None)
    expanded = request.json.get('expanded', None)
    if workspace_name is None and workspace_color is None and expanded is None:
        return jsonify({"error": "At least one of workspace_name or workspace_color or expanded must be provided."}), 400
    updateWorkspace(email, workspace_id, workspace_name, workspace_color, expanded)
    return jsonify({"message": "Workspace updated successfully"})

@app.route('/collapse_workspaces', methods=['POST'])
@limiter.limit("500 per minute")
@login_required
def collapse_workspaces():
    email, name, loggedin = check_login(session)
    workspace_ids = request.json.get('workspace_ids', [])
    collapseWorkspaces(workspace_ids)
    return jsonify({"message": "Workspaces collapsed successfully"})




@app.route('/delete_workspace/<domain>/<workspace_id>', methods=['DELETE'])
@limiter.limit("500 per minute")
@login_required
def delete_workspace(domain, workspace_id):
    """
    Deletes a workspace for the current user.
    All conversations in the workspace are moved to the user's default workspace before deletion.
    """
    email, name, loggedin = check_login(session)
    if not loggedin:
        return jsonify({"error": "User not logged in"}), 401

    try:
        deleteWorkspace(workspace_id, email, domain)
        return jsonify({"message": "Workspace deleted and conversations moved to default workspace."}), 200
    except Exception as e:
        logger.error(f"Error deleting workspace {workspace_id} for user {email}: {e}")
        return jsonify({"error": "Failed to delete workspace."}), 500

@app.route('/move_conversation_to_workspace/<conversation_id>', methods=['PUT'])
@limiter.limit("500 per minute")
@login_required
def move_conversation_to_workspace(conversation_id):
    """
    Moves a conversation to a different workspace for the current user.
    Expects JSON body: { "workspace_id": "<target_workspace_id>" }
    """
    email, name, loggedin = check_login(session)
    if not loggedin:
        return jsonify({"error": "User not logged in"}), 401

    data = request.get_json()
    if not data or "workspace_id" not in data:
        return jsonify({"error": "workspace_id is required in the request body."}), 400

    target_workspace_id = data["workspace_id"]

    try:
        moveConversationToWorkspace(email, conversation_id, target_workspace_id)
        return jsonify({"message": f"Conversation {conversation_id} moved to workspace {target_workspace_id}."}), 200
    except Exception as e:
        logger.error(f"Error moving conversation {conversation_id} for user {email} to workspace {target_workspace_id}: {e}")
        return jsonify({"error": "Failed to move conversation to workspace."}), 500

def create_conversation_simple(session, domain: str, workspace_id: str = None):
    email, name, loggedin = check_login(session)
    keys = keyParser(session)
    from base import get_embedding_model
    # str(mmh3.hash(email, signed=False))
    conversation_id = email + "_" + ''.join(secrets.choice(alphabet) for i in range(36))
    conversation = Conversation(email, openai_embed=get_embedding_model(keys), storage=conversation_folder,
                                conversation_id=conversation_id, domain=domain)
    conversation = set_keys_on_docs(conversation, keys)
    addConversation(email, conversation.conversation_id, workspace_id, domain)
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
    if not checkConversationExists(email, conversation_id):
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

@app.route('/get_conversation_history/<conversation_id>', methods=['GET'])
@limiter.limit("100 per minute")
@login_required
def get_conversation_history(conversation_id):
    """Get comprehensive conversation history including summary and recent messages"""
    try:
        # Check if user has access to this conversation
        user_email = session.get('email')
        keys = keyParser(session)
        if not checkConversationExists(user_email, conversation_id):
            logger.warning(f"User {user_email} attempted to access conversation {conversation_id} without permission")
            return jsonify({"error": "Conversation not found or access denied"}), 403
        
        # Load conversation
        conversation = load_conversation(conversation_id)
        
        # Get query parameter if provided
        query = request.args.get('query', '')
        
        # Generate conversation history
        history_text = conversation.get_conversation_history(query)
        
        logger.info(f"Generated conversation history for conversation {conversation_id}, length: {len(history_text)} characters")
        
        return jsonify({
            "conversation_id": conversation_id,
            "history": history_text,
            "timestamp": time.time()
        })

    except Exception as e:
        logger.error(f"Error getting conversation history for {conversation_id}: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/get_coding_hint/<conversation_id>', methods=['POST'])
@limiter.limit("20 per minute")
@login_required  
def get_coding_hint_endpoint(conversation_id):
    """Get a coding hint based on current context and code - streaming response"""
    keys = keyParser(session)
    try:
        # Check if user has access to this conversation
        user_email = session.get('email')
        if not checkConversationExists(user_email, conversation_id):
            logger.warning(f"User {user_email} attempted to access conversation {conversation_id} without permission")
            return jsonify({"error": "Conversation not found or access denied"}), 403
        
        # Get request data
        data = request.get_json()
        current_code = data.get('current_code', '')
        context_text = data.get('context', '')
        
        # Load conversation and get history
        conversation = load_conversation(conversation_id)
        conversation_history = conversation.get_conversation_history()
        
        # Import the function from base.py
        from base import get_coding_hint
        
        def generate_hint_stream():
            try:
                # Send initial status
                yield json.dumps({
                    "text": "",
                    "status": "Analyzing your code and generating hint...",
                    "conversation_id": conversation_id,
                    "type": "hint"
                }) + '\n'
                
                # Generate hint with streaming
                hint_generator = get_coding_hint(context_text, conversation_history, current_code, keys, stream=True, conversation_id=conversation_id)
                
                accumulated_text = ""
                for chunk in hint_generator:
                    if chunk:
                        accumulated_text += chunk
                        yield json.dumps({
                            "text": chunk,
                            "status": "Generating hint...",
                            "conversation_id": conversation_id,
                            "type": "hint",
                            "accumulated_text": accumulated_text
                        }) + '\n'
                
                # Final status
                yield json.dumps({
                    "text": "",
                    "status": "Hint generated successfully!",
                    "conversation_id": conversation_id,
                    "type": "hint",
                    "completed": True,
                    "accumulated_text": accumulated_text
                }) + '\n'
                
                logger.info(f"Generated streaming coding hint for conversation {conversation_id}, code length: {len(current_code)} chars")
                
            except Exception as e:
                logger.error(f"Error in hint streaming for {conversation_id}: {str(e)}")
                yield json.dumps({
                    "text": "",
                    "status": f"Error: {str(e)}",
                    "conversation_id": conversation_id,
                    "type": "hint",
                    "error": True
                }) + '\n'
        
        return Response(generate_hint_stream(), content_type='text/plain')

    except Exception as e:
        logger.error(f"Error getting coding hint for {conversation_id}: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/get_full_solution/<conversation_id>', methods=['POST'])
@limiter.limit("10 per minute")  # Lower limit for full solutions
@login_required
def get_full_solution_endpoint(conversation_id):
    """Get a complete solution based on current context and code - streaming response"""
    keys = keyParser(session)
    try:
        # Check if user has access to this conversation
        user_email = session.get('email')
        if not checkConversationExists(user_email, conversation_id):
            logger.warning(f"User {user_email} attempted to access conversation {conversation_id} without permission")
            return jsonify({"error": "Conversation not found or access denied"}), 403
        
        # Get request data
        data = request.get_json()
        current_code = data.get('current_code', '')
        context_text = data.get('context', '')
        
        # Load conversation and get history
        conversation = load_conversation(conversation_id)
        conversation_history = conversation.get_conversation_history()
        
        # Import the function from base.py
        from base import get_full_solution_code
        
        def generate_solution_stream():
            try:
                # Send initial status
                yield json.dumps({
                    "text": "",
                    "status": "Analyzing problem and generating complete solution...",
                    "conversation_id": conversation_id,
                    "type": "solution"
                }) + '\n'
                
                # Generate solution with streaming
                solution_generator = get_full_solution_code(context_text, conversation_history, current_code, keys, stream=True, conversation_id=conversation_id)
                
                accumulated_text = ""
                for chunk in solution_generator:
                    if chunk:
                        accumulated_text += chunk
                        yield json.dumps({
                            "text": chunk,
                            "status": "Generating complete solution...",
                            "conversation_id": conversation_id,
                            "type": "solution",
                            "accumulated_text": accumulated_text
                        }) + '\n'
                
                # Final status
                yield json.dumps({
                    "text": "",
                    "status": "Complete solution generated successfully!",
                    "conversation_id": conversation_id,
                    "type": "solution",
                    "completed": True,
                    "accumulated_text": accumulated_text
                }) + '\n'
                
                logger.info(f"Generated streaming full solution for conversation {conversation_id}, code length: {len(current_code)} chars")
                
            except Exception as e:
                logger.error(f"Error in solution streaming for {conversation_id}: {str(e)}")
                yield json.dumps({
                    "text": "",
                    "status": f"Error: {str(e)}",
                    "conversation_id": conversation_id,
                    "type": "solution",
                    "error": True
                }) + '\n'
        
        return Response(generate_solution_stream(), content_type='text/plain')

    except Exception as e:
        logger.error(f"Error getting full solution for {conversation_id}: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/send_message/<conversation_id>', methods=['POST'])
@limiter.limit("50 per minute")
@login_required
def send_message(conversation_id):
    keys = keyParser(session)
    email, name, loggedin = check_login(session)
    # check if the user has a user_details row
    user_details = getUserFromUserDetailsTable(email)
    
    if not checkConversationExists(email, conversation_id):
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
        conversation.clear_cancellation()

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
    """
    Returns conversation metadata along with full workspace information for the given conversation_id.
    """

    keys = keyParser(session)
    email, name, loggedin = check_login(session)

    if not checkConversationExists(email, conversation_id):
        return jsonify({"message": "Conversation not found"}), 404

    # Get conversation object and set keys
    conversation = conversation_cache[conversation_id]
    conversation = set_keys_on_docs(conversation, keys)

    # Get conversation metadata
    data = conversation.get_metadata()

    # Get workspace info for this conversation, including full metadata
    workspace_info = getWorkspaceForConversation(conversation_id)

    if not workspace_info:
        # If not found, default to None or a default workspace
        workspace_info = {
            "workspace_id": None
        }

    # Add workspace info to the response
    data['workspace'] = workspace_info

    return jsonify(data)

@app.route('/make_conversation_stateless/<conversation_id>', methods=['DELETE'])
@limiter.limit("25 per minute")
@login_required
def make_conversation_stateless(conversation_id):
    email, name, loggedin = check_login(session)
    keys = keyParser(session)
    if not checkConversationExists(email, conversation_id):
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
    if not checkConversationExists(email, conversation_id):
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
    message_text = request.json.get('text')
    if not checkConversationExists(email, conversation_id):
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
    message_ids = request.json.get('message_ids')
    assert isinstance(message_ids, list)
    assert all(isinstance(m, str) for m in message_ids)
    direction = request.json.get('direction')
    assert direction in ["up", "down"]
    if not checkConversationExists(email, conversation_id):
        return jsonify({"message": "Conversation not found"}), 404
    else:
        conversation = conversation_cache[conversation_id]
        conversation = set_keys_on_docs(conversation, keys)
    conversation.move_messages_up_or_down(message_ids, direction)
    return jsonify({'message': f'Messages {message_ids} moved {direction}'})


# Lets write a route to get the next question suggestions
@app.route('/get_next_question_suggestions/<conversation_id>', methods=['GET'])
@limiter.limit("30 per minute")
@login_required
def get_next_question_suggestions(conversation_id):
    email, name, loggedin = check_login(session)
    keys = keyParser(session)
    if not checkConversationExists(email, conversation_id):
        return jsonify({"message": "Conversation not found"}), 404
    else:
        conversation = conversation_cache[conversation_id]
        conversation = set_keys_on_docs(conversation, keys)
    
    # Get the next question suggestions from the conversation object
    suggestions = conversation.get_next_question_suggestions()
    
    # Return the suggestions as JSON
    return jsonify({'suggestions': suggestions})


# Lets write API to clear a doubt, it takes conversation_id and message_id, then uses conversation.clear_doubt(message_id), this function call streams text content.
@app.route('/clear_doubt/<conversation_id>/<message_id>', methods=['POST'])
@limiter.limit("30 per minute")
@login_required
def clear_doubt(conversation_id, message_id):
    """Clear a doubt for a specific message - streaming response"""
    email, name, loggedin = check_login(session)
    keys = keyParser(session)
    doubt_text = request.json.get('doubt_text')
    parent_doubt_id = request.json.get('parent_doubt_id')  # For follow-up questions
    reward_level = int(request.json.get('reward_level', 0))  # Reward level for gamification
    
    try:
        # Check if user has access to this conversation
        if not checkConversationExists(email, conversation_id):
            logger.warning(f"User {email} attempted to access conversation {conversation_id} without permission")
            return jsonify({"error": "Conversation not found or access denied"}), 404
        
        # Load conversation and set keys
        conversation = conversation_cache[conversation_id]
        conversation = set_keys_on_docs(conversation, keys)
        
        def generate_doubt_clearing_stream():
            accumulated_doubt_answer = ""
            try:
                # Send initial status
                yield json.dumps({
                    "text": "",
                    "status": "Analyzing message and clearing doubt...",
                    "conversation_id": conversation_id,
                    "message_id": message_id,
                    "type": "doubt_clearing"
                }) + '\n'
                
                # Get doubt history if this is a follow-up
                doubt_history = []
                if parent_doubt_id:
                    try:
                        doubt_history = get_doubt_history(parent_doubt_id)
                        logger.info(f"Retrieved doubt history with {len(doubt_history)} entries for follow-up")
                    except Exception as history_error:
                        logger.error(f"Error retrieving doubt history: {str(history_error)}")
                        # Continue without history rather than failing
                
                # Generate doubt clearing with streaming
                doubt_generator = conversation.clear_doubt(message_id, doubt_text, doubt_history, reward_level)
                
                accumulated_text = ""
                doubt_id = None
                
                try:
                    for chunk in doubt_generator:
                        if chunk:
                            accumulated_text += chunk
                            accumulated_doubt_answer += chunk
                            yield json.dumps({
                                "text": chunk,
                                "status": "Clearing doubt...",
                                "conversation_id": conversation_id,
                                "message_id": message_id,
                                "type": "doubt_clearing",
                                "accumulated_text": accumulated_text
                            }) + '\n'
                
                finally:
                    # Always save doubt and answer to database/storage, even if cancelled
                    if accumulated_doubt_answer.strip():  # Only save if we have some content
                        try:
                            # Save to DoubtsClearing table and get doubt_id
                            doubt_id = add_doubt(
                                conversation_id=conversation_id,
                                user_email=email,
                                message_id=message_id,
                                doubt_text=doubt_text or "Please explain this message in more detail.",
                                doubt_answer=accumulated_doubt_answer,
                                parent_doubt_id=parent_doubt_id
                            )
                            logger.info(f"Doubt clearing data saved successfully with ID {doubt_id}: {len(accumulated_doubt_answer)} characters")
                            
                        except Exception as save_error:
                            logger.error(f"Error saving doubt clearing data: {str(save_error)}")
                            doubt_id = None
                
                # Final status with doubt_id
                final_text = f"<doubt_id>{doubt_id}</doubt_id>" if doubt_id else ""
                yield json.dumps({
                    "text": final_text,
                    "status": "Doubt cleared successfully!",
                    "conversation_id": conversation_id,
                    "message_id": message_id,
                    "type": "doubt_clearing",
                    "completed": True,
                    "accumulated_text": accumulated_text,
                    "doubt_id": doubt_id
                }) + '\n'
                
                logger.info(f"Generated streaming doubt clearing for conversation {conversation_id}, message {message_id}")
                
            except Exception as e:
                logger.error(f"Error in doubt clearing streaming for {conversation_id}, message {message_id}: {str(e)}")
                yield json.dumps({
                    "text": "",
                    "status": f"Error: {str(e)}",
                    "conversation_id": conversation_id,
                    "message_id": message_id,
                    "type": "doubt_clearing",
                    "error": True
                }) + '\n'
        
        return Response(generate_doubt_clearing_stream(), content_type='text/plain')

    except Exception as e:
        logger.error(f"Error clearing doubt for {conversation_id}, message {message_id}: {str(e)}")
        return jsonify({"error": str(e)}), 500


# Temporary LLM action endpoint - ephemeral, no database storage
@app.route('/temporary_llm_action', methods=['POST'])
@limiter.limit("30 per minute")
@login_required
def temporary_llm_action():
    """
    Execute an ephemeral LLM action without database persistence.
    
    This endpoint handles context menu actions like:
    - explain: Explain the selected text
    - critique: Provide critical analysis
    - expand: Expand on the selected text
    - eli5: Explain like I'm 5 with intuition
    - ask_temp: Temporary chat conversation
    
    Unlike clear_doubt, this does NOT save anything to the database.
    """
    email, name, loggedin = check_login(session)
    keys = keyParser(session)
    
    try:
        data = request.json
        action_type = data.get('action_type', 'explain')
        selected_text = data.get('selected_text', '')
        user_message = data.get('user_message', '')
        message_id = data.get('message_id')
        message_text = data.get('message_text', '')
        conversation_id = data.get('conversation_id')
        history = data.get('history', [])  # Previous conversation history
        with_context = data.get('with_context', False)  # Whether to include conversation context
        
        logger.info(f"Temporary LLM action: {action_type} for user {email}, with_context: {with_context}")
        
        # Load conversation if available for context
        conversation = None
        if conversation_id and checkConversationExists(email, conversation_id):
            try:
                conversation = conversation_cache[conversation_id]
                conversation = set_keys_on_docs(conversation, keys)
            except Exception as e:
                logger.warning(f"Could not load conversation {conversation_id}: {e}")
                conversation = None
        
        def generate_temporary_llm_stream():
            try:
                # Send initial status
                status_msg = f"Processing {action_type}..."
                if with_context:
                    status_msg = f"Processing {action_type} with conversation context..."
                yield json.dumps({
                    "text": "",
                    "status": status_msg,
                    "type": "temporary_llm"
                }) + '\n'
                
                # Generate response using conversation method or direct LLM call
                if conversation:
                    response_generator = conversation.temporary_llm_action(
                        action_type=action_type,
                        selected_text=selected_text,
                        user_message=user_message,
                        message_context=message_text,
                        message_id=message_id,  # Pass message_id for context enrichment
                        history=history,
                        with_context=with_context  # Pass the context flag
                    )
                else:
                    # Fallback: Direct LLM call without conversation context
                    response_generator = direct_temporary_llm_action(
                        keys=keys,
                        action_type=action_type,
                        selected_text=selected_text,
                        user_message=user_message,
                        history=history
                    )
                
                accumulated_text = ""
                
                for chunk in response_generator:
                    if chunk:
                        accumulated_text += chunk
                        yield json.dumps({
                            "text": chunk,
                            "status": f"Processing {action_type}...",
                            "type": "temporary_llm"
                        }) + '\n'
                
                # Final status
                yield json.dumps({
                    "text": "",
                    "status": "Complete!",
                    "type": "temporary_llm",
                    "completed": True
                }) + '\n'
                
                logger.info(f"Completed temporary LLM action: {action_type}")
                
            except Exception as e:
                logger.error(f"Error in temporary LLM streaming: {str(e)}")
                yield json.dumps({
                    "text": "",
                    "status": f"Error: {str(e)}",
                    "type": "temporary_llm",
                    "error": True
                }) + '\n'
        
        return Response(generate_temporary_llm_stream(), content_type='text/plain')
    
    except Exception as e:
        logger.error(f"Error in temporary LLM action: {str(e)}")
        return jsonify({"error": str(e)}), 500


def direct_temporary_llm_action(keys, action_type, selected_text, user_message="", history=None):
    """
    Direct LLM call for temporary actions when no conversation context is available.
    
    This is a fallback function that generates responses without conversation context.
    """
    from call_llm import CallLLm
    from common import EXPENSIVE_LLM
    
    # Build prompt based on action type
    prompts = {
        'explain': f"""You are an expert educator. Please explain the following text clearly and thoroughly.

**Text to explain:**
```
{selected_text}
```

Provide a clear, comprehensive explanation that:
1. Breaks down complex concepts
2. Uses simple language where possible
3. Provides examples or analogies when helpful
4. Highlights key points and their significance

Your explanation:""",

        'critique': f"""You are a critical analyst. Please provide a thoughtful critique of the following text.

**Text to critique:**
```
{selected_text}
```

Analyze this text by considering:
1. Strengths and weaknesses
2. Logical consistency
3. Missing information or gaps
4. Potential biases or assumptions
5. Areas for improvement

Your critique:""",

        'expand': f"""You are a knowledgeable expert. Please expand on the following text with more details and depth.

**Text to expand:**
```
{selected_text}
```

Provide an expanded version that:
1. Adds more context and background
2. Explores related concepts
3. Provides additional examples
4. Discusses implications and applications
5. Connects to broader topics

Your expanded explanation:""",

        'eli5': f"""You are explaining to a curious 5-year-old. Please explain the following text using simple words, fun analogies, and clear examples.

**Text to explain simply:**
```
{selected_text}
```

Rules for your explanation:
1. Use very simple words a child would understand
2. Use fun analogies (like toys, animals, or everyday things)
3. Be engaging and friendly
4. Break things into tiny, easy steps
5. Include a simple "the big idea is..." summary at the end

Your simple explanation:""",

        'ask_temp': f"""You are a helpful assistant having a conversation. The user has selected some text and wants to discuss it.

**Selected text for context:**
```
{selected_text}
```

**User's question/message:**
{user_message}

Please respond helpfully and conversationally:"""
    }
    
    # Handle conversation history for ask_temp
    if action_type == 'ask_temp' and history:
        history_text = "\n\n**Previous conversation:**\n"
        for msg in history:
            role = "User" if msg.get('role') == 'user' else "Assistant"
            history_text += f"{role}: {msg.get('content', '')}\n"
        prompts['ask_temp'] = prompts['ask_temp'].replace(
            "**User's question/message:**",
            history_text + "\n**User's latest question/message:**"
        )
    
    prompt = prompts.get(action_type, prompts['explain'])
    
    # Initialize LLM and generate response
    llm = CallLLm(keys, model_name=EXPENSIVE_LLM[2], use_gpt4=False, use_16k=False)
    
    response_stream = llm(
        prompt,
        images=[],
        temperature=0.4,
        stream=True,
        max_tokens=2000,
        system="You are a helpful, clear, and engaging assistant. Respond concisely but thoroughly."
    )
    
    for chunk in response_stream:
        if chunk:
            yield chunk


@app.route('/get_doubt/<doubt_id>', methods=['GET'])
@limiter.limit("100 per minute")
@login_required
def get_doubt_endpoint(doubt_id):
    """Get a specific doubt clearing record by doubt_id"""
    email, name, loggedin = check_login(session)
    
    try:
        # Get the doubt clearing record
        doubt_record = get_doubt(doubt_id)
        
        if doubt_record:
            # Check if user has access to this conversation
            if not checkConversationExists(email, doubt_record["conversation_id"]):
                logger.warning(f"User {email} attempted to access doubt {doubt_id} without permission")
                return jsonify({"error": "Access denied"}), 403
            
            return jsonify({
                "success": True,
                "doubt": doubt_record
            })
        else:
            return jsonify({
                "success": False,
                "message": "No doubt clearing found with this ID"
            }), 404
            
    except Exception as e:
        logger.error(f"Error getting doubt {doubt_id}: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/delete_doubt/<doubt_id>', methods=['DELETE'])
@limiter.limit("50 per minute")
@login_required
def delete_doubt_endpoint(doubt_id):
    """Delete a specific doubt clearing record by doubt_id"""
    email, name, loggedin = check_login(session)
    
    try:
        # First get the doubt to check access permissions
        doubt_record = get_doubt(doubt_id)
        
        if not doubt_record:
            return jsonify({
                "success": False,
                "message": "No doubt clearing found with this ID"
            }), 404
        
        # Check if user has access to this conversation
        if not checkConversationExists(email, doubt_record["conversation_id"]):
            logger.warning(f"User {email} attempted to delete doubt {doubt_id} without permission")
            return jsonify({"error": "Access denied"}), 403
        
        # Delete the doubt clearing record
        deleted = delete_doubt(doubt_id)
        
        if deleted:
            return jsonify({
                "success": True,
                "message": "Doubt clearing deleted successfully"
            })
        else:
            return jsonify({
                "success": False,
                "message": "Failed to delete doubt clearing"
            }), 500
            
    except Exception as e:
        logger.error(f"Error deleting doubt {doubt_id}: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/get_doubts/<conversation_id>/<message_id>', methods=['GET'])
@limiter.limit("100 per minute")
@login_required
def get_doubts_for_message_endpoint(conversation_id, message_id):
    """Get all doubt clearing records for a specific message"""
    email, name, loggedin = check_login(session)
    
    try:
        # Check if user has access to this conversation
        if not checkConversationExists(email, conversation_id):
            logger.warning(f"User {email} attempted to access conversation {conversation_id} without permission")
            return jsonify({"error": "Conversation not found or access denied"}), 404
        
        # Get all doubt clearing records for this message
        doubts = get_doubts_for_message(conversation_id, message_id, email)
        
        return jsonify({
            "success": True,
            "doubts": doubts,
            "count": len(doubts)
        })
            
    except Exception as e:
        logger.error(f"Error getting doubts for message {conversation_id}/{message_id}: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/show_hide_message_from_conversation/<conversation_id>/<message_id>/<index>', methods=['POST'])
@limiter.limit("30 per minute")
@login_required
def show_hide_message_from_conversation(conversation_id, message_id, index):
    email, name, loggedin = check_login(session)
    keys = keyParser(session)
    show_hide = request.json.get('show_hide')
    if not checkConversationExists(email, conversation_id):
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
    """
    Clone an existing conversation, preserving its workspace association.
    """
    email, name, loggedin = check_login(session)
    keys = keyParser(session)

    # Ensure the conversation exists in the cache
    if conversation_id not in conversation_cache:
        return jsonify({"message": "Conversation not found"}), 404

    conversation = conversation_cache[conversation_id]
    conversation = set_keys_on_docs(conversation, keys)

    # Clone the conversation
    new_conversation: Conversation = conversation.clone_conversation()
    new_conversation.save_local()

    # Retrieve the correct workspace_id for the original conversation
    workspace_info = getWorkspaceForConversation(conversation_id)
    workspace_id = workspace_info.get('workspace_id') if workspace_info else None

    # Add the new conversation with the correct workspace_id and domain
    addConversation(
        email,
        new_conversation.conversation_id,
        workspace_id=workspace_id,
        domain=conversation.domain
    )

    # Cache the new conversation
    conversation_cache[new_conversation.conversation_id] = new_conversation

    return jsonify({
        'message': f'Conversation {conversation_id} cloned',
        'conversation_id': new_conversation.conversation_id
    })

@app.route('/delete_conversation/<conversation_id>', methods=['DELETE'])
@limiter.limit("5000 per minute")
@login_required
def delete_conversation(conversation_id):
    email, name, loggedin = check_login(session)
    keys = keyParser(session)
    if not checkConversationExists(email, conversation_id):
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
    if not checkConversationExists(email, conversation_id):
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
    if not checkConversationExists(email, conversation_id):
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
    if not checkConversationExists(email, conversation_id):
        return jsonify({"message": "Conversation not found"}), 404
    else:
        conversation = conversation_cache[conversation_id]
        conversation = set_keys_on_docs(conversation, keys)
    memory_pad = request.json.get('text')
    conversation.set_memory_pad(memory_pad)
    return jsonify({'message': f'Memory pad set'})

@app.route('/fetch_memory_pad/<conversation_id>', methods=['GET'])
@limiter.limit("1000 per minute")
@login_required
def fetch_memory_pad(conversation_id):
    email, name, loggedin = check_login(session)
    keys = keyParser(session)
    if not checkConversationExists(email, conversation_id):
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

    if not checkConversationExists(email, conversation_id):
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
    if 'audio' not in request.files:
        return jsonify({"error": "No audio file provided"}), 400

    audio_file = request.files['audio']

    if audio_file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    try:
        transcription = run_transcribe_audio(audio_file)
        return jsonify({"transcription": transcription})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500



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


# Prompt Management API Routes

@app.route('/get_prompts', methods=['GET'])
@limiter.limit("100 per minute")
@login_required
def get_prompts():
    """
    Get a list of all available prompt names with metadata.
    
    Returns:
        JSON response with list of prompts and their metadata
    """
    try:
        from prompts import manager
        import datetime
        
        # Get all prompt names
        prompt_names = manager.keys()
        
        # Build detailed prompt list with metadata
        prompts_with_metadata = []
        for name in prompt_names:
            try:
                # Try to get metadata for each prompt
                prompt_metadata = manager.get_raw(name, as_dict=True)
                prompts_with_metadata.append({
                    'name': name,
                    'description': prompt_metadata.get('description', ''),
                    'category': prompt_metadata.get('category', ''),
                    'tags': prompt_metadata.get('tags', []),
                    'created_at': prompt_metadata.get('created_at', ''),
                    'updated_at': prompt_metadata.get('last_modified', datetime.datetime.now().isoformat()),
                    'version': prompt_metadata.get('version', '')
                })
            except:
                # If metadata fails, just include the name with current timestamp
                prompts_with_metadata.append({
                    'name': name,
                    'description': '',
                    'category': '',
                    'tags': [],
                    'created_at': '',
                    'updated_at': datetime.datetime.now().isoformat(),
                    'version': ''
                })
        
        return jsonify({
            'status': 'success',
            'prompts': prompt_names,  # Keep backward compatibility
            'prompts_detailed': prompts_with_metadata,
            'count': len(prompt_names)
        })
    except Exception as e:
        logger.error(f"Error getting prompts: {str(e)}")
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500


@app.route('/get_prompt_by_name/<prompt_name>', methods=['GET'])
@limiter.limit("100 per minute")
@login_required
def get_prompt_by_name(prompt_name):
    """
    Get the content of a specific prompt by name.
    
    Args:
        prompt_name: Name of the prompt to retrieve
        
    Returns:
        JSON response with prompt content and metadata
    """
    try:
        from prompts import manager
        
        # Check if prompt exists
        if prompt_name not in manager:
            return jsonify({
                'status': 'error',
                'error': f"Prompt '{prompt_name}' not found"
            }), 404
        
        # Get the composed prompt content
        prompt_content = manager[prompt_name]
        
        # Also get the raw prompt with metadata if available
        try:
            prompt_metadata = manager.get_raw(prompt_name, as_dict=True)
            
            return jsonify({
                'status': 'success',
                'name': prompt_name,
                'content': prompt_content,
                'raw_content': prompt_metadata.get('content', prompt_content),
                'metadata': {
                    'description': prompt_metadata.get('description', ''),
                    'category': prompt_metadata.get('category', ''),
                    'tags': prompt_metadata.get('tags', []),
                    'version': prompt_metadata.get('version', ''),
                    'created_at': prompt_metadata.get('created_at', ''),
                    'updated_at': prompt_metadata.get('updated_at', '')
                }
            })
        except:
            # If getting metadata fails, just return the content
            return jsonify({
                'status': 'success',
                'name': prompt_name,
                'content': prompt_content,
                'raw_content': prompt_content,
                'metadata': {}
            })
            
    except Exception as e:
        logger.error(f"Error getting prompt '{prompt_name}': {str(e)}")
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500


@app.route('/create_prompt', methods=['POST'])
@limiter.limit("20 per minute")
@login_required
def create_prompt():
    """
    Create a new prompt.
    
    Expected JSON payload:
    {
        "name": "prompt_name",
        "content": "prompt content",
        "description": "optional description",
        "category": "optional category",
        "tags": ["optional", "tags"]
    }
    
    Returns:
        JSON response with creation status
    """
    try:
        from prompts import manager, prompt_cache
        
        # Get request data
        data = request.json
        if not data:
            return jsonify({
                'status': 'error',
                'error': 'No data provided'
            }), 400
        
        # Validate required fields
        prompt_name = data.get('name')
        if not prompt_name:
            return jsonify({
                'status': 'error',
                'error': 'Prompt name is required'
            }), 400
        
        # Check if prompt already exists
        if prompt_name in manager:
            return jsonify({
                'status': 'error',
                'error': f"Prompt '{prompt_name}' already exists"
            }), 409
        
        # Get the content
        content = data.get('content', '')
        
        # Create the prompt using the dictionary interface
        manager[prompt_name] = content
        
        # Update cache
        prompt_cache[prompt_name] = content
        
        # If additional metadata is provided, update it using edit method
        if any(key in data for key in ['description', 'category', 'tags']):
            try:
                edit_kwargs = {}
                if 'description' in data:
                    edit_kwargs['description'] = data['description']
                if 'category' in data:
                    edit_kwargs['category'] = data['category']
                if 'tags' in data:
                    edit_kwargs['tags'] = data['tags']
                
                manager.edit(prompt_name, **edit_kwargs)
            except Exception as e:
                logger.warning(f"Could not update metadata for prompt '{prompt_name}': {str(e)}")
        
        return jsonify({
            'status': 'success',
            'message': f"Prompt '{prompt_name}' created successfully",
            'name': prompt_name,
            'content': content
        })
        
    except Exception as e:
        logger.error(f"Error creating prompt: {str(e)}")
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500


@app.route('/update_prompt', methods=['PUT'])
@limiter.limit("50 per minute")
@login_required
def update_prompt():
    """
    Update the content of an existing prompt.
    
    Expected JSON payload:
    {
        "name": "prompt_name",
        "content": "new prompt content",
        "description": "optional description",
        "category": "optional category",
        "tags": ["optional", "tags"]
    }
    
    Returns:
        JSON response with update status
    """
    try:
        from prompts import manager, prompt_cache
        
        # Get request data
        data = request.json
        if not data:
            return jsonify({
                'status': 'error',
                'error': 'No data provided'
            }), 400
        
        # Validate required fields
        prompt_name = data.get('name')
        if not prompt_name:
            return jsonify({
                'status': 'error',
                'error': 'Prompt name is required'
            }), 400
        
        # Check if prompt exists
        if prompt_name not in manager:
            return jsonify({
                'status': 'error',
                'error': f"Prompt '{prompt_name}' not found"
            }), 404
        
        # Get the new content
        new_content = data.get('content')
        if new_content is None:
            return jsonify({
                'status': 'error',
                'error': 'Content field is required for update'
            }), 400
        
        # Update the prompt using the dictionary interface
        manager[prompt_name] = new_content
        
        # Update cache
        prompt_cache[prompt_name] = new_content
        
        # If additional metadata is provided, update it using edit method
        if any(key in data for key in ['description', 'category', 'tags']):
            try:
                edit_kwargs = {}
                if 'description' in data:
                    edit_kwargs['description'] = data['description']
                if 'category' in data:
                    edit_kwargs['category'] = data['category']
                if 'tags' in data:
                    edit_kwargs['tags'] = data['tags']
                
                manager.edit(prompt_name, **edit_kwargs)
            except Exception as e:
                logger.warning(f"Could not update metadata for prompt '{prompt_name}': {str(e)}")
        
        return jsonify({
            'status': 'success',
            'message': f"Prompt '{prompt_name}' updated successfully",
            'name': prompt_name,
            'new_content': new_content
        })
        
    except Exception as e:
        logger.error(f"Error updating prompt: {str(e)}")
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500


@app.route('/get_section_hidden_details', methods=['GET'])
@limiter.limit("100 per minute")
@login_required
def get_section_hidden_details_endpoint():
    conversation_id = request.args.get('conversation_id')
    section_ids = request.args.get('section_ids')
    section_ids = section_ids.split(',')
    section_ids = [str(section_id) for section_id in section_ids]
    section_hidden_details = get_section_hidden_details(conversation_id, section_ids)
    return jsonify({"section_details": section_hidden_details})

@app.route('/update_section_hidden_details', methods=['POST'])
@limiter.limit("100 per minute")
@login_required
def update_section_hidden_details_endpoint():
    """
    Update or create section hidden details for multiple sections in bulk.
    
    Expected JSON payload:
    {
        "conversation_id": "conv_123",
        "section_details": {
            "section_1": {"hidden": true},
            "section_2": {"hidden": false},
            "section_3": {"hidden": true}
        }
    }
    
    Returns:
        JSON response with status and updated section details
    """
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({
                'status': 'error',
                'error': 'No JSON data provided'
            }), 400
        
        conversation_id = data.get('conversation_id')
        section_details = data.get('section_details', {})
        
        if not conversation_id:
            return jsonify({
                'status': 'error',
                'error': 'conversation_id is required'
            }), 400
        
        if not section_details:
            return jsonify({
                'status': 'error',
                'error': 'section_details is required and must be a non-empty dictionary'
            }), 400
        
        # Validate that section_details is a dictionary
        if not isinstance(section_details, dict):
            return jsonify({
                'status': 'error',
                'error': 'section_details must be a dictionary'
            }), 400
        
        # Check if user has access to this conversation
        email, name, loggedin = check_login(session)
        if not checkConversationExists(email, conversation_id):
            return jsonify({
                'status': 'error',
                'error': 'Conversation not found or access denied'
            }), 404
        
        # Validate all section details before processing
        validated_updates = {}
        validation_errors = []
        
        for section_id, details in section_details.items():
            try:
                # Validate section details structure
                if not isinstance(details, dict):
                    validation_errors.append(f"Section {section_id}: details must be a dictionary")
                    continue
                
                if 'hidden' not in details:
                    validation_errors.append(f"Section {section_id}: 'hidden' field is required")
                    continue
                
                hidden_state = details['hidden']
                if not isinstance(hidden_state, bool):
                    validation_errors.append(f"Section {section_id}: 'hidden' must be a boolean value")
                    continue
                
                # Add to validated updates
                validated_updates[str(section_id)] = hidden_state
                
            except Exception as validation_error:
                validation_errors.append(f"Section {section_id}: {str(validation_error)}")
        
        # Return validation errors if any
        if validation_errors:
            return jsonify({
                'status': 'error',
                'error': 'Validation failed',
                'validation_errors': validation_errors
            }), 400
        
        # Perform bulk update in a single database operation
        try:
            bulk_update_section_hidden_detail(conversation_id, validated_updates)
            
            # Prepare successful response
            updated_sections = {
                section_id: {
                    'hidden': hidden_state,
                    'status': 'updated'
                }
                for section_id, hidden_state in validated_updates.items()
            }
            
            response_data = {
                'status': 'success',
                'message': f"Updated {len(updated_sections)} sections successfully",
                'updated_sections': updated_sections,
                'conversation_id': conversation_id
            }
            
            logger.info(f"Bulk updated section hidden details for conversation {conversation_id}: {len(updated_sections)} sections")
            
            return jsonify(response_data)
            
        except Exception as bulk_update_error:
            logger.error(f"Error in bulk update for conversation {conversation_id}: {str(bulk_update_error)}")
            return jsonify({
                'status': 'error',
                'error': f"Failed to update sections: {str(bulk_update_error)}"
            }), 500
        
    except Exception as e:
        logger.error(f"Error updating section hidden details: {str(e)}")
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500






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

