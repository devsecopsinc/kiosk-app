"""
Photo Kiosk Backend Media Handler

Handles media upload, download, and QR code generation for the Photo Kiosk system.
Supports file operations via S3 with signed URLs and DynamoDB for metadata storage.
"""

import json
import logging
import os
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, Protocol
from urllib.parse import urlparse

import boto3
import qrcode
from botocore.exceptions import ClientError, BotoCoreError
from pydantic import BaseModel, Field, ValidationError

import urllib3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def empty_bucket(bucket_name):
    s3 = boto3.resource('s3')
    bucket = s3.Bucket(bucket_name)
    # Delete all objects (including versions if versioning enabled)
    bucket.object_versions.delete()
    logger.info(f"Emptied bucket: {bucket_name}")

def send_response(event, context, status, reason=None):
    response_url = event['ResponseURL']
    response_body = {
        'Status': status,
        'Reason': reason or 'See the details in CloudWatch Log Stream: ' + context.log_stream_name,
        'PhysicalResourceId': context.log_stream_name,
        'StackId': event['StackId'],
        'RequestId': event['RequestId'],
        'LogicalResourceId': event['LogicalResourceId'],
        'Data': {}
    }
    json_response_body = json.dumps(response_body)
    http = urllib3.PoolManager()
    headers = {'content-type': '', 'content-length': str(len(json_response_body))}
    http.request('PUT', response_url, body=json_response_body, headers=headers)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants - match stable version environment variables
MEDIA_BUCKET = os.environ.get('MEDIA_BUCKET', 'photo-kiosk-media')
MEDIA_TABLE = os.environ.get('MEDIA_TABLE', 'photo-kiosk-media')
USER_TABLE = os.environ.get('USER_TABLE', 'photo-kiosk-users')
QR_MAPPING_TABLE = os.environ.get('QR_MAPPING_TABLE', 'photo-kiosk-qr')
MEDIA_EXPIRATION_DAYS = int(os.environ.get('MEDIA_EXPIRATION_DAYS', '7'))
ALLOWED_CONTENT_TYPES = [
    'image/jpeg', 'image/jpg', 'image/png', 'image/gif', 'image/webp',
    'video/mp4', 'video/quicktime', 'video/x-msvideo', 'video/webm'
]

# Domain Models
class ThemeOptions(BaseModel):
    """Theme configuration for media display."""
    background_color: Optional[str] = Field(default=None)
    text_color: Optional[str] = Field(default=None)
    accent_color: Optional[str] = Field(default=None)
    header_text: Optional[str] = Field(default=None)
    logo_url: Optional[str] = Field(default=None)
    custom_css: Optional[str] = Field(default=None)

class MediaMetadata(BaseModel):
    """Media metadata model with validation."""
    file_name: str
    content_type: str
    user_id: str = Field(default="anonymous")
    expires_at: int = Field(default_factory=lambda: int((datetime.now() + timedelta(days=MEDIA_EXPIRATION_DAYS)).timestamp()))
    theme_options: Optional[ThemeOptions] = Field(default=None)

class MediaItem(BaseModel):
    """Domain model for media items."""
    media_id: str
    file_name: str
    content_type: str
    user_id: str
    file_path: str
    created_at: datetime
    expires_at: int  # Unix timestamp
    status: str = "active"
    theme_options: Optional[Dict[str, Any]] = None

class QRMapping(BaseModel):
    """Domain model for QR code mappings."""
    media_id: str
    url: str
    created_at: datetime
    expires_at: int  # Unix timestamp
    status: str = "active"

# Utility Functions (match stable version)
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

def generate_media_path(media_id: str, file_name: str) -> str:
    """Generate a path for media storage with date-based structure (match stable version)."""
    now = datetime.now()
    date_string = now.strftime("%Y-%m-%d")
    
    # Extract just the filename without path if file_name includes path
    base_file_name = os.path.basename(file_name)
    
    # Create path: media/YYYY-MM-DD/media_id/file_name (match stable version)
    return f"media/{date_string}/{media_id}/{base_file_name}"

