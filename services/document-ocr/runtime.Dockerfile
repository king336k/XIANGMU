# Reproducible reference for the tool base; NOT downloaded/rebuilt in this run.
FROM python@sha256:ae52c5bef62a6bdd42cd1e8dffef86b9cd284bde9427da79839de7a4b983e7ca
RUN apt-get -o Acquire::Retries=0 update \
 && apt-get install -y --no-install-recommends \
    tesseract-ocr=5.5.0-1+b1 tesseract-ocr-chi-sim=1:4.1.0-2 \
    tesseract-ocr-eng=1:4.1.0-2 poppler-utils=25.03.0-5+deb13u4 \
 && rm -rf /var/lib/apt/lists/*
ENV OMP_THREAD_LIMIT=2 OPENBLAS_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1
USER 1000:1000
