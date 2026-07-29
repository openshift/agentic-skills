FROM registry.access.redhat.com/ubi9/ubi-minimal:latest AS builder

RUN mkdir -p /cincinnati-graph-data && \
    curl -L -o /cincinnati-graph-data/products.json https://access.redhat.com/product-life-cycles/api/v2/products || true

FROM scratch
COPY --from=builder /cincinnati-graph-data /cincinnati-graph-data
COPY . /skills/

LABEL distribution-scope="public" \
      url="https://github.com/openshift/agentic-skills"
