# MoveIt Pro Reusable CI Jobs
This repo showcases an example of integrating end-to-end CI jobs for MoveIt Pro applications, including workspace objective validation and intergration tests with the MoveIt Pro Runtime.

## Usage
In your main workflow file, to test all packages in your workspace **sequentially** in a container, you can use the following job definition:
```yaml
jobs:
  integration-test-in-studio-container:
    uses: PickNikRobotics/moveit_pro_ci/.github/workflows/workspace_integration_test.yaml@<version-chosen>
    with:
      image_tag: ${{ github.event_name == 'pull_request' && github.event.pull_request.base.ref || github.ref_name }}
      colcon_test_args: "--executor sequential"
    secrets: inherit
```
To test packages in your workspace **in parallel** in a container, you can utilize a matrix with the `config_package` input like in the following job definition:
```yaml
jobs:
  integration-test-in-studio-container:
    uses: PickNikRobotics/moveit_pro_ci/.github/workflows/workspace_integration_test.yaml@<version-chosen>
    strategy:
      fail-fast: false
      matrix:
        config_package: [lab_sim, hangar_sim, grinding_sim, factory_sim, space_satellite_sim, mock_sim]
    with:
      image_tag: ${{ github.event_name == 'pull_request' && github.event.pull_request.base.ref || github.ref_name }}
      colcon_test_args: "--executor sequential"
      config_package: ${{ matrix.config_package }}
    secrets: inherit
  ```

All input args:
- `image_tag`: The tag of the MoveIt Pro container image to use for the job. This can be set to the branch name or a specific tag version (example: 8.1.0). The ROS distro is automatically appended to this tag (see [Supported ROS Distributions](#supported-ros-distributions) below), so the image actually pulled is `picknikciuser/moveit-studio:<image_tag>-<ros_distro>`.
  - Note: we recommend creating branch names that match the MoveIt Pro container image tags, such as `8.1.0`, `8.2.0`, etc for your versioned out production robot applications.
- `config_package`: The name of the MoveIt Pro config package to test. This is only required when using a matrix to run tests in parallel. Default: `""` (build/test all packages).
- `colcon_build_args`: Additional colcon arguments to pass to the `colcon build` command. Default: `""`.
- `colcon_test_args`: Additional colcon arguments to pass to the `colcon test` command. Default: `""`.
- `runner`: A runner to be passed and run the integration tests. Default: `studio_16_core_runner`.
- `mujoco_ci_timestep`: If non-empty, set the MuJoCo `<option timestep>` to this value (in seconds) on every top-level `<mujoco>` scene file under `src/` before build. Used to keep the simulator at-or-under realtime on slower CI runners; leave empty for normal runs. Suggested: `"0.004"` (250 Hz). Default: `""`.
- `use_ccache`: If `true`, use ccache to speed up the colcon build. The ccache directory is restored from and saved to the GitHub Actions cache (keyed by image tag, ROS distro, and config package), and `CMAKE_{C,CXX}_COMPILER_LAUNCHER` is set to `ccache` for the build step. Default: `false`.
- `enable_gpu`: If `true`, pass `--gpus all` to the studio container so workloads inside it can access NVIDIA hardware (CUDA inference, GPU-accelerated simulation, etc.). The caller is responsible for routing the job to a GPU-equipped runner; setting `enable_gpu: true` on a runner with no GPU exposed will fail at container start with `could not select device driver "" with capabilities: [[gpu]]`. Default: `false`.
- `image_ref`: Full container image reference template that overrides the default Docker Hub `picknikciuser/moveit-studio:<image_tag>-<ros_distro>`. Used by sister repos that need to pull a PR-built private GHCR image via `repository_dispatch`. Uses Python-style `format()` semantics: `{0}` is substituted with the matrix ROS distro at job start, so one input covers every distro the matrix expands over. Example: `ghcr.io/picknikrobotics/moveit-studio:my-branch-{0}-amd64`. When set, `enable_gpu`'s CUDA suffix is NOT auto-appended; bake any suffix into the template if needed. Default: `""` (use Docker Hub via `image_tag`).
- `git_ref`: Git git_ref (branch, tag, or SHA) for the caller's repository to check out. Defaults to empty, which lets `actions/checkout` use the triggering ref (correct for `pull_request` and `push`). Set this when triggered by `repository_dispatch` and the caller needs to run against a specific paired branch carried in the dispatch payload (e.g., `v9.3`). Default: `""`.

Required secrets:
- `moveit_license_key`: The MoveIt Pro license key. Passing `secrets: inherit` (as in the examples above) is the easiest way to forward it from the calling workflow.

## Supported ROS Distributions

The reusable workflow runs each job once per supported ROS distro via a matrix. Currently supported:

- **Humble** (`humble`)
- **Jazzy** (`jazzy`)

For each distro, the workflow pulls `picknikciuser/moveit-studio:<image_tag>-<ros_distro>`. MoveIt Pro began supporting ROS Jazzy in 9.2.0. Jobs for each distro run in parallel and are reported as separate matrix entries in the GitHub Actions UI.

## Reusable Actions

### `find_release_branch`
Composite action that lists the calling repository's branches and outputs the highest `v<major>.<minor>` branch name (e.g. `v9.5`). Used by the `batch-merge-release-branch` workflows across MoveIt Pro repos to pick the active release branch to merge into `main`.
```yaml
- name: Get current release branch
  id: get_current_release_branch
  uses: PickNikRobotics/moveit_pro_ci/.github/actions/find_release_branch@<commit-sha>
- name: Use it
  run: echo "Release branch is ${{ steps.get_current_release_branch.outputs.branch }}"
```
Pin by commit SHA for reproducibility.
