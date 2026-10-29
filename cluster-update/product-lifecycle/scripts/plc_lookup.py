#!/usr/bin/env python3
"""Query Red Hat Product Life Cycle API for support status, EOL dates, and OCP compatibility."""

import argparse
import collections
import json
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import pathlib

_SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)"
    r"(?:-([0-9A-Za-z.-]+))?"
    r"(?:\+([0-9A-Za-z.-]+))?$"
)

API_BASE = "https://access.redhat.com/product-life-cycles/api/v2/products"

def search_local(name=None, path=None):
    try:
        with open(path, "r") as file:
            body = json.loads(file.read())
    except OSError as e:
        raise SystemExit(json.dumps({"error": "file_open_error", "detail": str(e)}, indent=2))
    except (json.JSONDecodeError, ValueError) as e:
        raise SystemExit(json.dumps({"error": "invalid_products_file", "detail": str(e)}, indent=2))
    if "data" not in body:
        raise SystemExit(json.dumps({"error": "malformatted_products_file", "detail": "missing expected field 'data' in products json"}, indent=2))

    if name is None:
        return body["data"]

    # Implemented based on the filtering logic used by the lifecycle api
    # https://gitlab.cee.redhat.com/cplabsapps/lifecycle/-/blob/3e54ac686aab49ebc7732f9fdcd0ada210fbf2bd/apps/lifecycle-api/src/services/productService.ts#L36
    # API implements name as a comma separated url parameter
    # body["data"][]["name"] is a string and body["data"][]["former_names"] is string array that may be empty
    # If at least one of the url parameter specified names is a substring of an entry's name, that entry is included in results
    # If NO results are found after checking all names, fall back to former_names and return entries where
    # at least one of the former_names values has one of the desired name strings.
    names = []
    former_names = []
    cleaned_names = [n.strip() for n in name.lower().split(",") if n.strip()]
    for i in body["data"]:
        match = False
        for n in cleaned_names:
            if match:
                break
            if "name" in i and n in i["name"].lower():
                names.append(i)
                break
            for fname in (i.get("former_names") or []):
                if n in fname.lower():
                    former_names.append(i)
                    match = True
                    break
    if len(names) > 0:
        return names
    else:
        return former_names


