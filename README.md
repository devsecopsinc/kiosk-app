# Kiosk Media Solution

Frontend and Backend code for Kiosk Media Solution project.

## Project Structure

```
/
├── backend/               # Python backend code
│   ├── Dockerfile         # Docker configuration for local development
│   ├── requirements.txt   # Python dependencies
│   └── src/
│       └── handlers/
│           └── media_handler.py  # Main Lambda handler
└── frontend/              # React TypeScript frontend
    ├── package.json       # npm dependencies
    ├── tsconfig.json      # TypeScript configuration
    ├── public/            # Static assets
    └── src/               # Source code
        ├── App.tsx        # Main React component
        └── index.tsx      # React entry point
```

## Development Setup

### Backend

```bash
# Navigate to backend directory
cd backend

# Create virtual environment (optional but recommended)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run locally (Optional: if you want to test the Lambda function)
# Install AWS SAM CLI: https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/serverless-sam-cli-install.html
sam local invoke -e events/event.json
```

### Frontend

```bash
# Navigate to frontend directory
cd frontend

# Install dependencies
npm install

# Start development server
npm start

# Build for production
npm run build
```

## Deployment

This repository is set up to deploy automatically through AWS CloudFormation using:

1. **Backend:**
   - AWS Lambda (Python)
   - AWS API Gateway
   - DynamoDB for data storage

2. **Frontend:**
   - S3 for hosting
   - CloudFront for CDN

The deployment process uses GitHub integration through AWS CodeStar Connections, CodePipeline and CodeBuild.

### Backend Build Process

```bash
cd backend
pip install -r requirements.txt -t ./package
cp -r src/* package/
cd package
zip -r ../lambda_package.zip .
```

### Frontend Build Process

```bash
cd frontend
npm ci
npm run build
# Sync build/ folder to S3
```

## Environment Variables

### Backend

- `MEDIA_BUCKET_NAME`: S3 bucket for media storage
- `MEDIA_TABLE_NAME`: DynamoDB table for media metadata
- `USER_TABLE_NAME`: DynamoDB table for user data
- `QR_MAPPING_TABLE_NAME`: DynamoDB table for QR code mappings
- `ENVIRONMENT`: Current environment (dev/prod)

### Frontend

- `REACT_APP_API_URL`: API Gateway endpoint URL
- `REACT_APP_ENVIRONMENT`: Current environment (dev/prod)

## License

[Add appropriate license information here]