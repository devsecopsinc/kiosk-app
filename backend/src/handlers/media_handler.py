"""
Kiosk Media Handler with proper OOP architecture.

This module follows SOLID principles and Clean Architecture patterns:
- Single Responsibility Principle
- Dependency Injection
- Repository Pattern
- Service Layer Pattern
- Strategy Pattern
"""

import json
import os
import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Protocol
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum

import boto3
import uuid
import qrcode
from io import BytesIO
import base64
from pydantic import BaseModel, Field
from decimal import Decimal


# =============================================================================
# DOMAIN MODELS (Data Transfer Objects)
# =============================================================================

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
    expires_at: Optional[int] = Field(default=None)
    theme_options: Optional[ThemeOptions] = Field(default=None)

    def __init__(self, **data):
        super().__init__(**data)
        if self.expires_at is None:
            expiration_days = int(os.environ.get('MEDIA_EXPIRATION_DAYS', '7'))
            self.expires_at = int((datetime.now() + timedelta(days=expiration_days)).timestamp())


@dataclass(frozen=True)
class MediaItem:
    """Immutable media item representation."""
    media_id: str
    file_name: str
    content_type: str
    user_id: str
    file_path: str
    created_at: datetime
    expires_at: int
    status: str = "active"
    theme_options: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class QRMapping:
    """Immutable QR code mapping representation."""
    media_id: str
    url: str
    created_at: datetime
    expires_at: int
    status: str = "active"


class UsageDimension(Enum):
    """Marketplace usage dimensions."""
    MEDIA_UPLOAD = "Media_Upload"
    MEDIA_DOWNLOAD = "Media_Download"
    QR_CODE_GENERATION = "QR_Code_Generation"
    USAGE_HOURS = "Usage_Hours"


# =============================================================================
# INTERFACES / PROTOCOLS
# =============================================================================

class StorageRepository(Protocol):
    """Protocol for storage operations."""
    
    def generate_upload_url(self, bucket: str, key: str, expires_in: int = 3600) -> str:
        """Generate presigned upload URL."""
        ...
    
    def generate_download_url(self, bucket: str, key: str, content_type: str, expires_in: int = 3600) -> str:
        """Generate presigned download URL."""
        ...


class MediaRepository(Protocol):
    """Protocol for media metadata operations."""
    
    def save_media_metadata(self, media_item: MediaItem) -> Dict[str, Any]:
        """Save media metadata."""
        ...
    
    def get_media_by_id(self, media_id: str) -> Optional[MediaItem]:
        """Get media by ID."""
        ...
    
    def update_file_path(self, media_id: str, file_name: str, file_path: str) -> None:
        """Update file path for media."""
        ...


class QRRepository(Protocol):
    """Protocol for QR code operations."""
    
    def save_qr_mapping(self, qr_mapping: QRMapping) -> Dict[str, Any]:
        """Save QR code mapping."""
        ...
    
    def get_qr_mapping(self, code: str) -> Optional[QRMapping]:
        """Get QR mapping by code."""
        ...


class MarketplaceService(Protocol):
    """Protocol for marketplace operations."""
    
    def check_subscription(self) -> Dict[str, Any]:
        """Check marketplace subscription status."""
        ...
    
    def report_usage(self, dimension: UsageDimension, quantity: int = 1) -> bool:
        """Report usage to marketplace."""
        ...


class QRCodeGenerator(Protocol):
    """Protocol for QR code generation."""
    
    def generate(self, url: str) -> str:
        """Generate QR code as base64 string."""
        ...


# =============================================================================
# CONCRETE IMPLEMENTATIONS
# =============================================================================

class AWSStorageRepository:
    """AWS S3 storage implementation."""
    
    def __init__(self, s3_client):
        self._s3 = s3_client
        self._logger = logging.getLogger(__name__)
    
    def generate_upload_url(self, bucket: str, key: str, expires_in: int = 3600) -> str:
        """Generate presigned upload URL."""
        try:
            self._logger.info(f"Generating upload URL: bucket={bucket}, key={key}")
            return self._s3.generate_presigned_url(
                'put_object',
                Params={'Bucket': bucket, 'Key': key},
                ExpiresIn=expires_in
            )
        except Exception as e:
            self._logger.error(f"Error generating upload URL: {str(e)}")
            raise
    
    def generate_download_url(self, bucket: str, key: str, content_type: str, expires_in: int = 3600) -> str:
        """Generate presigned download URL."""
        try:
            self._logger.info(f"Generating download URL: bucket={bucket}, key={key}")
            return self._s3.generate_presigned_url(
                'get_object',
                Params={
                    'Bucket': bucket, 
                    'Key': key,
                    'ResponseContentType': content_type
                },
                ExpiresIn=expires_in
            )
        except Exception as e:
            self._logger.error(f"Error generating download URL: {str(e)}")
            raise


