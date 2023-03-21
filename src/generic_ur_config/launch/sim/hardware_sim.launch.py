# Copyright 2021-2022 PickNik Inc.
# All rights reserved.
#
# Unauthorized copying of this code base via any medium is strictly prohibited.
# Proprietary and confidential.

import os
import re
import shlex

from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    ExecuteProcess,
    IncludeLaunchDescription,
    OpaqueFunction,
)
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

from moveit_studio_utils_py.launch_common import (
    get_launch_file,
    get_ros_path,
    xacro_to_urdf,
)
from moveit_studio_utils_py.system_config import (
    SystemConfigParser,
)

from moveit_studio_utils_py.generate_camera_frames import (
    generate_camera_frames,
)


system_config_parser = SystemConfigParser()
cameras_config = system_config_parser.get_cameras_config()


def path_pattern_change_for_ignition(urdf_string):
    """
    Replaces strings in a URDF file such as
        package://package_name/path/to/file
    to the actual full path of the file.

    TODO: This should be cleaned up to not require such a transformation, if possible.
    """
    data = urdf_string
    package_expressions = re.findall("(package://([^//]*))", data)
    for expr in set(package_expressions):
        data = data.replace(expr[0], get_ros_path(expr[1]))
    return data


def generate_simulation_description(context, *args, **settings):
    nodes = []
    is_test = LaunchConfiguration("is_test").perform(context).lower() == "true"

    if is_test:
        world_name_key = "gazebo_test_world_name"
    else:
        world_name_key = "gazebo_world_name"
    world_name = settings.get(world_name_key, "studio_simple.sdf")

    use_gui = settings.get("gazebo_gui", False)
    is_verbose = settings.get("gazebo_verbose", False)
    gz_renderer = os.environ.get("GAZEBO_RENDERER", "ogre")

    print(f"Starting Ignition Gazebo with world {world_name}")
    print(f"GUI: {use_gui}, Verbose: {is_verbose}, Test mode: {is_test}")

    sim_args = f"-r --render-engine {gz_renderer}"
    if is_verbose:
        sim_args += " -v 4"
    if not use_gui:
        sim_args += " -s --headless-rendering"

        # If no display is available, set up a Xvfb for headless rendering
        if not os.environ.get("DISPLAY"):
            print("Adding Xvfb for simulation...")
            display_id = ":99"
            os.environ["DISPLAY"] = display_id
            xvfb = ExecuteProcess(
                name="xvfb", cmd=["Xvfb", display_id, "-screen", "0", "1600x1200x16"]
            )
            nodes.append(xvfb)

    gazebo = IncludeLaunchDescription(
        get_launch_file("ros_gz_sim", "launch/gz_sim.launch.py"),
        launch_arguments=[("gz_args", [f"{sim_args} {world_name}"])],
    )
    nodes.append(gazebo)
    return nodes