def normalize_path(path: str) -> str:
    """Normalize API path to handle proxy integration properly (match stable version)."""
    logger.info(f"Original path received: {path}")
    
    # For proxy integration with {proxy+}, we might receive paths like
    # /api/v1/media or /media depending on configuration
    if path.startswith('/api/v1/'):
        # Path like /api/v1/media -> /media
        normalized = '/' + path[8:]
        logger.info(f"Path starts with /api/v1/ - normalized to: {normalized}")
        return normalized
    elif path == '/api/v1' or path == '/api/v1/':
        # If it's just the API root without additional path, use root
        logger.info(f"Path is API root - normalized to: /")
        return '/'
    elif path.startswith('/api/'):
        # Handle /api/media pattern
        normalized = '/' + path[5:]
        logger.info(f"Path starts with /api/ - normalized to: {normalized}")
        return normalized
    
    # Handle proxy path parameter if present
    if path.startswith('/proxy/') or path.startswith('/proxy'):
        normalized = '/' + path.replace('/proxy', '').strip('/')
        logger.info(f"Path contains proxy prefix - normalized to: {normalized}")
        return normalized
    
    # If the path is already clean (e.g., /media), return as is
    logger.info(f"Path appears to be already normalized: {path}")
    return path

# Repository Protocols
class MediaRepository(Protocol):
    """Protocol for media metadata operations."""
    
    def store_media_metadata(self, metadata: MediaMetadata, media_id: str) -> Dict[str, Any]:
        """Store media metadata."""
        ...
    
    def get_media_by_id(self, media_id: str) -> Optional[MediaItem]:
        """Get media metadata by ID."""
        ...
    
    def update_file_path(self, media_id: str, file_name: str, file_path: str) -> None:
        """Update file path for media."""
        ...

class QRRepository(Protocol):
    """Protocol for QR code operations."""
    
    def store_qr_mapping(self, qr_mapping: QRMapping) -> Dict[str, Any]:
        """Store QR code mapping."""
        ...
    
    def get_qr_mapping(self, code: str) -> Optional[QRMapping]:
        """Get QR mapping by code."""
        ...

class StorageRepository(Protocol):
    """Protocol for storage operations."""
    
    def generate_upload_url(self, bucket: str, key: str, expires_in: int = 3600) -> str:
        """Generate signed upload URL."""
        ...
    
    def generate_download_url(self, bucket: str, key: str, content_type: str, expires_in: int = 3600) -> str:
        """Generate signed download URL."""
        ...

class QRGenerator(Protocol):
    """Protocol for QR code generation."""
    
    def generate_qr_code(self, data: str) -> str:
        """Generate QR code and return base64 encoded image."""
        ...

# Repository Implementations
class DynamoDBMediaRepository:
    """DynamoDB implementation of MediaRepository."""
    
    def __init__(self, dynamodb_resource, table_name: str):
        self._dynamodb = dynamodb_resource
        self._table = dynamodb_resource.Table(table_name)
        self._logger = logging.getLogger(__name__)

    def store_media_metadata(self, metadata: MediaMetadata, media_id: str) -> Dict[str, Any]:
        """Store media metadata in DynamoDB (match stable version structure)."""
        try:
            item = {
                'pk': f"MEDIA#{media_id}",
                'sk': f"METADATA#{metadata.file_name}",  # Match stable version
                'user_id': metadata.user_id,
                'file_name': metadata.file_name,
                'content_type': metadata.content_type,
                'created_at': datetime.now().isoformat(),
                'expires_at': metadata.expires_at,
                'status': 'active'
            }
            
            # Add theme options if provided
            if metadata.theme_options:
                theme_dict = metadata.theme_options.dict(exclude_none=True)
                if theme_dict:
                    item['theme_options'] = theme_dict
            
            self._table.put_item(Item=item)
            self._logger.info(f"✅ Stored media metadata: {media_id}")
            return item
            
        except Exception as e:
            self._logger.error(f"❌ Failed to store media metadata: {str(e)}")
            raise

    def get_media_by_id(self, media_id: str) -> Optional[MediaItem]:
        """Get media metadata by ID from DynamoDB (match stable version query)."""
        try:
            response = self._table.query(
                KeyConditionExpression='pk = :pk AND begins_with(sk, :sk)',
                ExpressionAttributeValues={
                    ':pk': f"MEDIA#{media_id}",
                    ':sk': 'METADATA#'  # Match stable version
                }
            )
            
            if not response.get('Items'):
                self._logger.warning(f"Media not found: {media_id}")
                return None
            
            item = response['Items'][0]
            
            # Use stored file_path if available, otherwise generate path
            if 'file_path' in item:
                file_path = item['file_path']
            else:
                # Generate file path using the media_id directly (now using UUID)
                file_path = f"media/{media_id}/{item['file_name']}"
                # For newer format with date-based paths
                date_string = datetime.now().strftime("%Y-%m-%d")
                file_path = f"media/{date_string}/{media_id}/{item['file_name']}"
            
            return MediaItem(
                media_id=media_id,
                file_name=item['file_name'],
                content_type=item['content_type'],
                user_id=item['user_id'],
                file_path=file_path,
                created_at=datetime.fromisoformat(item['created_at']),
                expires_at=int(item['expires_at']),  # Convert Decimal to int
                status=item.get('status', 'active'),
                theme_options=item.get('theme_options')
            )
            
        except Exception as e:
            self._logger.error(f"❌ Failed to get media by ID: {str(e)}")
            return None
    
    def update_file_path(self, media_id: str, file_name: str, file_path: str) -> None:
        """Update file path for media (match stable version)."""
        try:
            self._table.update_item(
                Key={'pk': f"MEDIA#{media_id}", 'sk': f"METADATA#{file_name}"},
                UpdateExpression="SET file_path = :file_path",
                ExpressionAttributeValues={':file_path': file_path}
            )
            self._logger.info(f"✅ Updated file path for media: {media_id}")
        except Exception as e:
            self._logger.error(f"❌ Failed to update file path: {str(e)}")
            raise

