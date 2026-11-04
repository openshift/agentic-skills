#!/bin/bash

# use to save a snapshot of the products lifecycle data locally
dir="$(dirname "$(realpath "$0")")/data"
mkdir -p "$dir" && curl -L -o "$dir/products.json" https://access.redhat.com/product-life-cycles/api/v2/products
