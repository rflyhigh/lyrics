from flask import Flask, request, jsonify
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError
from apscheduler.schedulers.background import BackgroundScheduler
import random
import string
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv
import os
from logging.handlers import RotatingFileHandler
import time

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
handler = RotatingFileHandler('app.log', maxBytes=10000000, backupCount=5)
handler.setFormatter(logging.Formatter(
    '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
))
logger.addHandler(handler)

app = Flask(__name__)

# MongoDB configuration
def init_mongodb():
    try:
        mongo_uri = os.getenv("MONGODB_URI")
        if not mongo_uri:
            logger.error("MONGODB_URI environment variable is not set")
            return None

        # Initialize MongoDB client
        client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
        
        # Test connection
        try:
            client.admin.command('ping')
            db = client[os.getenv('MONGODB_DB', 'share_db')]
            logger.info("MongoDB connection successful")
            return db
        except (ConnectionFailure, ServerSelectionTimeoutError) as e:
            logger.error(f"MongoDB server not available: {e}")
            return None
            
    except Exception as e:
        logger.error(f"MongoDB connection failed: {e}")
        return None

def connect_with_retry(max_retries=3, delay=5):
    for attempt in range(max_retries):
        logger.info(f"Attempting to connect to MongoDB (attempt {attempt + 1}/{max_retries})")
        db = init_mongodb()
        if db is not None:  # Changed from if db:
            return db
        if attempt < max_retries - 1:
            time.sleep(delay)
    return None

db = None  # Initialize as None

def generate_id(length=5):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

def generate_delete_code(length=8):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

@app.route('/publish', methods=['POST'])
def publish_document():
    if db is None:  # Changed from if not db:
        return jsonify({'success': False, 'error': 'Database connection not available'}), 503
        
    try:
        if not request.is_json:
            return jsonify({'success': False, 'error': 'Content-Type must be application/json'}), 400
            
        data = request.json
        if not all(field in data for field in ['title', 'content']):
            return jsonify({'success': False, 'error': 'Missing required fields: title, content'}), 400
            
        document = {
            'id': generate_id(),
            'delete_code': generate_delete_code(),
            'title': data['title'],
            'content': data['content'],
            'author': data.get('author'),
            'fontSize': data.get('fontSize', '16px'),
            'textColor': data.get('textColor', '#000000'),
            'textFormat': data.get('textFormat', 'plain'),
            'lineHeight': data.get('lineHeight', '1.5'),
            'theme': data.get('theme', 'light'),
            'created_at': datetime.utcnow()
        }
        
        result = db.documents.insert_one(document)
        
        if result.inserted_id:
            return jsonify({
                'success': True,
                'id': document['id'],
                'delete_code': document['delete_code']
            })
            
        return jsonify({'success': False, 'error': 'Failed to insert document'}), 500
            
    except Exception as e:
        logger.error(f"Error publishing document: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/document/<doc_id>', methods=['GET'])
def get_document(doc_id):
    if db is None:  # Changed from if not db:
        return jsonify({'success': False, 'error': 'Database connection not available'}), 503
        
    try:
        doc = db.documents.find_one({'id': doc_id})
        
        if doc:
            return jsonify({
                'success': True,
                'document': {
                    'title': doc['title'],
                    'author': doc['author'],
                    'content': doc['content'],
                    'fontSize': doc['fontSize'],
                    'textColor': doc['textColor'],
                    'textFormat': doc['textFormat'],
                    'lineHeight': doc['lineHeight'],
                    'theme': doc['theme'],
                    'created_at': doc['created_at'].isoformat()
                }
            })
        return jsonify({'success': False, 'error': 'Document not found'}), 404
        
    except Exception as e:
        logger.error(f"Error retrieving document: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/delete/<doc_id>', methods=['DELETE'])
def delete_document(doc_id):
    if db is None:  # Changed from if not db:
        return jsonify({'success': False, 'error': 'Database connection not available'}), 503
        
    delete_code = request.args.get('code')
    
    if not delete_code:
        return jsonify({'success': False, 'error': 'Delete code required'}), 400
    
    try:
        result = db.documents.delete_one({
            'id': doc_id,
            'delete_code': delete_code
        })
        
        if result.deleted_count:
            return jsonify({
                'success': True,
                'message': 'Document deleted successfully'
            })
        return jsonify({'success': False, 'error': 'Document not found or invalid delete code'}), 404
            
    except Exception as e:
        logger.error(f"Error deleting document: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

def cleanup_old_documents():
    if db is not None:  # Changed from if db:
        try:
            threshold = datetime.utcnow() - timedelta(days=30)
            result = db.documents.delete_many({'created_at': {'$lt': threshold}})
            logger.info(f"Cleaned up {result.deleted_count} old documents")
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

if __name__ == '__main__':
    # Initialize MongoDB connection with retries
    db = connect_with_retry(max_retries=3, delay=5)
    
    # Initialize scheduler for cleanup
    scheduler = BackgroundScheduler()
    scheduler.add_job(cleanup_old_documents, 'interval', hours=24)
    scheduler.start()
    
    # Get port from environment variable or use default
    port = int(os.getenv('PORT', 5000))
    
    # Run the app
    if db is not None:  # Changed from if db:
        app.run(host='0.0.0.0', port=port)
    else:
        logger.error("Application failed to start: MongoDB connection not available")
        exit(1)