class DynamoDBQRRepository:
    """DynamoDB implementation of QRRepository."""
    
    def __init__(self, dynamodb_resource, table_name: str):
        self._dynamodb = dynamodb_resource
        self._table = dynamodb_resource.Table(table_name)
        self._logger = logging.getLogger(__name__)

    def store_qr_mapping(self, qr_mapping: QRMapping) -> Dict[str, Any]:
        """Store QR mapping in DynamoDB (match stable version structure)."""
        try:
            item = {
                'pk': f"QR#{qr_mapping.media_id}",
                'sk': 'MAPPING',  # Match stable version
                'url': qr_mapping.url,
                'created_at': qr_mapping.created_at.isoformat(),
                'expires_at': qr_mapping.expires_at,
                'status': qr_mapping.status
            }
            
            self._table.put_item(Item=item)
            self._logger.info(f"✅ Stored QR mapping: {qr_mapping.media_id}")
            return item
            
        except Exception as e:
            self._logger.error(f"❌ Failed to store QR mapping: {str(e)}")
            raise

    def get_qr_mapping(self, code: str) -> Optional[QRMapping]:
        """Get QR mapping by code from DynamoDB (match stable version structure)."""
        try:
            response = self._table.get_item(
                Key={
                    'pk': f"QR#{code}",
                    'sk': 'MAPPING'  # Match stable version
                }
            )
            
            if 'Item' not in response:
                self._logger.warning(f"QR mapping not found: {code}")
                return None
            
            item = response['Item']
            return QRMapping(
                media_id=code,
                url=item['url'],
                created_at=datetime.fromisoformat(item['created_at']),
                expires_at=int(item['expires_at']),  # Convert Decimal to int
                status=item.get('status', 'active')
            )
            
        except Exception as e:
            self._logger.error(f"❌ Failed to get QR mapping: {str(e)}")
            return None

class S3StorageRepository:
    """S3 implementation of StorageRepository."""
    
    def __init__(self, s3_client):
        self._s3 = s3_client
        self._logger = logging.getLogger(__name__)

    def generate_upload_url(self, bucket: str, key: str, expires_in: int = 3600) -> str:
        """Generate signed upload URL for S3 (match stable version)."""
        try:
            self._logger.info(f"Generating presigned URL: bucket={bucket}, key={key}, operation=put_object")
            url = self._s3.generate_presigned_url(
                'put_object',
                Params={'Bucket': bucket, 'Key': key},
                ExpiresIn=expires_in
            )
            
            # Log the generated URL
            safe_url = url[:50] + '...' if len(url) > 50 else url
            self._logger.info(f"Generated presigned URL: {safe_url}")
            
            return url
            
        except Exception as e:
            self._logger.error(f"❌ Failed to generate upload URL: {str(e)}")
            raise

    def generate_download_url(self, bucket: str, key: str, content_type: str, expires_in: int = 3600) -> str:
        """Generate signed download URL for S3 (match stable version)."""
        try:
            self._logger.info(f"Generating presigned URL: bucket={bucket}, key={key}, operation=get_object")
            params = {
                'Bucket': bucket, 
                'Key': key,
                'ResponseContentType': content_type
            }
            
            url = self._s3.generate_presigned_url(
                'get_object',
                Params=params,
                ExpiresIn=expires_in
            )
            
            # Log the generated URL
            safe_url = url[:50] + '...' if len(url) > 50 else url
            self._logger.info(f"Generated presigned URL: {safe_url}")
            
            return url
            
        except Exception as e:
            self._logger.error(f"❌ Failed to generate download URL: {str(e)}")
            raise

