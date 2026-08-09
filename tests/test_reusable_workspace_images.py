# Copyright 2026 PickNik Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Static contracts for reusable build-once/test-many workspace images."""

from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = REPO_ROOT / ".github/workflows"
BUILD_WORKFLOW = WORKFLOWS / "workspace_build_image.yaml"
TEST_WORKFLOW = WORKFLOWS / "workspace_test_image.yaml"
CI_WORKFLOW = WORKFLOWS / "reusable_workspace_images_ci.yaml"
README = REPO_ROOT / "README.md"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_build_workflow_exports_attested_caller_owned_image_without_license() -> None:
    text = _text(BUILD_WORKFLOW)
    yaml.safe_load(text)

    assert "workflow_call:" in text
    assert "image_ref:" in text
    assert "image_digest:" in text
    assert "packages: write" in text
    assert "attestations: write" in text
    assert "id-token: write" in text
    assert "moveit_license_key" not in text
    assert "runs-on: ubuntu-22.04" in text
    assert "timeout-minutes: 120" in text
    assert "base_image_ref:" in text
    assert "Base image must be pinned by an immutable sha256 digest" in text
    assert "INPUT_IMAGE_REPOSITORY" not in text
    assert "git_ref:" not in text
    assert "runner:" not in text
    assert "docker/login-action@c94ce9fb468520275223c153574b00df6fe4bcc9" in text
    assert "docker/build-push-action@10e90e3645eae34f1e60eeb005ba3a3d33f178e8" in text
    assert "actions/attest-build-provenance@977bb373ede98d70efdf65b84cb5f73e068dcc2a" in text
    assert "push-to-registry: true" in text
    assert 'echo "image_ref=${IMAGE_REPOSITORY}@${IMAGE_DIGEST}"' in text
    assert "PREBUILT_WS=/opt/prebuilt_ws" in text
    assert "colcon build" in text
    assert ".moveit-pro-ci-image.json" in text
    assert "org.opencontainers.image.revision" in text
    assert "visibility" in text and '!= "private"' in text
    assert "privacy-bootstrap" in text
    assert "HTTP 404" in text
    assert "Unable to determine workspace package visibility" in text


def test_build_source_is_trusted_complete_and_credential_free() -> None:
    text = _text(BUILD_WORKFLOW)

    assert "Unsupported caller event" in text
    assert "push|workflow_dispatch|schedule" in text
    assert "HEAD_REPOSITORY" in text
    assert "github.event.pull_request.head.repo.full_name" in text
    assert "persist-credentials: false" in text
    assert "submodules: recursive" in text
    assert "lfs: ${{ inputs.fetch_lfs }}" in text
    assert "git submodule foreach --recursive 'git lfs pull'" in text
    assert 'source_sha="$(git rev-parse HEAD)"' in text
    assert "credential-free build context" in text
    assert "--exclude=.git" in text
    assert "context: ${{ runner.temp }}/moveit-pro-workspace-context" in text
    assert "context: ${{ github.workspace }}" not in text
    assert "candidate.is_symlink()" in text
    assert "submodule_path_unresolved.is_symlink()" in text
    assert ".moveit-pro-ci-source-provenance.json" in text
    assert '"submodules"' in text
    assert '"lfs_objects"' in text
    assert '"materialized_sha256"' in text
    assert "source_provenance_sha256" in text


def test_build_arguments_and_network_indexes_have_defined_parsing_and_pins() -> None:
    text = _text(BUILD_WORKFLOW)

    assert "colcon_build_args_json:" in text
    assert "COLCON_BUILD_ARGS_JSON_B64" in text
    assert 'mapfile -d \'\' -t build_args' in text
    assert 'colcon build "${package_args[@]}" "${build_args[@]}"' in text
    assert "set +u;" in text
    assert 'source "/opt/ros/${ROS_DISTRO}/setup.sh"' in text
    assert "source /opt/overlay_ws/install/setup.sh" in text
    assert text.index("set +u;") < text.index('source "/opt/ros/${ROS_DISTRO}/setup.sh"') < text.index("set -u;")
    assert "colcon mixin update default" in text
    assert "colcon metadata update default" in text
    assert "colcon mixin update;" not in text
    assert "colcon metadata update;" not in text
    assert "colcon mixin remove default" in text
    assert "colcon metadata remove default" in text
    assert text.index("colcon mixin remove default") < text.index("7558e35befbff0d88d9b8f701b3ab1b073cbcaba/index.yaml")
    assert text.index("colcon metadata remove default") < text.index("28d11cfc270583b8ddf26812423c3dd9ecd6af33/index.yaml")
    assert "7558e35befbff0d88d9b8f701b3ab1b073cbcaba/index.yaml" in text
    assert "28d11cfc270583b8ddf26812423c3dd9ecd6af33/index.yaml" in text
    assert "/master/index.yaml" not in text


