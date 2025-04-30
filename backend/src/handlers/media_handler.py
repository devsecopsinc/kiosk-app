import json
import os
import logging
import boto3
from typing import Dict, Any
from datetime import datetime, timedelta
import qrcode
from io import BytesIO
import base64
from pydantic import BaseModel, Field
from decimal import Decimal

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize AWS clients
s3 = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')

# Get environment variables
MEDIA_BUCKET = os.environ['MEDIA_BUCKET']
MEDIA_TABLE = os.environ['MEDIA_TABLE']
USER_TABLE = os.environ['USER_TABLE']
QR_MAPPING_TABLE = os.environ['QR_MAPPING_TABLE']

# Initialize DynamoDB tables
media_table = dynamodb.Table(MEDIA_TABLE)
user_table = dynamodb.Table(USER_TABLE)
qr_mapping_table = dynamodb.Table(QR_MAPPING_TABLE)

class MediaMetadata(BaseModel):
    file_name: str
    content_type: str
    user_id: str = Field(default="anonymous")
    expires_at: int = Field(default_factory=lambda: int((datetime.now() + timedelta(days=30)).timestamp()))

def convert_dynamodb_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """Convert DynamoDB types to JSON serializable types."""
    if isinstance(item, dict):
        return {k: convert_dynamodb_item(v) for k, v in item.items()}
    elif isinstance(item, list):
        return [convert_dynamodb_item(i) for i in item]
    elif isinstance(item, Decimal):
        return float(item)
    elif isinstance(item, datetime):
        return item.isoformat()
    else:
        return item

def generate_presigned_url(bucket: str, key: str, operation: str, expires_in: int = 3600) -> str:
    """Generate a presigned URL for S3 operations."""
    try:
        url = s3.generate_presigned_url(
            ClientMethod=operation,
            Params={'Bucket': bucket, 'Key': key},
            ExpiresIn=expires_in
        )
        return url
    except Exception as e:
        logger.error(f"Error generating presigned URL: {str(e)}")
        raise

def generate_qr_code(url: str) -> str:
    """Generate QR code for a URL and return as base64 string."""
    try:
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(url)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        buffer = BytesIO()
        img.save(buffer, format="PNG")
        
        return base64.b64encode(buffer.getvalue()).decode()
    except Exception as e:
        logger.error(f"Error generating QR code: {str(e)}")
        raise

def store_media_metadata(metadata: MediaMetadata, media_id: str) -> Dict[str, Any]:
    """Store media metadata in DynamoDB."""
    try:
        item = {
            'pk': f"MEDIA#{media_id}",
            'sk': f"METADATA#{metadata.file_name}",
            'user_id': metadata.user_id,
            'file_name': metadata.file_name,
            'content_type': metadata.content_type,
            'created_at': datetime.now().isoformat(),
            'expires_at': metadata.expires_at,
            'status': 'active'
        }
        
        media_table.put_item(Item=item)
        return item
    except Exception as e:
        logger.error(f"Error storing media metadata: {str(e)}")
        raise

def create_qr_mapping(media_id: str, url: str, expires_at: int) -> Dict[str, Any]:
    """Create QR code mapping in DynamoDB."""
    try:
        item = {
            'pk': f"QR#{media_id}",
            'sk': 'MAPPING',
            'url': url,
            'created_at': datetime.now().isoformat(),
            'expires_at': expires_at,
            'status': 'active'
        }
        
        qr_mapping_table.put_item(Item=item)
        return item
    except Exception as e:
        logger.error(f"Error creating QR mapping: {str(e)}")
        raise

def normalize_path(path: str) -> str:
    """Normalize API path to handle proxy integration properly."""
    logger.info(f"Original path received: {path}")
    
    # For proxy integration with {proxy+}, we might receive paths like
    # /api/v1/media or /media depending on configuration
    if path.startswith('/api/v1/'):
        # Path like /api/v1/media -> /media
        path = '/' + path[8:]
    elif path == '/api/v1' or path == '/api/v1/':
        # If it's just the API root without additional path, use root
        path = '/'
    
    # Also handle proxy path parameter
    if 'proxy' in path:
        path = '/' + path.replace('proxy', '').strip('/')
    
    logger.info(f"Normalized path: {path}")
    return path

def extract_path_param(path: str, resource: str) -> str:
    """Extract path parameter from path based on resource pattern."""
    # Example: /media/abc123 with resource /media/{id} should return abc123
    parts = path.strip('/').split('/')
    resource_parts = resource.strip('/').split('/')
    
    if len(parts) != len(resource_parts):
        return None
    
    for i, (path_part, resource_part) in enumerate(zip(parts, resource_parts)):
        if resource_part.startswith('{') and resource_part.endswith('}'):
            return path_part
    
    return None