class DynamoDBMediaRepository:
    """DynamoDB media metadata implementation."""
    
    def __init__(self, table):
        self._table = table
        self._logger = logging.getLogger(__name__)
    
    def save_media_metadata(self, media_item: MediaItem) -> Dict[str, Any]:
        """Save media metadata to DynamoDB."""
        try:
            item = {
                'pk': f"MEDIA#{media_item.media_id}",
                'sk': f"METADATA#{media_item.file_name}",
                'user_id': media_item.user_id,
                'file_name': media_item.file_name,
                'content_type': media_item.content_type,
                'created_at': media_item.created_at.isoformat(),
                'expires_at': media_item.expires_at,
                'status': media_item.status,
                'file_path': media_item.file_path
            }
            
            if media_item.theme_options:
                item['theme_options'] = media_item.theme_options
            
            self._table.put_item(Item=item)
            return item
        except Exception as e:
            self._logger.error(f"Error saving media metadata: {str(e)}")
            raise
    
    def get_media_by_id(self, media_id: str) -> Optional[MediaItem]:
        """Get media by ID from DynamoDB."""
        try:
            response = self._table.query(
                KeyConditionExpression='pk = :pk AND begins_with(sk, :sk)',
                ExpressionAttributeValues={
                    ':pk': f"MEDIA#{media_id}",
                    ':sk': 'METADATA#'
                }
            )
            
            if not response.get('Items'):
                return None
            
            item = response['Items'][0]
            return MediaItem(
                media_id=media_id,
                file_name=item['file_name'],
                content_type=item['content_type'],
                user_id=item['user_id'],
                file_path=item.get('file_path', f"media/{media_id}/{item['file_name']}"),
                created_at=datetime.fromisoformat(item['created_at']),
                expires_at=int(item['expires_at']),  # Convert Decimal to int
                status=item.get('status', 'active'),
                theme_options=item.get('theme_options')
            )
        except Exception as e:
            self._logger.error(f"Error getting media by ID: {str(e)}")
            raise
    
    def update_file_path(self, media_id: str, file_name: str, file_path: str) -> None:
        """Update file path for media."""
        try:
            self._table.update_item(
                Key={'pk': f"MEDIA#{media_id}", 'sk': f"METADATA#{file_name}"},
                UpdateExpression="SET file_path = :file_path",
                ExpressionAttributeValues={':file_path': file_path}
            )
        except Exception as e:
            self._logger.error(f"Error updating file path: {str(e)}")
            raise


class DynamoDBQRRepository:
    """DynamoDB QR mapping implementation."""
    
    def __init__(self, table):
        self._table = table
        self._logger = logging.getLogger(__name__)
    
    def save_qr_mapping(self, qr_mapping: QRMapping) -> Dict[str, Any]:
        """Save QR mapping to DynamoDB."""
        try:
            item = {
                'pk': f"QR#{qr_mapping.media_id}",
                'sk': 'MAPPING',
                'url': qr_mapping.url,
                'created_at': qr_mapping.created_at.isoformat(),
                'expires_at': qr_mapping.expires_at,
                'status': qr_mapping.status
            }
            
            self._table.put_item(Item=item)
            return item
        except Exception as e:
            self._logger.error(f"Error saving QR mapping: {str(e)}")
            raise
    
    def get_qr_mapping(self, code: str) -> Optional[QRMapping]:
        """Get QR mapping by code."""
        try:
            response = self._table.get_item(
                Key={'pk': f"QR#{code}", 'sk': 'MAPPING'}
            )
            
            if 'Item' not in response:
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
            self._logger.error(f"Error getting QR mapping: {str(e)}")
            raise


