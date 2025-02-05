from flask import Flask, request, jsonify
from flask_pymongo import PyMongo
from pymongo.errors import PyMongoError, ConnectionFailure
from apscheduler.schedulers.background import BackgroundScheduler
from healthcheck import HealthCheck
import random
import string
import logging
import time
from datetime import datetime, timedelta
from dotenv import load_dotenv
import os
from logging.handlers import RotatingFileHandler
import urllib.parse

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

# MongoDB configuration with enhanced error handling
def init_mongodb():
    try:
        mongo_uri = os.getenv("MONGO_URI")
        if not mongo_uri:
            logger.error("MONGO_URI environment variable is not set")
            raise ValueError("MONGO_URI environment variable is not set")

        # Add database name if not present in URI
        if '?' in mongo_uri and not any(param.startswith('dbname=') for param in mongo_uri.split('?')[1].split('&')):
            mongo_uri = mongo_uri.replace('?', '/documents_db?')
        elif '?' not in mongo_uri:
            if mongo_uri.endswith('/'):
                mongo_uri += 'documents_db'
            else:
                mongo_uri += '/documents_db'

        # Configure Flask app with MongoDB URI
        app.config["MONGO_URI"] = mongo_uri
        
        # Initialize PyMongo
        mongodb = PyMongo(app)
        
        # Test connection with timeout
        mongodb.db.client.server_info()
        logger.info("MongoDB connection successful")
        return mongodb
    except ConnectionFailure as e:
        logger.error(f"MongoDB connection failed - could not connect to server: {e}")
        return None
    except Exception as e:
        logger.error(f"MongoDB connection failed: {e}")
        return None

mongo = init_mongodb()

# Health check setup
health = HealthCheck()

def mongo_available():
    try:
        if mongo and mongo.db:
            mongo.db.client.server_info()
            return True, "mongodb connection ok"
        return False, "mongodb not initialized"
    except Exception as e:
        return False, str(e)

health.add_check(mongo_available)
app.add_url_rule("/healthcheck", "healthcheck", view_func=lambda: health.run())

def generate_id(length=5):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

def generate_delete_code(length=8):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

@app.route('/publish', methods=['POST'])
def publish_document():
    if not mongo:
        return jsonify({
            'success': False,
            'error': 'Database connection not available'
        }), 503
        
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
            'fontSize': data.get('fontSize', '16px'),
            'textColor': data.get('textColor', '#000000'),
            'textFormat': data.get('textFormat', 'plain'),
            'lineHeight': data.get('lineHeight', '1.5'),
            'theme': data.get('theme', 'light'),
            'created_at': datetime.utcnow()
        }
        
        # Ensure the collection exists and create index if needed
        if 'documents' not in mongo.db.list_collection_names():
            mongo.db.create_collection('documents')
            mongo.db.documents.create_index('id', unique=True)
            mongo.db.documents.create_index('created_at')
        
        result = mongo.db.documents.insert_one(document)
        
        if result.inserted_id:
            return jsonify({
                'success': True,
                'id': doc_id,
                'delete_code': delete_code
            })
        else:
            raise PyMongoError("Failed to insert document")
            
    except PyMongoError as e:
        logger.error(f"Database error while publishing document: {e}")
        return jsonify({
            'success': False,
            'error': 'Database error'
        }), 500
    except Exception as e:
        logger.error(f"Error publishing document: {e}")
        return jsonify({
            'success': False,
            'error': 'Internal server error'
        }), 500

@app.route('/document/<doc_id>', methods=['GET'])
def get_document(doc_id):
    if not mongo:
        return jsonify({
            'success': False,
            'error': 'Database connection not available'
        }), 503
        
    try:
        if not doc_id:
            return jsonify({
                'success': False,
                'error': 'Document ID is required'
            }), 400
            
        # Ensure the collection exists
        if 'documents' not in mongo.db.list_collection_names():
            return jsonify({
                'success': False,
                'error': 'Document not found'
            }), 404
            
        doc = mongo.db.documents.find_one({'id': doc_id})
        
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
        return jsonify({
            'success': False,
            'error': 'Document not found'
        }), 404
    except PyMongoError as e:
        logger.error(f"Database error while retrieving document: {e}")
        return jsonify({
            'success': False,
            'error': 'Database error'
        }), 500
    except Exception as e:
        logger.error(f"Error retrieving document: {e}")
        return jsonify({
            'success': False,
            'error': 'Internal server error'
        }), 500

@app.route('/delete/<doc_id>', methods=['DELETE'])
def delete_document(doc_id):
    if not mongo:
        return jsonify({
            'success': False,
            'error': 'Database connection not available'
        }), 503
        
    delete_code = request.args.get('code')
    
    if not delete_code:
        return jsonify({
            'success': False,
            'error': 'Delete code required'
        }), 400
    
    try:
        # Ensure the collection exists
        if 'documents' not in mongo.db.list_collection_names():
            return jsonify({
                'success': False,
                'error': 'Document not found'
            }), 404
            
        doc = mongo.db.documents.find_one({'id': doc_id})
        
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
        
        result = mongo.db.documents.delete_one({'id': doc_id})
        
        if result.deleted_count:
            return jsonify({
                'success': True,
                'message': 'Document deleted successfully'
            })
        else:
            raise PyMongoError("Failed to delete document")
            
    except PyMongoError as e:
        logger.error(f"Database error while deleting document: {e}")
        return jsonify({
            'success': False,
            'error': 'Database error'
        }), 500
    except Exception as e:
        logger.error(f"Error deleting document: {e}")
        return jsonify({
            'success': False,
            'error': 'Internal server error'
        }), 500

def cleanup_old_documents():
    if not mongo:
        logger.error("Cleanup failed: Database connection not available")
        return
        
    try:
        # Ensure the collection exists
        if 'documents' in mongo.db.list_collection_names():
            threshold = datetime.utcnow() - timedelta(days=30)
            result = mongo.db.documents.delete_many({'created_at': {'$lt': threshold}})
            logger.info(f"Cleaned up {result.deleted_count} old documents")
    except Exception as e:
        logger.error(f"Error during cleanup: {e}")

if __name__ == '__main__':
    retries = 3
    retry_delay = 5  # seconds
    
    # Try to establish MongoDB connection with retries
    for attempt in range(retries):
        if not mongo:
            logger.info(f"Attempting to connect to MongoDB (attempt {attempt + 1}/{retries})")
            mongo = init_mongodb()
            if mongo:
                break
            if attempt < retries - 1:
                time.sleep(retry_delay)
    
    # Initialize scheduler
    scheduler = BackgroundScheduler()
    scheduler.add_job(cleanup_old_documents, 'interval', hours=24)
    scheduler.start()
    
    # Get port from environment variable or use default
    port = int(os.getenv('PORT', 5000))
    
    # Only run the app if MongoDB connection is successful
    if mongo:
        app.run(host='0.0.0.0', port=port)
    else:
        logger.error("Application failed to start: MongoDB connection not available after retries")
        exit(1)
