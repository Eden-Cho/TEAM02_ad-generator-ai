FROM python:3.10-slim

WORKDIR /app

RUN pip install streamlit requests

COPY . .

EXPOSE 8501

CMD ["streamlit", "run", "app.py", "--server.address", "0.0.0.0"]
