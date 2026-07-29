#!/bin/bash

# use to save a snapshot of the products lifecycle data locally
curl -L -o data/products.json https://access.redhat.com/product-life-cycles/api/v2/products