def generate_launch_description():
    system_config_parser = SystemConfigParser()
    optional_feature_setting = system_config_parser.get_optional_feature_configs()

    # Launch arguments
    is_test_arg = DeclareLaunchArgument(
        name="is_test",
        default_value="false",
        description="If true, declares that the launch should be configured for testing.",
    )

    # The path to the auto_created urdf files
    robot_urdf = system_config_parser.get_processed_urdf()

    robot_urdf_ignition = path_pattern_change_for_ignition(robot_urdf)

    # Include URDF
    scene_xacro_path = get_ros_path(
        "generic_ur_config", "description/simulation_scene.urdf.xacro"
    )
    scene_urdf = xacro_to_urdf(scene_xacro_path, None)
    scene_urdf_ignition = path_pattern_change_for_ignition(scene_urdf)

    # Launch Ignition Gazebo
    gazebo = OpaqueFunction(
        function=generate_simulation_description, kwargs=optional_feature_setting
    )

    init_pose_args = shlex.split("-x 0.0 -y 0.0 -z 1.03 -R 0.0 -P 0.0 -Y 0.0")
    spawn_robot = Node(
        package="ros_gz_sim",
        executable="create",
        output="screen",
        arguments=[
            "-string",
            robot_urdf_ignition,
            "-name",
            "robot",
            "-allow_renaming",
            "true",
        ]
        + init_pose_args,
    )

    ########################
    # Camera Topic Bridges #
    ########################
    # For the scene camera, enable RGB image topics only.
    scene_image_rgb_ignition_bridge = Node(
        package="ros_gz_image",
        executable="image_bridge",
        name="scene_image_rgb_ignition_bridge",
        arguments=[
            "/scene_camera/image",
        ],
        remappings=[
            ("/scene_camera/image", "/scene_camera/color/image_raw"),
        ],
        parameters=[{"qos": "sensor_data"}],
        output="screen",
    )
    scene_image_depth_ignition_bridge = Node(
        package="ros_gz_image",
        executable="image_bridge",
        name="scene_image_depth_ignition_bridge",
        arguments=[
            "/scene_camera/depth_image",
        ],
        remappings=[
            (
                "/scene_camera/depth_image",
                "/scene_camera/depth/image_rect_raw",
            ),
        ],
        parameters=[{"qos": "sensor_data"}],
        output="screen",
    )

    scene_camera_info_ignition_bridge = Node(
        package="ros_gz_bridge",
        executable="parameter_bridge",
        name="scene_camera_info_ignition_bridge",
        arguments=[
            "/scene_camera/camera_info@sensor_msgs/msg/CameraInfo[ignition.msgs.CameraInfo",
        ],
        remappings=[
            ("/scene_camera/camera_info", "/scene_camera/color/camera_info"),
        ],
        output="screen",
    )

    # For the wrist mounted camera, enable RGB and depth topics.
    wrist_image_rgb_ignition_bridge = Node(
        package="ros_gz_image",
        executable="image_bridge",
        name="wrist_image_rgb_ignition_bridge",
        arguments=[
            "/wrist_mounted_camera/image",
        ],
        remappings=[
            ("/wrist_mounted_camera/image", "/wrist_mounted_camera/color/image_raw"),
        ],
        parameters=[{"qos": "sensor_data"}],
        output="screen",
    )
    wrist_image_depth_ignition_bridge = Node(
        package="ros_gz_image",
        executable="image_bridge",
        name="wrist_image_depth_ignition_bridge",
        arguments=[
            "/wrist_mounted_camera/depth_image",
        ],
        remappings=[
            (
                "/wrist_mounted_camera/depth_image",
                "/wrist_mounted_camera/depth/image_rect_raw",
            ),
        ],
        parameters=[{"qos": "sensor_data"}],
        output="screen",
    )
    wrist_camera_pointcloud_ignition_bridge = Node(
        package="ros_gz_bridge",
        executable="parameter_bridge",
        name="wrist_camera_pointcloud_ignition_bridge",
        arguments=[
            "/wrist_mounted_camera/points@sensor_msgs/msg/PointCloud2[ignition.msgs.PointCloudPacked",
        ],
        remappings=[
            (
                "/wrist_mounted_camera/points",
                "/wrist_mounted_camera/depth/color/points",
            ),
        ],
        output="screen",
    )
    wrist_camera_info_ignition_bridge = Node(
        package="ros_gz_bridge",
        executable="parameter_bridge",
        name="wrist_camera_info_ignition_bridge",
        arguments=[
            "/wrist_mounted_camera/camera_info@sensor_msgs/msg/CameraInfo[ignition.msgs.CameraInfo",
        ],
        remappings=[
            (
                "/wrist_mounted_camera/camera_info",
                "/wrist_mounted_camera/color/camera_info",
            ),
        ],
        output="screen",
    )

    #######################
    # Force Torque Sensor #
    #######################
    fts_bridge = Node(
        package="ros_gz_bridge",
        executable="parameter_bridge",
        name="fts_bridge",
        arguments=[
            "/tcp_fts_sensor/ft_data@geometry_msgs/msg/WrenchStamped[ignition.msgs.Wrench",
        ],
        remappings=[
            (
                "/tcp_fts_sensor/ft_data",
                "/force_torque_sensor_broadcaster/wrench",
            ),
        ],
        output="screen",
    )

    clock_bridge = Node(
        package="ros_gz_bridge",
        executable="parameter_bridge",
        name="clock_bridge",
        arguments=["/clock@rosgraph_msgs/msg/Clock[ignition.msgs.Clock"],
        output="screen",
    )

    spawn_cabinet = Node(
        package="ros_gz_sim",
        executable="create",
        output="screen",
        arguments=[
            "-string",
            scene_urdf_ignition,
            "-name",
            "cabinet",
            "-allow_renaming",
            "true",
        ]
        + init_pose_args,
    )

    frame_pair_params = [
        {
            "world_frame": "world",
            "camera_frames": generate_camera_frames(cameras_config),
        }
    ]

    camera_transforms_node = Node(
        package="moveit_studio_agent",
        executable="camera_transforms_node",
        name="camera_transforms_node",
        output="screen",
        parameters=frame_pair_params,
        arguments=["--ros-args"],
    )

    return LaunchDescription(
        [
            is_test_arg,
            scene_image_rgb_ignition_bridge,
            scene_image_depth_ignition_bridge,
            scene_camera_info_ignition_bridge,
            wrist_image_rgb_ignition_bridge,
            wrist_camera_info_ignition_bridge,
            wrist_image_depth_ignition_bridge,
            wrist_camera_pointcloud_ignition_bridge,
            clock_bridge,
            fts_bridge,
            gazebo,
            spawn_robot,
            spawn_cabinet,
            camera_transforms_node,
        ]
    )
