# Agentic skills — image packaging and mount contract

Scope: OCI image build layout, directory conventions, skill document shape, and consumption expectations for agent sandboxes. Does not define individual skill authoring quality bars beyond inventory — see [PLANNED: OLS-3029].

## Behavioral Rules

1. The repository builds a container image using `Containerfile` with a RHEL-based minimal base image from the OpenShift CI registry pattern (`ocp` image stream) and copies the **entire repository tree** into `/skills/` in the image filesystem (not only markdown files).
2. The image is intended to be consumed as an **image volume** mounted into workload pods (e.g. agent sandbox); mount target path in the workload is **not** fixed by this repository — sandbox/runtime configuration chooses the mount path; product default elsewhere documents as `LIGHTSPEED_SKILLS_DIR` defaulting to `/app/skills` in the agentic sandbox context.
3. Consumers may mount the whole image root or restrict to a **subdirectory** of the image using image volume `subPath` (or equivalent), so category or single-skill slices are supported without separate images.
4. **Skill category** = top-level directory under the repo root (e.g. `cluster-update/`). **Individual skill** = subdirectory containing a `SKILL.md` file.
5. Each `SKILL.md` consists of YAML frontmatter (at minimum `name` and `description` keys) followed by Markdown body content consumed by agent runtimes.
6. Skills are **provider-agnostic** at the file level: same on-disk layout is compatible with Claude Skills, OpenAI Skills, and Google ADK SkillToolset-style discovery as described in upstream agent-skills ecosystems (discovery mechanics are SDK-specific).
7. Agent SDKs discover skills from the mounted directory tree using each provider’s native discovery rules; this repository does not ship a custom discovery daemon.
8. At runtime, skills are treated as **read-only** inputs to the sandbox pod; the image and mount contract do not support mutating packaged skill content inside the running container.
9. Current inventory: `cluster-update/update-advisor` — `SKILL.md` exists in **draft** state (placeholder body pending real guidance content).

## Configuration Surface

- **Image build**: `Containerfile` `FROM` image reference (OCP CI base selection); `COPY` source (repository root) and destination path `/skills/`.
- **Workload mount**: Kubernetes/container runtime image volume spec: image reference, mount path (align with sandbox `LIGHTSPEED_SKILLS_DIR` or operator override), optional `subPath` selecting a subtree under `/skills/`.
- **Skill metadata**: Per-skill `SKILL.md` frontmatter fields `name`, `description` (extensible per provider conventions).

## Constraints

- OpenShift policy disallows `FROM scratch` for this artifact; base image must satisfy enterprise policy (RHEL-based ocp base).
- Packaged tree includes non-skill files (README, Containerfile, etc.) under `/skills/` unless future build stages prune them; consumers relying on clean discovery should use `subPath` into category or skill directories.
- Skill acceptance criteria, review workflow, and versioning policy are out of scope for this file — tracked under epic [PLANNED: OLS-3029].

## Planned Changes

- [PLANNED: OLS-3029] Formal framework and criteria for skill acceptance, maintenance, and publication.
- Replace draft `update-advisor` body with completed OpenShift cluster update readiness guidance.
- Optional multi-stage build to copy only skill subtrees into the image and reduce extraneous files at `/skills/`.
- Document operator/Sandbox CR field names that reference `SkillsSource.image` and `paths` once finalized in operator specs (cross-ref `lightspeed-agentic-operator` CRD docs rather than duplicating here).
