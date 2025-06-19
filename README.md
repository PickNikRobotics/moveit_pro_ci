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
    uses: PickNikRobotics/moveit_pro_ci/.github/workflows/workspace_integration_test.yaml@fix-artifact-upload
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
- `image_tag`: The tag of the MoveIt Pro container image to use for the job. This can be set to the branch name or a specific tag version (example: 8.1.0).
  - Note: we recommend creating branch names that match the MoveIt Pro container image tags, such as `8.1.0`, `8.2.0`, etc for your versioned out production robot applications.
- `config_package`: The name of the MoveIt Pro config package to test. This is only required when using a matrix to run tests in parallel.
- `colcon_build_args`: Additional colcon arguments to pass to the `colcon build` command.
-` colcon_test_args`: Additional colcon arguments to pass to the `colcon test` command.