class AWSMarketplaceService:
    """AWS Marketplace service implementation."""
    
    def __init__(self, marketplace_client):
        self._marketplace = marketplace_client
        self._logger = logging.getLogger(__name__)
        self._cache = {'status': None, 'timestamp': 0}
        self._cache_ttl = 3600  # 1 hour
    
    def check_subscription(self) -> Dict[str, Any]:
        """Check marketplace subscription with caching."""
        now = datetime.now().timestamp()
        
        if (self._cache['status'] and 
            now - self._cache['timestamp'] < self._cache_ttl):
            return self._cache['status']
        
        try:
            # Try to get marketplace registration token from environment
            registration_token = os.environ.get('MARKETPLACE_REGISTRATION_TOKEN')
            
            if not registration_token:
                # No token means not subscribed through marketplace
                status = {
                    'is_subscribed': False,
                    'customer_id': "anonymous",
                    'message': "No marketplace registration token found"
                }
                self._cache = {'status': status, 'timestamp': now}
                return status
            
            # Resolve customer using registration token (proper AWS approach)
            self._logger.info("Resolving marketplace customer with registration token")
            response = self._marketplace.resolve_customer(
                RegistrationToken=registration_token
            )
            
            customer_identifier = response.get('CustomerIdentifier')
            if customer_identifier:
                status = {
                    'is_subscribed': True,
                    'customer_id': customer_identifier,
                    'product_code': response.get('ProductCode'),
                    'message': "Active marketplace subscription"
                }
                self._logger.info(f"✅ Marketplace subscription active: customer={customer_identifier}")
            else:
                status = {
                    'is_subscribed': False,
                    'customer_id': "anonymous",
                    'message': "Invalid marketplace registration token"
                }
                self._logger.warning("❌ Marketplace registration token is invalid")
            
            self._cache = {'status': status, 'timestamp': now}
            return status
            
        except Exception as e:
            self._logger.warning(f"Failed to check marketplace subscription: {str(e)}")
            status = {
                'is_subscribed': False,
                'customer_id': "anonymous",
                'message': f"Subscription check failed: {str(e)}"
            }
            self._cache = {'status': status, 'timestamp': now}
            return status
    
    def report_usage(self, dimension: UsageDimension, quantity: int = 1) -> bool:
        """Report usage to AWS Marketplace."""
        try:
            subscription = self.check_subscription()
            
            if not subscription['is_subscribed']:
                self._logger.info("Skipping marketplace usage reporting - no active subscription")
                return False
            
            # Product code comes from ResolveCustomer response, not hardcoded
            product_code = subscription.get('product_code')
            if not product_code:
                self._logger.warning("No product code available from marketplace subscription")
                return False
            
            self._logger.info(f"Reporting marketplace usage: {dimension.value}, quantity={quantity}")
            
            response = self._marketplace.batch_meter_usage(
                UsageRecords=[{
                    'Timestamp': datetime.utcnow(),
                    'CustomerIdentifier': subscription['customer_id'],
                    'Dimension': dimension.value,
                    'Quantity': quantity
                }],
                ProductCode=product_code
            )
            
            self._logger.info(f"Usage reported successfully: {response}")
            return True
            
        except Exception as e:
            self._logger.warning(f"Failed to report marketplace usage: {str(e)}")
            return False


class DefaultQRCodeGenerator:
    """Default QR code generator implementation."""
    
    def __init__(self):
        self._logger = logging.getLogger(__name__)
    
    def generate(self, url: str) -> str:
        """Generate QR code as base64 string."""
        try:
            qr = qrcode.QRCode(version=1, box_size=10, border=5)
            qr.add_data(url)
            qr.make(fit=True)
            
            img = qr.make_image(fill_color="black", back_color="white")
            buffer = BytesIO()
            img.save(buffer, format="PNG")
            
            return base64.b64encode(buffer.getvalue()).decode()
        except Exception as e:
            self._logger.error(f"Error generating QR code: {str(e)}")
            raise


# =============================================================================
# SERVICE LAYER (Business Logic)
# =============================================================================