def test_test_workflow_preflights_attestation_before_license_exposure() -> None:
    text = _text(TEST_WORKFLOW)
    yaml.safe_load(text)

    assert "preflight-workspace-image:" in text
    assert "licensed-workspace-tests:" in text
    assert "needs: preflight-workspace-image" in text
    assert "attestations: read" in text
    assert "runs-on: ubuntu-22.04" in text
    assert "timeout-minutes: 15" in text
    assert "timeout-minutes: 90" in text
    assert "Unsupported caller event" in text
    assert "push|workflow_dispatch|schedule" in text
    assert "expected_repository=" in text
    assert "ghcr.io/" in text
    assert 'image_repository="${IMAGE_REF%@sha256:*}"' in text
    assert '[[ "$image_repository" != "$expected_repository"' in text
    assert "docker login ghcr.io" in text
    assert "gh attestation verify" in text
    assert "--repo \"$GITHUB_REPOSITORY\"" in text
    assert "--signer-workflow" in text
    assert "--signer-digest \"$BUILDER_WORKFLOW_SHA\"" in text
    assert "--source-digest \"$EXPECTED_SOURCE_SHA\"" in text
    assert "--deny-self-hosted-runners" in text
    assert "container:" not in text
    assert "docker create" in text
    assert "docker start --attach" in text
    assert "docker cp" in text
    assert "docker rm -f" in text
    assert "stat.S_ISREG" in text
    assert "path.is_symlink()" in text
    assert "1024 * 1024" in text
    assert "workspace image metadata mismatch" in text
    assert "marker!r" not in text
    assert text.count("docker login ghcr.io") >= 2
    preflight = text.split("licensed-workspace-tests:", maxsplit=1)[0]
    assert "MOVEIT_LICENSE_KEY" not in preflight
    assert "/opt/prebuilt_ws/.moveit-pro-ci-image.json" in text
    assert "/opt/prebuilt_ws/.moveit-pro-ci-source-provenance.json" in text
    assert "source_provenance_sha256" in text
    assert "materialized_sha256" in text
    assert "actions/checkout@" not in text
    assert "rosdep install" not in text
    assert "colcon build" not in text
    assert "--retest-until-pass" not in text


def test_test_workflow_preserves_argument_boundaries_and_all_external_packages() -> None:
    text = _text(TEST_WORKFLOW)

    assert text.count("set +u;") >= 1
    assert text.count("set -u;") >= 1
    assert "colcon_test_args_json:" in text
    assert "test_packages_json:" in text
    assert "test_args_file=" in text
    assert "test_packages_file=" in text
    assert 'mapfile -d \'\' -t test_args < /moveit-pro-ci-input/test-args.nul' in text
    assert 'mapfile -d \'\' -t test_packages < /moveit-pro-ci-input/test-packages.nul' in text
    assert 'mapfile -d \'\' -t test_args < <(' not in text
    assert 'mapfile -d \'\' -t test_packages < <(' not in text
    assert "mapfile -t external_package_array" in text
    assert "unknown requested test package" in text
    assert "requested external dependency package is not eligible" in text
    assert 'colcon test "${skip_args[@]}" "${package_args[@]}" "${test_args[@]}"' in text


def test_test_workflow_scans_and_stages_bounded_diagnostics() -> None:
    text = _text(TEST_WORKFLOW)

    assert "Sanitize diagnostic artifacts" in text
    assert "MOVEIT_LICENSE_KEY: ${{ secrets.moveit_license_key }}" in text
    assert "$RUNNER_TEMP/moveit-pro-ci-upload" in text
    assert ".moveit-pro-ci-upload" not in text
    assert "is_symlink()" in text
    assert "secret" in text.lower()
    assert "relative.parts" in text
    assert "300 * 1024 * 1024" in text
    assert "1024 * 1024 * 1024" in text
    assert "steps.sanitize.outcome == 'success'" in text
    assert "id: remove" in text
    assert "steps.remove.outcome == 'success'" in text
    assert "diagnostics.tar.gz" in text
    assert "chmod(0o444)" in text
    assert "steps.sanitize.outputs.archive_path" in text
    assert "/opt/prebuilt_ws/build/*/test_results/" not in text


def test_readme_documents_build_once_trust_and_existing_workflow_alternative() -> None:
    text = _text(README)

    assert "workspace_build_image.yaml" in text
    assert "workspace_test_image.yaml" in text
    assert "needs.build.outputs.image_ref" in text
    assert "immutable digest" in text
    assert "artifact attestation" in text
    assert "pull_request_target" in text
    assert "base image" in text and "@sha256:" in text
    assert "skip_colcon_build" in text
    assert "not implemented" in text


def test_pull_requests_run_contract_and_actionlint_checks() -> None:
    text = _text(CI_WORKFLOW)
    yaml.safe_load(text)

    assert "pull_request:" in text
    assert "contents: read" in text
    assert "pytest -q tests/test_reusable_workspace_images.py" in text
    assert (
        "rhysd/actionlint:1.7.12@"
        "sha256:b1934ee5f1c509618f2508e6eb47ee0d3520686341fec936f3b79331f9315667"
    ) in text
    assert "workspace_build_image.yaml" in text
    assert "workspace_test_image.yaml" in text
