from flask import Flask, request, jsonify
from flask_pymongo import PyMongo
from pymongo.errors import PyMongoError
from apscheduler.schedulers.background import BackgroundScheduler
from healthcheck import HealthCheck
import random
import string
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv
import os
from logging.handlers import RotatingFileHandler

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
app.config["MONGO_URI"] = os.getenv("MONGO_URI", "mongodb://localhost:27017/documents_db")
try:
    mongo = PyMongo(app)
    # Test the connection
    mongo.db.command('ping')
    logger.info("MongoDB connection successful")
except Exception as e:
    logger.error(f"MongoDB connection failed: {e}")
    raise

# Health check setup
health = HealthCheck()

def mongo_available():
    try:
        mongo.db.command('ping')
        return True, "mongodb connection ok"
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
            'fontSize': data.get('fontSize'),
            'textColor': data.get('textColor'),
            'textFormat': data.get('textFormat'),
            'lineHeight': data.get('lineHeight'),
            'theme': data.get('theme'),
            'created_at': datetime.utcnow()
        }
        
        # Ensure the collection exists
        if 'documents' not in mongo.db.list_collection_names():
            mongo.db.create_collection('documents')
        
        mongo.db.documents.insert_one(document)
        
        return jsonify({
            'success': True,
            'id': doc_id,
            'delete_code': delete_code
        })
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
    try:
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
                    'theme': doc['theme']
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
        
        mongo.db.documents.delete_one({'id': doc_id})
        
        return jsonify({
            'success': True
        })
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
    try:
        # Ensure the collection exists
        if 'documents' in mongo.db.list_collection_names():
            threshold = datetime.utcnow() - timedelta(days=30)
            result = mongo.db.documents.delete_many({'created_at': {'$lt': threshold}})
            logger.info(f"Cleaned up {result.deleted_count} old documents")
    except Exception as e:
        logger.error(f"Error during cleanup: {e}")

if __name__ == '__main__':
    # Initialize scheduler
    scheduler = BackgroundScheduler()
    scheduler.add_job(cleanup_old_documents, 'interval', hours=24)
    scheduler.start()
    
    # Get port from environment variable or use default
    port = int(os.getenv('PORT', 5000))
    
    app.run(host='0.0.0.0', port=port)
