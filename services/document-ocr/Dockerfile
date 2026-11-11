# Build the fixed tool layer with runtime.Dockerfile, or use its verified offline image.
ARG OCR_RUNTIME_IMAGE=engramproject/document-ocr-runtime:163
FROM ${OCR_RUNTIME_IMAGE}
WORKDIR /service
COPY server.py extractor.py /service/
ENV DOCUMENT_OCR_WORK_DIR=/work OMP_THREAD_LIMIT=2 OPENBLAS_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1
USER 1000:1000
EXPOSE 18886
ENTRYPOINT ["python", "/service/server.py"]
