import json
import os
import logging
import boto3
import uuid
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
import qrcode
from io import BytesIO
import base64
import urllib.parse
from pydantic import BaseModel, Field
from decimal import Decimal

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize AWS clients
s3 = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')
# Add marketplace metering client
marketplace_metering = boto3.client('meteringmarketplace')

# Get environment variables
MEDIA_BUCKET = os.environ['MEDIA_BUCKET']
MEDIA_TABLE = os.environ['MEDIA_TABLE']
USER_TABLE = os.environ['USER_TABLE']
QR_MAPPING_TABLE = os.environ['QR_MAPPING_TABLE']
MARKETPLACE_CUSTOMERS_TABLE = os.environ['MARKETPLACE_CUSTOMERS_TABLE']
MEDIA_EXPIRATION_DAYS = int(os.environ['MEDIA_EXPIRATION_DAYS'])
MPS_REGISTRATION_TOKEN = os.environ.get('MPS_REGISTRATION_TOKEN', '')

# Initialize DynamoDB tables
media_table = dynamodb.Table(MEDIA_TABLE)
user_table = dynamodb.Table(USER_TABLE)
qr_mapping_table = dynamodb.Table(QR_MAPPING_TABLE)
marketplace_customers_table = dynamodb.Table(MARKETPLACE_CUSTOMERS_TABLE)

# Global flag to track if marketplace token has been processed
_marketplace_token_processed = False

class ThemeOptions(BaseModel):
    background_color: Optional[str] = Field(default=None)
    text_color: Optional[str] = Field(default=None)
    accent_color: Optional[str] = Field(default=None)
    header_text: Optional[str] = Field(default=None)
    logo_url: Optional[str] = Field(default=None)
    custom_css: Optional[str] = Field(default=None)

class MediaMetadata(BaseModel):
    file_name: str
    content_type: str
    user_id: str = Field(default="anonymous")
    expires_at: int = Field(default_factory=lambda: int((datetime.now() + timedelta(days=MEDIA_EXPIRATION_DAYS)).timestamp()))
    theme_options: Optional[ThemeOptions] = Field(default=None)

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

def generate_presigned_url(bucket: str, key: str, operation: str, expires_in: int = 3600, response_headers: Dict[str, str] = None) -> str:
    """Generate a presigned URL for S3 operations."""
    try:
        logger.info(f"Generating presigned URL: bucket={bucket}, key={key}, operation={operation}")
        params = {'Bucket': bucket, 'Key': key}
        
        # Add response headers if provided
        if response_headers:
            params.update(response_headers)
            logger.info(f"Adding response headers: {response_headers}")
            
        url = s3.generate_presigned_url(
            ClientMethod=operation,
            Params=params,
            ExpiresIn=expires_in
        )
        
        # Log the generated URL
        safe_url = url[:50] + '...' if len(url) > 50 else url
        logger.info(f"Generated presigned URL: {safe_url}")
        
        # Make sure the URL is properly encoded
        # URL format should be: https://bucket.s3.amazonaws.com/key?params
        # AWS SDK should handle encoding properly, but we can add extra verification here
        if '%' in key and '%25' not in url:
            logger.warning(f"Key contains percent signs that might not be properly encoded: {key}")
        
        # Return the URL
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
        
        # Add theme options if provided
        if metadata.theme_options:
            theme_dict = metadata.theme_options.dict(exclude_none=True)
            if theme_dict:
                item['theme_options'] = theme_dict
        
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

def generate_media_path(media_id: str, file_name: str) -> str:
    """Generate a path for media storage with simplified date-based structure."""
    now = datetime.now()
    date_string = now.strftime("%Y-%m-%d")
    
    # Extract just the filename without path if file_name includes path
    base_file_name = os.path.basename(file_name)
    
    # Create simplified path: media/YYYY-MM-DD/media_id/file_name
    # Keep the "media/" prefix for compatibility
    return f"media/{date_string}/{media_id}/{base_file_name}"