class StandardQRGenerator:
    """Standard QR code generator implementation."""
    
    def __init__(self):
        self._logger = logging.getLogger(__name__)

    def generate_qr_code(self, data: str) -> str:
        """Generate QR code and return base64 encoded image (match stable version)."""
        try:
            import base64
            from io import BytesIO
            
            qr = qrcode.QRCode(version=1, box_size=10, border=5)
            qr.add_data(data)
            qr.make(fit=True)
            
            img = qr.make_image(fill_color="black", back_color="white")
            buffer = BytesIO()
            img.save(buffer, 'PNG')
            
            encoded_img = base64.b64encode(buffer.getvalue()).decode()
            self._logger.info(f"✅ Generated QR code for data length: {len(data)}")
            
            return encoded_img
            
        except Exception as e:
            self._logger.error(f"❌ Failed to generate QR code: {str(e)}")
            raise

# Service Layer
class MediaService:
    """Service for media operations."""
    
    def __init__(self, storage_repo: StorageRepository, media_repo: MediaRepository):
        self._storage = storage_repo
        self._media_repo = media_repo
        self._logger = logging.getLogger(__name__)

    def create_upload_url(self, metadata: MediaMetadata) -> Dict[str, Any]:
        """Create upload URL for media (match stable version logic)."""
        try:
            # Strip any path from the filename - only use basename
            file_name = os.path.basename(metadata.file_name)
            metadata.file_name = file_name
            
            # Generate media_id using UUID instead of base64 to avoid special characters
            # This ensures we don't have any URL encoding issues with + / = characters
            media_id = str(uuid.uuid4()).replace('-', '')
            
            # Log the generated ID
            self._logger.info(f"Generated media_id: {media_id}")
            
            file_path = generate_media_path(media_id, file_name)
            upload_url = self._storage.generate_upload_url(MEDIA_BUCKET, file_path)
            
            metadata_item = self._media_repo.store_media_metadata(metadata, media_id)
            
            # Store the file path in metadata for later retrieval (match stable version)
            metadata_item['file_path'] = file_path
            self._media_repo.update_file_path(media_id, file_name, file_path)
            
            self._logger.info(f"✅ Generated upload URL for media: {media_id}")
            
            return {
                'upload_url': upload_url,
                'media_id': media_id,
                'metadata': convert_dynamodb_item(metadata_item)
            }
            
        except Exception as e:
            self._logger.error(f"❌ Failed to create upload URL: {str(e)}")
            raise

    def get_media_download_url(self, media_id: str) -> Dict[str, Any]:
        """Get download URL for media file (match stable version logic)."""
        try:
            # Get media metadata
            media_item = self._media_repo.get_media_by_id(media_id)
            if not media_item:
                raise ValueError("Media not found")
            
            # Add debug info for troubleshooting
            self._logger.info(f"Media ID: {media_id}")
            self._logger.info(f"File path: {media_item.file_path}")
            
            # Generate download URL
            download_url = self._storage.generate_download_url(
                MEDIA_BUCKET, 
                media_item.file_path, 
                media_item.content_type
            )
            
            self._logger.info(f"✅ Generated download URL for media: {media_id}")
            
            return {
                'download_url': download_url,
                'metadata': self._media_item_to_dict(media_item)
            }
            
        except Exception as e:
            self._logger.error(f"❌ Failed to get media download URL: {str(e)}")
            raise

    def _media_item_to_dict(self, media_item: MediaItem) -> Dict[str, Any]:
        """Convert MediaItem to dictionary."""
        return convert_dynamodb_item({
            'file_name': media_item.file_name,
            'content_type': media_item.content_type,
            'user_id': media_item.user_id,
            'created_at': media_item.created_at.isoformat(),
            'expires_at': media_item.expires_at,
            'status': media_item.status,
            'theme_options': media_item.theme_options,
            'file_path': media_item.file_path
        })