def api_search(name=None, local_products_json_file=None):
    """Fetch products from the PLC API, optionally filtering by name."""
    if local_products_json_file is not None:
        return search_local(name, local_products_json_file)
    url = API_BASE
    if name:
        url = f"{url}?{urllib.parse.urlencode({'name': name, 'match_mode':'contains'})}"
    req = urllib.request.Request(url, headers={"User-Agent": "plc-lookup/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read())
    except urllib.error.URLError as e:
        raise SystemExit(json.dumps({"error": "api_request_failed", "detail": str(e)}, indent=2))
    except (json.JSONDecodeError, ValueError) as e:
        raise SystemExit(json.dumps({"error": "invalid_response", "detail": str(e)}, indent=2))
    if "data" not in body:
        raise SystemExit(json.dumps({"error": "unexpected_response", "detail": "missing expected key 'data' in response", "keys": list(body.keys())}, indent=2))
    return body["data"]


def _plc_version_matches(plc_name, norm):
      """Check if version string matches any format present in PLCC shipped version strings
      Handled formats: <major>.x, <major>.<minor>, <major>.<minor>.x, <major>.<minor>.<patch>
      """
      plc_name = (plc_name or "").strip()
      return (
          plc_name == norm
          or plc_name.startswith(norm + ".")
          or plc_name == norm.split(".")[0] + ".x"
      )


def _normalize_version(version):
    """Normalize to major.minor, stripping leading 'v' (e.g. 'v1.9.0' → '1.9')."""
    version = version.lstrip("v")
    parts = version.split(".")
    return ".".join(parts[:2]) if len(parts) >= 2 else version


def parse_ocp_versions(compat_string):
    if not compat_string:
        return []
    if compat_string == "N/A":
        return []
    return [v.strip() for v in compat_string.split(",") if v.strip()]


def parse_semver(value):
    """Parse SemVer (plus optional leading v); return None if invalid."""
    value = value.lstrip("v")

    # Your requested versions are normalized to major.minor.
    if re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)", value):
        value += ".0"

    match = _SEMVER_RE.fullmatch(value)
    if not match:
        return None

    major, minor, patch, prerelease, build = match.groups()

    # SemVer forbids leading zeroes in numeric prerelease identifiers.
    prerelease_ids = prerelease.split(".") if prerelease else []
    if any(
        identifier.isdigit() and len(identifier) > 1 and identifier.startswith("0")
        for identifier in prerelease_ids
    ):
        return None

    return (
        (int(major), int(minor), int(patch)),
        prerelease_ids,
    )


def semver_is_higher(candidate, requested):
    """Return True if candidate has higher SemVer precedence than requested."""
    candidate = parse_semver(candidate)
    requested = parse_semver(requested)

    if candidate is None or requested is None:
        return False

    candidate_core, candidate_pre = candidate
    requested_core, requested_pre = requested

    if candidate_core != requested_core:
        return candidate_core > requested_core

    # A release outranks a prerelease of the same core version.
    if not candidate_pre:
        return bool(requested_pre)
    if not requested_pre:
        return False

    for candidate_id, requested_id in zip(candidate_pre, requested_pre):
        if candidate_id == requested_id:
            continue

        candidate_numeric = candidate_id.isdigit()
        requested_numeric = requested_id.isdigit()

        if candidate_numeric and requested_numeric:
            return int(candidate_id) > int(requested_id)
        if candidate_numeric != requested_numeric:
            return not candidate_numeric  # numeric identifiers have lower precedence
        return candidate_id > requested_id  # lexical comparison

    # Equal prefixes: the prerelease with more identifiers has higher precedence.
    return len(candidate_pre) > len(requested_pre)


def format_product_version(product, version, target_ocp=None):
    ocp_versions = parse_ocp_versions(version.get("openshift_compatibility"))
    result = {
        "product": product.get("name"),
        "former_names": product.get("former_names") or [],
        "package": product.get("package"),
        "version": version.get("name"), # some entries shipped with no version
        "status": version.get("type", ""),
        "ocp_versions": ocp_versions,
        "phases": [
            {
                "name": ph.get("name"),
                "start_date": ph.get("start_date"),
                "end_date": ph.get("end_date"),
                "start_date_format": ph.get("start_date_format", "string"),
                "end_date_format": ph.get("end_date_format", "string"),
            }
            for ph in (version.get("phases") or [])
        ],
    }
    if target_ocp:
        result["ocp_target"] = target_ocp
        result["ocp_compatible"] = version.get("openshift_compatibility") == "N/A" or (target_ocp in ocp_versions if ocp_versions else None)
    return result


def cmd_products(args, output=sys.stdout, local_products_json_file=None):
    if local_products_json_file is None and args.productsfile and pathlib.Path(args.productsfile).exists():
        local_products_json_file = args.productsfile
    products = api_search(args.name, local_products_json_file)
    if not products:
        json.dump({"error": "no products found", "query": args.name}, output, indent=2)
        output.write("\n")
        return 1

    target_ocp = getattr(args, "ocp", None)
    results = []
    for p in products:
        for v in (p.get("versions") or []):
            results.append(format_product_version(p, v, target_ocp=target_ocp))

    out = {"results": results, "total": len(results)}
    if target_ocp:
        out["ocp_target"] = target_ocp
    json.dump(out, output, indent=2)
    output.write("\n")
    return 0

def fetch_packagemanifests(local_json_manifest_path=None):
    if local_json_manifest_path is not None:
        with open(local_json_manifest_path, 'r') as f:
            pm_data = json.load(f)
            return pm_data.get('items', [])
    else:
        # Query packagemanifest
        cmd = [
            "oc", "get", "packagemanifests.packages.operators.coreos.com",
            "-o", "json",
            "-A"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if result.returncode != 0:
            return {
                "error": "failed to list packagemanifests: exit code " + str(result.returncode)
            }
        pm_data = json.loads(result.stdout)
        return pm_data.get('items', [])

def load_v0_operator_metadata(operators, local_json_manifest_path=None):
    try:
        pm_data = fetch_packagemanifests(local_json_manifest_path)
        if isinstance(pm_data, dict):
            return pm_data
        pm_data_dict = {}
        for packagemanifest in pm_data:
            package = packagemanifest.get('metadata', {}).get('name',"")
            if not package:
                continue

            pm_status = packagemanifest.get('status', {})
            # more than one catalog may provide a package
            pm_data_catalog = {
                "catalog": pm_status.get('catalogSource', ""),
                "catalog_namespace": pm_status.get('catalogSourceNamespace', ""),
                "versions": {},
            }
            for channel in pm_status.get('channels', []):
                channel_name = channel.get('name', "")
                if not channel_name:
                    continue
                for entry in channel.get('entries', []):
                    entry_bundle = entry.get('name', "")
                    entry_version = entry.get('version', "")
                    if not entry_version:
                        continue
                    version_info = pm_data_catalog["versions"].setdefault(entry_version, {"channels": [], "bundle": entry_bundle})
                    if channel_name not in version_info["channels"]:
                        version_info["channels"].append(channel_name)
            if pm_data_catalog["versions"]:
                pm_data_dict.setdefault(package, []).append(pm_data_catalog)
        for op in operators:
            op["mode"] = "olmv0"
            pkg = op.get("package", "")
            if pkg in pm_data_dict:
                op["metadata"] = pm_data_dict[pkg]
    except subprocess.TimeoutExpired:
        return {
            "error": "Timeout querying packagemanifest"
        }
    except Exception as e:
        return {
            "error": f"Error querying packagemanifest: {str(e)}"
        }


def cmd_olm_check(args, output=sys.stdout, local_products_json_file=None, local_json_manifest_path=None):
    operators, v0operators, v1operators = [], [], []
    metadata_error = None
    if local_json_manifest_path is None and args.packagemanifestsfile and pathlib.Path(args.packagemanifestsfile).exists():
        local_json_manifest_path = args.packagemanifestsfile
    if args.olmv0:
        v0operators = json.loads(args.olmv0)
        metadata_error = load_v0_operator_metadata(v0operators, local_json_manifest_path)
        operators += v0operators
    if args.olmv1:
        v1operators = json.loads(args.olmv1)
        operators += v1operators
    target = args.ocp

    if local_products_json_file is None and args.productsfile and pathlib.Path(args.productsfile).exists():
        local_products_json_file = args.productsfile
    all_products = api_search(None, local_products_json_file)
    by_package = collections.defaultdict(list)
    for p in all_products:
        pkg = p.get("package")
        if pkg:
            for pkg_name in pkg.split(","):
                by_package[pkg_name.strip()].append(p)

    results = []

    for op in operators:
        pkg = op.get("package", "")
        requested_version = (op.get("version") or "").lstrip("v")

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

        if args.compatibleonly:
            all_versions = {v.get("name") for p in products for v in (p.get("versions") or []) if (v.get("openshift_compatibility") == "N/A" or target in parse_ocp_versions(v.get("openshift_compatibility")))} - {None}
        else:
            all_versions = {v.get("name") for p in products for v in p.get("versions") or []} - {None}

        metadata = op.get("metadata") or []
        if args.compatibleonly:
            filtered_metadata = []
            for catalog in metadata:
                filtered_versions = {
                    version: info for version, info in (catalog.get("versions", {}) or {}).items() if any(_plc_version_matches(plc, _normalize_version(version)) for plc in all_versions)
                }

                if filtered_versions:
                    filtered_catalog = {**catalog, "versions": filtered_versions}
                    filtered_metadata.append(filtered_catalog)
            metadata = filtered_metadata

        if not requested_version:
            pkg_result = {
                "package": pkg,
                "product": products[0].get("name"),
                "available_versions": sorted(all_versions),
            }
            if metadata:
                pkg_result["source_catalogs"] = metadata
            results.append(pkg_result)
            continue

        norm = _normalize_version(requested_version)
        # check if the product lifecycle version string includes the requested version. 
        # product lifecycle API may contain lifecycle info about packages
        # applicable to version ranges represented in any of the following formats: 
        # <major>.x, <major.minor>, <major>.<minor>.x, and <major>,<minor>.<patch>
        matches = [(p, v) for p in products for v in (p.get("versions") or []) if _plc_version_matches(v.get("name"), norm)]
        # first matching version for result
        matched = next((m for m in matches if m[1].get("openshift_compatibility")), matches[0] if matches else None)

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
        product_result = {
            "package": pkg,
            "requested_version": norm,
            "product": formatted["product"],
            "status": formatted["status"],
            "ocp_compatible": formatted.get("ocp_compatible"),
            "ocp_versions": formatted["ocp_versions"],
            "phases": formatted["phases"],
        }

        # add version information for compatible operator versions higher than the currently installed
        # incompatible version.
        if product_result["ocp_compatible"] is False and args.compatibleonly:
            filtered_metadata = []
            for catalog in metadata:
                filtered_versions = {
                    # metadata sourced from packagemanifests and clustercatalogs have full semver for comparison.
                    # PLCC API only provides version information for major.minor versions of products
                    version: info for version, info in (catalog.get("versions") or {}).items() if semver_is_higher(version, requested_version)  # already excludes None, incompatible
                }

                if filtered_versions:
                    filtered_catalog = {**catalog, "versions": filtered_versions}
                    filtered_metadata.append(filtered_catalog)
            if filtered_metadata:
                product_result["source_catalogs"] = filtered_metadata
            product_result["available_versions"] = sorted(all_versions)
        results.append(product_result)

    out = {
        "ocp_target": target,
        "operators_checked": len(operators),
        "lifecycle_unavailable": [r["package"] for r in results if "error" in r],
        "results": results,
    }
    if metadata_error:
        out["packagemanifest_error"] = metadata_error

    json.dump(out, output, indent=2)
    output.write("\n")
    return 0


def main(args=None, output=sys.stdout):
    parser = argparse.ArgumentParser(
        description="Query Red Hat Product Life Cycle API for support status, EOL dates, and OCP compatibility.",
        epilog="Examples:\n"
               '  %(prog)s products "logging for Red Hat OpenShift"\n'
               '  %(prog)s products "logging for Red Hat OpenShift" --ocp 4.21\n'
               '  %(prog)s olm-check --ocp 4.21 --olmv1 \'[{"package":"cluster-logging"}]\'\n'
               '  %(prog)s olm-check --ocp 4.21 --olmv1 \'[{"package":"cluster-logging","version":"6.5.1"},{"package":"openshift-pipelines-operator-rh","version":"1.22.0"}]\'\n',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_products = subparsers.add_parser(
        "products",
        help="Query products by name (substring match)",
    )
    p_products.add_argument("name", help="Product name (substring match)")
    p_products.add_argument("--ocp", help="Check compatibility against this OCP version (e.g. 4.21)")
    p_products.add_argument("--productsfile", help="path to local JSON file with products lifecycle data")

    p_olm = subparsers.add_parser(
        "olm-check",
        help="Batch check OLM operators against a target OCP version",
    )
    p_olm.add_argument("--ocp", required=True, help="Target OCP version (e.g. 4.21)")
    p_olm.add_argument(
        "--olmv0",
        required=False,
        help='JSON array of OLMv0 managed operators, e.g. \'[{"package":"cluster-logging"}]\'. At least one of --olmv0 and --olmv1 should be provided.',
    )
    p_olm.add_argument(
        "--olmv1",
        required=False,
        help='JSON array of OLMv1 operators, e.g. \'[{"package":"cluster-logging"}]\'. At least one of --olmv0 and --olmv1 should be provided.',
    )
    p_olm.add_argument(
        "--compatibleonly",
        required=False,
        action='store_true',
        help='Show only compatible operator versions for a target OCP version.',
    )
    p_olm.add_argument("--productsfile", help="path to local JSON file with products lifecycle data")
    p_olm.add_argument("--packagemanifestsfile", help="path to local JSON file with packagemanifest data")
    parsed = parser.parse_args(args)
    if parsed.command == "olm-check" and not parsed.olmv0 and not parsed.olmv1:
        parser.error("olm-check requires at least one of --olmv0 or --olmv1")
    handlers = {"products": cmd_products, "olm-check": cmd_olm_check}
    return handlers[parsed.command](parsed, output=output)


if __name__ == "__main__":
    sys.exit(main())
