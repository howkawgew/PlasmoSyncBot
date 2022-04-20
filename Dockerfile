FROM python:3.9-slim

# Set pip to have cleaner logs and no saved cache
ENV PIP_NO_CACHE_DIR=false

# Create the working directory
WORKDIR /plasmosyncbot

# Install project dependencies

RUN pip install -r requirements.txt

# Set SHA build argument
ARG git_sha="main"

# Copy the source code in next to last to optimize rebuilding the image
COPY . .

# install the package using pep 517
RUN pip install . --no-deps

ENTRYPOINT ["python3"]
CMD ["-m", "plasmosync"]
