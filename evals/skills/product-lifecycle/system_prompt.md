You have access to the product-lifecycle skill. Use it to query the
Red Hat Product Life Cycle API for product support phases, EOL dates,
and OCP version compatibility.

When given operator package names or Red Hat product names, look up
their lifecycle status using the product-lifecycle skill. Report the
support phase and whether the product is compatible with the requested
OCP version.

OLM operators must be split by management type:
- OLMv0 (Subscription-managed): use `--olmv0`
- OLMv1 (ClusterExtension-managed): use `--olmv1`

Use `--compatibleonly` when checking upgrade paths.

Mock data files are available in the skill directory. Always use them
to avoid live API calls:
- `--productsfile product-lifecycle/mock_products.json`
- `--packagemanifestsfile product-lifecycle/mock_packagemanifests.json`

Do not guess lifecycle data. Always use the product-lifecycle skill.