class MediaService:
    """Media management service."""
    
    def __init__(
        self,
        storage_repo: StorageRepository,
        media_repo: MediaRepository,
        marketplace_service: MarketplaceService
    ):
        self._storage = storage_repo
        self._media = media_repo
        self._marketplace = marketplace_service
        self._logger = logging.getLogger(__name__)
        self._bucket = os.environ['MEDIA_BUCKET']
    
    def create_upload_url(self, metadata: MediaMetadata) -> Dict[str, Any]:
        """Create upload URL for media."""
        # Generate unique media ID
        media_id = str(uuid.uuid4()).replace('-', '')
        
        # Generate file path
        file_name = os.path.basename(metadata.file_name)
        date_string = datetime.now().strftime("%Y-%m-%d")
        file_path = f"media/{date_string}/{media_id}/{file_name}"
        
        # Create media item
        media_item = MediaItem(
            media_id=media_id,
            file_name=file_name,
            content_type=metadata.content_type,
            user_id=metadata.user_id,
            file_path=file_path,
            created_at=datetime.now(),
            expires_at=metadata.expires_at,
            theme_options=metadata.theme_options.model_dump(exclude_none=True) if metadata.theme_options else None
        )
        
        # Generate upload URL
        upload_url = self._storage.generate_upload_url(self._bucket, file_path)
        
        # Save metadata
        saved_item = self._media.save_media_metadata(media_item)
        
        # Report usage
        self._marketplace.report_usage(UsageDimension.MEDIA_UPLOAD)
        
        return {
            'upload_url': upload_url,
            'media_id': media_id,
            'metadata': self._convert_dynamodb_item(saved_item)
        }
    
    def get_media_download_url(self, media_id: str) -> Dict[str, Any]:
        """Get download URL for media."""
        media_item = self._media.get_media_by_id(media_id)
        if not media_item:
            raise ValueError("Media not found")
        
        download_url = self._storage.generate_download_url(
            self._bucket,
            media_item.file_path,
            media_item.content_type
        )
        
        # Report usage
        self._marketplace.report_usage(UsageDimension.MEDIA_DOWNLOAD)
        
        return {
            'download_url': download_url,
            'metadata': self._media_item_to_dict(media_item)
        }
    
    def _convert_dynamodb_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """Convert DynamoDB types to JSON serializable types."""
        if isinstance(item, dict):
            return {k: self._convert_dynamodb_item(v) for k, v in item.items()}
        elif isinstance(item, list):
            return [self._convert_dynamodb_item(i) for i in item]
        elif isinstance(item, Decimal):
            return float(item)
        elif isinstance(item, datetime):
            return item.isoformat()
        else:
            return item
    
    def _media_item_to_dict(self, media_item: MediaItem) -> Dict[str, Any]:
        """Convert MediaItem to dictionary."""
        return {
            'file_name': media_item.file_name,
            'content_type': media_item.content_type,
            'user_id': media_item.user_id,
            'created_at': media_item.created_at.isoformat(),
            'expires_at': media_item.expires_at,
            'status': media_item.status,
            'theme_options': self._convert_dynamodb_item(media_item.theme_options) if media_item.theme_options else None
        }