class QRService:
    """Service for QR code operations."""
    
    def __init__(self, qr_repo: QRRepository, media_repo: MediaRepository, 
                 storage_repo: StorageRepository, qr_generator: QRGenerator):
        self._qr_repo = qr_repo
        self._media_repo = media_repo
        self._storage = storage_repo
        self._qr_generator = qr_generator
        self._logger = logging.getLogger(__name__)

    def generate_qr_code(self, media_id: str, frontend_url: Optional[str] = None, expires_at: Optional[int] = None) -> Dict[str, Any]:
        """Generate QR code for media access (match stable version logic)."""
        try:
            # Default expiration if not provided
            final_expires_at = expires_at if expires_at else int((datetime.now() + timedelta(days=7)).timestamp())
            
            # Get media info first
            media_item = self._media_repo.get_media_by_id(media_id)
            if not media_item:
                raise ValueError("Media not found")
            
            # Check if frontend URL is provided, otherwise use direct S3 link (match stable version)
            if frontend_url:
                # Ensure the URL has a trailing slash before query parameters
                if '?' in frontend_url:
                    base_url, query_part = frontend_url.split('?', 1)
                    if not base_url.endswith('/'):
                        base_url = f"{base_url}/"
                    url_to_use = f"{base_url}?{query_part}"
                else:
                    if not frontend_url.endswith('/'):
                        url_to_use = f"{frontend_url}/"
                    else:
                        url_to_use = frontend_url
                
                self._logger.info(f"Using normalized frontend URL for QR code: {url_to_use}")
            else:
                # Use direct S3 download link
                url_to_use = self._storage.generate_download_url(
                    MEDIA_BUCKET,
                    media_item.file_path,
                    media_item.content_type,
                    expires_in=7*24*3600  # 7 days
                )
                self._logger.info(f"Using direct S3 URL for QR code: {url_to_use}")
            
            # Generate QR code image
            qr_code_image = self._qr_generator.generate_qr_code(url_to_use)
            
            # Create QR mapping
            qr_mapping = QRMapping(
                media_id=media_id,
                url=url_to_use,
                created_at=datetime.now(),
                expires_at=final_expires_at
            )
            
            # Store QR mapping
            mapping_item = self._qr_repo.store_qr_mapping(qr_mapping)
            
            self._logger.info(f"✅ Generated QR code for media: {media_id}")
            
            return {
                'qr_code': qr_code_image,
                'media_id': media_id,
                'mapping': convert_dynamodb_item(mapping_item)
            }
            
        except Exception as e:
            self._logger.error(f"❌ Failed to generate QR code: {str(e)}")
            raise

    def get_qr_mapping(self, code: str) -> Dict[str, Any]:
        """Get QR mapping by code (match stable version logic)."""
        try:
            mapping = self._qr_repo.get_qr_mapping(code)
            if not mapping:
                raise ValueError("QR code not found")
            
            # Check if expired
            if mapping.expires_at < int(datetime.now().timestamp()):
                raise ValueError("QR code has expired")
            
            return convert_dynamodb_item({
                'url': mapping.url,
                'created_at': mapping.created_at.isoformat(),
                'expires_at': mapping.expires_at,
                'status': mapping.status
            })
            
        except Exception as e:
            self._logger.error(f"❌ Failed to get QR mapping: {str(e)}")
            raise

