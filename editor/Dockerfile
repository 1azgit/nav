FROM python:3.12-alpine
WORKDIR /app
COPY editor/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY . /app/nav
WORKDIR /app/nav
EXPOSE 8080
CMD ["python", "editor/server.py"]
