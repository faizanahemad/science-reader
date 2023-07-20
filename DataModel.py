from datetime import datetime
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Boolean, Table, UniqueConstraint
from sqlalchemy.orm import relationship, backref
from sqlalchemy.sql import func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy import Boolean, Column, Integer, String, DateTime, Float, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.sql.schema import ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.dialects.postgresql import ARRAY
import time
from sqlalchemy.orm import joinedload
from sqlalchemy import event
from sqlalchemy.orm import Session
from sqlalchemy import PickleType
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy import JSON
from sqlalchemy.orm.attributes import flag_modified

from common import print_code

Base = declarative_base()

# TimestampMixin to include created_at and updated_at fields
class TimestampMixin:
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    row_version = Column(Integer, default=0)
    
# Event listener function
def increment_row_version(mapper, connection, target):
    target.row_version += 1

# Associate the listener function with 'before_update' event for TimestampMixin classes
event.listen(TimestampMixin, 'before_update', increment_row_version)

# Association tables for many-to-many relationships
document_user_association = Table('document_user_association', Base.metadata,
    Column('user_id', String, ForeignKey('users.id')),
    Column('document_id', String, ForeignKey('documents.id'))
)

document_conversation_association = Table('document_conversation_association', Base.metadata,
    Column('conversation_id', Integer, ForeignKey('conversations.id')),
    Column('document_id', String, ForeignKey('documents.id'))
)

class Document(TimestampMixin, Base):
    __tablename__ = 'documents'
    id = Column(String, primary_key=True)
    doc_source = Column(String)
    doc_filetype = Column(String)
    doc_type = Column(String)
    _title = Column(String)
    _short_summary = Column(String)
    _paper_details = Column(JSON, default=dict)
    is_local = Column(Boolean)
    _storage = Column(String)
    # doc_data = Column(JSON, default=dict) # Column(MutableDict.as_mutable(PickleType), default=dict) 
    
    # Relationships
    questions = relationship('Question', backref='document',  lazy='joined')
    in_depth_readers = relationship('InDepthReader', backref='document',  lazy='joined')
    reviews = relationship('Review', backref='document',  lazy='joined')
    
    users = relationship(
        'User',
        secondary=document_user_association,
        back_populates='documents'
    )
    conversations = relationship(
        'Conversation',
        secondary=document_conversation_association,
        back_populates='documents'
    )
    __table_args__ = (UniqueConstraint('doc_source', name='uix_1'), )
    @staticmethod
    def get_all_questions(session, document_id):
        return session.query(Document).options(joinedload(Document.questions)).filter(Document.id == document_id).one_or_none()

    @staticmethod
    def get_all_in_depth_readers(session, document_id):
        return session.query(Document).options(joinedload(Document.in_depth_readers)).filter(Document.id == document_id).one_or_none()

    @staticmethod
    def get_all_reviews(session, document_id):
        return session.query(Document).options(joinedload(Document.reviews)).filter(Document.id == document_id).one_or_none()

class User(TimestampMixin, Base):
    __tablename__ = 'users'
    id = Column(String, primary_key=True)
    name = Column(String)
    # Relationships
    questions = relationship('Question', backref='user')
    reviews = relationship('Review', backref='user')
    feedbacks = relationship('Feedback', backref='user')
    conversations = relationship('Conversation', backref='user')
    messages = relationship('Message', backref='user')
    documents = relationship(
        'Document',
        secondary=document_user_association,
        back_populates='users'
        
    )
    

    @staticmethod
    def get_all_feedbacks(session, user_id):
        return session.query(User).options(joinedload(User.feedbacks)).filter(User.id == user_id).one_or_none()

    @staticmethod
    def get_all_conversations(session, user_id):
        return session.query(User).options(joinedload(User.conversations)).filter(User.id == user_id).one_or_none()

    @staticmethod
    def get_all_messages(session, user_id):
        return session.query(User).options(joinedload(User.messages)).filter(User.id == user_id).one_or_none()

    
    
class Question(TimestampMixin, Base):
    __tablename__ = 'questions'
    id = Column(String, primary_key=True)
    question = Column(String)
    answer = Column(String)

    # Relationships
    document_id = Column(String, ForeignKey('documents.id'))
    user_id = Column(String, ForeignKey('users.id'))
    feedbacks = relationship('Feedback', uselist=False, backref='question')


class InDepthReader(TimestampMixin, Base):
    __tablename__ = 'indepthreaders'
    id = Column(String, primary_key=True)
    key = Column(String)
    text = Column(String)
    document_id = Column(String, ForeignKey('documents.id'))
    feedbacks = relationship('Feedback', uselist=False, backref='in_depth_reader')


class Review(TimestampMixin, Base):
    __tablename__ = 'reviews'
    id = Column(String, primary_key=True)
    review = Column(String)
    score = Column(String)
    tone = Column(String)
    review_topic = Column(String)
    additional_instructions = Column(String)
    is_meta_review = Column(Boolean)

    # Relationships
    document_id = Column(String, ForeignKey('documents.id'))
    user_id = Column(String, ForeignKey('users.id'))
    feedbacks = relationship('Feedback', uselist=False, backref='review')


class Feedback(TimestampMixin, Base):
    __tablename__ = 'feedbacks'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey('users.id'))
    question_id = Column(String, ForeignKey('questions.id'))
    in_depth_reader_id = Column(String, ForeignKey('indepthreaders.id'))
    review_id = Column(String, ForeignKey('reviews.id'))
    message_id = Column(String, ForeignKey('messages.id'))

    upvoted = Column(Integer)
    downvoted = Column(Integer)
    feedback_type = Column(String)
    feedback_items = Column(String)
    comments = Column(String)
    question_text = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # question = relationship('Question', uselist=False, back_populates='feedback')
    # in_depth_reader = relationship('InDepthReader', uselist=False, back_populates='feedback')
    # review = relationship('Review', uselist=False, back_populates='feedback')
    # user = relationship('User', back_populates='feedbacks')
    # message = relationship('Message', uselist=False, back_populates='feedbacks')

    __table_args__ = (UniqueConstraint('user_id', 'question_id', 'in_depth_reader_id', 'review_id', name='idx_feedback_user_question_in_depth_reader_review'),)

    def addUpvoteOrDownvote(self, upvote, downvote):
        self.upvoted = upvote
        self.downvoted = downvote

    def addGranularFeedback(self, feedback_type, feedback_items, comments, question_text):
        self.feedback_type = feedback_type
        self.feedback_items = ','.join(feedback_items)
        self.comments = comments
        self.question_text = question_text


class Message(TimestampMixin, Base):
    __tablename__ = 'messages'
    id = Column(String, primary_key=True)
    text = Column(String)
    previous_message_id = Column(String, ForeignKey('messages.id'))

    # Relationships
    user_id = Column(String, ForeignKey('users.id'))
    conversation_id = Column(Integer, ForeignKey('conversations.id'))
    feedbacks = relationship('Feedback', uselist=False, backref='message')



class Conversation(TimestampMixin, Base):
    __tablename__ = 'conversations'
    id = Column(Integer, primary_key=True)
    user_id = Column(String, ForeignKey('users.id'))
    

    # Relationships
    messages = relationship('Message', backref='conversation')
    users = relationship('User', backref='conversation')
    documents = relationship(
        'Document',
        secondary=document_conversation_association,
        back_populates='conversations'
    )
    

    