class QRService:
    """QR code management service."""
    
    def __init__(
        self,
        qr_repo: QRRepository,
        media_repo: MediaRepository,
        storage_repo: StorageRepository,
        qr_generator: QRCodeGenerator,
        marketplace_service: MarketplaceService
    ):
        self._qr_repo = qr_repo
        self._media_repo = media_repo
        self._storage = storage_repo
        self._qr_generator = qr_generator
        self._marketplace = marketplace_service
        self._logger = logging.getLogger(__name__)
        self._bucket = os.environ['MEDIA_BUCKET']
    
    def generate_qr_code(self, media_id: str, frontend_url: Optional[str] = None, expires_at: Optional[int] = None) -> Dict[str, Any]:
        """Generate QR code for media."""
        # Get media info
        media_item = self._media_repo.get_media_by_id(media_id)
        if not media_item:
            raise ValueError("Media not found")
        
        # Determine expiration - ensure we have a valid int
        final_expires_at: int
        if expires_at is None:
            final_expires_at = int((datetime.now() + timedelta(days=7)).timestamp())
        else:
            final_expires_at = expires_at
        
        # Determine URL to use
        if frontend_url:
            url_to_use = self._normalize_frontend_url(frontend_url)
        else:
            url_to_use = self._storage.generate_download_url(
                self._bucket,
                media_item.file_path,
                media_item.content_type,
                expires_in=7*24*3600  # 7 days
            )
        
        # Generate QR code
        qr_code = self._qr_generator.generate(url_to_use)
        
        # Save mapping
        qr_mapping = QRMapping(
            media_id=media_id,
            url=url_to_use,
            created_at=datetime.now(),
            expires_at=final_expires_at
        )
        
        mapping_item = self._qr_repo.save_qr_mapping(qr_mapping)
        
        # Report usage
        self._marketplace.report_usage(UsageDimension.QR_CODE_GENERATION)
        
        return {
            'qr_code': qr_code,
            'media_id': media_id,
            'mapping': self._convert_dynamodb_item(mapping_item)
        }
    
    def get_qr_mapping(self, code: str) -> Dict[str, Any]:
        """Get QR mapping by code."""
        mapping = self._qr_repo.get_qr_mapping(code)
        if not mapping:
            raise ValueError("QR code not found")
        
        # Check if expired
        if mapping.expires_at < int(datetime.now().timestamp()):
            raise ValueError("QR code has expired")
        
        return {
            'url': mapping.url,
            'created_at': mapping.created_at.isoformat(),
            'expires_at': mapping.expires_at,
            'status': mapping.status
        }
    
    def _normalize_frontend_url(self, frontend_url: str) -> str:
        """Normalize frontend URL."""
        if '?' in frontend_url:
            base_url, query_part = frontend_url.split('?', 1)
            if not base_url.endswith('/'):
                base_url = f"{base_url}/"
            return f"{base_url}?{query_part}"
        else:
            if not frontend_url.endswith('/'):
                return f"{frontend_url}/"
            return frontend_url
    
    def _convert_dynamodb_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """Convert DynamoDB types to JSON serializable types."""
        if isinstance(item, dict):
            return {k: self._convert_dynamodb_item(v) for k, v in item.items()}
        elif isinstance(item, list):
            return [self._convert_dynamodb_item(i) for i in item]
        elif isinstance(item, Decimal):
            return float(item)
        elif isinstance(item, datetime):
            return item.isoformat()
        else:
            return item


# =============================================================================
# API LAYER (Controllers)
# =============================================================================

class APIResponse:
    """API response helper."""
    
    @staticmethod
    def success(data: Any, status_code: int = 200) -> Dict[str, Any]:
        """Create success response."""
        return {
            'statusCode': status_code,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*',
                'Cache-Control': 'no-cache, no-store, must-revalidate'
            },
            'body': json.dumps(data)
        }
        
    @staticmethod
    def error(message: str, status_code: int = 400) -> Dict[str, Any]:
        """Create error response."""
        return APIResponse.success({'error': message}, status_code)


