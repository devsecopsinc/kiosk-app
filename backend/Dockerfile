FROM --platform=linux/amd64 public.ecr.aws/lambda/python:3.10

# Copy requirements.txt
COPY requirements.txt ${LAMBDA_TASK_ROOT}

# Install the specified packages
RUN pip install -r requirements.txt

# Copy function code
COPY src/ ${LAMBDA_TASK_ROOT}

# Set the CMD to your handler
CMD [ "handlers/media_handler.handler" ] 