# Lambda Handler
def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Main Lambda handler with OOP architecture but matching stable version logic."""
    try:
        logger.info(f"Received event: {json.dumps(event)}")
        
        # Custom Resource S3 cleanup logic
        if event.get('RequestType') in ['Create', 'Update', 'Delete'] and 'BucketNames' in event.get('ResourceProperties', {}):
            try:
                if event['RequestType'] == 'Delete':
                    bucket_names = event['ResourceProperties']['BucketNames']
                    for bucket_name in bucket_names:
                        if bucket_name and bucket_name != "NoCloudTrailLogsBucket":
                            empty_bucket(bucket_name)
                send_response(event, context, 'SUCCESS')
            except Exception as e:
                logger.error(f"Failed to empty buckets: {e}")
                send_response(event, context, 'FAILED', reason=str(e))
            return {'statusCode': 200, 'body': 'Custom resource handled'}
        
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
                logger.info(f"Updated path using proxy parameter: {path}")
        
        # Initialize dependencies
        s3_client = boto3.client('s3')
        dynamodb_resource = boto3.resource('dynamodb')
        
        storage_repo = S3StorageRepository(s3_client)
        media_repo = DynamoDBMediaRepository(dynamodb_resource, MEDIA_TABLE)
        qr_repo = DynamoDBQRRepository(dynamodb_resource, QR_MAPPING_TABLE)
        qr_generator = StandardQRGenerator()
        
        media_service = MediaService(storage_repo, media_repo)
        qr_service = QRService(qr_repo, media_repo, storage_repo, qr_generator)
        
        # Handle OpenAPI specification (match stable version)
        if method == 'GET' and (path == '/api/v1' or path == '/api/v1/' or path.rstrip('/') == '/api/v1'):
            logger.info(f"Exact /api/v1 path detected, returning OpenAPI spec: {path}")
            
            # Create OpenAPI object (match stable version structure)
            openapi_spec = {
                "openapi": "3.0.0",
                "info": {
                    "title": "Kiosk Media API",
                    "description": "API for Kiosk Media Solution that provides QR code generation and media upload/download functionality",
                    "version": "1.0.0",
                    "contact": {
                        "name": "DevSecOps, Inc"
                    }
                },
                "servers": [
                    {
                        "url": "/api/v1",
                        "description": "API Gateway endpoint"
                    }
                ],
                "paths": {
                    "/media": {
                        "post": {
                            "summary": "Generate upload URL for media",
                            "description": "Generate a presigned S3 URL for uploading media",
                            "requestBody": {
                                "required": True,
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {
                                                "file_name": {
                                                    "type": "string",
                                                    "description": "Name of the file to upload"
                                                },
                                                "content_type": {
                                                    "type": "string",
                                                    "description": "MIME type of the file"
                                                },
                                                "user_id": {
                                                    "type": "string",
                                                    "description": "User ID (defaults to anonymous)"
                                                },
                                                "theme_options": {
                                                    "type": "object",
                                                    "properties": {
                                                        "background_color": {"type": "string"},
                                                        "text_color": {"type": "string"},
                                                        "accent_color": {"type": "string"},
                                                        "header_text": {"type": "string"},
                                                        "logo_url": {"type": "string"},
                                                        "custom_css": {"type": "string"}
                                                    }
                                                }
                                            },
                                            "required": ["file_name", "content_type"]
                                        }
                                    }
                                }
                            },
                            "responses": {
                                "200": {
                                    "description": "Upload URL generated successfully",
                                    "content": {
                                        "application/json": {
                                            "schema": {
                                                "type": "object",
                                                "properties": {
                                                    "upload_url": {"type": "string"},
                                                    "media_id": {"type": "string"},
                                                    "metadata": {"type": "object"}
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    },
                    "/media/{id}": {
                        "get": {
                            "summary": "Get media information and download URL",
                            "description": "Get information about media and a presigned URL for downloading",
                            "parameters": [
                                {
                                    "name": "id",
                                    "in": "path",
                                    "required": True,
                                    "schema": {"type": "string"},
                                    "description": "Media ID"
                                }
                            ],
                            "responses": {
                                "200": {
                                    "description": "Media information retrieved successfully"
                                },
                                "404": {
                                    "description": "Media not found"
                                }
                            }
                        }
                    },
                    "/qr": {
                        "post": {
                            "summary": "Generate QR code for media",
                            "description": "Generate a QR code for media access",
                            "requestBody": {
                                "required": True,
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {
                                                "media_id": {
                                                    "type": "string",
                                                    "description": "Media ID"
                                                },
                                                "frontend_url": {
                                                    "type": "string",
                                                    "description": "Optional frontend URL to use for QR code"
                                                },
                                                "expires_at": {
                                                    "type": "integer",
                                                    "description": "Expiration timestamp (defaults to 7 days)"
                                                }
                                            },
                                            "required": ["media_id"]
                                        }
                                    }
                                }
                            },
                            "responses": {
                                "200": {
                                    "description": "QR code generated successfully"
                                },
                                "404": {
                                    "description": "Media not found"
                                }
                            }
                        }
                    }
                }
            }
            
            return {
                'statusCode': 200,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*',
                    'Cache-Control': 'no-cache, no-store, must-revalidate'
                },
                'body': json.dumps(openapi_spec)
            }
        
        # Check and detect duplication of /api/v1 path (match stable version)
        if path.endswith('/api/v1/v1'):
            logger.info(f"Detected path duplication: {path}, fixing")
            path = path.replace('/api/v1/v1', '/api/v1')
            logger.info(f"Fixed path: {path}")
            
        # For CloudFront routing to API Gateway through /api/v1/* (match stable version)
        if path.startswith('/api/') and not path.startswith('/api/v1/'):
            logger.info(f"Converting API path: {path} to include v1")
            path = path.replace('/api/', '/api/v1/')
        
        # Normalize the path (match stable version)
        normalized_path = normalize_path(path)
        logger.info(f"Normalized path from {path} to {normalized_path}")
        
        # Extract the base path and ID if present
        path_parts = normalized_path.strip('/').split('/')
        base_path = f"/{path_parts[0]}" if path_parts else "/"
        path_id = path_parts[1] if len(path_parts) > 1 else None
        
        logger.info(f"Base path: {base_path}, Path ID: {path_id}")
        
        # API Root path handling - list available endpoints (match stable version)
        if method == 'GET' and (normalized_path == '/' or normalized_path == ''):
            return {
                'statusCode': 200,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'message': 'Kiosk Media API',
                    'endpoints': {
                        'GET /media/{id}': 'Get media by ID',
                        'POST /media': 'Create new media upload URL',
                        'POST /qr': 'Generate QR code for media'
                    },
                    'version': '1.0'
                })
            }
        
        # Handle media upload request
        if method == 'POST' and base_path == '/media':
            try:
                body = json.loads(event['body']) if event.get('body') else {}
                
                # Extract theme options if provided
                theme_options = None
                if 'theme_options' in body:
                    theme_data = body.pop('theme_options', {})
                    theme_options = ThemeOptions(**theme_data)
                
                metadata = MediaMetadata(**body)
                
                # Apply theme options if provided
                if theme_options:
                    metadata.theme_options = theme_options
                
                result = media_service.create_upload_url(metadata)
                
                return {
                    'statusCode': 200,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps(result)
                }
                
            except Exception as e:
                logger.error(f"Error creating upload URL: {str(e)}")
                return {
                    'statusCode': 400,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({'error': f'Invalid metadata: {str(e)}'})
                }
            
        # Handle media retrieval
        elif method == 'GET' and base_path == '/media' and path_id:
            try:
                media_id = path_id  # No need to URL decode with new UUID format
                result = media_service.get_media_download_url(media_id)
                
                return {
                    'statusCode': 200,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps(result)
                }
                
            except ValueError:
                return {
                    'statusCode': 404,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({'error': 'Media not found'})
                }
            except Exception as e:
                logger.error(f"Error getting media: {str(e)}")
                return {
                    'statusCode': 500,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({'error': 'Internal server error'})
                }
            
        # Handle QR code generation
        elif method == 'POST' and base_path == '/qr':
            try:
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
                
                frontend_url = body.get('frontend_url')
                expires_at = body.get('expires_at')
                
                result = qr_service.generate_qr_code(media_id, frontend_url, expires_at)
                
                return {
                    'statusCode': 200,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps(result)
                }
                
            except ValueError as e:
                return {
                    'statusCode': 404,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({'error': str(e)})
                }
            except Exception as e:
                logger.error(f"Error generating QR: {str(e)}")
                return {
                    'statusCode': 500,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({'error': 'Internal server error'})
                }
        
        # Handle QR code lookup
        elif method == 'GET' and base_path == '/qr' and path_id:
            try:
                code = path_id
                result = qr_service.get_qr_mapping(code)
                
                return {
                    'statusCode': 200,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps(result)
                }
                
            except ValueError as e:
                error_message = str(e)
                if "expired" in error_message:
                    status_code = 410
                else:
                    status_code = 404
                    
                return {
                    'statusCode': status_code,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({'error': error_message})
                }
            except Exception as e:
                logger.error(f"Error getting QR mapping: {str(e)}")
                return {
                    'statusCode': 500,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({'error': 'Internal server error'})
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