def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Main Lambda handler."""
    try:
        logger.info(f"Received event: {json.dumps(event)}")
        
        # Extract method and path from event
        method = event['httpMethod']
        path = event.get('path', '')
        
        # Get the proxy parameter if it exists (for proxy integration)
        proxy_param = None
        if event.get('pathParameters') and 'proxy' in event['pathParameters']:
            proxy_param = event['pathParameters']['proxy']
            logger.info(f"Proxy parameter: {proxy_param}")
            
            # If path is empty but we have a proxy param, use it
            if not path or path == '/api/v1':
                path = f"/api/v1/{proxy_param}"
        
        # Normalize the path
        normalized_path = normalize_path(path)
        logger.info(f"Normalized path: {normalized_path}")
        
        # Extract the base path and ID if present
        path_parts = normalized_path.strip('/').split('/')
        base_path = f"/{path_parts[0]}" if path_parts else "/"
        path_id = path_parts[1] if len(path_parts) > 1 else None
        
        logger.info(f"Base path: {base_path}, Path ID: {path_id}")
        
        # Handle media upload request
        if method == 'POST' and base_path == '/media':
            body = json.loads(event['body']) if event.get('body') else {}
            metadata = MediaMetadata(**body)
            
            media_id = base64.urlsafe_b64encode(os.urandom(16)).decode('utf-8')
            upload_url = generate_presigned_url(MEDIA_BUCKET, f"media/{media_id}/{metadata.file_name}", 'put_object')
            
            metadata_item = store_media_metadata(metadata, media_id)
            
            return {
                'statusCode': 200,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'upload_url': upload_url,
                    'media_id': media_id,
                    'metadata': convert_dynamodb_item(metadata_item)
                })
            }
            
        # Handle media retrieval
        elif method == 'GET' and base_path == '/media' and path_id:
            media_id = path_id
            
            # Query for items with the given media_id
            response = media_table.query(
                KeyConditionExpression='pk = :pk AND begins_with(sk, :sk)',
                ExpressionAttributeValues={
                    ':pk': f"MEDIA#{media_id}",
                    ':sk': 'METADATA#'
                }
            )
            
            if not response.get('Items'):
                return {
                    'statusCode': 404,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({'error': 'Media not found'})
                }
                
            item = response['Items'][0]
            download_url = generate_presigned_url(
                MEDIA_BUCKET,
                f"media/{media_id}/{item['file_name']}",
                'get_object'
            )
            
            return {
                'statusCode': 200,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'download_url': download_url,
                    'metadata': convert_dynamodb_item(item)
                })
            }
            
        # Handle QR code generation
        elif method == 'POST' and base_path == '/qr':
            body = json.loads(event['body']) if event.get('body') else {}
            media_id = body.get('media_id')
            
            if not media_id:
                return {
                    'statusCode': 400,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({'error': 'media_id is required'})
                }
                
            expires_at = body.get('expires_at', int((datetime.now() + timedelta(days=7)).timestamp()))
            
            # Get media info first
            response = media_table.query(
                KeyConditionExpression='pk = :pk AND begins_with(sk, :sk)',
                ExpressionAttributeValues={
                    ':pk': f"MEDIA#{media_id}",
                    ':sk': 'METADATA#'
                }
            )
            
            if not response.get('Items'):
                return {
                    'statusCode': 404,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({'error': 'Media not found'})
                }
            
            item = response['Items'][0]
            download_url = generate_presigned_url(
                MEDIA_BUCKET,
                f"media/{media_id}/{item['file_name']}",
                'get_object',
                expires_in=7*24*3600  # 7 days
            )
            
            qr_code = generate_qr_code(download_url)
            mapping = create_qr_mapping(media_id, download_url, expires_at)
            
            return {
                'statusCode': 200,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'qr_code': qr_code,
                    'media_id': media_id,
                    'mapping': convert_dynamodb_item(mapping)
                })
            }
            
        # Handle QR code lookup
        elif method == 'GET' and base_path == '/qr' and path_id:
            code = path_id
            
            response = qr_mapping_table.get_item(
                Key={
                    'pk': f"QR#{code}",
                    'sk': 'MAPPING'
                }
            )
            
            if 'Item' not in response:
                return {
                    'statusCode': 404,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({'error': 'QR code not found'})
                }
                
            item = response['Item']
            
            # Check if expired
            if item['expires_at'] < int(datetime.now().timestamp()):
                return {
                    'statusCode': 410,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({'error': 'QR code has expired'})
                }
                
            return {
                'statusCode': 200,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps(convert_dynamodb_item(item))
            }
        
        # Root API path - return available endpoints
        elif method == 'GET' and (normalized_path == '/' or normalized_path == ''):
            return {
                'statusCode': 200,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'message': 'Kiosk Media API',
                    'version': '1.0',
                    'endpoints': {
                        'POST /api/v1/media': 'Generate upload URL for media',
                        'GET /api/v1/media/{id}': 'Get media information and download URL',
                        'POST /api/v1/qr': 'Generate QR code for media',
                        'GET /api/v1/qr/{code}': 'Lookup QR code mapping'
                    }
                })
            }
            
        else:
            logger.warning(f"Path not found: {path} (normalized: {normalized_path})")
            return {
                'statusCode': 404,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'error': 'Not found',
                    'path': path,
                    'normalized_path': normalized_path,
                    'method': method
                })
            }
            
    except Exception as e:
        logger.error(f"Error processing request: {str(e)}", exc_info=True)
        return {
            'statusCode': 500,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({'error': f'Internal server error: {str(e)}'})
        } 