def resolve_marketplace_customer(registration_token: str) -> Optional[Dict[str, Any]]:
    """
    Resolve customer information from AWS Marketplace using registration token.
    
    Args:
        registration_token: Token received from AWS Marketplace fulfillment URL
        
    Returns:
        Dictionary with customer information or None if failed
    """
    try:
        # Check if token is URL-encoded and decode if needed
        if '%' in registration_token:
            logger.info("Token appears to be URL-encoded, decoding it")
            registration_token = urllib.parse.unquote(registration_token)
        
        logger.info(f"Resolving marketplace customer with token: {registration_token[:10]}...")
        
        response = marketplace_metering.resolve_customer(
            RegistrationToken=registration_token
        )
        
        logger.info(f"Raw marketplace response: {json.dumps(response)}")
        
        customer_data = {
            'customer_identifier': response['CustomerIdentifier'],
            'product_code': response['ProductCode'],
            'customer_aws_account_id': response.get('CustomerAWSAccountId', ''),
            'resolved_at': datetime.now().isoformat()
        }
        
        logger.info(f"Successfully resolved customer: {customer_data['customer_identifier']}")
        return customer_data
        
    except Exception as e:
        logger.error(f"Failed to resolve marketplace customer: {str(e)}")
        logger.error(f"Token used (first 10 chars): {registration_token[:10] if registration_token else 'None'}")
        return None

def store_marketplace_customer(customer_data: Dict[str, Any], user_id: str = "anonymous") -> bool:
    """
    Store marketplace customer mapping in DynamoDB users table.
    
    Args:
        customer_data: Customer information from ResolveCustomer API
        user_id: Internal user ID to associate with marketplace customer
        
    Returns:
        True if stored successfully, False otherwise
    """
    try:
        item = {
            'pk': f"MARKETPLACE#{customer_data['customer_identifier']}",
            'sk': f"USER#{user_id}",
            'type': 'marketplace_customer',
            'customer_identifier': customer_data['customer_identifier'],
            'product_code': customer_data['product_code'],
            'customer_aws_account_id': customer_data['customer_aws_account_id'],
            'user_id': user_id,
            'created_at': datetime.now().isoformat(),
            'last_validated_at': customer_data['resolved_at'],
            'status': 'active'
        }
        
        marketplace_customers_table.put_item(Item=item)
        logger.info(f"Stored marketplace customer mapping: {customer_data['customer_identifier']} -> {user_id}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to store marketplace customer: {str(e)}")
        return False

def validate_marketplace_access(user_id: str = "anonymous") -> bool:
    """
    Validate if user has active marketplace subscription.
    
    Args:
        user_id: Internal user ID to check
        
    Returns:
        True if user has valid marketplace access, False otherwise
    """
    try:
        from boto3.dynamodb.conditions import Key, Attr
        
        # Query for marketplace customer records for this user
        response = marketplace_customers_table.query(
            IndexName='GSI_TypeIndex',
            KeyConditionExpression=Key('type').eq('marketplace_customer'),
            FilterExpression=Attr('user_id').eq(user_id) & Attr('status').eq('active')
        )
        
        if not response['Items']:
            logger.warning(f"No active marketplace subscription found for user: {user_id}")
            return False
            
        # Check if subscription is still valid (last validated within 24 hours)
        customer_record = response['Items'][0]
        last_validated = datetime.fromisoformat(customer_record['last_validated_at'])
        
        if datetime.now() - last_validated > timedelta(hours=24):
            logger.warning(f"Marketplace subscription needs revalidation for user: {user_id}")
            # TODO: Implement periodic revalidation via ResolveCustomer
            return False
            
        logger.info(f"Valid marketplace subscription found for user: {user_id}")
        return True
        
    except Exception as e:
        logger.error(f"Error validating marketplace access: {str(e)}")
        return False

