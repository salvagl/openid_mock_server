FROM python:3.9
WORKDIR /app
COPY . .
RUN pip install flask pyjwt
CMD ["python", "server.py"]