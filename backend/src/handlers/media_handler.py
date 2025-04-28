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

def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Main Lambda handler."""
    try:
        logger.info(f"Processing event: {json.dumps(event)}")
        
        method = event['httpMethod']
        path = event['path']
        
        # Handle media upload request
        if method == 'POST' and path == '/media':
            body = json.loads(event['body'])
            metadata = MediaMetadata(**body)
            
            media_id = base64.urlsafe_b64encode(os.urandom(16)).decode('utf-8')
            upload_url = generate_presigned_url(MEDIA_BUCKET, f"media/{media_id}/{metadata.file_name}", 'put_object')
            
            metadata_item = store_media_metadata(metadata, media_id)
            
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'upload_url': upload_url,
                    'media_id': media_id,
                    'metadata': convert_dynamodb_item(metadata_item)
                })
            }
            
        # Handle media retrieval
        elif method == 'GET' and path.startswith('/media/'):
            media_id = event['pathParameters']['id']
            
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
                'body': json.dumps({
                    'download_url': download_url,
                    'metadata': convert_dynamodb_item(item)
                })
            }
            
        # Handle QR code generation
        elif method == 'POST' and path == '/qr':
            body = json.loads(event['body'])
            media_id = body['media_id']
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
                'body': json.dumps({
                    'qr_code': qr_code,
                    'media_id': media_id,
                    'mapping': convert_dynamodb_item(mapping)
                })
            }
            
        # Handle QR code lookup
        elif method == 'GET' and path.startswith('/qr/'):
            code = event['pathParameters']['code']
            
            response = qr_mapping_table.get_item(
                Key={
                    'pk': f"QR#{code}",
                    'sk': 'MAPPING'
                }
            )
            
            if 'Item' not in response:
                return {
                    'statusCode': 404,
                    'body': json.dumps({'error': 'QR code not found'})
                }
                
            item = response['Item']
            
            # Check if expired
            if item['expires_at'] < int(datetime.now().timestamp()):
                return {
                    'statusCode': 410,
                    'body': json.dumps({'error': 'QR code has expired'})
                }
                
            return {
                'statusCode': 200,
                'body': json.dumps(convert_dynamodb_item(item))
            }
            
        else:
            return {
                'statusCode': 404,
                'body': json.dumps({'error': 'Not found'})
            }
            
    except Exception as e:
        logger.error(f"Error processing request: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': 'Internal server error'})
        } 