from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import random
import string
import time
import logging
from datetime import datetime
import requests
from dotenv import load_dotenv
import os
from pymongo import MongoClient, ASCENDING
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError
import pytz
from waitress import serve
from apscheduler.schedulers.background import BackgroundScheduler

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://"
)

def connect_to_mongodb(max_retries=3, retry_delay=5):
    for attempt in range(max_retries):
        try:
            client = MongoClient(
                os.getenv('MONGODB_URI', 'mongodb://localhost:27017'),
                serverSelectionTimeoutMS=5000
            )
            client.admin.command('ping')
            logger.info("Connected to MongoDB successfully")
            return client
        except (ConnectionFailure, ServerSelectionTimeoutError) as e:
            if attempt == max_retries - 1:
                logger.error(f"Failed to connect to MongoDB after {max_retries} attempts: {e}")
                raise
            logger.warning(f"MongoDB connection attempt {attempt + 1} failed, retrying in {retry_delay} seconds...")
            time.sleep(retry_delay)

client = connect_to_mongodb()
db = client[os.getenv('MONGODB_DB', 'documents_db')]

try:
    db.documents.create_index([("id", ASCENDING)], unique=True)
    db.documents.create_index([("created_at", ASCENDING)])
except Exception as e:
    logger.error(f"Failed to create indexes: {e}")

def generate_id(length=5):
    while True:
        doc_id = ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))
        if not db.documents.find_one({'id': doc_id}):
            return doc_id

def generate_delete_code(length=8):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

def keep_alive():
    try:
        response = requests.get(f"https://ai-lf07.onrender.com/health")
        logger.info(f"Keep-alive ping status: {response.status_code}")
    except Exception as e:
        logger.error(f"Keep-alive ping failed: {e}")

@app.route('/health', methods=['GET'])
def health_check():
    try:
        client.admin.command('ping')
        return jsonify({
            'status': 'healthy',
            'timestamp': datetime.now(pytz.UTC).isoformat()
        })
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return jsonify({
            'status': 'unhealthy',
            'error': str(e)
        }), 500

@app.route('/publish', methods=['POST'])
@limiter.limit("5 per minute")
def publish_document():
    try:
        if not request.is_json:
            return jsonify({
                'success': False,
                'error': 'Content-Type must be application/json'
            }), 400

        data = request.json
        required_fields = ['title', 'content']
        if not all(field in data for field in required_fields):
            return jsonify({
                'success': False,
                'error': f'Missing required fields: {", ".join(required_fields)}'
            }), 400

        doc_id = generate_id()
        delete_code = generate_delete_code()
        
        document = {
            'id': doc_id,
            'delete_code': delete_code,
            'title': data.get('title'),
            'author': data.get('author'),
            'content': data.get('content'),
            'font_size': data.get('fontSize', '16px'),
            'text_color': data.get('textColor', '#000000'),
            'text_format': data.get('textFormat', 'plain'),
            'line_height': data.get('lineHeight', '1.5'),
            'theme': data.get('theme', 'light'),
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
@limiter.limit("30 per minute")
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
                    'theme': doc['theme'],
                    'created_at': doc['created_at'].isoformat()
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
@limiter.limit("10 per minute")
def delete_document(doc_id):
    delete_code = request.args.get('code')
    
    if not delete_code:
        return jsonify({
            'success': False,
            'error': 'Delete code required'
        }), 400
    
    try:
        result = db.documents.delete_one({
            'id': doc_id,
            'delete_code': delete_code
        })
        
        if result.deleted_count == 0:
            return jsonify({
                'success': False,
                'error': 'Document not found or invalid delete code'
            }), 404
        
        return jsonify({
            'success': True
        })
    except Exception as e:
        logger.error(f"Error deleting document: {e}")
        return jsonify({
            'success': False,
            'error': 'Internal server error'
        }), 500

# Error handlers
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
        scheduler = BackgroundScheduler(timezone=pytz.UTC)
        scheduler.add_job(keep_alive, 'interval', minutes=2)
        scheduler.start()

        port = int(os.getenv('PORT', 10000))
        
        logger.info(f"Starting production server on port {port}")
        serve(app, host='0.0.0.0', port=port)
    except Exception as e:
        logger.error(f"Application startup failed: {e}")
        if 'scheduler' in locals():
            scheduler.shutdown()