def initialize_marketplace_token() -> None:
    """Initialize marketplace token automatically on Lambda cold start."""
    global _marketplace_token_processed
    
    if _marketplace_token_processed:
        logger.info("Marketplace token already processed, skipping initialization")
        return
    
    if not MPS_REGISTRATION_TOKEN or MPS_REGISTRATION_TOKEN.strip() == '':
        logger.info("No marketplace registration token provided - skipping marketplace initialization")
        _marketplace_token_processed = True
        return
    
    try:
        logger.info(f"Initializing marketplace token from environment variable (token length: {len(MPS_REGISTRATION_TOKEN)})")
        
        # Resolve the customer using the token
        logger.info("Calling resolve_marketplace_customer with token")
        customer_data = resolve_marketplace_customer(MPS_REGISTRATION_TOKEN)
        
        if customer_data:
            logger.info(f"Successfully resolved customer data: {json.dumps(customer_data)}")
            # Store the customer data
            if store_marketplace_customer(customer_data, "anonymous"):
                logger.info(f"Successfully processed marketplace token for customer: {customer_data.get('customer_identifier', 'unknown')}")
            else:
                logger.warning("Failed to store marketplace customer data")
        else:
            logger.warning("Failed to resolve marketplace customer from token")
        
        _marketplace_token_processed = True
        
    except Exception as e:
        logger.error(f"Error processing marketplace token during initialization: {str(e)}")
        # Set the flag to prevent retry on every request
        _marketplace_token_processed = True

def create_pause_mode_response(message: str = "Marketplace subscription required") -> Dict[str, Any]:
    """
    Create a standardized response for when marketplace subscription is required.
    
    Args:
        message: Custom message to display
        
    Returns:
        HTTP 403 response with marketplace registration information
    """
    return {
        'statusCode': 403,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token',
            'Access-Control-Allow-Methods': 'GET,POST,OPTIONS'
        },
        'body': json.dumps({
            'error': 'marketplace_subscription_required',
            'message': message,
            'registration_url': 'https://devsecopsinc.io/products/photo-kiosk-backend/user-guide#completing-deployment',
            'details': 'Please complete AWS Marketplace subscription to access this service.'
        })
    }

