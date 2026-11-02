Objective revisions from [moveit_pro_example_ws](https://github.com/PickNikRobotics/moveit_pro_example_ws) (BSD-3-Clause, PickNik Inc.), used as matching regression fixtures:

- `wrap_block`: `src/dual_arm_sim/objectives/sort_blocks.xml` at 2d6f8409, a block wrapped in `ForceSuccess`.
- `delete_block`: `src/lab_sim/objectives/pick_all_bottles_with_apriltags.xml` at 20bce2f2, one nested `Sequence` deleted.
- `restructure_loop`: `src/hangar_sim/objectives/ml_move_boxes_to_loading_zone.xml` at c4fcf9ef, a retry loop rewritten around a `Fallback`.
- `rewrite_perception`: `src/hangar_sim/objectives/move_boxes_to_loading_zone_from_waypoint.xml` at c4fcf9ef, a perception pipeline rewritten inside its existing `Sequence`.
- `rename_waypoints`: `src/lab_sim/objectives/3_waypoint_pick_and_place.xml` at b00dc79b, waypoint names changed in two look-alike `Sequence` blocks.
