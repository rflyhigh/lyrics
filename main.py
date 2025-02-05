from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import random
import string
import time
import threading
import logging
from datetime import datetime
from dotenv import load_dotenv
import os
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError
import pytz
from waitress import serve

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# Configure rate limiter
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://"
)

# MongoDB Connection
try:
    client = MongoClient(os.getenv('MONGODB_URI', 'mongodb://localhost:27017'), 
                        serverSelectionTimeoutMS=5000)
    client.admin.command('ping')
    db = client[os.getenv('MONGODB_DB', 'documents_db')]
    print("Connected to MongoDB successfully")
except (ConnectionFailure, ServerSelectionTimeoutError) as e:
    logger.error(f"Failed to connect to MongoDB: {e}")
    raise

def generate_id(length=5):
    while True:
        doc_id = ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))
        # Check if ID already exists
        if not db.documents.find_one({'id': doc_id}):
            return doc_id

def generate_delete_code(length=8):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

# Keep-alive mechanism
def keep_alive():
    while True:
        logger.info("Keep-alive ping")
        time.sleep(300)

@app.route('/publish', methods=['POST'])
@limiter.limit("5 per minute")  # Specific limit for publishing
def publish_document():
    try:
        data = request.json
        doc_id = generate_id()
        delete_code = generate_delete_code()
        
        document = {
            'id': doc_id,
            'delete_code': delete_code,
            'title': data.get('title'),
            'author': data.get('author'),
            'content': data.get('content'),
            'font_size': data.get('fontSize'),
            'text_color': data.get('textColor'),
            'text_format': data.get('textFormat'),
            'line_height': data.get('lineHeight'),
            'theme': data.get('theme'),
            'created_at': datetime.now(pytz.UTC)
        }
        
        db.documents.insert_one(document)
            
        return jsonify({
            'success': True,
            'id': doc_id,
            'delete_code': delete_code
        })
    except Exception as e:
        logger.error(f"Error publishing document: {e}")
        return jsonify({
            'success': False,
            'error': 'Internal server error'
        }), 500

@app.route('/document/<doc_id>', methods=['GET'])
@limiter.limit("30 per minute")  # Specific limit for retrieving documents
def get_document(doc_id):
    try:
        doc = db.documents.find_one({'id': doc_id})
            
        if doc:
            return jsonify({
                'success': True,
                'document': {
                    'title': doc['title'],
                    'author': doc['author'],
                    'content': doc['content'],
                    'fontSize': doc['font_size'],
                    'textColor': doc['text_color'],
                    'textFormat': doc['text_format'],
                    'lineHeight': doc['line_height'],
                    'theme': doc['theme']
                }
            })
        return jsonify({
            'success': False,
            'error': 'Document not found'
        }), 404
    except Exception as e:
        logger.error(f"Error retrieving document: {e}")
        return jsonify({
            'success': False,
            'error': 'Internal server error'
        }), 500

@app.route('/delete/<doc_id>', methods=['DELETE'])
@limiter.limit("10 per minute")  # Specific limit for deletions
def delete_document(doc_id):
    delete_code = request.args.get('code')
    
    if not delete_code:
        return jsonify({
            'success': False,
            'error': 'Delete code required'
        }), 400
    
    try:
        doc = db.documents.find_one({'id': doc_id})
        
        if not doc:
            return jsonify({
                'success': False,
                'error': 'Document not found'
            }), 404
        
        if doc['delete_code'] != delete_code:
            return jsonify({
                'success': False,
                'error': 'Invalid delete code'
            }), 403
        
        db.documents.delete_one({'id': doc_id})
        
        return jsonify({
            'success': True
        })
    except Exception as e:
        logger.error(f"Error deleting document: {e}")
        return jsonify({
            'success': False,
            'error': 'Internal server error'
        }), 500

@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'Resource not found'}), 404

@app.errorhandler(500)
def server_error(e):
    return jsonify({'error': 'Internal server error'}), 500

@app.errorhandler(429)
def ratelimit_handler(e):
    return jsonify({'error': f"Rate limit exceeded. {e.description}"}), 429

if __name__ == '__main__':
    try:
        # Start keep-alive thread
        threading.Thread(target=keep_alive, daemon=True).start()
        
        # Get port from environment variable or use default
        port = int(os.getenv('PORT', 5000))
        
        # Use Waitress instead of Flask's development server
        logger.info(f"Starting production server on port {port}")
        serve(app, host='0.0.0.0', port=port)
    except Exception as e:
        logger.error(f"Application startup failed: {e}")
