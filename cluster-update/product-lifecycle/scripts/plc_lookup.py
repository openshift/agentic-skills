#!/usr/bin/env python3
"""Query Red Hat Product Life Cycle API for support status, EOL dates, and OCP compatibility."""

import argparse
import collections
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

API_BASE = "https://access.redhat.com/product-life-cycles/api/v2/products"


def api_search(name=None):
    """Fetch products from the PLC API, optionally filtering by name."""
    url = API_BASE
    if name:
        url = f"{url}?{urllib.parse.urlencode({'name': name})}"
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


def _normalize_version(version):
    """Normalize to major.minor, stripping leading 'v' (e.g. 'v1.9.0' → '1.9')."""
    version = version.lstrip("v")
    parts = version.split(".")
    return ".".join(parts[:2]) if len(parts) >= 2 else version


def parse_ocp_versions(compat_string):
    if not compat_string:
        return []
    return [v.strip() for v in compat_string.split(",") if v.strip()]


def format_product_version(product, version, target_ocp=None):
    ocp_versions = parse_ocp_versions(version.get("openshift_compatibility"))
    result = {
        "product": product["name"],
        "former_names": product.get("former_names", []),
        "package": product.get("package"),
        "version": version["name"],
        "status": version.get("type", ""),
        "ocp_versions": ocp_versions,
        "phases": [
            {
                "name": ph["name"],
                "start_date": ph.get("start_date"),
                "end_date": ph.get("end_date"),
                "start_date_format": ph.get("start_date_format", "string"),
                "end_date_format": ph.get("end_date_format", "string"),
            }
            for ph in version.get("phases", [])
        ],
    }
    if target_ocp:
        result["ocp_target"] = target_ocp
        result["ocp_compatible"] = target_ocp in ocp_versions if ocp_versions else None
    return result


def cmd_products(args, output=sys.stdout):
    products = api_search(name=args.name)
    if not products:
        json.dump({"error": "no products found", "query": args.name}, output, indent=2)
        output.write("\n")
        return 1

    target_ocp = getattr(args, "ocp", None)
    results = []
    for p in products:
        for v in p["versions"]:
            results.append(format_product_version(p, v, target_ocp=target_ocp))

    out = {"results": results, "total": len(results)}
    if target_ocp:
        out["ocp_target"] = target_ocp
    json.dump(out, output, indent=2)
    output.write("\n")
    return 0


def cmd_olm_check(args, output=sys.stdout):
    operators = json.loads(args.operators)
    target = args.ocp

    all_products = api_search()
    by_package = collections.defaultdict(list)
    for p in all_products:
        pkg = p.get("package")
        if pkg:
            by_package[pkg].append(p)

    results = []

    for op in operators:
        pkg = op.get("package", "")
        requested_version = op.get("version", "")

        if not pkg:
            results.append({"package": pkg, "error": "empty package name"})
            continue

        products = by_package.get(pkg)

        if not products:
            entry = {"package": pkg, "error": "package not found in PLC API"}
            if requested_version:
                entry["requested_version"] = _normalize_version(requested_version)
            results.append(entry)
            continue

        all_versions = {v.get("name") for p in products for v in p["versions"]} - {None}

        if not requested_version:
            results.append({
                "package": pkg,
                "product": products[0]["name"],
                "available_versions": sorted(all_versions),
            })
            continue

        norm = _normalize_version(requested_version)
        matches = []
        for p in products:
            for v in p["versions"]:
                if v.get("name") in (norm, f"{norm}.x"):
                    matches.append((p, v))

        matched = next(
            (m for m in matches if m[1].get("openshift_compatibility")),
            matches[0] if matches else None,
        )

        if not matched:
            results.append({
                "package": pkg,
                "requested_version": norm,
                "error": f"version {norm} not tracked",
                "available_versions": sorted(all_versions),
            })
            continue

        product, version = matched
        formatted = format_product_version(product, version, target_ocp=target)
        results.append({
            "package": pkg,
            "requested_version": norm,
            "product": formatted["product"],
            "status": formatted["status"],
            "ocp_compatible": formatted.get("ocp_compatible"),
            "phases": formatted["phases"],
        })

    json.dump({
        "ocp_target": target,
        "operators_checked": len(operators),
        "lifecycle_unavailable": [r["package"] for r in results if "error" in r],
        "results": results,
    }, output, indent=2)
    output.write("\n")
    return 0


def main(args=None, output=sys.stdout):
    parser = argparse.ArgumentParser(
        description="Query Red Hat Product Life Cycle API for support status, EOL dates, and OCP compatibility.",
        epilog="Examples:\n"
               '  %(prog)s products "logging for Red Hat OpenShift"\n'
               '  %(prog)s products "logging for Red Hat OpenShift" --ocp 4.21\n'
               '  %(prog)s olm-check --ocp 4.21 --operators \'[{"package":"cluster-logging"}]\'\n'
               '  %(prog)s olm-check --ocp 4.21 --operators \'[{"package":"cluster-logging","version":"6.5.1"},{"package":"openshift-pipelines-operator-rh","version":"1.22.0"}]\'\n',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_products = subparsers.add_parser(
        "products",
        help="Query products by name (substring match)",
    )
    p_products.add_argument("name", help="Product name (substring match)")
    p_products.add_argument("--ocp", help="Check compatibility against this OCP version (e.g. 4.21)")

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

    parsed = parser.parse_args(args)
    handlers = {"products": cmd_products, "olm-check": cmd_olm_check}
    return handlers[parsed.command](parsed, output=output)


if __name__ == "__main__":
    sys.exit(main())