def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Main Lambda handler."""
    try:
        # Initialize marketplace token if not already processed
        initialize_marketplace_token()
        
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
                logger.info(f"Updated path using proxy parameter: {path}")
        
        # For exact /api/v1 path or variations, process here before path transformations
        if method == 'GET' and (path == '/api/v1' or path == '/api/v1/' or path.rstrip('/') == '/api/v1'):
            logger.info(f"Exact /api/v1 path detected, avoiding path conversion: {path}")
            
            # Create OpenAPI object using Python dictionaries and lists
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
                                    "description": "Media information retrieved successfully",
                                    "content": {
                                        "application/json": {
                                            "schema": {
                                                "type": "object",
                                                "properties": {
                                                    "download_url": {"type": "string"},
                                                    "metadata": {"type": "object"}
                                                }
                                            }
                                        }
                                    }
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
                                    "description": "QR code generated successfully",
                                    "content": {
                                        "application/json": {
                                            "schema": {
                                                "type": "object",
                                                "properties": {
                                                    "qr_code": {"type": "string"},
                                                    "media_id": {"type": "string"},
                                                    "mapping": {"type": "object"}
                                                }
                                            }
                                        }
                                    }
                                },
                                "404": {
                                    "description": "Media not found"
                                }
                            }
                        }
                    },
                    "/qr/{id}": {
                        "get": {
                            "summary": "Get QR code mapping",
                            "description": "Get information about a QR code mapping",
                            "parameters": [
                                {
                                    "name": "id",
                                    "in": "path",
                                    "required": True,
                                    "schema": {"type": "string"},
                                    "description": "QR code ID"
                                }
                            ],
                            "responses": {
                                "200": {
                                    "description": "QR code mapping retrieved successfully",
                                    "content": {
                                        "application/json": {
                                            "schema": {
                                                "type": "object",
                                                "properties": {
                                                    "url": {"type": "string"},
                                                    "created_at": {"type": "string"},
                                                    "expires_at": {"type": "integer"},
                                                    "status": {"type": "string"}
                                                }
                                            }
                                        }
                                    }
                                },
                                "404": {
                                    "description": "QR code not found"
                                },
                                "410": {
                                    "description": "QR code has expired"
                                }
                            }
                        }
                    }
                },
                "components": {
                    "schemas": {
                        "MediaMetadata": {
                            "type": "object",
                            "properties": {
                                "file_name": {"type": "string"},
                                "content_type": {"type": "string"},
                                "user_id": {"type": "string"},
                                "expires_at": {"type": "integer"},
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
                            }
                        }
                    }
                }
            }
            
            # Convert dictionary to JSON and return response
            return {
                'statusCode': 200,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*',
                    'Cache-Control': 'no-cache, no-store, must-revalidate'
                },
                'body': json.dumps(openapi_spec)
            }
        
        # Check and detect duplication of /api/v1 path
        if path.endswith('/api/v1/v1'):
            logger.info(f"Detected path duplication: {path}, fixing")
            path = path.replace('/api/v1/v1', '/api/v1')
            logger.info(f"Fixed path: {path}")
            
        # For CloudFront routing to API Gateway through /api/v1/*
        if path.startswith('/api/') and not path.startswith('/api/v1/'):
            logger.info(f"Converting API path: {path} to include v1")
            path = path.replace('/api/', '/api/v1/')
        
        # Normalize the path
        normalized_path = normalize_path(path)
        logger.info(f"Normalized path from {path} to {normalized_path}")
        
        # Extract the base path and ID if present
        path_parts = normalized_path.strip('/').split('/')
        base_path = f"/{path_parts[0]}" if path_parts else "/"
        path_id = path_parts[1] if len(path_parts) > 1 else None
        
        logger.info(f"Base path: {base_path}, Path ID: {path_id}")
        
        # API Root path handling - list available endpoints
        if (method == 'GET' and (normalized_path == '/' or normalized_path == '')):
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
            body = json.loads(event['body']) if event.get('body') else {}
            
            # Extract user_id for marketplace validation
            user_id = body.get('user_id', 'anonymous')
            
            # Validate marketplace subscription for protected endpoints
            if not validate_marketplace_access(user_id):
                logger.warning(f"Marketplace access denied for user: {user_id}")
                return create_pause_mode_response("AWS Marketplace subscription required for media upload")
            
            # Extract theme options if provided
            theme_options = None
            if 'theme_options' in body:
                theme_data = body.pop('theme_options', {})
                theme_options = ThemeOptions(**theme_data)
            
            metadata = MediaMetadata(**body)
            
            # Apply theme options if provided
            if theme_options:
                metadata.theme_options = theme_options
                
            # Strip any path from the filename - only use basename
            file_name = os.path.basename(metadata.file_name)
            metadata.file_name = file_name
            
            # Generate media_id using UUID instead of base64 to avoid special characters
            # This ensures we don't have any URL encoding issues with + / = characters
            media_id = str(uuid.uuid4()).replace('-', '')
            
            # Log the generated ID
            logger.info(f"Generated media_id: {media_id}")
            
            file_path = generate_media_path(media_id, file_name)
            upload_url = generate_presigned_url(MEDIA_BUCKET, file_path, 'put_object')
            
            metadata_item = store_media_metadata(metadata, media_id)
            
            # Store the file path in metadata for later retrieval
            metadata_item['file_path'] = file_path
            media_table.update_item(
                Key={'pk': f"MEDIA#{media_id}", 'sk': f"METADATA#{file_name}"},
                UpdateExpression="SET file_path = :file_path",
                ExpressionAttributeValues={':file_path': file_path}
            )
            
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
            # URL decode the media_id from the path parameter only once
            # Since we now use UUID, we likely won't have encoding issues
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
            
            # Use stored file_path if available, otherwise generate path
            if 'file_path' in item:
                file_path = item['file_path']
            else:
                # Generate file path using the media_id directly (now using UUID)
                file_path = f"media/{media_id}/{item['file_name']}"
                # For newer format with date-based paths
                date_string = datetime.now().strftime("%Y-%m-%d")
                file_path = f"media/{date_string}/{media_id}/{item['file_name']}"
            
            # Add debug info for troubleshooting
            logger.info(f"Media ID: {media_id}")
            logger.info(f"File path: {file_path}")
            
            download_url = generate_presigned_url(
                MEDIA_BUCKET,
                file_path,
                'get_object',
                response_headers={'ResponseContentType': item['content_type']}
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
            user_id = body.get('user_id', 'anonymous')
            
            # Validate marketplace subscription for QR generation
            if not validate_marketplace_access(user_id):
                logger.warning(f"Marketplace access denied for QR generation for user: {user_id}")
                return create_pause_mode_response("AWS Marketplace subscription required for QR code generation")
            
            if not media_id:
                return {
                    'statusCode': 400,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({'error': 'media_id is required'})
                }
            
            # No need to URL decode with new UUID format
            
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
            
            # Check if frontend URL is provided, otherwise use direct S3 link
            frontend_url = body.get('frontend_url', '')
            
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
                
                logger.info(f"Using normalized frontend URL for QR code: {url_to_use}")
            else:
                # Use direct S3 download link
                # Use stored file_path if available, otherwise generate path
                if 'file_path' in item:
                    file_path = item['file_path']
                else:
                    # Generate a path using UUID (no special characters)
                    date_string = datetime.now().strftime("%Y-%m-%d")
                    file_path = f"media/{date_string}/{media_id}/{item['file_name']}"
                
                url_to_use = generate_presigned_url(
                    MEDIA_BUCKET,
                    file_path,
                    'get_object',
                    expires_in=7*24*3600,  # 7 days
                    response_headers={'ResponseContentType': item['content_type']}
                )
                logger.info(f"Using direct S3 URL for QR code: {url_to_use}")
            
            qr_code = generate_qr_code(url_to_use)
            mapping = create_qr_mapping(media_id, url_to_use, expires_at)
            
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
            
        # Handle marketplace customer registration
        elif method == 'POST' and base_path == '/marketplace' and path_id == 'register':
            body = json.loads(event['body']) if event.get('body') else {}
            registration_token = body.get('registration_token')
            user_id = body.get('user_id', 'anonymous')
            
            if not registration_token:
                return {
                    'statusCode': 400,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
                        'error': 'registration_token is required',
                        'message': 'Please provide the registration token from AWS Marketplace fulfillment URL'
                    })
                }
            
            # Resolve customer using AWS Marketplace API
            customer_data = resolve_marketplace_customer(registration_token)
            
            if not customer_data:
                return {
                    'statusCode': 400,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
                        'error': 'invalid_registration_token',
                        'message': 'Failed to resolve customer information from AWS Marketplace'
                    })
                }
            
            # Store marketplace customer mapping
            success = store_marketplace_customer(customer_data, user_id)
            
            if not success:
                return {
                    'statusCode': 500,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
                        'error': 'registration_failed',
                        'message': 'Failed to store marketplace customer information'
                    })
                }
            
            return {
                'statusCode': 200,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'message': 'Successfully registered with AWS Marketplace',
                    'customer_identifier': customer_data['customer_identifier'],
                    'product_code': customer_data['product_code'],
                    'user_id': user_id
                })
            }
            
        # Handle marketplace subscription validation
        elif method == 'GET' and base_path == '/marketplace' and path_id == 'validate':
            query_params = event.get('queryStringParameters') or {}
            user_id = query_params.get('user_id', 'anonymous')
            
            is_valid = validate_marketplace_access(user_id)
            
            return {
                'statusCode': 200,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'valid': is_valid,
                    'user_id': user_id,
                    'message': 'Subscription is active' if is_valid else 'No active marketplace subscription found'
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