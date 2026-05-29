#!/usr/bin/env python3
"""Query Red Hat Product Life Cycle API for support status, EOL dates, and OCP compatibility."""

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

API_BASE = "https://access.redhat.com/product-life-cycles/api/v2/products"

STATUS_MAP = {
    "Full Support": "supported",
    "Maintenance Support": "maintenance",
    "Extended Support": "extended",
    "End of Maintenance": "end-of-maintenance",
    "End of life": "eol",
}


def api_search(name):
    url = f"{API_BASE}?{urllib.parse.urlencode({'name': name})}"
    req = urllib.request.Request(url, headers={"User-Agent": "plc-lookup/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read())
    except urllib.error.URLError as e:
        raise SystemExit(json.dumps({"error": "api_request_failed", "detail": str(e)}, indent=2))
    except (json.JSONDecodeError, ValueError) as e:
        raise SystemExit(json.dumps({"error": "invalid_response", "detail": str(e)}, indent=2))
    if "data" not in body:
        raise SystemExit(json.dumps({"error": "unexpected_response", "keys": list(body.keys())}, indent=2))
    return body["data"]


def normalize_status(raw_type):
    return STATUS_MAP.get(raw_type, "unknown")


def parse_ocp_versions(compat_string):
    if not compat_string:
        return []
    return [v.strip() for v in compat_string.split(",") if v.strip()]


def extract_phase_date(version, phase_name):
    for ph in version.get("phases", []):
        if ph["name"].lower() == phase_name.lower():
            fmt = ph.get("end_date_format", "string")
            return {"date": ph["end_date"], "format": fmt}
    return None


def format_product_version(product, version, target_ocp=None):
    ocp_versions = parse_ocp_versions(version.get("openshift_compatibility"))
    result = {
        "product": product["name"],
        "package": product.get("package"),
        "version": version["name"],
        "status": normalize_status(version.get("type", "")),
        "status_raw": version.get("type", ""),
        "ocp_versions": ocp_versions,
        "ga_date": extract_phase_date(version, "General availability"),
        "full_support_end": extract_phase_date(version, "Full support"),
        "maintenance_end": extract_phase_date(version, "Maintenance support"),
    }
    if target_ocp:
        result["ocp_target"] = target_ocp
        result["ocp_compatible"] = target_ocp in ocp_versions if ocp_versions else None
    return result


def paginate(results, limit, offset):
    total = len(results)
    start = min(offset, total)
    end = min(start + limit, total) if limit else total
    page = results[start:end]
    meta = {"total": total, "offset": start, "limit": limit, "returned": len(page)}
    if end < total:
        meta["next_offset"] = end
    return page, meta


def cmd_products(args):
    products = api_search(args.name)
    if not products:
        json.dump({"error": "no products found", "query": args.name}, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 1

    target_ocp = getattr(args, "ocp", None)
    results = []
    for p in products:
        for v in p["versions"]:
            results.append(format_product_version(p, v, target_ocp=target_ocp))

    page, meta = paginate(results, args.limit, args.offset)
    output = {"results": page, **meta}
    if target_ocp:
        output["ocp_target"] = target_ocp
    json.dump(output, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def cmd_olm_check(args):
    operators = json.loads(args.operators)
    target = args.ocp

    batch = api_search("OpenShift")
    by_package = {}
    for p in batch:
        pkg = p.get("package")
        if pkg:
            by_package[pkg] = p

    results = []
    missed_packages = []

    for op in operators:
        pkg = op.get("package", "")
        product = by_package.get(pkg)

        if not product:
            extra = api_search(pkg)
            product = next((p for p in extra if p.get("package") == pkg), None)

        if not product:
            results.append({
                "package": pkg,
                "status": "unavailable",
                "reason": "no lifecycle data found",
            })
            missed_packages.append(pkg)
            continue

        for v in product["versions"]:
            results.append(format_product_version(product, v, target_ocp=target))

    json.dump({
        "ocp_target": target,
        "operators_checked": len(operators),
        "lifecycle_unavailable": missed_packages,
        "results": results,
    }, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Query Red Hat Product Life Cycle API (v2) for support status, EOL dates, and OCP compatibility.",
        epilog="Examples:\n"
               '  %(prog)s products "logging for Red Hat OpenShift"\n'
               '  %(prog)s products "logging for Red Hat OpenShift" --ocp 4.21\n'
               '  %(prog)s products "OpenShift" --limit 5\n'
               '  %(prog)s products "OpenShift" --limit 5 --offset 5\n'
               '  %(prog)s olm-check --ocp 4.21 --operators \'[{"package":"cluster-logging"}]\'\n',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_products = subparsers.add_parser(
        "products",
        help="Query products by name. Maps to GET /v2/products?name=<name>",
    )
    p_products.add_argument("name", help="Product name (substring match, e.g. 'logging for Red Hat OpenShift')")
    p_products.add_argument("--ocp", help="Check compatibility against this OCP version (e.g. 4.21)")
    p_products.add_argument("--limit", type=int, default=0, help="Max results to return (0 = all, default: all)")
    p_products.add_argument("--offset", type=int, default=0, help="Skip this many results (for pagination, default: 0)")

    p_olm = subparsers.add_parser(
        "olm-check",
        help="Batch check OLM operators against a target OCP version",
    )
    p_olm.add_argument("--ocp", required=True, help="Target OCP version (e.g. 4.21)")
    p_olm.add_argument(
        "--operators",
        required=True,
        help='JSON array of operators, e.g. \'[{"package":"cluster-logging"}]\'',
    )

    args = parser.parse_args()
    handlers = {"products": cmd_products, "olm-check": cmd_olm_check}
    sys.exit(handlers[args.command](args))


if __name__ == "__main__":
    main()