class MediaController:
    """Media API controller."""
    
    def __init__(self, media_service: MediaService):
        self._media_service = media_service
        self._logger = logging.getLogger(__name__)
    
    def create_upload_url(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Handle POST /media."""
        try:
            # Validate body
            if not event.get('body'):
                return APIResponse.error('Request body is required', 400)
            
            body = json.loads(event['body'])
            
            # Extract theme options
            theme_options = None
            if 'theme_options' in body:
                theme_data = body.pop('theme_options', {})
                theme_options = ThemeOptions(**theme_data)
            
            # Create metadata
            metadata = MediaMetadata(**body)
            if theme_options:
                metadata.theme_options = theme_options
                
            # Create upload URL
            result = self._media_service.create_upload_url(metadata)
            return APIResponse.success(result)
            
        except json.JSONDecodeError:
            return APIResponse.error('Invalid JSON in request body', 400)
        except Exception as e:
            self._logger.error(f"Error creating upload URL: {str(e)}")
            return APIResponse.error(f'Invalid metadata: {str(e)}', 400)
    
    def get_media(self, media_id: str) -> Dict[str, Any]:
        """Handle GET /media/{id}."""
        try:
            result = self._media_service.get_media_download_url(media_id)
            return APIResponse.success(result)
        except ValueError as e:
            return APIResponse.error(str(e), 404)
        except Exception as e:
            self._logger.error(f"Error getting media: {str(e)}")
            return APIResponse.error('Internal server error', 500)


class QRController:
    """QR code API controller."""
    
    def __init__(self, qr_service: QRService):
        self._qr_service = qr_service
        self._logger = logging.getLogger(__name__)
    
    def generate_qr(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Handle POST /qr."""
        try:
            if not event.get('body'):
                return APIResponse.error('Request body is required', 400)
            
            body = json.loads(event['body'])
            media_id = body.get('media_id')
            
            if not media_id:
                return APIResponse.error('media_id is required', 400)
            
            if not isinstance(media_id, str) or len(media_id) != 32:
                return APIResponse.error('Invalid media_id format', 400)
            
            frontend_url = body.get('frontend_url')
            expires_at = body.get('expires_at')
            
            result = self._qr_service.generate_qr_code(media_id, frontend_url, expires_at)
            return APIResponse.success(result)
            
        except json.JSONDecodeError:
            return APIResponse.error('Invalid JSON in request body', 400)
        except ValueError as e:
            return APIResponse.error(str(e), 404)
        except Exception as e:
            self._logger.error(f"Error generating QR: {str(e)}")
            return APIResponse.error('Internal server error', 500)
    
    def get_qr_mapping(self, code: str) -> Dict[str, Any]:
        """Handle GET /qr/{id}."""
        try:
            result = self._qr_service.get_qr_mapping(code)
            return APIResponse.success(result)
        except ValueError as e:
            error_message = str(e)
            if "expired" in error_message:
                return APIResponse.error(error_message, 410)
            else:
                return APIResponse.error(error_message, 404)
        except Exception as e:
            self._logger.error(f"Error getting QR mapping: {str(e)}")
            return APIResponse.error('Internal server error', 500)


# =============================================================================
# APPLICATION FACTORY & DEPENDENCY INJECTION
# =============================================================================

class ApplicationFactory:
    """Factory for creating application dependencies."""
    
    @staticmethod
    def create_media_controller() -> MediaController:
        """Create media controller with all dependencies."""
        # AWS clients
        s3_client = boto3.client('s3')
        dynamodb = boto3.resource('dynamodb')
        marketplace_client = boto3.client('meteringmarketplace')
        
        # Tables
        media_table = dynamodb.Table(os.environ['MEDIA_TABLE'])
        
        # Repositories
        storage_repo = AWSStorageRepository(s3_client)
        media_repo = DynamoDBMediaRepository(media_table)
        marketplace_service = AWSMarketplaceService(marketplace_client)
        
        # Services
        media_service = MediaService(storage_repo, media_repo, marketplace_service)
        
        # Controller
        return MediaController(media_service)
    
    @staticmethod
    def create_qr_controller() -> QRController:
        """Create QR controller with all dependencies."""
        # AWS clients
        s3_client = boto3.client('s3')
        dynamodb = boto3.resource('dynamodb')
        marketplace_client = boto3.client('meteringmarketplace')
        
        # Tables
        media_table = dynamodb.Table(os.environ['MEDIA_TABLE'])
        qr_table = dynamodb.Table(os.environ['QR_MAPPING_TABLE'])
        
        # Repositories
        storage_repo = AWSStorageRepository(s3_client)
        media_repo = DynamoDBMediaRepository(media_table)
        qr_repo = DynamoDBQRRepository(qr_table)
        marketplace_service = AWSMarketplaceService(marketplace_client)
        qr_generator = DefaultQRCodeGenerator()
        
        # Services
        qr_service = QRService(qr_repo, media_repo, storage_repo, qr_generator, marketplace_service)
        
        # Controller
        return QRController(qr_service)


# =============================================================================
# MAIN HANDLER
# =============================================================================

def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Main Lambda handler with proper dependency injection."""
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    try:
        logger.info(f"Received event: {json.dumps(event)}")
        
        method = event['httpMethod']
        path = event.get('path', '')
        
        # Simple routing (can be extracted to Router class)
        if method == 'POST' and '/media' in path:
            controller = ApplicationFactory.create_media_controller()
            return controller.create_upload_url(event)
        
        elif method == 'GET' and '/media/' in path:
            media_id = path.split('/')[-1]
            controller = ApplicationFactory.create_media_controller()
            return controller.get_media(media_id)
        
        elif method == 'POST' and '/qr' in path:
            controller = ApplicationFactory.create_qr_controller()
            return controller.generate_qr(event)
        
        elif method == 'GET' and '/qr/' in path:
            code = path.split('/')[-1]
            controller = ApplicationFactory.create_qr_controller()
            return controller.get_qr_mapping(code)
        
        else:
            return APIResponse.error('Not found', 404)
            
    except Exception as e:
        logger.error(f"Error processing request: {str(e)}", exc_info=True)
        return APIResponse.error('Internal server error', 500) 